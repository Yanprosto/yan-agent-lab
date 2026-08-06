import json
from types import SimpleNamespace

import pytest

from mcbuild.llm import client as client_module
from mcbuild.llm.client import (
    LLMProvider,
    OpenRouterClient,
    PlanJSONMode,
    StructuredOutputSchemaError,
    Usage,
    consume_stream,
)


def _chunk(content=None, reasoning=None, reasoning_details=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(
        content=content, reasoning=reasoning, reasoning_details=reasoning_details, tool_calls=tool_calls
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _tool_call_delta(index, id=None, name=None, arguments=None):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


def test_reasoning_details_fragments_merge_into_complete_signed_block():
    # a thinking block streams as text pieces first, signature last, all at index 0
    chunks = [
        _chunk(reasoning_details=[{"type": "reasoning.text", "text": "Let me ", "index": 0}]),
        _chunk(reasoning_details=[{"type": "reasoning.text", "text": "think.", "index": 0}]),
        _chunk(reasoning_details=[{"type": "reasoning.text", "signature": "SIG123", "index": 0}]),
    ]
    message, _ = consume_stream(chunks)
    assert message.reasoning_details is not None
    assert len(message.reasoning_details) == 1  # one merged block, not three fragments
    block = message.reasoning_details[0]
    assert block["text"] == "Let me think."
    assert block["signature"] == "SIG123"  # signature stays attached to the full text


def test_reasoning_details_separate_indices_stay_separate():
    chunks = [
        _chunk(reasoning_details=[{"type": "reasoning.text", "text": "A", "index": 0, "signature": "S0"}]),
        _chunk(reasoning_details=[{"type": "reasoning.text", "text": "B", "index": 1, "signature": "S1"}]),
    ]
    message, _ = consume_stream(chunks)
    assert message.reasoning_details is not None
    assert [b["signature"] for b in message.reasoning_details] == ["S0", "S1"]


def test_consume_stream_accumulates_content():
    chunks = [_chunk(content="Design "), _chunk(content="brief: "), _chunk(content="a hut.")]
    message, usage = consume_stream(chunks)
    assert message.content == "Design brief: a hut."
    assert message.tool_calls is None


def test_consume_stream_accumulates_reasoning_separately_from_content():
    chunks = [
        _chunk(reasoning="Thinking about "),
        _chunk(reasoning="the doorway."),
        _chunk(content="Here's my plan."),
    ]
    message, usage = consume_stream(chunks)
    assert message.reasoning == "Thinking about the doorway."
    assert message.content == "Here's my plan."


def test_consume_stream_fires_on_delta_callback_for_each_piece():
    chunks = [_chunk(reasoning="a"), _chunk(content="b"), _chunk(reasoning="c")]
    seen = []
    consume_stream(chunks, on_delta=lambda kind, text: seen.append((kind, text)))
    assert seen == [("reasoning", "a"), ("content", "b"), ("reasoning", "c")]


def test_consume_stream_accumulates_tool_call_arguments_across_chunks():
    chunks = [
        _chunk(tool_calls=[_tool_call_delta(0, id="call_1", name="submit_blueprint", arguments="")]),
        _chunk(tool_calls=[_tool_call_delta(0, arguments='{"code": "fill(')]),
        _chunk(tool_calls=[_tool_call_delta(0, arguments='0,0,0,1,1,1,\'stone\')", "design_notes": "x"}')]),
    ]
    message, usage = consume_stream(chunks)
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    tc = message.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.function.name == "submit_blueprint"
    assert tc.function.arguments == '{"code": "fill(0,0,0,1,1,1,\'stone\')", "design_notes": "x"}'


def test_consume_stream_handles_multiple_parallel_tool_calls_by_index():
    chunks = [
        _chunk(tool_calls=[_tool_call_delta(0, id="call_a", name="inspect", arguments="{}")]),
        _chunk(tool_calls=[_tool_call_delta(1, id="call_b", name="finish", arguments='{"summary":')]),
        _chunk(tool_calls=[_tool_call_delta(1, arguments='"done"}')]),
    ]
    message, usage = consume_stream(chunks)
    assert message.tool_calls is not None
    assert [tc.id for tc in message.tool_calls] == ["call_a", "call_b"]
    assert message.tool_calls[1].function.arguments == '{"summary":"done"}'


def test_consume_stream_captures_final_usage_chunk():
    usage_obj = SimpleNamespace(prompt_tokens=12, completion_tokens=34, cost=0.05)
    chunks = [_chunk(content="hi"), _chunk(usage=usage_obj)]
    message, usage = consume_stream(chunks)
    assert usage is usage_obj


def test_consume_stream_empty_yields_none_content_and_tool_calls():
    message, usage = consume_stream([])
    assert message.content is None
    assert message.reasoning is None
    assert message.tool_calls is None
    assert usage is None


def test_usage_cache_rate_is_fraction_of_cached_prompt_tokens():
    assert Usage(prompt_tokens=100, cached_tokens=25).cache_rate == 0.25
    assert Usage(prompt_tokens=0, cached_tokens=0).cache_rate == 0.0  # no div-by-zero on an empty turn


def test_usage_add_accumulates_cached_tokens():
    total = Usage()
    total.add(Usage(prompt_tokens=100, cached_tokens=80, cost_usd=0.01))
    total.add(Usage(prompt_tokens=50, cached_tokens=50, cost_usd=0.001))
    assert total.prompt_tokens == 150
    assert total.cached_tokens == 130
    assert total.cache_rate == 130 / 150


def test_client_session_id_defaults_to_a_generated_value_and_can_be_pinned():
    a = OpenRouterClient(api_key="test-key")
    b = OpenRouterClient(api_key="test-key")
    assert a.session_id and isinstance(a.session_id, str)
    assert a.session_id != b.session_id  # auto-generated ids don't collide

    pinned = OpenRouterClient(api_key="test-key", session_id="resume-me")
    assert pinned.session_id == "resume-me"


def test_usage_from_obj_parses_cached_tokens_for_cache_rate_reporting():
    client = OpenRouterClient(api_key="test-key")
    usage_obj = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=50,
        cost=0.02,
        prompt_tokens_details=SimpleNamespace(cached_tokens=900),
    )
    usage = client._usage_from_obj(usage_obj)
    assert usage.cached_tokens == 900
    assert usage.cache_rate == 0.9


def test_usage_from_obj_defaults_cached_tokens_to_zero_when_absent():
    client = OpenRouterClient(api_key="test-key")
    usage_obj = SimpleNamespace(prompt_tokens=100, completion_tokens=10, cost=0.0)
    usage = client._usage_from_obj(usage_obj)
    assert usage.cached_tokens == 0
    assert usage.cache_rate == 0.0


def test_usage_from_obj_defaults_cost_to_zero_when_provider_omits_it():
    client = OpenRouterClient(api_key="test-key")
    usage_obj = SimpleNamespace(prompt_tokens=100, completion_tokens=10)
    usage = client._usage_from_obj(usage_obj)
    assert usage.cost_usd == 0.0


def test_poe_environment_selects_poe_endpoint_and_key(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("POE_API_KEY", "poe-test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    OpenRouterClient()

    assert captured == {"api_key": "poe-test-key", "base_url": "https://api.poe.com/v1"}


def test_openrouter_remains_default_when_both_provider_keys_are_present(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("POE_API_KEY", "poe-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-test-key")

    OpenRouterClient()

    assert captured == {"api_key": "openrouter-test-key", "base_url": "https://openrouter.ai/api/v1"}


def test_explicit_openrouter_endpoint_keeps_openrouter_key_and_behavior(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("POE_API_KEY", "poe-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-test-key")

    OpenRouterClient(base_url="https://openrouter.ai/api/v1")

    assert captured == {"api_key": "openrouter-test-key", "base_url": "https://openrouter.ai/api/v1"}


def test_poe_chat_maps_high_reasoning_and_preserves_tools_and_images():
    client = OpenRouterClient(api_key="test-key", base_url="https://api.poe.com/v1")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        tool_call = SimpleNamespace(
            id="call_visual",
            function=SimpleNamespace(name="report_visual", arguments='{"color":"red"}'),
        )
        message = SimpleNamespace(content=None, tool_calls=[tool_call], reasoning=None, reasoning_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

    client._client.chat.completions.create = fake_create  # ty: ignore[invalid-assignment]
    tools = [{"type": "function", "function": {"name": "report_visual", "parameters": {"type": "object"}}}]
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "inspect", "cache_control": {"type": "ephemeral"}}],
        },
        {
            "role": "assistant",
            "content": "",
            "reasoning_details": [{"type": "reasoning.text", "text": "private", "signature": "sig"}],
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what color?", "cache_control": {"type": "ephemeral"}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
    ]

    result = client.chat(model="gpt-5.6-sol", messages=messages, tools=tools, reasoning="high")

    assert captured["extra_body"] == {"reasoning_effort": "high"}
    assert "user" not in captured
    assert captured["tools"] is tools
    assert captured["messages"][2]["content"][1] == messages[2]["content"][1]
    assert "cache_control" not in captured["messages"][0]["content"][0]
    assert "cache_control" not in captured["messages"][2]["content"][0]
    assert "reasoning_details" not in captured["messages"][1]
    assert "cache_control" in messages[0]["content"][0]  # caller history is not mutated
    result_calls = getattr(result.message, "tool_calls", None)
    assert result_calls is not None
    assert result_calls[0].function.name == "report_visual"


def test_poe_streaming_reassembles_tool_fragments_and_usage():
    client = OpenRouterClient(api_key="test-key", base_url="https://api.poe.com/v1")
    captured = {}
    usage_obj = SimpleNamespace(prompt_tokens=21, completion_tokens=8)
    chunks = [
        _chunk(tool_calls=[_tool_call_delta(0, id="call_1", name="report_visual", arguments="")]),
        _chunk(tool_calls=[_tool_call_delta(0, arguments='{"color":')]),
        _chunk(tool_calls=[_tool_call_delta(0, arguments='"red"}')]),
        _chunk(usage=usage_obj),
    ]

    def fake_create(**kwargs):
        captured.update(kwargs)
        return iter(chunks)

    client._client.chat.completions.create = fake_create  # ty: ignore[invalid-assignment]
    result = client.chat(
        model="gpt-5.6-sol",
        messages=[{"role": "user", "content": "report"}],
        tools=[{"type": "function", "function": {"name": "report_visual", "parameters": {"type": "object"}}}],
        reasoning="high",
        stream=True,
    )

    assert captured["stream"] is True
    assert captured["stream_options"] == {"include_usage": True}
    assert captured["extra_body"] == {"reasoning_effort": "high"}
    assert "user" not in captured
    result_calls = getattr(result.message, "tool_calls", None)
    assert result_calls is not None
    assert result_calls[0].function.arguments == '{"color":"red"}'
    assert result.usage.prompt_tokens == 21
    assert result.usage.completion_tokens == 8
    assert result.usage.cost_usd == 0.0


def test_poe_reasoning_off_omits_custom_thinking_parameter():
    client = OpenRouterClient(api_key="test-key", base_url="https://api.poe.com/v1")
    assert client._extra_body("off") == {}


def test_poe_generate_image_declines_openrouter_only_contract():
    client = OpenRouterClient(api_key="test-key", base_url="https://api.poe.com/v1")
    assert client.generate_image("image-model", "prompt") is None


def test_chat_blocking_sends_session_id_as_user_for_sticky_routing():
    client = OpenRouterClient(api_key="test-key", session_id="sticky-123")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="hi", tool_calls=None, reasoning=None, reasoning_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

    client._client.chat.completions.create = fake_create  # ty: ignore[invalid-assignment]
    client.chat(model="anthropic/claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert captured["user"] == "sticky-123"
    assert captured["extra_body"] == {"usage": {"include": True}, "reasoning": {"effort": "medium"}}


def _strict_test_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }


def test_plan_json_routing_uses_explicit_provider_not_model_name():
    clients = [
        OpenRouterClient(api_key="test", provider="poe"),
        OpenRouterClient(api_key="test", provider="openai"),
        OpenRouterClient(api_key="test", provider="openrouter"),
        OpenRouterClient(
            api_key="test",
            base_url="https://compatible.invalid/v1",
            provider="openai_compatible",
        ),
    ]

    assert [client.provider for client in clients] == [
        LLMProvider.POE,
        LLMProvider.OPENAI,
        LLMProvider.OPENROUTER,
        LLMProvider.OPENAI_COMPATIBLE,
    ]
    assert [client.plan_json_mode for client in clients] == [
        PlanJSONMode.RESPONSES,
        PlanJSONMode.RESPONSES,
        PlanJSONMode.CHAT_RESPONSE_FORMAT,
        PlanJSONMode.TOOL_CALL,
    ]
    assert [client.supports_structured_plan_json for client in clients] == [True, True, True, False]


@pytest.mark.parametrize("provider", ["poe", "openai"])
def test_responses_plan_json_uses_text_format_and_maps_usage(provider):
    client = OpenRouterClient(api_key="test", provider=provider)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            status="completed",
            output_text=json.dumps({"answer": "ready"}),
            output=[],
            usage=SimpleNamespace(
                input_tokens=11,
                output_tokens=7,
                input_tokens_details=SimpleNamespace(cached_tokens=3),
                output_tokens_details=SimpleNamespace(reasoning_tokens=2),
            ),
        )

    client._client.responses.create = fake_create  # ty: ignore[invalid-assignment]
    result = client.generate_plan_json(
        model="same-model-id",
        system_prompt="system",
        user_prompt="user",
        schema=_strict_test_schema(),
        reasoning="high",
    )

    assert captured["instructions"] == "system"
    assert captured["input"] == "user"
    assert captured["store"] is False
    assert captured["reasoning"] == {"effort": "high", "summary": "auto"}
    assert captured["text"] == {
        "format": {
            "type": "json_schema",
            "name": "project_plan",
            "strict": True,
            "schema": _strict_test_schema(),
        }
    }
    assert result.data == {"answer": "ready"}
    assert result.usage == Usage(prompt_tokens=11, completion_tokens=7, reasoning_tokens=2, cached_tokens=3)
    assert client.total_usage.prompt_tokens == 11


def test_responses_plan_json_stream_uses_terminal_response_and_separates_reasoning():
    client = OpenRouterClient(api_key="test", provider="poe")
    captured = {}
    final = SimpleNamespace(
        status="completed",
        output_text='{"answer":"terminal"}',
        output=[],
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )
    events = [
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="think"),
        SimpleNamespace(type="response.output_text.delta", delta='{"answer":"streamed"}'),
        SimpleNamespace(type="response.completed", response=final),
    ]

    def fake_create(**kwargs):
        captured.update(kwargs)
        return iter(events)

    client._client.responses.create = fake_create  # ty: ignore[invalid-assignment]
    deltas = []
    result = client.generate_plan_json(
        model="same-model-id",
        system_prompt="system",
        user_prompt="user",
        schema=_strict_test_schema(),
        stream=True,
        on_delta=lambda kind, text: deltas.append((kind, text)),
    )

    assert captured["stream"] is True
    assert result.data == {"answer": "terminal"}
    assert deltas == [("reasoning", "think"), ("content", '{"answer":"streamed"}')]
    assert result.usage.prompt_tokens == 5
    assert result.usage.completion_tokens == 3


def test_responses_plan_json_rejects_refusal_incomplete_and_non_object():
    client = OpenRouterClient(api_key="test", provider="openai")
    billed_usage = SimpleNamespace(
        input_tokens=9,
        output_tokens=4,
        input_tokens_details=SimpleNamespace(cached_tokens=2),
        output_tokens_details=SimpleNamespace(reasoning_tokens=1),
        cost=0.02,
    )
    responses = [
        SimpleNamespace(
            status="completed",
            output_text="",
            output=[SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="cannot comply")])],
            usage=billed_usage,
        ),
        SimpleNamespace(status="incomplete", output_text='{"answer":"x"}', output=[], usage=None),
        SimpleNamespace(status="completed", output_text="[]", output=[], usage=None),
    ]
    client._client.responses.create = lambda **_kwargs: responses.pop(0)  # ty: ignore[invalid-assignment]

    with pytest.raises(RuntimeError, match="refused") as refusal_error:
        client.generate_plan_json(model="model", system_prompt="s", user_prompt="u", schema=_strict_test_schema())
    assert client.total_usage == Usage(
        prompt_tokens=9,
        completion_tokens=4,
        reasoning_tokens=1,
        cached_tokens=2,
        cost_usd=0.02,
    )
    assert refusal_error.value.usage.cost_usd == 0.02  # ty: ignore[unresolved-attribute]
    with pytest.raises(RuntimeError, match="incomplete"):
        client.generate_plan_json(model="model", system_prompt="s", user_prompt="u", schema=_strict_test_schema())
    with pytest.raises(ValueError, match="root must be an object"):
        client.generate_plan_json(model="model", system_prompt="s", user_prompt="u", schema=_strict_test_schema())


