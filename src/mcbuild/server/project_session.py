"""Stream one multi-component project through the existing WebSocket protocol."""

from __future__ import annotations

import asyncio
from typing import Any

from mcbuild.config import Config
from mcbuild.llm.client import OpenRouterClient
from mcbuild.orchestrator.loop import run_project
from mcbuild.orchestrator.models import ProjectConfig, WorkPackage
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.server import protocol
from mcbuild.server.delta import compute_block_delta
from mcbuild.server.message_queue import Send, drain_messages, finish_message_drain
from mcbuild.voxel import VoxelGrid


async def run_project_session(
    prompt: str,
    send: Send,
    config: Config | None = None,
    project_config: ProjectConfig | None = None,
) -> None:
    """Run ``run_project`` in a worker thread and stream per-component global deltas."""

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def enqueue(message: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, message)

    drain_task = asyncio.create_task(drain_messages(queue, send))
    worker_config = config or Config()
    project_config = project_config or ProjectConfig(
        worker_config=worker_config,
        planner_model=worker_config.model,
        cost_ceiling=worker_config.cost_ceiling,
    )
    rundir = ProjectRunDir.create(prompt, base=worker_config.out_dir)
    queue.put_nowait(protocol.hello(str(rundir.root)))

    try:
        planner_llm = OpenRouterClient()
    except RuntimeError as error:
        queue.put_nowait(protocol.error(str(error)))
        await finish_message_drain(queue, drain_task)
        return

    def worker_factory(package: WorkPackage) -> OpenRouterClient:
        del package
        return OpenRouterClient()

    previous_grid: VoxelGrid | None = None

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        nonlocal previous_grid
        if event_type == "plan_submitted":
            enqueue(protocol.chat(f"[mcbuild-project] planning: draft {data['version']}"))
        elif event_type == "plan_revised":
            enqueue(protocol.chat(f"[mcbuild-project] planning: revision {data['version']}"))
        elif event_type == "plan_validation":
            report = data["report"]
            if report.get("valid"):
                enqueue(protocol.chat("[mcbuild-project] planning: validation passed"))
            else:
                enqueue(
                    protocol.chat(f"[mcbuild-project] planning: {len(report.get('errors', []))} validation error(s)")
                )
        elif event_type == "plan_approved":
            enqueue(protocol.chat("[mcbuild-project] planning: approved"))
        elif event_type == "component_start":
            enqueue(protocol.chat(f"[mcbuild-project] component {data['index']}/{data['total']}: {data['package_id']}"))
        elif event_type == "component_patch_validation":
            report = data["report"]
            clipped = int(report.get("clipped_voxels", 0))
            if clipped:
                enqueue(
                    protocol.chat(
                        f"[mcbuild-project] component {data['package_id']} clipped {clipped} soft-boundary voxels"
                    )
                )
        elif event_type == "component_merged":
            current_grid = data.get("grid")
            if isinstance(current_grid, VoxelGrid):
                changes = compute_block_delta(previous_grid, current_grid)
                previous_grid = current_grid.clone()
                if changes:
                    enqueue(protocol.blocks(int(data["index"]), changes))
            enqueue(
                protocol.chat(
                    f"[mcbuild-project] component {data['package_id']} merged: "
                    f"{int(data['block_count']):,} stored voxels"
                )
            )
        elif event_type == "project_abort":
            enqueue(protocol.chat(f"[mcbuild-project] aborted: {data['reason']}"))
        # Planner deltas/reasoning and nested worker reasoning/content events are
        # intentionally never forwarded to Minecraft chat.

    result = await asyncio.to_thread(
        run_project,
        prompt,
        planner_llm,
        worker_factory,
        project_config,
        rundir,
        on_event,
    )

    # Every worker-thread enqueue was scheduled before ``to_thread`` completed. Yield once
    # so those callbacks reach the queue, then append the terminal message directly; this
    # guarantees finish/error follows the final blocks/chat frame.
    await asyncio.sleep(0)
    if result.finished:
        queue.put_nowait(
            protocol.finish(
                f"finished: {len(result.completed_packages)}/"
                f"{len(result.plan.work_packages) if result.plan else 0} components, "
                f"{len(result.grid) if result.grid is not None else 0:,} stored voxels"
            )
        )
    else:
        queue.put_nowait(protocol.error(result.summary))

    await finish_message_drain(queue, drain_task)
