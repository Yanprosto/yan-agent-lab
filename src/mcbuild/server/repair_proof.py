"""Compact v1.1 local-repair proof helpers."""

from __future__ import annotations

from typing import Any

from mcbuild.server.environment_planner import BranchRoute, replan_failed_branch
from mcbuild.server import protocol


async def create_test_blockage(connection, action, branch: BranchRoute) -> tuple[int, int, int]:
    pos = branch.path[len(branch.path) // 2]
    await action(connection, "v11-gap-remove", "remove_block", {"x": pos[0], "y": pos[1], "z": pos[2]})
    await action(connection, "v11-gap-block", "place_block", {
        "x": pos[0], "y": pos[1], "z": pos[2], "block": "minecraft:stone"
    })
    await connection.send(protocol.chat(
        f"[yan-agent] v1.1 TEST BLOCKAGE created at {pos} on branch 2"
    ))
    return pos


async def remove_branch_except(connection, action, branch: BranchRoute, keep: tuple[int, int, int], label: str) -> None:
    removed = 0
    for i, pos in enumerate(reversed(branch.path), start=1):
        if pos == keep:
            continue
        try:
            row = await action(connection, f"{label}-{i}", "remove_block", {
                "x": pos[0], "y": pos[1], "z": pos[2]
            })
            removed += int(bool(row.get("is_air")))
        except RuntimeError:
            pass
    await connection.send(protocol.chat(
        f"[yan-agent] {label}: removed={removed}, blockage preserved at {keep}"
    ))


def local_alternatives(*, source, sink, occupied, healthy: BranchRoute, failed: BranchRoute, blockage, bounds):
    blocked = set(occupied)
    blocked.add(blockage)
    return replan_failed_branch(
        source=source,
        sink=sink,
        occupied=blocked,
        working_path=set(healthy.path),
        bounds=bounds,
        avoid_paths=[set(failed.path)],
    )