def test_openrouter_plan_json_uses_chat_response_format_without_tools():
    client = OpenRouterClient(api_key="test", provider="openrouter", session_id="sticky")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content='{"answer":"ready"}', refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

    client._client.chat.completions.create = fake_create  # ty: ignore[invalid-assignment]
    result = client.generate_plan_json(
        model="same-model-id",
        system_prompt="system",
        user_prompt="user",
        schema=_strict_test_schema(),
        reasoning="high",
    )

    assert "tools" not in captured
    assert captured["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "project_plan",
            "strict": True,
            "schema": _strict_test_schema(),
        },
    }
    assert captured["extra_body"] == {
        "usage": {"include": True},
        "reasoning": {"effort": "high"},
        "provider": {"require_parameters": True},
    }
    assert captured["user"] == "sticky"
    assert result.data == {"answer": "ready"}


def test_strict_schema_is_rejected_before_any_provider_request():
    client = OpenRouterClient(api_key="test", provider="poe")
    called = False

    def fake_create(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    client._client.responses.create = fake_create  # ty: ignore[invalid-assignment]
    invalid_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {"answer": {"const": "yes"}},
    }

    with pytest.raises(StructuredOutputSchemaError):
        client.generate_plan_json(
            model="model",
            system_prompt="system",
            user_prompt="user",
            schema=invalid_schema,
        )
    assert called is False


