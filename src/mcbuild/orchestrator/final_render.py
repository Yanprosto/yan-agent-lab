"""Render presentation images from a completed project's merged voxel grid."""

from __future__ import annotations

import json
from pathlib import Path

from mcbuild.palette import get_block_by_index
from mcbuild.render.camera import render_isometric
from mcbuild.render.iso import render_topdown
from mcbuild.render.views import build_contact_sheet
from mcbuild.voxel import VoxelGrid

FINAL_VIEW_SPECS = [
    {"yaw": 0},
    {"yaw": 1},
    {"yaw": 2},
    {"yaw": 3},
    {"mode": "top-down"},
]


def render_final_grid(grid: VoxelGrid, output_dir: str | Path, *, hero_yaw: int = 0) -> dict[str, Path]:
    """Write a hero view, five-view contact sheet, top-down view, and stats.

    The input must be the final merged project grid, not an individual worker grid or
    the planner's footprint preview.
    """
    if grid.bounds is None or not len(grid):
        raise ValueError("Cannot render an empty final voxel grid.")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "hero": output / "town_hero.png",
        "contact_sheet": output / "town_contact_sheet.png",
        "topdown": output / "town_topdown.png",
        "stats": output / "town_render_stats.json",
    }

    hero = render_isometric(grid, yaw=hero_yaw, width=1400, height=1000)
    contact_sheet, labels, stats = build_contact_sheet(grid, FINAL_VIEW_SPECS)
    topdown = render_topdown(grid, cell=6)
    for name, image in (("hero", hero), ("contact_sheet", contact_sheet), ("topdown", topdown)):
        if image.getbbox() is None:
            raise ValueError(f"Final {name} render is blank.")
        image.save(paths[name])

    non_air_blocks = sum(1 for _, index in grid.items() if get_block_by_index(index).mc_id != "minecraft:air")
    stats_payload = {
        **stats,
        "non_air_blocks": non_air_blocks,
        "hero_yaw": hero_yaw % 4,
        "contact_sheet_labels": labels,
    }
    paths["stats"].write_text(json.dumps(stats_payload, indent=2), encoding="utf-8")
    return paths
