"""Deterministic Pillow renderer for a 2.5D :class:`ProjectPlan`.

The plan view is intentionally independent from the Minecraft voxel renderer.  It draws
integer responsibility cells directly, which makes permissions, interfaces, repeated
instance anchors, and invalid overlaps legible before any worker is started.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from mcbuild.orchestrator.models import ProjectPlan

_BACKGROUND = (246, 247, 249, 255)
_INK = (36, 42, 48, 255)
_MUTED = (102, 112, 122, 255)
_GRID = (214, 219, 224, 255)
_INTERFACE = (105, 57, 173, 255)
_CONFLICT = (220, 38, 38, 255)
_PACKAGE_COLORS = (
    (44, 123, 182),
    (230, 126, 34),
    (46, 160, 67),
    (193, 67, 73),
    (139, 92, 246),
    (0, 142, 156),
    (190, 105, 24),
    (85, 94, 108),
)


def _safe_text(value: object) -> str:
    """Make arbitrary model text displayable by Pillow's built-in bitmap font."""

    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _bounds_tuple(bounds: Any) -> tuple[int, int, int, int] | None:
    if bounds is None:
        return None
    if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
        return int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3])
    raise TypeError(f"Unsupported RegionExpr bounds value: {bounds!r}")


def _region_cells(region: Any) -> frozenset[tuple[int, int]]:
    return frozenset((int(x), int(z)) for x, z in region.iter_cells())


def _nice_grid_step(span: int) -> int:
    target = max(span / 10.0, 1.0)
    magnitude = 10 ** math.floor(math.log10(target))
    for multiple in (1, 2, 5, 10):
        candidate = int(multiple * magnitude)
        if candidate >= target:
            return max(candidate, 1)
    return max(int(10 * magnitude), 1)


@dataclass(frozen=True)
class _Transform:
    left: int
    top: int
    right: int
    bottom: int
    min_x_edge: float
    max_x_edge: float
    min_z_edge: float
    max_z_edge: float

    def point(self, x: float, z: float) -> tuple[int, int]:
        px = self.left + (x - self.min_x_edge) * (self.right - self.left) / (self.max_x_edge - self.min_x_edge)
        pz = self.top + (z - self.min_z_edge) * (self.bottom - self.top) / (self.max_z_edge - self.min_z_edge)
        return round(px), round(pz)

    def cell_box(self, x: int, z: int) -> tuple[int, int, int, int]:
        x0, z0 = self.point(x - 0.5, z - 0.5)
        x1, z1 = self.point(x + 0.5, z + 0.5)
        return min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1)


def _composite_cells(
    image: Image.Image,
    cells: Iterable[tuple[int, int]],
    transform: _Transform,
    color: tuple[int, int, int, int],
) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for x, z in cells:
        draw.rectangle(transform.cell_box(x, z), fill=color)
    image.alpha_composite(overlay)


def _draw_cell_boundary(
    draw: ImageDraw.ImageDraw,
    cells: frozenset[tuple[int, int]],
    transform: _Transform,
    color: tuple[int, int, int, int],
    *,
    width: int = 2,
    dashed: bool = False,
) -> None:
    for x, z in sorted(cells):
        x0, z0, x1, z1 = transform.cell_box(x, z)
        edges = (
            ((x0, z0), (x1, z0), (x, z - 1)),
            ((x1, z0), (x1, z1), (x + 1, z)),
            ((x0, z1), (x1, z1), (x, z + 1)),
            ((x0, z0), (x0, z1), (x - 1, z)),
        )
        for start, end, neighbor in edges:
            if neighbor in cells:
                continue
            if dashed:
                _dashed_line(draw, start, end, fill=color, width=width)
            else:
                draw.line((start, end), fill=color, width=width)


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    x0, y0 = start
    x1, y1 = end
    length = math.hypot(x1 - x0, y1 - y0)
    if length <= 0:
        return
    dash = 5.0
    dx = (x1 - x0) / length
    dy = (y1 - y0) / length
    position = 0.0
    while position < length:
        stop = min(position + dash, length)
        draw.line(
            (x0 + dx * position, y0 + dy * position, x0 + dx * stop, y0 + dy * stop),
            fill=fill,
            width=width,
        )
        position += dash * 2


