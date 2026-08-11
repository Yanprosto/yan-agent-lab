import copy
import json
from dataclasses import dataclass

import pytest

from mcbuild.config import Config
from mcbuild.llm.client import (
    ChatResult,
    PlanJSONMode,
    PlanJSONResult,
    Usage,
    validate_strict_json_schema,
)
from mcbuild.orchestrator import planner as planner_module
from mcbuild.orchestrator.models import ProjectConfig
from mcbuild.orchestrator.planner import (
    PLANNER_REVIEW_TOOLS,
    PLANNER_TOOLS,
    PROJECT_PLAN_JSON_SCHEMA,
    run_planner,
)
from mcbuild.orchestrator.prompts import build_planner_system_prompt
from mcbuild.orchestrator.run_dir import ProjectRunDir


@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Message:
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None
    reasoning_details: list | None = None


def _rectangle(min_x, max_x, min_z, max_z):
    return {
        "op": "shape",
        "shape": {
            "kind": "axis_aligned_rectangle",
            "min_x": min_x,
            "max_x": max_x,
            "min_z": min_z,
            "max_z": max_z,
        },
    }


def _package(package_id, min_x, max_x, *, anchor_x):
    return {
        "id": package_id,
        "name": package_id.replace("_", " ").title(),
        "semantic_type": "building",
        "objective": f"Build {package_id}",
        "instances": [{"id": "main", "anchor": [anchor_x, 0, 0], "rotation": 0}],
        "responsibility": {
            "boundary_kind": "hard",
            "core": _rectangle(min_x, max_x, -3, 3),
            "halo": None,
            "min_y": 0,
            "max_y": 8,
            "write_policy": "preserve_existing",
        },
        "depends_on": [],
        "neighbor_context": [],
        "worker_brief": f"Build only {package_id}",
        "acceptance_criteria": ["complete structure"],
        "requested_views": [{"yaw": 0}],
    }


def _plan(*, overlap):
    second_min = 0 if overlap else 6
    return {
        "schema_version": 1,
        "title": "Fortified Test Site",
        "project_summary": "Two semantic structures.",
        "site": {"min_x": -20, "max_x": 20, "min_z": -12, "max_z": 12, "base_y": 0},
        "style_bible": {
            "architectural_style": "medieval",
            "scale_and_massing": "compact",
            "primary_palette": ["stone_bricks"],
            "secondary_palette": ["cobblestone"],
            "accent_palette": ["iron_bars"],
            "roof_language": "crenellated",
            "opening_language": "narrow arches",
            "detail_language": "stone trim",
            "landscape_language": "simple paths",
            "global_constraints": ["walkable"],
        },
        "work_packages": [
            _package("keep", -6, 2, anchor_x=-2),
            _package("gatehouse", second_min, 12, anchor_x=8),
        ],
        "interfaces": [],
    }


def _call(name, payload, call_id):
    return _Message(tool_calls=[_ToolCall(call_id, _Function(name, json.dumps(payload)))])


class _ScriptedLLM:
    def __init__(self, messages, *, cost=0.0):
        self.script = list(messages)
        self.cost = cost
        self.calls = []
        self.total_usage = Usage()

    def chat(self, model, messages, tools=None, reasoning="off", **kwargs):
        self.calls.append(
            {
                "model": model,
                "messages": copy.deepcopy(messages),
                "tools": tools,
                "reasoning": reasoning,
                "kwargs": kwargs,
            }
        )
        message = self.script.pop(0) if self.script else _Message(content="still thinking")
        usage = Usage(prompt_tokens=10, completion_tokens=4, cost_usd=self.cost)
        self.total_usage.add(usage)
        return ChatResult(message=message, usage=usage)