def test_generic_compatible_provider_keeps_planner_tool_call_fallback():
    client = OpenRouterClient(
        api_key="test",
        base_url="https://compatible.invalid/v1",
        provider="openai_compatible",
    )
    assert client.plan_json_mode is PlanJSONMode.TOOL_CALL
    with pytest.raises(RuntimeError, match="tool-call fallback"):
        client.generate_plan_json(
            model="model",
            system_prompt="system",
            user_prompt="user",
            schema=_strict_test_schema(),
        )


def test_generic_compatible_requires_explicit_endpoint_and_dedicated_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-reused")
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="explicit base_url"):
        OpenRouterClient(provider="openai_compatible")
    with pytest.raises(RuntimeError, match="OPENAI_COMPATIBLE_API_KEY"):
        OpenRouterClient(
            base_url="https://compatible.invalid/v1",
            provider="openai_compatible",
        )


@pytest.mark.parametrize(
    ("provider", "invalid_mode"),
    [
        ("poe", "chat_response_format"),
        ("openai", "tool_call"),
        ("openrouter", "responses"),
    ],
)
def test_known_provider_plan_transport_cannot_be_overridden(provider, invalid_mode):
    with pytest.raises(RuntimeError, match="requires Planner JSON mode"):
        OpenRouterClient(api_key="test", provider=provider, plan_json_mode=invalid_mode)