def _draw_interface(
    image: Image.Image,
    cells: frozenset[tuple[int, int]],
    transform: _Transform,
) -> None:
    if not cells:
        return
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    for x, z in cells:
        mask_draw.rectangle(transform.cell_box(x, z), fill=150)

    layer = Image.new("RGBA", image.size, (120, 72, 190, 45))
    hatch = ImageDraw.Draw(layer)
    spacing = 9
    for offset in range(-image.height, image.width + image.height, spacing):
        hatch.line((offset, image.height, offset + image.height, 0), fill=(90, 41, 160, 205), width=1)
    image.alpha_composite(Image.composite(layer, Image.new("RGBA", image.size), mask))
    _draw_cell_boundary(ImageDraw.Draw(image), cells, transform, _INTERFACE, width=3)


def _issue_bounds(report: object | None) -> list[tuple[int, int, int, int]]:
    """Best-effort extraction of validator-provided conflict bounds."""

    if report is None:
        return []
    to_dict = getattr(report, "to_dict", None)
    payload = to_dict() if callable(to_dict) else report
    if not isinstance(payload, dict):
        return []
    found: list[tuple[int, int, int, int]] = []

    def visit(value: object, key: str = "") -> None:
        if key in {"bounds", "affected_bounds", "overlap_bounds"}:
            try:
                normalized = _bounds_tuple(value)
            except (TypeError, ValueError):
                normalized = None
            if normalized is not None:
                found.append(normalized)
                return
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(payload)
    return found


def _report_counts(report: object | None) -> tuple[bool | None, int, int]:
    if report is None:
        return None, 0, 0
    valid = bool(getattr(report, "valid", False))
    errors = getattr(report, "errors", [])
    warnings = getattr(report, "warnings", [])
    return valid, len(errors), len(warnings)