class _StructuredScriptedLLM:
    plan_json_mode = PlanJSONMode.RESPONSES
    supports_structured_plan_json = True

    def __init__(self, plans, reviews, *, generation_cost=0.0, review_cost=0.0):
        self.plans = list(plans)
        self.reviews = list(reviews)
        self.generation_cost = generation_cost
        self.review_cost = review_cost
        self.generation_calls = []
        self.review_calls = []

    def generate_plan_json(self, **kwargs):
        self.generation_calls.append(copy.deepcopy(kwargs))
        plan = self.plans.pop(0)
        return PlanJSONResult(
            data=copy.deepcopy(plan),
            usage=Usage(prompt_tokens=12, completion_tokens=6, cost_usd=self.generation_cost),
        )

    def chat(self, model, messages, tools=None, reasoning="off", **kwargs):
        self.review_calls.append(
            {
                "model": model,
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "reasoning": reasoning,
                "kwargs": kwargs,
            }
        )
        message = self.reviews.pop(0) if self.reviews else _Message(content="missing review tool")
        return ChatResult(
            message=message,
            usage=Usage(prompt_tokens=8, completion_tokens=3, cost_usd=self.review_cost),
        )


def _strict_plan(*, overlap):
    plan = _plan(overlap=overlap)
    for package in plan["work_packages"]:
        package["requested_views"] = [{"mode": "iso", "yaw": 0}]
    return plan


def _config(*, max_iters=3, cost_ceiling=None):
    return ProjectConfig(
        worker_config=Config(reasoning="low", stream=False),
        planner_model="test/planner",
        planner_max_iters=max_iters,
        max_components=8,
        cost_ceiling=cost_ceiling,
    )


def test_planner_revises_invalid_plan_then_approves_valid_render(tmp_path):
    llm = _ScriptedLLM(
        [
            _call("submit_project_plan", {"plan": _plan(overlap=True)}, "submit"),
            _call("revise_project_plan", {"plan": _plan(overlap=False)}, "revise"),
            _call(
                "approve_project_plan",
                {"summary": "Ready for workers", "review_notes": "Checked image and validation."},
                "approve",
            ),
        ]
    )
    rundir = ProjectRunDir(tmp_path / "run")
    events = []

    result = run_planner(
        "a fortified site", llm, _config(), rundir, on_event=lambda kind, data: events.append((kind, data))
    )

    assert result.approved is True
    assert result.versions == 2
    assert result.plan is not None
    assert result.summary == "Ready for workers"
    assert result.usage.prompt_tokens == 30
    assert (rundir.root / "project" / "plan_v01.json").exists()
    assert (rundir.root / "project" / "plan_v01.png").exists()
    assert (rundir.root / "project" / "plan_v02.json").exists()
    assert (rundir.root / "project" / "plan_v02.png").exists()
    assert (rundir.root / "project" / "approved_plan.json").exists()
    assert (rundir.root / "project" / "approved_plan.png").exists()

    first_report = json.loads((rundir.root / "project" / "plan_v01_validation.json").read_text())
    second_report = json.loads((rundir.root / "project" / "plan_v02_validation.json").read_text())
    assert first_report["valid"] is False
    assert any(error["code"] == "core_overlap" for error in first_report["errors"])
    assert second_report["valid"] is True

    # The revision and approval turns receive real vision input, but persisted history does not retain base64 blobs.
    assert "data:image/png;base64," in json.dumps(llm.calls[1]["messages"])
    session_text = (rundir.root / "project" / "planner_session.json").read_text(encoding="utf-8")
    assert "data:image/png;base64," not in session_text
    assert "project/plan_v01.png" in session_text
    assert "project/plan_v02.png" in session_text
    assert [kind for kind, _data in events if kind in {"plan_submitted", "plan_revised", "plan_approved"}] == [
        "plan_submitted",
        "plan_revised",
        "plan_approved",
    ]
    first_version_events = [kind for kind, data in events if data.get("version") == 1 and kind != "planner_turn_usage"]
    assert first_version_events[:3] == ["plan_submitted", "plan_validation", "plan_render"]


