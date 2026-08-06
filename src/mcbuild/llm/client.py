"""OpenRouter chat client: tool calling + images + reasoning + usage/cost tracking."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from typing import Any, cast
from urllib.parse import urlparse

from openai import OpenAI
from PIL import Image

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
POE_BASE_URL = "https://api.poe.com/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# (kind, text) delta callback, kind in {"reasoning", "content"}.
OnDelta = Callable[[str, str], None]


class LLMProvider(StrEnum):
    """Explicit provider identity; routing never depends on a model id."""

    OPENROUTER = "openrouter"
    POE = "poe"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class PlanJSONMode(StrEnum):
    """Provider capability used only by the project Planner."""

    RESPONSES = "responses"
    CHAT_RESPONSE_FORMAT = "chat_response_format"
    TOOL_CALL = "tool_call"


class StructuredOutputSchemaError(ValueError):
    """Raised before a request when a schema cannot be used in strict mode."""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def cache_rate(self) -> float:
        """Fraction of prompt_tokens served from cache (0.0-1.0), or 0.0 if none/unknown."""
        return self.cached_tokens / self.prompt_tokens if self.prompt_tokens else 0.0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cached_tokens += other.cached_tokens
        self.cost_usd += other.cost_usd


class StructuredOutputResponseError(RuntimeError):
    """A billed provider-level structured-output failure."""

    def __init__(self, message: str, usage: Usage):
        super().__init__(message)
        self.usage = usage


class StructuredOutputParseError(ValueError):
    """A billed response whose output could not be decoded as a JSON object."""

    def __init__(self, message: str, usage: Usage):
        super().__init__(message)
        self.usage = usage


@dataclass
class ChatResult:
    message: object
    usage: Usage
    raw: object = None


@dataclass
class PlanJSONResult:
    """One schema-constrained Planner payload plus provider usage metadata."""

    data: dict[str, Any]
    usage: Usage
    raw: object = None


@dataclass
class _StreamFnCall:
    name: str | None
    arguments: str


@dataclass
class _StreamToolCall:
    id: str | None
    function: _StreamFnCall
    type: str = "function"


@dataclass
class StreamedMessage:
    """Duck-typed like an OpenAI ChatCompletionMessage: content/tool_calls/reasoning*."""

    content: str | None = None
    reasoning: str | None = None
    reasoning_details: list | None = None
    tool_calls: list[_StreamToolCall] | None = None
    refusal: str | None = None


def _rd_field(piece, key):
    if isinstance(piece, dict):
        return piece.get(key)
    return getattr(piece, key, None)


def _merge_reasoning_detail(acc: dict[int, dict], fragment) -> None:
    """Merge one streamed reasoning_details fragment into its per-index block.

    Streaming delivers a reasoning block in pieces: `text`/`data` arrive across several
    fragments and the `signature` usually lands in a later one, all keyed by `index`.
    We reassemble complete blocks so the signature stays attached to its full text — a
    naive concat would send Anthropic a thinking block with a mismatched/missing
    signature and the request would be rejected.
    """
    idx = _rd_field(fragment, "index")
    idx = int(idx) if idx is not None else 0
    entry = acc.setdefault(idx, {})
    for key in ("type", "format", "id"):
        val = _rd_field(fragment, key)
        if val and not entry.get(key):
            entry[key] = val
    for key in ("text", "data", "summary"):
        val = _rd_field(fragment, key)
        if val:
            entry[key] = entry.get(key, "") + val
    sig = _rd_field(fragment, "signature")
    if sig:  # last non-empty wins; the signature covers the whole reassembled block
        entry["signature"] = sig


def consume_stream(chunks: Iterable, on_delta: OnDelta | None = None) -> tuple[StreamedMessage, object | None]:
    """Accumulate a stream of chat-completion-chunk objects into a full message.

    Works against any iterable of duck-typed chunks (real OpenAI SDK stream chunks,
    or plain objects/SimpleNamespaces in tests) each exposing `.choices[0].delta`
    (with optional `.content`, `.reasoning`, `.reasoning_details`, `.tool_calls`)
    and an optional `.usage` (populated on the final chunk when requested).
    """
    content_parts: list[str] = []
    refusal_parts: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_acc: dict[int, dict] = {}
    tool_call_acc: dict[int, dict] = {}
    usage_obj = None

    for chunk in chunks:
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage_obj = chunk_usage

        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = choices[0].delta

        content_piece = getattr(delta, "content", None)
        if content_piece:
            content_parts.append(content_piece)
            if on_delta:
                on_delta("content", content_piece)

        refusal_piece = getattr(delta, "refusal", None)
        if refusal_piece:
            refusal_parts.append(refusal_piece)

        reasoning_piece = getattr(delta, "reasoning", None)
        if reasoning_piece:
            reasoning_parts.append(reasoning_piece)
            if on_delta:
                on_delta("reasoning", reasoning_piece)

        details_piece = getattr(delta, "reasoning_details", None)
        if details_piece:
            for fragment in details_piece:
                _merge_reasoning_detail(reasoning_acc, fragment)

        delta_tool_calls = getattr(delta, "tool_calls", None)
        if delta_tool_calls:
            for tc in delta_tool_calls:
                idx = getattr(tc, "index", 0)
                entry = tool_call_acc.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                if getattr(tc, "id", None):
                    entry["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        entry["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        entry["arguments"] += fn.arguments

    tool_calls = [
        _StreamToolCall(id=v["id"], function=_StreamFnCall(name=v["name"], arguments=v["arguments"]))
        for _, v in sorted(tool_call_acc.items())
    ] or None

    reasoning_details = [reasoning_acc[i] for i in sorted(reasoning_acc)] or None
    message = StreamedMessage(
        content="".join(content_parts) or None,
        reasoning="".join(reasoning_parts) or None,
        reasoning_details=reasoning_details,
        tool_calls=tool_calls,
        refusal="".join(refusal_parts) or None,
    )
    return message, usage_obj


def consume_responses_stream(
    events: Iterable, on_delta: OnDelta | None = None
) -> tuple[str, object | None, str | None]:
    """Collect Responses API SSE events without mixing reasoning into JSON output."""

    output_parts: list[str] = []
    refusal_parts: list[str] = []
    final_response = None
    for event in events:
        event_type = _rd_field(event, "type") or ""
        delta = _rd_field(event, "delta")
        if event_type == "response.output_text.delta" and isinstance(delta, str):
            output_parts.append(delta)
            if on_delta:
                on_delta("content", delta)
        elif event_type == "response.refusal.delta" and isinstance(delta, str):
            refusal_parts.append(delta)
        elif "reasoning" in event_type and event_type.endswith(".delta") and isinstance(delta, str):
            if on_delta:
                on_delta("reasoning", delta)

        response = _rd_field(event, "response")
        if response is not None and event_type in {
            "response.completed",
            "response.failed",
            "response.incomplete",
        }:
            final_response = response

    refusal = "".join(refusal_parts) or None
    return "".join(output_parts), final_response, refusal


def image_to_data_url(img: Image.Image) -> str:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        return False
    return status in RETRYABLE_STATUS_CODES


def _provider_from_url(base_url: str) -> LLMProvider:
    host = (urlparse(base_url).hostname or "").lower()
    if host == "api.poe.com":
        return LLMProvider.POE
    if host == "openrouter.ai":
        return LLMProvider.OPENROUTER
    if host == "api.openai.com":
        return LLMProvider.OPENAI
    return LLMProvider.OPENAI_COMPATIBLE


def _parse_provider(value: str | LLMProvider) -> LLMProvider:
    try:
        return value if isinstance(value, LLMProvider) else LLMProvider(value.strip().lower())
    except (AttributeError, ValueError) as error:
        allowed = ", ".join(item.value for item in LLMProvider)
        raise RuntimeError(f"Unknown LLM provider {value!r}; expected one of: {allowed}.") from error


def _parse_plan_json_mode(value: str | PlanJSONMode) -> PlanJSONMode:
    try:
        return value if isinstance(value, PlanJSONMode) else PlanJSONMode(value.strip().lower())
    except (AttributeError, ValueError) as error:
        allowed = ", ".join(item.value for item in PlanJSONMode)
        raise RuntimeError(f"Unknown Planner JSON mode {value!r}; expected one of: {allowed}.") from error


def _default_plan_json_mode(provider: LLMProvider) -> PlanJSONMode:
    if provider in {LLMProvider.POE, LLMProvider.OPENAI}:
        return PlanJSONMode.RESPONSES
    if provider is LLMProvider.OPENROUTER:
        return PlanJSONMode.CHAT_RESPONSE_FORMAT
    return PlanJSONMode.TOOL_CALL


def validate_strict_json_schema(schema: dict[str, Any]) -> None:
    """Reject schema shapes unsupported by OpenAI-style strict Structured Outputs.

    This is intentionally narrower than general JSON Schema. It catches the failure modes
    that otherwise reach the provider late: a non-object/union root, ``oneOf`` or other
    unsupported composition, optional object fields, missing ``additionalProperties:false``,
    and dangling local definition references.
    """

    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise StructuredOutputSchemaError("Strict structured-output schema root must be an object.")
    if "anyOf" in schema:
        raise StructuredOutputSchemaError("Strict structured-output schema root cannot be anyOf.")

    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        raise StructuredOutputSchemaError("$defs must be an object when present.")
    unsupported = {
        "oneOf",
        "allOf",
        "not",
        "if",
        "then",
        "else",
        "dependentRequired",
        "dependentSchemas",
        "default",
        "patternProperties",
        "minProperties",
        "maxProperties",
        "propertyNames",
        "unevaluatedProperties",
        "contains",
        "uniqueItems",
    }
    allowed_keywords = {
        "$defs",
        "$ref",
        "additionalProperties",
        "anyOf",
        "description",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
        "properties",
        "required",
        "title",
        "type",
    }

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            raise StructuredOutputSchemaError(f"{path} must be a JSON Schema object.")
        if "const" in node:
            raise StructuredOutputSchemaError(f"{path} uses unsupported keyword 'const'; use a single-value enum.")
        found = sorted(unsupported.intersection(node))
        if found:
            raise StructuredOutputSchemaError(f"{path} uses unsupported keyword {found[0]!r}; use anyOf.")
        unknown = sorted(set(node) - allowed_keywords)
        if unknown:
            raise StructuredOutputSchemaError(f"{path} uses unsupported keyword {unknown[0]!r}.")
        if not any(keyword in node for keyword in ("$ref", "anyOf", "type", "enum")):
            raise StructuredOutputSchemaError(f"{path} does not declare a type, enum, anyOf, or $ref.")

        node_type = node.get("type")
        if node_type is not None and node_type not in {
            "object",
            "array",
            "string",
            "number",
            "integer",
            "boolean",
            "null",
        }:
            raise StructuredOutputSchemaError(f"{path} has unsupported type {node_type!r}.")
        enum = node.get("enum")
        if enum is not None and (not isinstance(enum, list) or not enum):
            raise StructuredOutputSchemaError(f"{path}.enum must be a non-empty array.")

        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
                raise StructuredOutputSchemaError(f"{path} has an unsupported $ref {reference!r}.")
            definition_name = reference.removeprefix("#/$defs/")
            if definition_name not in definitions:
                raise StructuredOutputSchemaError(f"{path} references missing definition {definition_name!r}.")

        if node.get("type") == "object":
            properties = node.get("properties")
            if not isinstance(properties, dict):
                raise StructuredOutputSchemaError(f"{path}.properties must be an object.")
            if node.get("additionalProperties") is not False:
                raise StructuredOutputSchemaError(f"{path} must set additionalProperties to false.")
            required = node.get("required")
            if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
                raise StructuredOutputSchemaError(f"{path}.required must list every property.")
            if len(required) != len(set(required)) or set(required) != set(properties):
                raise StructuredOutputSchemaError(f"{path}.required must contain every property exactly once.")
            for name, child in properties.items():
                walk(child, f"{path}.properties.{name}")

        if node.get("type") == "array" and "items" not in node:
            raise StructuredOutputSchemaError(f"{path} array schema must define items.")

        any_of = node.get("anyOf")
        if any_of is not None:
            if not isinstance(any_of, list) or not any_of:
                raise StructuredOutputSchemaError(f"{path}.anyOf must be a non-empty array.")
            for index, child in enumerate(any_of):
                walk(child, f"{path}.anyOf[{index}]")

        items = node.get("items")
        if items is not None:
            walk(items, f"{path}.items")

        nested_definitions = node.get("$defs")
        if nested_definitions is not None:
            if not isinstance(nested_definitions, dict):
                raise StructuredOutputSchemaError(f"{path}.$defs must be an object.")
            for name, child in nested_definitions.items():
                walk(child, f"{path}.$defs.{name}")

    walk(schema, "$")


def _strip_cache_control(value: Any) -> Any:
    """Copy a message value without OpenRouter/Anthropic cache annotations."""
    if isinstance(value, dict):
        return {key: _strip_cache_control(item) for key, item in value.items() if key != "cache_control"}
    if isinstance(value, list):
        return [_strip_cache_control(item) for item in value]
    return value


def _response_output_text(response: object | None) -> str | None:
    if response is None:
        return None
    output_text = _rd_field(response, "output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    parts: list[str] = []
    for item in _rd_field(response, "output") or []:
        for content in _rd_field(item, "content") or []:
            if _rd_field(content, "type") == "output_text":
                text = _rd_field(content, "text")
                if isinstance(text, str):
                    parts.append(text)
    return "".join(parts) or None


def _response_refusal(response: object | None) -> str | None:
    if response is None:
        return None
    parts: list[str] = []
    for item in _rd_field(response, "output") or []:
        for content in _rd_field(item, "content") or []:
            if _rd_field(content, "type") == "refusal" or _rd_field(content, "refusal") is not None:
                refusal = _rd_field(content, "refusal") or _rd_field(content, "text")
                if isinstance(refusal, str):
                    parts.append(refusal)
    return "".join(parts) or None


def _parse_json_object(text: str | None) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Structured output response did not contain JSON text.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Structured output was invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise ValueError("Structured output JSON root must be an object.")
    return value


class OpenRouterClient:
    """OpenAI-compatible chat client with OpenRouter defaults and Poe support."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        session_id: str | None = None,
        *,
        provider: str | LLMProvider | None = None,
        plan_json_mode: str | PlanJSONMode | None = None,
    ):
        base_url = base_url or os.environ.get("MCBUILD_LLM_BASE_URL")
        provider_value = provider or os.environ.get("MCBUILD_LLM_PROVIDER")
        if provider_value is not None:
            resolved_provider = _parse_provider(provider_value)
        elif base_url is not None:
            resolved_provider = _provider_from_url(base_url)
        elif os.environ.get("OPENROUTER_API_KEY"):
            resolved_provider = LLMProvider.OPENROUTER
        elif os.environ.get("POE_API_KEY"):
            resolved_provider = LLMProvider.POE
        elif os.environ.get("OPENAI_API_KEY"):
            resolved_provider = LLMProvider.OPENAI
        else:
            # Preserve the historical error/default when no provider is configured.
            resolved_provider = LLMProvider.OPENROUTER

        if provider_value is not None and base_url is not None:
            endpoint_provider = _provider_from_url(base_url)
            if endpoint_provider is not LLMProvider.OPENAI_COMPATIBLE and endpoint_provider is not resolved_provider:
                raise RuntimeError(
                    f"Provider {resolved_provider.value!r} does not match endpoint provider "
                    f"{endpoint_provider.value!r}."
                )
        if resolved_provider is LLMProvider.OPENAI_COMPATIBLE and base_url is None:
            raise RuntimeError("openai_compatible requires an explicit base_url.")
        if base_url is None:
            base_url = {
                LLMProvider.OPENROUTER: DEFAULT_BASE_URL,
                LLMProvider.POE: POE_BASE_URL,
                LLMProvider.OPENAI: OPENAI_BASE_URL,
                LLMProvider.OPENAI_COMPATIBLE: DEFAULT_BASE_URL,
            }[resolved_provider]

        key_name = {
            LLMProvider.OPENROUTER: "OPENROUTER_API_KEY",
            LLMProvider.POE: "POE_API_KEY",
            LLMProvider.OPENAI: "OPENAI_API_KEY",
            LLMProvider.OPENAI_COMPATIBLE: "OPENAI_COMPATIBLE_API_KEY",
        }[resolved_provider]
        api_key = api_key or os.environ.get(key_name)
        if not api_key:
            raise RuntimeError(f"{key_name} is not set. Put it in the environment or a .env file.")

        mode_value = plan_json_mode or os.environ.get("MCBUILD_PLAN_JSON_MODE")
        self.provider = resolved_provider
        expected_mode = _default_plan_json_mode(resolved_provider)
        requested_mode = _parse_plan_json_mode(mode_value) if mode_value is not None else expected_mode
        if resolved_provider is not LLMProvider.OPENAI_COMPATIBLE and requested_mode is not expected_mode:
            raise RuntimeError(
                f"Provider {resolved_provider.value!r} requires Planner JSON mode {expected_mode.value!r}."
            )
        self.plan_json_mode = requested_mode
        self.base_url = base_url
        self._is_poe = resolved_provider is LLMProvider.POE
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.total_usage = Usage()
        # A stable `user` id, sent with every request in this run, lets OpenRouter route
        # repeat calls to the same upstream/provider instance — without it, requests can
        # bounce between backends and lose the prompt-cache hits _with_prompt_caching relies on.
        self.session_id = session_id or uuid.uuid4().hex

    def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        reasoning: str = "medium",
        max_retries: int = 4,
        stream: bool = False,
        on_delta: OnDelta | None = None,
    ) -> ChatResult:
        if stream:
            return self._chat_streaming(model, messages, tools, reasoning, max_retries, on_delta)
        return self._chat_blocking(model, messages, tools, reasoning, max_retries)

    def _extra_body(self, reasoning: str) -> dict:
        if self.provider is LLMProvider.POE:
            return {"reasoning_effort": reasoning} if reasoning and reasoning != "off" else {}
        if self.provider is not LLMProvider.OPENROUTER:
            return {}
        extra_body: dict = {"usage": {"include": True}}
        if reasoning and reasoning != "off":
            extra_body["reasoning"] = {"effort": reasoning}
        return extra_body

    def _request_messages(self, messages: list[dict]) -> list[dict]:
        if self.provider is LLMProvider.OPENROUTER:
            return messages
        # Standard OpenAI-compatible schemas do not define OpenRouter/Anthropic cache
        # or signed-reasoning extensions. Preserve normal multimodal message parts.
        return [
            {key: _strip_cache_control(value) for key, value in message.items() if key != "reasoning_details"}
            for message in messages
        ]

    def _chat_request_kwargs(
        self, model: str, messages: list[dict], tools: list[dict] | None, reasoning: str
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": cast(Any, self._request_messages(messages)),
        }
        if tools is not None:
            kwargs["tools"] = cast(Any, tools)
        extra_body = self._extra_body(reasoning)
        if extra_body:
            kwargs["extra_body"] = extra_body
        if self.provider is LLMProvider.OPENROUTER:
            kwargs["user"] = self.session_id
        elif self.provider is LLMProvider.OPENAI and reasoning and reasoning != "off":
            kwargs["reasoning_effort"] = reasoning
        return kwargs

    def _usage_from_obj(self, usage_obj: object | None) -> Usage:
        completion_details = getattr(usage_obj, "completion_tokens_details", None)
        prompt_details = getattr(usage_obj, "prompt_tokens_details", None)
        return Usage(
            prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
            reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
            cached_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
            cost_usd=getattr(usage_obj, "cost", 0.0) or 0.0,
        )

    def _responses_usage_from_obj(self, usage_obj: object | None) -> Usage:
        output_details = _rd_field(usage_obj, "output_tokens_details")
        input_details = _rd_field(usage_obj, "input_tokens_details")
        return Usage(
            prompt_tokens=_rd_field(usage_obj, "input_tokens") or 0,
            completion_tokens=_rd_field(usage_obj, "output_tokens") or 0,
            reasoning_tokens=_rd_field(output_details, "reasoning_tokens") or 0,
            cached_tokens=_rd_field(input_details, "cached_tokens") or 0,
            cost_usd=_rd_field(usage_obj, "cost") or 0.0,
        )

    @property
    def supports_structured_plan_json(self) -> bool:
        """Whether Planner JSON has an explicitly configured structured transport."""
        return self.plan_json_mode is not PlanJSONMode.TOOL_CALL

    def generate_plan_json(
        self,
        model: str,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str = "project_plan",
        reasoning: str = "medium",
        max_retries: int = 4,
        stream: bool = False,
        on_delta: OnDelta | None = None,
    ) -> PlanJSONResult:
        """Generate one strict Planner JSON object using the configured provider capability.

        This method deliberately does not fall back between transports. A generic compatible
        provider advertises ``tool_call`` and is handled by the Planner's legacy loop; a failed
        strict request remains a failed strict request.
        """
        validate_strict_json_schema(schema)
        if not isinstance(schema_name, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", schema_name) is None:
            raise StructuredOutputSchemaError("Structured-output schema_name must match [A-Za-z0-9_-]{1,64}.")
        if self.plan_json_mode is PlanJSONMode.RESPONSES:
            return self._generate_plan_json_responses(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
                schema_name=schema_name,
                reasoning=reasoning,
                max_retries=max_retries,
                stream=stream,
                on_delta=on_delta,
            )
        if self.plan_json_mode is PlanJSONMode.CHAT_RESPONSE_FORMAT:
            return self._generate_plan_json_chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
                schema_name=schema_name,
                reasoning=reasoning,
                max_retries=max_retries,
                stream=stream,
                on_delta=on_delta,
            )
        raise RuntimeError(
            "This provider is configured for Planner tool-call fallback; run the Planner through run_planner instead."
        )

    def _generate_plan_json_responses(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        reasoning: str,
        max_retries: int,
        stream: bool,
        on_delta: OnDelta | None,
    ) -> PlanJSONResult:
        responses = getattr(self._client, "responses", None)
        create = getattr(responses, "create", None)
        if not callable(create):
            raise RuntimeError("The installed OpenAI SDK does not expose the Responses API.")

        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system_prompt,
            "input": user_prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            "store": False,
        }
        if reasoning and reasoning != "off":
            kwargs["reasoning"] = {"effort": reasoning, "summary": "auto"}
        if stream:
            kwargs["stream"] = True

        attempt = 0
        response: object | None = None
        while True:
            try:
                response_or_events = create(**kwargs)
                if stream:
                    streamed_text, response, streamed_refusal = consume_responses_stream(response_or_events, on_delta)
                    if response is None:
                        raise RuntimeError("Responses stream ended without a terminal response event.")
                    refusal = streamed_refusal or _response_refusal(response)
                    output_text = _response_output_text(response) or streamed_text
                else:
                    response = response_or_events
                    refusal = _response_refusal(response)
                    output_text = _response_output_text(response)
                break
            except Exception as error:
                attempt += 1
                if stream or attempt > max_retries or not _is_retryable(error):
                    raise
                time.sleep(min(2**attempt, 30))

        usage = self._responses_usage_from_obj(_rd_field(response, "usage"))
        self.total_usage.add(usage)
        status = _rd_field(response, "status")
        if status in {"failed", "incomplete", "cancelled"}:
            raise StructuredOutputResponseError(
                f"Responses structured-output request ended with status {status!r}.", usage
            )
        if refusal:
            raise StructuredOutputResponseError(f"Responses structured-output request was refused: {refusal}", usage)
        try:
            data = _parse_json_object(output_text)
        except ValueError as error:
            raise StructuredOutputParseError(str(error), usage) from error
        return PlanJSONResult(data=data, usage=usage, raw=None if stream else response)

    def _generate_plan_json_chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        reasoning: str,
        max_retries: int,
        stream: bool,
        on_delta: OnDelta | None,
    ) -> PlanJSONResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs = self._chat_request_kwargs(model, messages, None, reasoning)
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
        if self.provider is LLMProvider.OPENROUTER:
            extra_body = dict(kwargs.get("extra_body", {}))
            extra_body["provider"] = {"require_parameters": True}
            kwargs["extra_body"] = extra_body
        if stream:
            kwargs.update(stream=True, stream_options={"include_usage": True})

        attempt = 0
        while True:
            try:
                response_or_chunks = self._client.chat.completions.create(**kwargs)
                if stream:
                    message, usage_obj = consume_stream(response_or_chunks, on_delta)
                    raw = None
                else:
                    raw = response_or_chunks
                    message = response_or_chunks.choices[0].message
                    usage_obj = getattr(response_or_chunks, "usage", None)
                break
            except Exception as error:
                attempt += 1
                if stream or attempt > max_retries or not _is_retryable(error):
                    raise
                time.sleep(min(2**attempt, 30))

        usage = self._usage_from_obj(usage_obj)
        self.total_usage.add(usage)
        refusal = _rd_field(message, "refusal")
        if isinstance(refusal, str) and refusal:
            raise StructuredOutputResponseError(f"Chat structured-output request was refused: {refusal}", usage)
        try:
            data = _parse_json_object(_rd_field(message, "content"))
        except ValueError as error:
            raise StructuredOutputParseError(str(error), usage) from error
        return PlanJSONResult(data=data, usage=usage, raw=raw)

    def _chat_blocking(
        self, model: str, messages: list[dict], tools: list[dict] | None, reasoning: str, max_retries: int
    ) -> ChatResult:
        request_kwargs = self._chat_request_kwargs(model, messages, tools, reasoning)

        attempt = 0
        resp = None
        while True:
            try:
                resp = self._client.chat.completions.create(**request_kwargs)
                break
            except Exception as e:
                attempt += 1
                if attempt > max_retries or not _is_retryable(e):
                    raise
                time.sleep(min(2**attempt, 30))

        choice = resp.choices[0]
        usage = self._usage_from_obj(getattr(resp, "usage", None))
        self.total_usage.add(usage)
        return ChatResult(message=choice.message, usage=usage, raw=resp)

    def _chat_streaming(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        reasoning: str,
        max_retries: int,
        on_delta: OnDelta | None,
    ) -> ChatResult:
        request_kwargs = self._chat_request_kwargs(model, messages, tools, reasoning)
        request_kwargs.update(stream=True, stream_options={"include_usage": True})

        attempt = 0
        while True:
            try:
                stream = self._client.chat.completions.create(**request_kwargs)
                message, usage_obj = consume_stream(stream, on_delta)
                break
            except Exception as e:
                attempt += 1
                if attempt > max_retries or not _is_retryable(e):
                    raise
                time.sleep(min(2**attempt, 30))

        usage = self._usage_from_obj(usage_obj)
        self.total_usage.add(usage)
        return ChatResult(message=message, usage=usage, raw=None)

    def generate_image(self, model: str, prompt: str) -> bytes | None:
        """Best-effort concept-reference image generation. Returns None on any failure."""
        if self.provider is not LLMProvider.OPENROUTER:
            # `modalities` below is an OpenRouter-specific contract. Avoid spending on
            # any provider whose response cannot satisfy this method's image extraction.
            return None
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                user=self.session_id,
                extra_body={"modalities": ["image", "text"]},
            )
            choice = resp.choices[0]
            images = getattr(choice.message, "images", None)
            if not images:
                return None
            first = images[0]
            image_url = (
                first.get("image_url", {}).get("url")
                if isinstance(first, dict)
                else getattr(getattr(first, "image_url", None), "url", None)
            )
            if not image_url or not image_url.startswith("data:"):
                return None
            b64_data = image_url.split(",", 1)[1]
            return base64.b64decode(b64_data)
        except Exception:
            return None
