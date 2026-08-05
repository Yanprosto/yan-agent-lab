import json

import pytest
from PIL import Image

from mcbuild.agent.loop import AgentResult
from mcbuild.config import Config
from mcbuild.llm.client import Usage
from mcbuild.orchestrator.executor import execute_plan
from mcbuild.orchestrator.models import (
    BoundaryKind,
    Instance,
    ProjectConfig,
    ProjectPlan,
    Responsibility,
    Site,
    StyleBible,
    WorkPackage,
)
from mcbuild.orchestrator.region import RegionExpr
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.palette import get_block
from mcbuild.voxel import VoxelGrid


def _rect(x):
    return RegionExpr.from_dict(
        {
            "op": "shape",
            "shape": {
                "kind": "axis_aligned_rectangle",
                "min_x": x,
                "max_x": x,
                "min_z": 0,
                "max_z": 0,
            },
        }
    )


def _package(package_id, x, *, depends_on=None, instances=None):
    return WorkPackage(
        id=package_id,
        name=package_id,
        semantic_type="structure_family",
        objective=f"build {package_id}",
        instances=instances or [Instance("main", (x, 0, 0), 0)],
        responsibility=Responsibility(BoundaryKind.HARD, _rect(x), 0, 2),
        depends_on=depends_on or [],
        neighbor_context=[],
        worker_brief="Build the assigned structure",
        acceptance_criteria=["complete"],
        requested_views=[{"yaw": 0}],
    )


def _plan():
    family = _package(
        "tower_family",
        0,
        instances=[
            Instance("north_west", (0, 0, 0), 0),
            Instance("north_east", (0, 0, 0), 90),
            Instance("south_west", (0, 0, 0), 270),
            Instance("south_east", (0, 0, 0), 180),
        ],
    )
    gate = _package("gatehouse", 2, depends_on=["tower_family"])
    style = StyleBible(**{name: "shared" for name in StyleBible.FIELD_NAMES})
    return ProjectPlan(1, "Project", "Two components", Site(-10, 10, -10, 10, 0), style, [gate, family], [])


def _worker_grid(x, *, outside=False):
    grid = VoxelGrid()
    grid.set(x, 0, 0, get_block("stone" if x == 0 else "glass").index)
    if outside:
        grid.set(9, 0, 0, get_block("air").index)
    return grid


def test_executor_runs_one_worker_per_package_in_stable_order_and_writes_artifacts(tmp_path):
    plan = _plan()
    config = ProjectConfig(Config(max_iters=2), "planner", cost_ceiling=1.0)
    rundir = ProjectRunDir(tmp_path / "run")
    factory_calls = []
    runner_calls = []
    events = []

    def factory(package):
        factory_calls.append(package.id)
        return package

    def runner(
        prompt,
        llm,
        config,
        rundir,
        reference_image=None,
        on_event=None,
        *,
        system_context=None,
    ):
        runner_calls.append((llm.id, prompt, config, rundir, system_context))
        grid = _worker_grid(0 if llm.id == "tower_family" else 2)
        if on_event:
            on_event("render", {"image": Image.new("RGB", (1, 1)), "grid": grid, "stats": {"ok": True}})
        return AgentResult(True, "done", grid, {"block_count": 1}, 1, Usage(cost_usd=0.25))

    result = execute_plan(
        "build a castle",
        plan,
        factory,
        config,
        rundir,
        on_event=lambda event_type, data: events.append((event_type, data)),
        worker_runner=runner,
        initial_usage=Usage(cost_usd=0.2),
    )

    assert result.finished is True
    # The source plan deliberately lists gatehouse first; its dependency forces the family first.
    assert factory_calls == ["tower_family", "gatehouse"]
    assert [call[0] for call in runner_calls] == ["tower_family", "gatehouse"]
    assert len(runner_calls) == 2  # four instances remain one semantic worker call
    assert runner_calls[0][2] is not runner_calls[1][2]
    assert runner_calls[0][2].cost_ceiling == pytest.approx(0.8)
    assert runner_calls[1][2].cost_ceiling == pytest.approx(0.55)
    assert "shared blueprint helper/construction logic once" in runner_calls[0][1]
    assert "project-global" in runner_calls[0][4]
    assert result.completed_packages == ["tower_family", "gatehouse"]
    assert result.usage.cost_usd == pytest.approx(0.7)
    assert result.grid.get(0, 0, 0) is not None
    assert result.grid.get(2, 0, 0) is not None

    for index, package_id in ((1, "tower_family"), (2, "gatehouse")):
        component = rundir.root / "components" / f"{index:02d}_{package_id}"
        assert (component / "worker_prompt.txt").exists()
        assert (component / "worker_result.json").exists()
        assert (component / "patch_validation.json").exists()
        assert (component / "accepted_patch.schem").exists()
        assert (component / "merged_after_component.schem").exists()
        assert (rundir.root / "merge_reports" / f"component_{index:02d}.json").exists()

    worker_events = [data for event_type, data in events if event_type == "component_worker_event"]
    assert worker_events and worker_events[0]["data"] == {"stats": {"ok": True}}
    merged_events = [data for event_type, data in events if event_type == "component_merged"]
    assert len(merged_events) == 2
    assert isinstance(merged_events[-1]["grid"], VoxelGrid)  # runtime-only channel for WS delta

    # Persisted JSON remains strict and never contains the runtime grid object.
    report = json.loads((rundir.root / "merge_reports" / "component_01.json").read_text())
    assert report["accepted"] is True