def test_planner_rejects_approval_of_invalid_current_plan(tmp_path):
    llm = _ScriptedLLM(
        [
            _call("submit_project_plan", {"plan": _plan(overlap=True)}, "submit"),
            _call("approve_project_plan", {"summary": "approve", "review_notes": "looks fine"}, "bad_approve"),
            _call("revise_project_plan", {"plan": _plan(overlap=False)}, "revise"),
            _call("approve_project_plan", {"summary": "approve", "review_notes": "now valid"}, "approve"),
        ]
    )

    result = run_planner("site", llm, _config(max_iters=2), ProjectRunDir(tmp_path / "run"))

    assert result.approved is True
    assert len(llm.calls) == 4
    third_request = json.dumps(llm.calls[2]["messages"])
    assert "current plan is invalid" in third_request.lower()


def test_planner_runtime_schema_error_is_artifacted_without_fake_png(tmp_path):
    malformed = _plan(overlap=False)
    del malformed["site"]
    llm = _ScriptedLLM(
        [
            _call("submit_project_plan", {"plan": malformed}, "submit"),
            _call("revise_project_plan", {"plan": _plan(overlap=False)}, "revise"),
            _call("approve_project_plan", {"summary": "valid", "review_notes": "reviewed"}, "approve"),
        ]
    )
    rundir = ProjectRunDir(tmp_path / "run")

    result = run_planner("site", llm, _config(max_iters=2), rundir)

    assert result.approved is True
    first_report = json.loads((rundir.root / "project" / "plan_v01_validation.json").read_text())
    assert first_report["valid"] is False
    assert first_report["errors"][0]["code"] == "schema_error"
    assert not (rundir.root / "project" / "plan_v01.png").exists()


def test_planner_fails_at_invalid_version_limit_without_running_forever(tmp_path):
    llm = _ScriptedLLM([_call("submit_project_plan", {"plan": _plan(overlap=True)}, "submit")])

    result = run_planner("site", llm, _config(max_iters=1), ProjectRunDir(tmp_path / "run"))

    assert result.approved is False
    assert result.versions == 1
    assert result.error == "No valid plan after 1 versions."
    assert len(llm.calls) == 1


def test_planner_enforces_cost_and_text_only_turn_limits(tmp_path):
    costly = _ScriptedLLM([_call("submit_project_plan", {"plan": _plan(overlap=False)}, "submit")], cost=0.2)
    costly_result = run_planner(
        "site",
        costly,
        _config(max_iters=1, cost_ceiling=0.1),
        ProjectRunDir(tmp_path / "costly"),
    )
    assert costly_result.approved is False
    assert "cost ceiling" in (costly_result.error or "").lower()
    assert costly_result.versions == 0

    exact = _ScriptedLLM(
        [
            _call("submit_project_plan", {"plan": _plan(overlap=False)}, "submit"),
            _call("approve_project_plan", {"summary": "ready", "review_notes": "checked"}, "approve"),
        ],
        cost=0.1,
    )
    exact_result = run_planner(
        "site",
        exact,
        _config(max_iters=1, cost_ceiling=0.1),
        ProjectRunDir(tmp_path / "exact"),
    )
    assert exact_result.approved is False
    assert len(exact.calls) == 1
    assert exact_result.usage.cost_usd == pytest.approx(0.1)

    text_only = _ScriptedLLM([_Message(content="thinking") for _ in range(10)])
    bounded_result = run_planner("site", text_only, _config(max_iters=1), ProjectRunDir(tmp_path / "bounded"))
    assert bounded_result.approved is False
    assert "5-turn safety limit" in (bounded_result.error or "")
    assert len(text_only.calls) == 5


def test_planner_tools_are_structured_and_complete():
    functions = {tool["function"]["name"]: tool["function"] for tool in PLANNER_TOOLS}
    assert set(functions) == {"submit_project_plan", "revise_project_plan", "approve_project_plan"}
    assert functions["submit_project_plan"]["parameters"]["required"] == ["plan"]
    assert functions["approve_project_plan"]["parameters"]["required"] == ["summary", "review_notes"]


