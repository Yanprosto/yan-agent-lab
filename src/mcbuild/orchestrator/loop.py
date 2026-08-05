"""Top-level orchestration for planning, serial workers, validation, merge, and export."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from mcbuild.agent.loop import run_agent
from mcbuild.export.schem import export_schem
from mcbuild.llm.client import Usage
from mcbuild.orchestrator.executor import ExecutionResult, execute_plan
from mcbuild.orchestrator.models import ProjectConfig, ProjectPlan, ProjectResult
from mcbuild.orchestrator.planner import PlannerResult, run_planner
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.orchestrator.validator import validate_project_plan
from mcbuild.voxel import VoxelGrid

EventCallback = Callable[[str, dict[str, Any]], None]
PlannerRunner = Callable[..., PlannerResult]
ExecutorRunner = Callable[..., ExecutionResult]

_OMIT = object()


def _json_safe(value: Any) -> Any:
    """Convert event payloads to strict JSON while omitting runtime-heavy objects."""

    if isinstance(value, (Image.Image, VoxelGrid)):
        return _OMIT
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            converted = _json_safe(item)
            if converted is not _OMIT:
                result[str(key)] = converted
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            converted = _json_safe(item)
            if converted is not _OMIT:
                result.append(converted)
        return result
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return str(value)


def _copy_usage(usage: Usage) -> Usage:
    return Usage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cached_tokens=usage.cached_tokens,
        cost_usd=usage.cost_usd,
    )


def run_project(
    prompt: str,
    planner_llm: Any,
    worker_llm_factory: Callable[[Any], Any],
    project_config: ProjectConfig,
    rundir: ProjectRunDir,
    on_event: EventCallback | None = None,
    *,
    planner: PlannerRunner = run_planner,
    executor: ExecutorRunner = execute_plan,
    worker_runner: Callable[..., Any] = run_agent,
) -> ProjectResult:
    """Run a complete bounded project and preserve artifacts/partial grid on failure.

    The planner and every worker contribute to one project-wide usage/cost budget. The
    existing :func:`run_agent` remains the default worker implementation and is invoked
    once per semantic WorkPackage by :func:`execute_plan`.
    """

    def emit(event_type: str, **data: Any) -> None:
        clean = _json_safe(data)
        assert isinstance(clean, dict)
        rundir.append_jsonl("project_events.jsonl", {"type": event_type, **clean})
        if on_event is not None:
            on_event(event_type, data)

    def forward(event_type: str, data: dict[str, Any]) -> None:
        emit(event_type, **data)

    rundir.write_text("prompt.txt", prompt)
    rundir.write_json("project_config.json", project_config.to_dict())
    emit("project_start", prompt=prompt, run_dir=str(rundir.root))

    plan: ProjectPlan | None = None
    usage = Usage()
    grid: VoxelGrid | None = None
    completed: list[str] = []
    failed_package: str | None = None
    patch_reports: list[Any] = []

    try:
        planner_result = planner(prompt, planner_llm, project_config, rundir, on_event=forward)
        plan = planner_result.plan
        usage = _copy_usage(planner_result.usage)
        if not planner_result.approved or plan is None:
            reason = planner_result.error or "Planner stopped without approving a project plan."
            result = ProjectResult(False, reason, plan, None, [], None, [], usage)
            rundir.write_json("project_result.json", result.to_dict())
            emit("project_abort", stage="planning", reason=reason)
            return result

        # Revalidate the exact approved object at the orchestration boundary. This protects
        # injected planners and keeps transport/CLI callers from bypassing planner validation.
        approval_report = validate_project_plan(plan, max_components=project_config.max_components)
        rundir.write_project_json("approved_plan_runtime_validation.json", approval_report.to_dict())
        if not approval_report.valid:
            reason = "Approved plan failed orchestration-boundary validation."
            result = ProjectResult(False, reason, plan, None, [], None, [], usage)
            rundir.write_json("project_result.json", result.to_dict())
            emit("project_abort", stage="plan_validation", reason=reason, report=approval_report.to_dict())
            return result

        execution = executor(
            prompt,
            plan,
            worker_llm_factory,
            project_config,
            rundir,
            on_event=forward,
            worker_runner=worker_runner,
            initial_usage=usage,
        )
        usage = _copy_usage(execution.usage)
        grid = execution.grid
        completed = list(execution.completed_packages)
        failed_package = execution.failed_package
        patch_reports = list(execution.validation_reports)

        final_path: Path | None = None
        if grid is not None and len(grid):
            final_path = rundir.path("final.schem" if execution.finished else "partial.schem")
            export_schem(grid, str(final_path))

        result = ProjectResult(
            execution.finished,
            execution.summary,
            plan,
            grid,
            completed,
            failed_package,
            patch_reports,
            usage,
        )
        rundir.write_json("project_result.json", result.to_dict())
        if result.finished:
            emit(
                "project_finish",
                summary=result.summary,
                completed_packages=completed,
                total_packages=len(plan.work_packages),
                block_count=len(grid),
                final_path=str(final_path) if final_path is not None else None,
                usage=result.to_dict()["usage"],
            )
        else:
            emit(
                "project_abort",
                stage="execution",
                reason=result.summary,
                failed_package=failed_package,
                completed_packages=completed,
                block_count=len(grid),
            )
        return result
    except Exception as error:
        reason = f"Project orchestration failed: {type(error).__name__}: {error}"
        result = ProjectResult(False, reason, plan, grid, completed, failed_package, patch_reports, usage)
        rundir.write_json("project_result.json", result.to_dict())
        emit("project_abort", stage="orchestration", reason=reason, failed_package=failed_package)
        return result
