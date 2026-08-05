import copy
import json
from dataclasses import dataclass

import pytest

from mcbuild.config import Config
from mcbuild.llm.client import ChatResult, Usage
from mcbuild.orchestrator.models import ProjectConfig
from mcbuild.orchestrator.planner import PLANNER_TOOLS, run_planner
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