def test_planner_submit_tool_exposes_the_exact_nested_runtime_contract():
    submit = next(tool["function"] for tool in PLANNER_TOOLS if tool["function"]["name"] == "submit_project_plan")
    parameters = submit["parameters"]
    defs = parameters["$defs"]
    plan = parameters["properties"]["plan"]

    assert plan["additionalProperties"] is False
    assert set(plan["properties"]) == {
        "schema_version",
        "title",
        "project_summary",
        "site",
        "style_bible",
        "work_packages",
        "interfaces",
    }
    assert set(defs["site"]["properties"]) == {"min_x", "max_x", "min_z", "max_z", "base_y"}
    assert set(defs["style_bible"]["required"]) == {
        "architectural_style",
        "scale_and_massing",
        "primary_palette",
        "secondary_palette",
        "accent_palette",
        "roof_language",
        "opening_language",
        "detail_language",
        "landscape_language",
        "global_constraints",
    }
    assert set(defs["work_package"]["required"]) == {
        "id",
        "name",
        "semantic_type",
        "objective",
        "instances",
        "responsibility",
        "depends_on",
        "neighbor_context",
        "worker_brief",
        "acceptance_criteria",
        "requested_views",
    }
    assert set(defs["responsibility"]["properties"]) == {
        "boundary_kind",
        "core",
        "halo",
        "min_y",
        "max_y",
        "write_policy",
    }
    view_branches = defs["requested_view"]["oneOf"]
    assert [branch["required"] for branch in view_branches] == [
        ["mode"],
        ["mode", "yaw"],
        ["mode", "yaw", "cutaway"],
        ["mode", "yaw", "slice_axis", "slice_at"],
    ]
    assert all(branch["additionalProperties"] is False for branch in view_branches)
    assert set().union(*(branch["properties"] for branch in view_branches)) == {
        "mode",
        "yaw",
        "cutaway",
        "slice_axis",
        "slice_at",
    }
    assert all(branch["additionalProperties"] is False for branch in defs["region_expr"]["oneOf"])
    assert [branch["properties"]["op"] for branch in defs["region_expr"]["oneOf"]] == [
        {"const": "shape"},
        {"enum": ["union", "intersection"]},
        {"const": "difference"},
    ]


def test_planner_prompt_names_schema_discriminators_that_providers_must_not_infer():
    prompt = build_planner_system_prompt(6)

    assert "WorkPackage keys: id, name, semantic_type, objective" in prompt
    assert "RegionExpr always uses discriminator key `op`, never `type`" in prompt
    assert '{"mode":"top-down"}' in prompt
    assert "The mode is `iso`, never" in prompt
    assert "The difference `subtract` value is always an array" in prompt


def test_provider_structured_plan_schema_is_self_contained_and_strict():
    validate_strict_json_schema(PROJECT_PLAN_JSON_SCHEMA)
    encoded = json.dumps(PROJECT_PLAN_JSON_SCHEMA)

    assert "$defs" in PROJECT_PLAN_JSON_SCHEMA
    assert "oneOf" not in encoded
    assert '"const"' not in encoded
    responsibility = PROJECT_PLAN_JSON_SCHEMA["$defs"]["responsibility"]
    assert set(responsibility["required"]) == set(responsibility["properties"])
    assert set(responsibility["required"]) >= {"halo", "write_policy"}
    assert "anyOf" in responsibility["properties"]["halo"]

    review_functions = {tool["function"]["name"]: tool["function"] for tool in PLANNER_REVIEW_TOOLS}
    assert set(review_functions) == {"approve_project_plan", "request_project_plan_revision"}
    assert all("plan" not in function["parameters"]["properties"] for function in review_functions.values())


