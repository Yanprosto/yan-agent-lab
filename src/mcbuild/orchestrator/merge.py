"""Validate one worker VoxelGrid as a responsibility-scoped patch and merge it.

Worker grids contain three distinct states: a missing coordinate, an explicitly
stored ``air`` palette entry, or a stored non-air block.  This module preserves
that distinction and never mutates either input grid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mcbuild.orchestrator.models import BoundaryKind, ProjectPlan, WorkPackage, WritePolicy
from mcbuild.palette import get_block_by_index
from mcbuild.voxel import Coord, VoxelGrid, VoxelLimitError

Bounds3D = tuple[Coord, Coord]


class _PatchRegion(StrEnum):
    INTERFACE = "interface"
    CORE = "core"
    HALO = "halo"
    OUTSIDE = "outside"


@dataclass
class PatchValidation:
    """Serializable accounting for one worker patch.

    Region counters are exclusive: every stored worker intent is counted once
    as interface, core, halo, clipped (soft outside), or forbidden (hard
    outside).  Conflicts and ignored air are additional outcome counters.
    """

    accepted: bool
    total_voxels: int
    core_voxels: int = 0
    halo_voxels: int = 0
    interface_voxels: int = 0
    clipped_voxels: int = 0
    forbidden_voxels: int = 0
    conflict_voxels: int = 0
    applied_voxels: int = 0
    ignored_air_voxels: int = 0
    affected_bounds: Bounds3D | None = None
    clipped_bounds: Bounds3D | None = None
    forbidden_bounds: Bounds3D | None = None
    accepted_bounds: Bounds3D | None = None
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "total_voxels": self.total_voxels,
            "core_voxels": self.core_voxels,
            "halo_voxels": self.halo_voxels,
            "interface_voxels": self.interface_voxels,
            "clipped_voxels": self.clipped_voxels,
            "forbidden_voxels": self.forbidden_voxels,
            "conflict_voxels": self.conflict_voxels,
            "applied_voxels": self.applied_voxels,
            "ignored_air_voxels": self.ignored_air_voxels,
            "affected_bounds": _bounds_to_json(self.affected_bounds),
            "clipped_bounds": _bounds_to_json(self.clipped_bounds),
            "forbidden_bounds": _bounds_to_json(self.forbidden_bounds),
            "accepted_bounds": _bounds_to_json(self.accepted_bounds),
            "messages": list(self.messages),
        }


@dataclass(frozen=True)
class MergeResult:
    """The validation report, transaction result, and effective write patch."""

    validation: PatchValidation
    merged_grid: VoxelGrid
    accepted_patch: VoxelGrid

    @property
    def grid(self) -> VoxelGrid:
        """Compatibility alias for callers interested only in the merged grid."""
        return self.merged_grid


def _bounds_to_json(bounds: Bounds3D | None) -> list[list[int]] | None:
    if bounds is None:
        return None
    return [list(bounds[0]), list(bounds[1])]


def _coordinate_bounds(coords: list[Coord]) -> Bounds3D | None:
    if not coords:
        return None
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    zs = [coord[2] for coord in coords]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _is_air(palette_index: int) -> bool:
    return get_block_by_index(palette_index).name == "air"


def _interface_contains(plan: ProjectPlan, package: WorkPackage, x: int, y: int, z: int) -> bool:
    responsibility = package.responsibility
    include_halo = responsibility.boundary_kind is BoundaryKind.SOFT
    if not responsibility.contains(x, y, z, include_halo=include_halo):
        return False
    packages = {candidate.id: candidate for candidate in plan.work_packages}
    for interface in plan.interfaces:
        if package.id not in interface.participants or not interface.region.contains(x, z):
            continue
        participant_packages = [packages.get(participant) for participant in interface.participants]
        if any(participant is None for participant in participant_packages):
            # The plan validator owns this error. Treat an invalid, unknown interface
            # as unusable here instead of accidentally granting write permission.
            continue
        min_y = max(participant.responsibility.min_y for participant in participant_packages if participant is not None)
        max_y = min(participant.responsibility.max_y for participant in participant_packages if participant is not None)
        if min_y <= y <= max_y:
            return True
    return False


def _classify(plan: ProjectPlan, package: WorkPackage, coord: Coord) -> _PatchRegion:
    x, y, z = coord
    responsibility = package.responsibility
    # An intentional interface has precedence over ordinary responsibility so
    # its preserve-existing rule cannot be bypassed by overwrite/carve.
    if _interface_contains(plan, package, x, y, z):
        return _PatchRegion.INTERFACE
    if responsibility.contains(x, y, z):
        return _PatchRegion.CORE
    if responsibility.boundary_kind is BoundaryKind.SOFT and responsibility.contains(x, y, z, include_halo=True):
        return _PatchRegion.HALO
    return _PatchRegion.OUTSIDE


def validate_and_merge_patch(
    global_grid: VoxelGrid,
    worker_grid: VoxelGrid,
    package: WorkPackage,
    plan: ProjectPlan,
) -> MergeResult:
    """Validate and transactionally merge one worker patch.

    Hard-boundary violations reject the complete patch, including when the
    offending intent is explicit air.  Soft-boundary violations are clipped.
    Interface and halo cells always use preserve-existing semantics.  Explicit
    air can affect the destination only for ``carve`` cells in the core.
    """
    source_items = sorted(worker_grid.items())
    source_coords = [coord for coord, _ in source_items]
    report = PatchValidation(
        accepted=True,
        total_voxels=len(source_items),
        affected_bounds=_coordinate_bounds(source_coords),
    )

    classified: list[tuple[Coord, int, _PatchRegion]] = []
    outside_coords: list[Coord] = []
    for coord, palette_index in source_items:
        region = _classify(plan, package, coord)
        classified.append((coord, palette_index, region))
        if region is _PatchRegion.INTERFACE:
            report.interface_voxels += 1
        elif region is _PatchRegion.CORE:
            report.core_voxels += 1
        elif region is _PatchRegion.HALO:
            report.halo_voxels += 1
        else:
            outside_coords.append(coord)

    if outside_coords and package.responsibility.boundary_kind is BoundaryKind.HARD:
        report.accepted = False
        report.forbidden_voxels = len(outside_coords)
        report.forbidden_bounds = _coordinate_bounds(outside_coords)
        report.messages.append(
            f"work package {package.id}: hard boundary rejected {len(outside_coords)} forbidden voxel intent(s)"
        )
        return MergeResult(report, global_grid.clone(), VoxelGrid())

    if outside_coords:
        report.clipped_voxels = len(outside_coords)
        report.clipped_bounds = _coordinate_bounds(outside_coords)
        report.messages.append(
            f"work package {package.id}: clipped {len(outside_coords)} voxel intent(s) outside the soft boundary"
        )

    operations: list[tuple[Coord, int]] = []
    try:
        for coord, source_index, region in classified:
            if region is _PatchRegion.OUTSIDE:
                continue
            source_is_air = _is_air(source_index)
            x, y, z = coord
            target_index = global_grid.get(x, y, z)
            target_is_fillable = target_index is None or _is_air(target_index)

            # Halo and interface have fixed preserve-existing behavior regardless
            # of the package's core write policy.
            if region in (_PatchRegion.HALO, _PatchRegion.INTERFACE):
                if source_is_air:
                    report.ignored_air_voxels += 1
                elif target_is_fillable:
                    operations.append((coord, source_index))
                else:
                    report.conflict_voxels += 1
                continue

            policy = package.responsibility.write_policy
            if source_is_air:
                if policy is WritePolicy.CARVE:
                    operations.append((coord, source_index))
                else:
                    report.ignored_air_voxels += 1
                continue

            if policy is WritePolicy.OVERWRITE:
                operations.append((coord, source_index))
            elif target_is_fillable:
                # preserve_existing, additive, and the non-air half of carve all
                # fill only empty/explicit-air destinations.
                operations.append((coord, source_index))
            else:
                report.conflict_voxels += 1
    except (IndexError, KeyError) as exc:
        report.accepted = False
        report.messages.append(f"work package {package.id}: invalid palette index during patch validation: {exc}")
        return MergeResult(report, global_grid.clone(), VoxelGrid())

    candidate = global_grid.clone()
    accepted_patch = VoxelGrid()
    try:
        for (x, y, z), palette_index in operations:
            candidate.set(x, y, z, palette_index)
            accepted_patch.set(x, y, z, palette_index)
    except VoxelLimitError as exc:
        report.accepted = False
        report.applied_voxels = 0
        report.accepted_bounds = None
        report.messages.append(f"work package {package.id}: merge rejected by VoxelGrid limits: {exc}")
        return MergeResult(report, global_grid.clone(), VoxelGrid())

    report.applied_voxels = len(operations)
    report.accepted_bounds = _coordinate_bounds([coord for coord, _ in operations])
    if report.conflict_voxels:
        report.messages.append(
            f"work package {package.id}: preserved {report.conflict_voxels} existing non-air voxel(s)"
        )
    if report.ignored_air_voxels:
        report.messages.append(
            f"work package {package.id}: ignored {report.ignored_air_voxels} explicit air intent(s) outside carve/core"
        )
    return MergeResult(report, candidate, accepted_patch)
