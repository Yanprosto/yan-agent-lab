"""Serial execution of validated semantic work packages using the existing agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from mcbuild.agent.loop import AgentResult, run_agent
from mcbuild.config import Config
from mcbuild.export.schem import export_schem
from mcbuild.llm.client import Usage
from mcbuild.orchestrator.merge import PatchValidation, validate_and_merge_patch
from mcbuild.orchestrator.models import ProjectConfig, ProjectPlan, WorkPackage
from mcbuild.orchestrator.prompt_writer import build_worker_prompt
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.orchestrator.validator import PlanValidationError, stable_topological_order
from mcbuild.rundir import RunDir
from mcbuild.voxel import VoxelGrid

EventCallback = Callable[[str, dict[str, Any]], None]


class WorkerLLMFactory(Protocol):
    """Create one isolated LLM client for one semantic package."""

    def __call__(self, package: WorkPackage) -> Any: ...


class WorkerRunner(Protocol):
    """The injectable subset of :func:`run_agent` used by the executor."""

    def __call__(
        self,
        prompt: str,
        llm: Any,
        config: Config,
        rundir: RunDir,
        reference_image: Image.Image | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        *,
        system_context: str | None = None,
    ) -> AgentResult: ...


@dataclass
class ExecutionResult:
    """Outcome of the worker/merge phase, including a safe partial grid on failure."""

    finished: bool
    summary: str
    grid: VoxelGrid
    completed_packages: list[str]
    failed_package: str | None
    validation_reports: list[PatchValidation]
    usage: Usage

    def to_dict(self) -> dict[str, Any]:
        return {
            "finished": self.finished,
            "summary": self.summary,
            "grid": {"block_count": len(self.grid), "bounds": self.grid.bounds},
            "completed_packages": list(self.completed_packages),
            "failed_package": self.failed_package,
            "validation_reports": [report.to_dict() for report in self.validation_reports],
            "usage": _usage_to_dict(self.usage),
        }


_OMIT = object()


def _json_safe(value: Any) -> Any:
    """Convert an event/artifact value to strict JSON, omitting large runtime objects."""
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


def _usage_to_dict(usage: Usage) -> dict[str, int | float]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "cached_tokens": usage.cached_tokens,
        "cost_usd": usage.cost_usd,
    }


def _copy_usage(usage: Usage | None) -> Usage:
    if usage is None:
        return Usage()
    return Usage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cached_tokens=usage.cached_tokens,
        cost_usd=usage.cost_usd,
    )


def _worker_result_to_dict(result: AgentResult) -> dict[str, Any]:
    return {
        "finished": result.finished,
        "summary": result.summary,
        "grid": ({"block_count": len(result.grid), "bounds": result.grid.bounds} if result.grid is not None else None),
        "stats": _json_safe(result.stats),
        "iterations": result.iterations,
        "usage": _usage_to_dict(result.usage),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _failed_patch(package: WorkPackage, reason: str) -> PatchValidation:
    return PatchValidation(
        accepted=False,
        total_voxels=0,
        messages=[reason],
    )


def _stage_failure(package: WorkPackage, stage: str, detail: str) -> str:
    detail = detail.removeprefix(f"work package {package.id}: ")
    return f"work package {package.id}: {stage} stage: {detail}"


def execute_plan(
    project_prompt: str,
    plan: ProjectPlan,
    worker_llm_factory: WorkerLLMFactory,
    project_config: ProjectConfig,
    rundir: ProjectRunDir,
    on_event: EventCallback | None = None,
    *,
    worker_runner: WorkerRunner = run_agent,
    initial_usage: Usage | None = None,
) -> ExecutionResult:
    """Run packages in stable dependency order and fail fast with a partial grid.

    A WorkPackage maps to exactly one worker call, regardless of its instance
    count.  The global project budget is converted into a remaining per-worker
    cost ceiling before each invocation.  An unfinished worker result is never
    merged, even if it carries a best-effort grid.
    """

    def emit(event_type: str, **data: Any) -> None:
        if on_event is not None:
            on_event(event_type, data)

    global_grid = VoxelGrid()
    completed: list[str] = []
    reports: list[PatchValidation] = []
    usage = _copy_usage(initial_usage)

    try:
        ordered_packages = stable_topological_order(plan)
    except PlanValidationError as exc:
        return ExecutionResult(
            False,
            f"Plan execution order failed: {exc}",
            global_grid,
            completed,
            None,
            reports,
            usage,
        )

    total = len(ordered_packages)
    for index, package in enumerate(ordered_packages, start=1):
        emit("component_start", index=index, total=total, package_id=package.id, package_name=package.name)
        component_rundir = rundir.component_rundir(index, package.id)
        worker_prompt = build_worker_prompt(project_prompt, plan, package)
        component_rundir.write_text(
            "worker_prompt.txt",
            f"SYSTEM CONTEXT\n==============\n{worker_prompt.system_context}\n\n"
            f"USER PROMPT\n===========\n{worker_prompt.user_prompt}\n",
        )

        remaining: float | None = None
        if project_config.cost_ceiling is not None:
            remaining = project_config.cost_ceiling - usage.cost_usd
            if remaining <= 0:
                reason = _stage_failure(
                    package,
                    "budget",
                    f"project cost ceiling of ${project_config.cost_ceiling:.2f} reached before worker start",
                )
                report = _failed_patch(package, reason)
                reports.append(report)
                component_rundir.write_json("worker_result.json", {"finished": False, "summary": reason})
                component_rundir.write_json("patch_validation.json", report.to_dict())
                _write_json(rundir.merge_report_path(index), report.to_dict())
                emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())
                return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)

        worker_config = replace(project_config.worker_config)
        if remaining is not None:
            worker_config.cost_ceiling = remaining

        def on_worker_event(
            worker_event: str,
            data: dict,
            _index: int = index,
            _package_id: str = package.id,
        ) -> None:
            clean = _json_safe(data)
            assert isinstance(clean, dict)
            emit(
                "component_worker_event",
                index=_index,
                package_id=_package_id,
                worker_event=worker_event,
                data=clean,
            )

        try:
            worker_llm = worker_llm_factory(package)
            worker_result = worker_runner(
                worker_prompt.user_prompt,
                worker_llm,
                worker_config,
                component_rundir,
                on_event=on_worker_event,
                system_context=worker_prompt.system_context,
            )
        except Exception as exc:
            reason = _stage_failure(package, "worker", f"raised {type(exc).__name__}: {exc}")
            report = _failed_patch(package, reason)
            reports.append(report)
            component_rundir.write_json("worker_result.json", {"finished": False, "summary": reason})
            component_rundir.write_json("patch_validation.json", report.to_dict())
            _write_json(rundir.merge_report_path(index), report.to_dict())
            emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())
            return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)

        usage.add(worker_result.usage)
        component_rundir.write_json("worker_result.json", _worker_result_to_dict(worker_result))

        if project_config.cost_ceiling is not None and usage.cost_usd >= project_config.cost_ceiling:
            reason = _stage_failure(
                package,
                "budget",
                f"worker reached project cost ceiling of ${project_config.cost_ceiling:.2f}",
            )
            report = _failed_patch(package, reason)
            reports.append(report)
            component_rundir.write_json("patch_validation.json", report.to_dict())
            _write_json(rundir.merge_report_path(index), report.to_dict())
            emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())
            return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)

        if not worker_result.finished:
            reason = _stage_failure(package, "worker", f"did not finish: {worker_result.summary}")
            report = _failed_patch(package, reason)
            reports.append(report)
            component_rundir.write_json("patch_validation.json", report.to_dict())
            _write_json(rundir.merge_report_path(index), report.to_dict())
            emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())
            return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)
        if worker_result.grid is None:
            reason = _stage_failure(package, "worker", "finished without a final VoxelGrid")
            report = _failed_patch(package, reason)
            reports.append(report)
            component_rundir.write_json("patch_validation.json", report.to_dict())
            _write_json(rundir.merge_report_path(index), report.to_dict())
            emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())
            return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)
        if len(worker_result.grid) == 0:
            reason = _stage_failure(package, "worker", "finished with an empty final VoxelGrid")
            report = _failed_patch(package, reason)
            reports.append(report)
            component_rundir.write_json("patch_validation.json", report.to_dict())
            _write_json(rundir.merge_report_path(index), report.to_dict())
            emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())
            return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)

        merge_result = validate_and_merge_patch(global_grid, worker_result.grid, package, plan)
        report = merge_result.validation
        reports.append(report)
        component_rundir.write_json("patch_validation.json", report.to_dict())
        merge_report_path = rundir.merge_report_path(index)
        _write_json(merge_report_path, report.to_dict())
        emit("component_patch_validation", index=index, package_id=package.id, report=report.to_dict())

        if not report.accepted:
            detail = report.messages[-1] if report.messages else "patch validation failed"
            reason = _stage_failure(package, "merge", detail)
            return ExecutionResult(False, reason, global_grid, completed, package.id, reports, usage)

        accepted_patch_path: Path | None = None
        if len(merge_result.accepted_patch):
            accepted_patch_path = component_rundir.path("accepted_patch.schem")
            export_schem(merge_result.accepted_patch, str(accepted_patch_path))
        global_grid = merge_result.merged_grid
        merged_path: Path | None = None
        if len(global_grid):
            merged_path = component_rundir.path("merged_after_component.schem")
            export_schem(global_grid, str(merged_path))

        completed.append(package.id)
        emit(
            "component_merged",
            index=index,
            total=total,
            package_id=package.id,
            block_count=len(global_grid),
            applied_voxels=report.applied_voxels,
            report=report.to_dict(),
            merge_report_path=str(merge_report_path),
            accepted_patch_path=str(accepted_patch_path) if accepted_patch_path is not None else None,
            merged_path=str(merged_path) if merged_path is not None else None,
            grid=global_grid.clone(),
        )

    if len(global_grid) == 0:
        return ExecutionResult(
            False,
            "Project execution produced no merged voxels.",
            global_grid,
            completed,
            None,
            reports,
            usage,
        )

    return ExecutionResult(
        True,
        f"Completed {len(completed)}/{total} work packages.",
        global_grid,
        completed,
        None,
        reports,
        usage,
    )