def test_structured_planner_separates_visual_revision_from_strict_generation(tmp_path):
    llm = _StructuredScriptedLLM(
        [_strict_plan(overlap=False), _strict_plan(overlap=False)],
        [
            _call(
                "request_project_plan_revision",
                {
                    "review_notes": "The image needs a clearer arrival sequence.",
                    "revision_instructions": (
                        "Move the gatehouse east and widen the central approach. "
                        "data:image/png;base64,SHOULD_NOT_PERSIST"
                    ),
                },
                "review-1",
            ),
            _call(
                "approve_project_plan",
                {"summary": "Ready for workers", "review_notes": "The revised image is coherent."},
                "review-2",
            ),
        ],
    )
    rundir = ProjectRunDir(tmp_path / "run")

    result = run_planner("a fortified site", llm, _config(max_iters=2), rundir)

    assert result.approved is True
    assert result.versions == 2
    assert len(llm.generation_calls) == 2
    assert len(llm.review_calls) == 2
    assert "Move the gatehouse east" in llm.generation_calls[1]["user_prompt"]
    assert "data:image/" not in llm.generation_calls[1]["user_prompt"]
    assert "data:image/png;base64," in json.dumps(llm.review_calls[0]["messages"])
    assert llm.review_calls[0]["tools"] == PLANNER_REVIEW_TOOLS
    assert "submit_project_plan" not in json.dumps(llm.review_calls[0]["tools"])
    assert result.usage.prompt_tokens == 40
    assert result.usage.completion_tokens == 18

    session_text = (rundir.root / "project" / "planner_session.json").read_text(encoding="utf-8")
    assert "data:image/png;base64," not in session_text
    assert "Move the gatehouse east" in session_text
    assert "Ready for workers" in session_text


def test_structured_planner_auto_regenerates_schema_invalid_plan_without_visual_review(tmp_path):
    malformed = _strict_plan(overlap=False)
    del malformed["site"]
    llm = _StructuredScriptedLLM(
        [malformed, _strict_plan(overlap=False)],
        [
            _call(
                "approve_project_plan",
                {"summary": "Valid replacement", "review_notes": "Image reviewed."},
                "review",
            )
        ],
    )
    rundir = ProjectRunDir(tmp_path / "run")

    result = run_planner("site", llm, _config(max_iters=2), rundir)

    assert result.approved is True
    assert len(llm.generation_calls) == 2
    assert len(llm.review_calls) == 1
    assert "schema_error" in llm.generation_calls[1]["user_prompt"]
    assert "No image could be rendered" in llm.generation_calls[1]["user_prompt"]
    assert not (rundir.root / "project" / "plan_v01.png").exists()
    assert (rundir.root / "project" / "plan_v02.png").exists()


def test_structured_planner_local_validation_overrides_visual_approval(tmp_path):
    llm = _StructuredScriptedLLM(
        [_strict_plan(overlap=True), _strict_plan(overlap=False)],
        [
            _call(
                "approve_project_plan",
                {"summary": "Looks fine", "review_notes": "Visual approval."},
                "bad-approval",
            ),
            _call(
                "approve_project_plan",
                {"summary": "Now valid", "review_notes": "Validated and reviewed."},
                "approval",
            ),
        ],
    )

    result = run_planner("site", llm, _config(max_iters=2), ProjectRunDir(tmp_path / "run"))

    assert result.approved is True
    assert result.versions == 2
    assert "local validation is authoritative" in llm.generation_calls[1]["user_prompt"]
    assert "core_overlap" in llm.generation_calls[1]["user_prompt"]