def render_plan(
    plan: ProjectPlan,
    validation: object | None = None,
    *,
    width: int = 1200,
    height: int = 820,
) -> Image.Image:
    """Render a stable top-down planning image from a validated or invalid plan.

    Package colors depend only on their order in ``ProjectPlan``.  World ``x`` grows to
    the right and world ``z`` grows down the page, so the north marker points toward
    decreasing ``z``.  Any core overlap with intersecting height ranges is highlighted
    in red even when a validation report does not expose coordinate details.
    """

    if width < 720 or height < 500:
        raise ValueError("Plan render dimensions must be at least 720x500")

    font = ImageFont.load_default()
    image = Image.new("RGBA", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)

    map_left, map_top = 70, 68
    map_right, map_bottom = width - 330, height - 76
    site = plan.site
    extents: list[tuple[int, int, int, int]] = [(site.min_x, site.max_x, site.min_z, site.max_z)]
    for package in plan.work_packages:
        for region in (package.responsibility.core, package.responsibility.halo):
            if region is not None:
                bounds = _bounds_tuple(region.bounds())
                if bounds is not None:
                    extents.append(bounds)
    for interface in plan.interfaces:
        bounds = _bounds_tuple(interface.region.bounds())
        if bounds is not None:
            extents.append(bounds)
    extents.extend(_issue_bounds(validation))

    min_x = min(item[0] for item in extents)
    max_x = max(item[1] for item in extents)
    min_z = min(item[2] for item in extents)
    max_z = max(item[3] for item in extents)
    x_span = max(max_x - min_x + 1, 1)
    z_span = max(max_z - min_z + 1, 1)

    # Keep world cells square; pad the shorter world dimension inside the fixed map box.
    map_ratio = (map_right - map_left) / (map_bottom - map_top)
    world_ratio = x_span / z_span
    if world_ratio > map_ratio:
        target_z_span = x_span / map_ratio
        padding = (target_z_span - z_span) / 2
        min_z_edge, max_z_edge = min_z - 0.5 - padding, max_z + 0.5 + padding
        min_x_edge, max_x_edge = min_x - 0.5, max_x + 0.5
    else:
        target_x_span = z_span * map_ratio
        padding = (target_x_span - x_span) / 2
        min_x_edge, max_x_edge = min_x - 0.5 - padding, max_x + 0.5 + padding
        min_z_edge, max_z_edge = min_z - 0.5, max_z + 0.5
    transform = _Transform(
        map_left,
        map_top,
        map_right,
        map_bottom,
        min_x_edge,
        max_x_edge,
        min_z_edge,
        max_z_edge,
    )

    # Coordinate grid and labels.
    step = _nice_grid_step(max(x_span, z_span))
    first_x = math.ceil(min_x / step) * step
    first_z = math.ceil(min_z / step) * step
    for x in range(first_x, max_x + 1, step):
        px, _ = transform.point(x, 0)
        draw.line((px, map_top, px, map_bottom), fill=_GRID, width=1)
        draw.text((px + 2, map_bottom + 5), str(x), font=font, fill=_MUTED)
    for z in range(first_z, max_z + 1, step):
        _, pz = transform.point(0, z)
        draw.line((map_left, pz, map_right, pz), fill=_GRID, width=1)
        draw.text((map_left - 35, pz - 5), str(z), font=font, fill=_MUTED)

    # Site border is separate from responsibility coloring.
    sx0, sz0 = transform.point(site.min_x - 0.5, site.min_z - 0.5)
    sx1, sz1 = transform.point(site.max_x + 0.5, site.max_z + 0.5)
    draw.rectangle((sx0, sz0, sx1, sz1), outline=_INK, width=3)
    draw.text((sx0 + 5, sz0 + 5), f"site base_y={site.base_y}", font=font, fill=_INK)

    package_cells: list[tuple[Any, frozenset[tuple[int, int]], frozenset[tuple[int, int]], tuple[int, int, int]]] = []
    for index, package in enumerate(plan.work_packages):
        color = _PACKAGE_COLORS[index % len(_PACKAGE_COLORS)]
        core = _region_cells(package.responsibility.core)
        halo = _region_cells(package.responsibility.halo) if package.responsibility.halo is not None else frozenset()
        package_cells.append((package, core, halo, color))
        if halo:
            _composite_cells(image, halo, transform, (*color, 30))
            _draw_cell_boundary(ImageDraw.Draw(image), halo, transform, (*color, 210), width=2, dashed=True)
        _composite_cells(image, core, transform, (*color, 72))
        boundary_width = 4 if _enum_value(package.responsibility.boundary_kind) == "hard" else 2
        _draw_cell_boundary(ImageDraw.Draw(image), core, transform, (*color, 255), width=boundary_width)

        if core:
            label_x = min(x for x, _ in core)
            label_z = min(z for _, z in core)
            px, pz = transform.point(label_x - 0.35, label_z - 0.35)
            label = _safe_text(f"{package.name} [{package.id}]")
            box = draw.textbbox((px, pz), label, font=font, anchor="la")
            draw.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill=(255, 255, 255, 220))
            draw.text((px, pz), label, font=font, fill=(*color, 255), anchor="la")

    # Interfaces are always visually dominant over package fills.
    for interface in plan.interfaces:
        cells = _region_cells(interface.region)
        _draw_interface(image, cells, transform)
        if cells:
            x, z = min(cells, key=lambda cell: (cell[1], cell[0]))
            px, pz = transform.point(x, z)
            draw.text((px + 5, pz + 7), _safe_text(interface.id), font=font, fill=_INTERFACE, anchor="la")

    # Repeated instances: 0=N (-z), 90=E (+x), 180=S, 270=W.
    for package, _core, _halo, color in package_cells:
        for instance in package.instances:
            x, _y, z = instance.anchor
            px, pz = transform.point(x, z)
            radians = math.radians(instance.rotation - 90)
            arrow = 18
            tip = (px + round(math.cos(radians) * arrow), pz + round(math.sin(radians) * arrow))
            draw.ellipse((px - 4, pz - 4, px + 4, pz + 4), fill=(*color, 255), outline=(255, 255, 255, 255))
            draw.line((px, pz, *tip), fill=(*color, 255), width=3)
            draw.ellipse((tip[0] - 2, tip[1] - 2, tip[0] + 2, tip[1] + 2), fill=(*color, 255))
            draw.text((px + 6, pz + 5), _safe_text(instance.id), font=font, fill=_INK)

    # Validator-independent core collision detection, respecting the 2.5D height range.
    conflict_cells: set[tuple[int, int]] = set()
    for left_index, (left_pkg, left_core, _left_halo, _left_color) in enumerate(package_cells):
        for right_pkg, right_core, _right_halo, _right_color in package_cells[left_index + 1 :]:
            left_resp = left_pkg.responsibility
            right_resp = right_pkg.responsibility
            if max(left_resp.min_y, right_resp.min_y) <= min(left_resp.max_y, right_resp.max_y):
                conflict_cells.update(left_core & right_core)
    for bx0, bx1, bz0, bz1 in _issue_bounds(validation):
        conflict_cells.update((x, z) for x in range(bx0, bx1 + 1) for z in range(bz0, bz1 + 1))
    if conflict_cells:
        frozen_conflicts = frozenset(conflict_cells)
        _composite_cells(image, frozen_conflicts, transform, (239, 34, 34, 112))
        _draw_cell_boundary(ImageDraw.Draw(image), frozen_conflicts, transform, _CONFLICT, width=4)

    # North arrow and scale.
    north_x, north_y = map_right - 34, map_top + 45
    draw.line((north_x, north_y + 24, north_x, north_y - 12), fill=_INK, width=3)
    draw.polygon(((north_x, north_y - 20), (north_x - 6, north_y - 8), (north_x + 6, north_y - 8)), fill=_INK)
    draw.text((north_x, north_y - 35), "N", font=font, fill=_INK, anchor="mm")
    scale_px_a = transform.point(min_x, max_z)[0]
    scale_px_b = transform.point(min_x + step, max_z)[0]
    scale_y = map_bottom + 32
    draw.line((scale_px_a, scale_y, scale_px_b, scale_y), fill=_INK, width=3)
    draw.line((scale_px_a, scale_y - 4, scale_px_a, scale_y + 4), fill=_INK, width=2)
    draw.line((scale_px_b, scale_y - 4, scale_px_b, scale_y + 4), fill=_INK, width=2)
    draw.text(((scale_px_a + scale_px_b) // 2, scale_y + 6), f"{step} blocks", font=font, fill=_INK, anchor="ma")

    # Title and fixed legend sidebar.
    draw.text((map_left, 22), _safe_text(plan.title), font=font, fill=_INK)
    valid, error_count, warning_count = _report_counts(validation)
    if valid is not None:
        status = "VALID" if valid else f"INVALID ({error_count} errors)"
        status_color = (24, 128, 56, 255) if valid else _CONFLICT
        draw.text((map_right, 22), status, font=font, fill=status_color, anchor="ra")
        if warning_count:
            draw.text((map_right, 39), f"{warning_count} warnings", font=font, fill=(178, 112, 0, 255), anchor="ra")

    legend_x = width - 292
    draw.line((legend_x - 18, 20, legend_x - 18, height - 20), fill=_GRID, width=2)
    draw.text((legend_x, 24), "LEGEND", font=font, fill=_INK)
    y = 51
    for index, package in enumerate(plan.work_packages):
        color = _PACKAGE_COLORS[index % len(_PACKAGE_COLORS)]
        draw.rectangle((legend_x, y, legend_x + 14, y + 10), fill=(*color, 80), outline=(*color, 255), width=2)
        draw.text((legend_x + 21, y), _safe_text(package.id)[:38], font=font, fill=_INK)
        y += 20
    y += 4
    draw.line((legend_x, y + 5, legend_x + 15, y + 5), fill=_INK, width=4)
    draw.text((legend_x + 21, y), "hard/core (solid heavy)", font=font, fill=_INK)
    y += 20
    _dashed_line(draw, (legend_x, y + 5), (legend_x + 15, y + 5), fill=_MUTED, width=2)
    draw.text((legend_x + 21, y), "soft/halo (dashed)", font=font, fill=_INK)
    y += 20
    draw.rectangle((legend_x, y, legend_x + 14, y + 10), outline=_INTERFACE, width=2)
    draw.line((legend_x, y + 10, legend_x + 14, y), fill=_INTERFACE, width=1)
    draw.text((legend_x + 21, y), "interface", font=font, fill=_INK)
    y += 20
    draw.rectangle((legend_x, y, legend_x + 14, y + 10), fill=(239, 34, 34, 112), outline=_CONFLICT, width=2)
    draw.text((legend_x + 21, y), "invalid overlap", font=font, fill=_INK)
    y += 28
    draw.text((legend_x, y), "Instances", font=font, fill=_INK)
    y += 17
    draw.text((legend_x, y), "dot + arrow; 0=N, 90=E", font=font, fill=_MUTED)
    y += 25
    draw.text((legend_x, y), f"Grid / scale: {step} blocks", font=font, fill=_MUTED)
    draw.text((legend_x, height - 45), f"site x={site.min_x}..{site.max_x}", font=font, fill=_MUTED)
    draw.text((legend_x, height - 29), f"site z={site.min_z}..{site.max_z}", font=font, fill=_MUTED)

    return image