def test_unfinished_worker_grid_is_not_merged_and_later_packages_do_not_run(tmp_path):
    plan = _plan()
    calls = []

    def runner(
        prompt,
        llm,
        config,
        rundir,
        reference_image=None,
        on_event=None,
        *,
        system_context=None,
    ):
        del prompt, config, rundir, reference_image, on_event, system_context
        calls.append(llm.id)
        return AgentResult(False, "edit budget reached", _worker_grid(0), None, 1, Usage(cost_usd=0.1))

    result = execute_plan(
        "castle",
        plan,
        lambda package: package,
        ProjectConfig(Config(), "planner"),
        ProjectRunDir(tmp_path / "run"),
        worker_runner=runner,
    )

    assert result.finished is False
    assert result.failed_package == "tower_family"
    assert result.completed_packages == []
    assert len(result.grid) == 0
    assert calls == ["tower_family"]
    assert result.validation_reports[0].accepted is False


def test_finished_worker_with_empty_grid_fails_before_merge(tmp_path):
    plan = _plan()

    def runner(
        prompt,
        llm,
        config,
        rundir,
        reference_image=None,
        on_event=None,
        *,
        system_context=None,
    ):
        del prompt, llm, config, rundir, reference_image, on_event, system_context
        return AgentResult(True, "done", VoxelGrid(), None, 1, Usage())

    result = execute_plan(
        "castle",
        plan,
        lambda package: package,
        ProjectConfig(Config(), "planner"),
        ProjectRunDir(tmp_path / "run"),
        worker_runner=runner,
    )

    assert result.finished is False
    assert result.failed_package == "tower_family"
    assert result.completed_packages == []
    assert "empty final VoxelGrid" in result.summary
    assert result.summary.startswith("work package tower_family: worker stage:")
    assert not (tmp_path / "run" / "final.schem").exists()


def test_all_soft_voxels_clipped_cannot_finish_with_empty_global_grid(tmp_path):
    package = _package("soft_component", 0)
    package.responsibility = Responsibility(
        BoundaryKind.SOFT,
        _rect(0),
        0,
        2,
        halo=_rect(1),
    )
    style = StyleBible(**{name: "shared" for name in StyleBible.FIELD_NAMES})
    plan = ProjectPlan(1, "Project", "Soft component", Site(-10, 10, -10, 10, 0), style, [package], [])

    def runner(
        prompt,
        llm,
        config,
        rundir,
        reference_image=None,
        on_event=None,
        *,
        system_context=None,
    ):
        del prompt, llm, config, rundir, reference_image, on_event, system_context
        grid = VoxelGrid()
        grid.set(1000, 0, 1000, get_block("stone").index)
        return AgentResult(True, "done", grid, None, 1, Usage())

    result = execute_plan(
        "soft project",
        plan,
        lambda package: package,
        ProjectConfig(Config(), "planner"),
        ProjectRunDir(tmp_path / "run"),
        worker_runner=runner,
    )

    assert result.finished is False
    assert result.completed_packages == ["soft_component"]
    assert result.validation_reports[0].clipped_voxels == 1
    assert len(result.grid) == 0
    assert "no merged voxels" in result.summary


def test_worker_stops_when_global_cost_exactly_reaches_ceiling(tmp_path):
    calls: list[str] = []

    def runner(
        prompt,
        llm,
        config,
        rundir,
        reference_image=None,
        on_event=None,
        *,
        system_context=None,
    ):
        del prompt, config, rundir, reference_image, on_event, system_context
        calls.append(llm.id)
        return AgentResult(True, "done", _worker_grid(0), None, 1, Usage(cost_usd=0.5))

    result = execute_plan(
        "castle",
        _plan(),
        lambda package: package,
        ProjectConfig(Config(), "planner", cost_ceiling=1.0),
        ProjectRunDir(tmp_path / "run"),
        worker_runner=runner,
        initial_usage=Usage(cost_usd=0.5),
    )

    assert result.finished is False
    assert calls == ["tower_family"]
    assert len(result.grid) == 0
    assert result.usage.cost_usd == pytest.approx(1.0)
    assert result.summary.startswith("work package tower_family: budget stage:")


def test_hard_patch_rejection_is_fail_fast_and_atomic(tmp_path):
    plan = _plan()
    calls = []

    def runner(
        prompt,
        llm,
        config,
        rundir,
        reference_image=None,
        on_event=None,
        *,
        system_context=None,
    ):
        del prompt, config, rundir, reference_image, on_event, system_context
        calls.append(llm.id)
        return AgentResult(True, "done", _worker_grid(0, outside=True), None, 1, Usage())

    result = execute_plan(
        "castle",
        plan,
        lambda package: package,
        ProjectConfig(Config(), "planner"),
        ProjectRunDir(tmp_path / "run"),
        worker_runner=runner,
    )

    assert result.finished is False
    assert result.failed_package == "tower_family"
    assert result.validation_reports[0].forbidden_voxels == 1
    assert len(result.grid) == 0
    assert calls == ["tower_family"]
    assert result.summary.startswith("work package tower_family: merge stage:")