def test_structured_planner_visual_review_failures_are_bounded_and_sanitized(tmp_path):
    llm = _StructuredScriptedLLM(
        [_strict_plan(overlap=False)],
        [_Message(content="no tool"), _Message(content="still no tool")],
    )
    rundir = ProjectRunDir(tmp_path / "run")

    result = run_planner("site", llm, _config(max_iters=2), rundir)

    assert result.approved is False
    assert "Visual review failed after 2 attempts" in (result.error or "")
    assert len(llm.generation_calls) == 1
    assert len(llm.review_calls) == 2
    session = json.loads((rundir.root / "project" / "planner_session.json").read_text(encoding="utf-8"))
    failed_attempts = [entry for entry in session if entry["stage"] == "visual_review_attempt"]
    assert len(failed_attempts) == 2
    assert "data:image" not in json.dumps(session)


def test_structured_planner_accumulates_generation_and_review_cost_before_stopping(tmp_path):
    llm = _StructuredScriptedLLM(
        [_strict_plan(overlap=False)],
        [
            _call(
                "approve_project_plan",
                {"summary": "ready", "review_notes": "reviewed"},
                "approval",
            )
        ],
        generation_cost=0.06,
        review_cost=0.05,
    )
    rundir = ProjectRunDir(tmp_path / "run")

    result = run_planner(
        "site",
        llm,
        _config(max_iters=1, cost_ceiling=0.1),
        rundir,
    )

    assert result.approved is False
    assert "cost ceiling" in (result.error or "").lower()
    assert result.usage.cost_usd == pytest.approx(0.11)
    assert not (rundir.root / "project" / "approved_plan.json").exists()


def test_structured_planner_does_not_misclassify_render_failure_as_schema_error(tmp_path, monkeypatch):
    llm = _StructuredScriptedLLM([_strict_plan(overlap=False)], [])
    rundir = ProjectRunDir(tmp_path / "run")

    def fail_render(*_args, **_kwargs):
        raise ValueError("renderer unavailable")

    monkeypatch.setattr(planner_module, "render_plan", fail_render)
    result = run_planner("site", llm, _config(max_iters=1), rundir)

    assert result.approved is False
    assert result.plan is not None
    assert "Plan rendering failed" in (result.error or "")
    report = json.loads((rundir.root / "project" / "plan_v01_validation.json").read_text())
    assert report["valid"] is True
    assert all(error["code"] != "schema_error" for error in report["errors"])
    assert len(llm.review_calls) == 0


def test_structured_generation_failure_usage_reaches_planner_cost_ceiling(tmp_path):
    class _BilledFailure:
        plan_json_mode = PlanJSONMode.RESPONSES
        supports_structured_plan_json = True

        def generate_plan_json(self, **_kwargs):
            error = ValueError("invalid provider JSON")
            error.usage = Usage(  # ty: ignore[unresolved-attribute]
                prompt_tokens=20, completion_tokens=8, cost_usd=0.2
            )
            raise error

    result = run_planner(
        "site",
        _BilledFailure(),
        _config(max_iters=1, cost_ceiling=0.1),
        ProjectRunDir(tmp_path / "run"),
    )

    assert result.approved is False
    assert "cost ceiling" in (result.error or "").lower()
    assert result.usage.prompt_tokens == 20
    assert result.usage.cost_usd == pytest.approx(0.2)


def test_explicit_tool_call_capability_uses_legacy_planner_even_with_new_method(tmp_path):
    class _CompatibleFallback(_ScriptedLLM):
        plan_json_mode = PlanJSONMode.TOOL_CALL
        supports_structured_plan_json = False

        def generate_plan_json(self, **_kwargs):
            raise AssertionError("generic compatible Planner must use tool-call fallback")

    llm = _CompatibleFallback(
        [
            _call("submit_project_plan", {"plan": _plan(overlap=False)}, "submit"),
            _call(
                "approve_project_plan",
                {"summary": "ready", "review_notes": "reviewed"},
                "approve",
            ),
        ]
    )

    result = run_planner("site", llm, _config(max_iters=1), ProjectRunDir(tmp_path / "run"))

    assert result.approved is True
    assert len(llm.calls) == 2
    assert llm.calls[0]["tools"] == PLANNER_TOOLS
