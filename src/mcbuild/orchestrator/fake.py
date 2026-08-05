"""Deterministic offline planner and worker fixtures for the full project pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mcbuild.agent.loop import AgentResult
from mcbuild.llm.client import ChatResult, Usage
from mcbuild.orchestrator.models import ProjectPlan, WorkPackage
from mcbuild.palette import get_block
from mcbuild.rundir import RunDir
from mcbuild.voxel import VoxelGrid


@dataclass(frozen=True)
class _FunctionCall:
    name: str
    arguments: str


@dataclass(frozen=True)
class _ToolCall:
    id: str
    function: _FunctionCall
    type: str = "function"


@dataclass
class _Message:
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None
    reasoning: str | None = None
    reasoning_details: list[Any] | None = None


def fake_project_plan() -> ProjectPlan:
    """Return a small valid plan with a gatehouse and one four-instance tower family."""

    circle = lambda x, z, radius: {  # noqa: E731 - keeps the fixture readable
        "op": "shape",
        "shape": {"kind": "circle", "center": [x, z], "radius": radius},
    }
    rectangle = lambda min_x, max_x, min_z, max_z: {  # noqa: E731
        "op": "shape",
        "shape": {
            "kind": "axis_aligned_rectangle",
            "min_x": min_x,
            "max_x": max_x,
            "min_z": min_z,
            "max_z": max_z,
        },
    }
    tower_centers = [(-10, 0), (10, 0), (-10, 12), (10, 12)]
    plan = {
        "schema_version": 1,
        "title": "Offline Fortified Settlement",
        "project_summary": "A gatehouse connected to a consistent family of four defensive towers.",
        "site": {"min_x": -20, "max_x": 20, "min_z": -8, "max_z": 20, "base_y": 0},
        "style_bible": {
            "architectural_style": "compact medieval fortification",
            "scale_and_massing": "low gatehouse with matching squat towers",
            "primary_palette": ["stone_bricks", "cobblestone"],
            "secondary_palette": ["spruce_planks"],
            "accent_palette": ["iron_bars"],
            "roof_language": "crenellated stone parapets",
            "opening_language": "narrow defensive openings",
            "detail_language": "simple stone trim",
            "landscape_language": "unmodified flat test site",
            "global_constraints": ["project-global coordinates", "shared tower dimensions"],
        },
        "work_packages": [
            {
                "id": "gatehouse",
                "name": "Gatehouse",
                "semantic_type": "fortified_entrance",
                "objective": "Create the settlement entrance and its passage.",
                "instances": [{"id": "main", "anchor": [0, 0, 0], "rotation": 0}],
                "responsibility": {
                    "boundary_kind": "soft",
                    "core": rectangle(-4, 4, -3, 3),
                    "halo": rectangle(-8, 8, -5, 5),
                    "min_y": 0,
                    "max_y": 8,
                    "write_policy": "preserve_existing",
                },
                "depends_on": [],
                "neighbor_context": ["Tower connectors meet the east and west halo."],
                "worker_brief": "Build a small stone gatehouse with a centered opening.",
                "acceptance_criteria": ["A passable centered entrance is visually legible."],
                "requested_views": [{"yaw": 0}, {"mode": "top-down"}],
            },
            {
                "id": "tower_family",
                "name": "Defensive Tower Family",
                "semantic_type": "defensive_tower_family",
                "objective": "Create four identical defensive towers from one shared design.",
                "instances": [
                    {"id": instance_id, "anchor": [x, 0, z], "rotation": rotation}
                    for instance_id, (x, z), rotation in zip(
                        ("north_west", "north_east", "south_west", "south_east"),
                        tower_centers,
                        (0, 90, 270, 180),
                        strict=True,
                    )
                ],
                "responsibility": {
                    "boundary_kind": "soft",
                    "core": {"op": "union", "children": [circle(x, z, 2) for x, z in tower_centers]},
                    "halo": {"op": "union", "children": [circle(x, z, 5) for x, z in tower_centers]},
                    "min_y": 0,
                    "max_y": 8,
                    "write_policy": "preserve_existing",
                },
                "depends_on": ["gatehouse"],
                "neighbor_context": ["The front pair connects to the gatehouse through declared interfaces."],
                "worker_brief": "Define one tower helper and instantiate it at all four anchors.",
                "acceptance_criteria": ["All four towers share dimensions and material language."],
                "requested_views": [{"yaw": 1}, {"mode": "top-down"}],
            },
        ],
        "interfaces": [
            {
                "id": "gatehouse_tower_connectors",
                "participants": ["gatehouse", "tower_family"],
                "region": {
                    "op": "union",
                    "children": [rectangle(-8, -6, -2, 2), rectangle(6, 8, -2, 2)],
                },
                "description": "Short intentional connection bands from the gatehouse to the front towers.",
                "merge_policy": "preserve_existing",
            }
        ],
    }
    return ProjectPlan.from_dict(plan)


class FakeProjectPlannerLLM:
    """Script submit then approve tool calls while tracking ordinary Usage values."""

    def __init__(self, plan: ProjectPlan | None = None) -> None:
        self.plan = plan or fake_project_plan()
        self.total_usage = Usage()
        self.session_id = "offline-project-planner"
        self._step = 0

    def chat(self, model: str, messages: list[dict], tools=None, reasoning: str = "off", **kwargs) -> ChatResult:
        del model, messages, tools, reasoning, kwargs
        if self._step == 0:
            call = _ToolCall(
                "fake_plan_submit",
                _FunctionCall("submit_project_plan", json.dumps({"plan": self.plan.to_dict()})),
            )
        else:
            call = _ToolCall(
                "fake_plan_approve",
                _FunctionCall(
                    "approve_project_plan",
                    json.dumps(
                        {
                            "summary": "The offline plan is valid and ready for serial execution.",
                            "review_notes": "Checked responsibilities, instances, dependencies, and connectors.",
                        }
                    ),
                ),
            )
        self._step += 1
        usage = Usage(prompt_tokens=5, completion_tokens=5)
        self.total_usage.add(usage)
        return ChatResult(message=_Message(tool_calls=[call]), usage=usage)


@dataclass(frozen=True)
class FakeWorkerLLM:
    """Carries package identity to the injected deterministic worker runner."""

    package_id: str
    total_usage: Usage = field(default_factory=Usage)


def fake_worker_llm_factory(package: WorkPackage) -> FakeWorkerLLM:
    return FakeWorkerLLM(package.id)


def fake_worker_runner(
    prompt: str,
    llm: FakeWorkerLLM,
    config: Any,
    rundir: RunDir,
    reference_image=None,
    on_event=None,
    *,
    system_context: str | None = None,
) -> AgentResult:
    """Return deterministic legal component voxels through the normal executor seam."""

    del prompt, config, reference_image, system_context
    grid = VoxelGrid()
    stone = get_block("stone_bricks").index

    if llm.package_id == "gatehouse":
        for x in range(-4, 5):
            for z in range(-3, 4):
                grid.set(x, 0, z, stone)
        for y in range(1, 5):
            for x in range(-4, 5):
                if x != 0 or y >= 3:
                    grid.set(x, y, -3, stone)
                    grid.set(x, y, 3, stone)
            for z in range(-2, 3):
                grid.set(-4, y, z, stone)
                grid.set(4, y, z, stone)
    elif llm.package_id == "tower_family":
        for anchor_x, anchor_z in ((-10, 0), (10, 0), (-10, 12), (10, 12)):
            for y in range(0, 6):
                for dx in range(-1, 2):
                    for dz in range(-1, 2):
                        if y == 0 or abs(dx) == 1 or abs(dz) == 1:
                            grid.set(anchor_x + dx, y, anchor_z + dz, stone)
    else:
        return AgentResult(False, f"No offline worker fixture for {llm.package_id}", None, None, 0, Usage())

    stats = {"block_count": len(grid), "bounds": grid.bounds}
    rundir.write_json("session.json", [{"role": "fixture", "package_id": llm.package_id}])
    if on_event is not None:
        on_event("render", {"iteration": 1, "grid": grid, "stats": stats})
        on_event("finish", {"summary": f"Built offline fixture {llm.package_id}."})
    return AgentResult(True, f"Built offline fixture {llm.package_id}.", grid, stats, 1, Usage())