def test_explicit_provider_rejects_a_different_known_provider_endpoint():
    with pytest.raises(RuntimeError, match="does not match endpoint provider"):
        OpenRouterClient(
            api_key="test",
            base_url="https://api.poe.com/v1",
            provider="openai",
        )


@pytest.mark.parametrize("schema_name", ["contains spaces", "x" * 65])
def test_invalid_schema_name_is_rejected_before_request(schema_name):
    client = OpenRouterClient(api_key="test", provider="poe")
    called = False

    def fake_create(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    client._client.responses.create = fake_create  # ty: ignore[invalid-assignment]
    with pytest.raises(StructuredOutputSchemaError, match="schema_name"):
        client.generate_plan_json(
            model="model",
            system_prompt="system",
            user_prompt="user",
            schema=_strict_test_schema(),
            schema_name=schema_name,
        )
    assert called is False


def test_strict_schema_guard_rejects_unknown_keyword_invalid_type_and_array_without_items():
    client = OpenRouterClient(api_key="test", provider="poe")
    invalid_schemas = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string", "bogus": True}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "str"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "array"}},
        },
    ]

    for schema in invalid_schemas:
        with pytest.raises(StructuredOutputSchemaError):
            client.generate_plan_json(
                model="model",
                system_prompt="system",
                user_prompt="user",
                schema=schema,
            )
