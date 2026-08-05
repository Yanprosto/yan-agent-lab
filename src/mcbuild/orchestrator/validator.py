"""Semantic validation and stable dependency ordering for ``ProjectPlan``."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from typing import Any

from mcbuild.orchestrator.models import BoundaryKind, MergePolicy, ProjectPlan, WorkPackage
from mcbuild.orchestrator.region import Bounds2D, RegionExpr
from mcbuild.voxel import MAX_BLOCKS, MAX_EXTENT

_MAX_VALIDATION_CELLS = MAX_EXTENT * MAX_EXTENT


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """One machine-readable plan diagnostic."""

    code: str
    message: str
    severity: ValidationSeverity
    package_ids: tuple[str, ...] = ()
    interface_id: str | None = None
    voxel_count: int | None = None
    bounds: Bounds2D | None = None
    min_y: int | None = None
    max_y: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
        }
        if self.package_ids:
            result["package_ids"] = list(self.package_ids)
        if self.interface_id is not None:
            result["interface_id"] = self.interface_id
        if self.voxel_count is not None:
            result["voxel_count"] = self.voxel_count
        if self.bounds is not None:
            result["bounds"] = list(self.bounds)
        if self.min_y is not None:
            result["min_y"] = self.min_y
        if self.max_y is not None:
            result["max_y"] = self.max_y
        return result


@dataclass
class PlanValidationReport:
    """All errors and warnings produced before any worker is allowed to run."""

    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def is_valid(self) -> bool:
        """Compatibility alias for callers that prefer an adjective property."""
        return self.valid

    @property
    def messages(self) -> list[str]:
        return [issue.message for issue in (*self.errors, *self.warnings)]

    def add_error(self, code: str, message: str, **details: Any) -> None:
        self.errors.append(ValidationIssue(code=code, message=message, severity=ValidationSeverity.ERROR, **details))

    def add_warning(self, code: str, message: str, **details: Any) -> None:
        self.warnings.append(
            ValidationIssue(code=code, message=message, severity=ValidationSeverity.WARNING, **details)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


class PlanValidationError(ValueError):
    """Raised when an ordering operation is requested for an invalid dependency graph."""

    def __init__(self, message: str, report: PlanValidationReport | None = None) -> None:
        self.report = report
        super().__init__(message)


def _bounds_intersection(left: Bounds2D | None, right: Bounds2D | None) -> Bounds2D | None:
    if left is None or right is None:
        return None
    min_x = max(left[0], right[0])
    max_x = min(left[1], right[1])
    min_z = max(left[2], right[2])
    max_z = min(left[3], right[3])
    if min_x > max_x or min_z > max_z:
        return None
    return min_x, max_x, min_z, max_z


def _height_intersection(left: WorkPackage, right: WorkPackage) -> tuple[int, int] | None:
    min_y = max(left.responsibility.min_y, right.responsibility.min_y)
    max_y = min(left.responsibility.max_y, right.responsibility.max_y)
    return (min_y, max_y) if min_y <= max_y else None


def _bounds_area(bounds: Bounds2D) -> int:
    return (bounds[1] - bounds[0] + 1) * (bounds[3] - bounds[2] + 1)


def _matching_cells(left: RegionExpr, right: RegionExpr) -> list[tuple[int, int]] | None:
    envelope = _bounds_intersection(left.bounds(), right.bounds())
    if envelope is None:
        return []
    if _bounds_area(envelope) > _MAX_VALIDATION_CELLS:
        return None
    return [
        (x, z)
        for x in range(envelope[0], envelope[1] + 1)
        for z in range(envelope[2], envelope[3] + 1)
        if left.contains(x, z) and right.contains(x, z)
    ]


def _cell_bounds(cells: list[tuple[int, int]]) -> Bounds2D | None:
    if not cells:
        return None
    xs = [cell[0] for cell in cells]
    zs = [cell[1] for cell in cells]
    return min(xs), max(xs), min(zs), max(zs)


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _dependency_order(plan: ProjectPlan) -> tuple[list[WorkPackage], list[str]]:
    ids = [package.id for package in plan.work_packages]
    if _duplicate_values(ids):
        return [], []
    package_map = {package.id: package for package in plan.work_packages}
    if any(
        dependency not in package_map or dependency == package.id
        for package in plan.work_packages
        for dependency in package.depends_on
    ):
        return [], []

    remaining = {package.id: set(package.depends_on) for package in plan.work_packages}
    ordered: list[WorkPackage] = []
    while remaining:
        ready_ids = [
            package.id for package in plan.work_packages if package.id in remaining and not remaining[package.id]
        ]
        if not ready_ids:
            return ordered, [package.id for package in plan.work_packages if package.id in remaining]
        ready_set = set(ready_ids)
        ordered.extend(package_map[package_id] for package_id in ready_ids)
        for package_id in ready_ids:
            del remaining[package_id]
        for dependencies in remaining.values():
            dependencies.difference_update(ready_set)
    return ordered, []


def stable_topological_order(plan: ProjectPlan) -> list[WorkPackage]:
    """Return dependency layers in order, preserving plan order within every layer."""
    report = PlanValidationReport()
    package_ids = [package.id for package in plan.work_packages]
    duplicates = _duplicate_values(package_ids)
    if duplicates:
        report.add_error("duplicate_package_id", f"duplicate work package id(s): {', '.join(duplicates)}")
    known = set(package_ids)
    for package in plan.work_packages:
        for dependency in package.depends_on:
            if dependency not in known:
                report.add_error(
                    "unknown_dependency",
                    f"work package {package.id} depends on unknown package {dependency}",
                    package_ids=(package.id,),
                )
            elif dependency == package.id:
                report.add_error(
                    "self_dependency",
                    f"work package {package.id} cannot depend on itself",
                    package_ids=(package.id,),
                )
    if report.errors:
        raise PlanValidationError("project dependency graph is invalid", report)
    ordered, cycle_ids = _dependency_order(plan)
    if cycle_ids:
        report.add_error(
            "dependency_cycle",
            f"dependency cycle involves: {', '.join(cycle_ids)}",
            package_ids=tuple(cycle_ids),
        )
        raise PlanValidationError("project dependency graph contains a cycle", report)
    return ordered


def _check_region_within_site(
    region: RegionExpr,
    plan: ProjectPlan,
    report: PlanValidationReport,
    *,
    code: str,
    label: str,
    package_ids: tuple[str, ...] = (),
    interface_id: str | None = None,
) -> None:
    bounds = region.bounds()
    if bounds is None:
        report.add_error(
            f"empty_{code}",
            f"{label} has no possible bounds",
            package_ids=package_ids,
            interface_id=interface_id,
        )
        return
    if _bounds_area(bounds) > _MAX_VALIDATION_CELLS:
        report.add_error(
            "region_extent_limit",
            f"{label} envelope is too large to validate safely",
            package_ids=package_ids,
            interface_id=interface_id,
            bounds=bounds,
        )
        return
    cells = list(region.iter_cells())
    if not cells:
        report.add_error(
            f"empty_{code}",
            f"{label} contains no integer cells",
            package_ids=package_ids,
            interface_id=interface_id,
            bounds=bounds,
        )
        return
    outside = [(x, z) for x, z in cells if not plan.site.contains(x, z)]
    if outside:
        report.add_error(
            f"{code}_outside_site",
            f"{label} contains {len(outside)} cell(s) outside the project site",
            package_ids=package_ids,
            interface_id=interface_id,
            voxel_count=len(outside),
            bounds=_cell_bounds(outside),
        )


def _check_identifiers_and_dependencies(plan: ProjectPlan, report: PlanValidationReport) -> None:
    package_ids = [package.id for package in plan.work_packages]
    for duplicate in _duplicate_values(package_ids):
        report.add_error(
            "duplicate_package_id",
            f"duplicate work package id: {duplicate}",
            package_ids=(duplicate,),
        )
    interface_ids = [zone.id for zone in plan.interfaces]
    for duplicate in _duplicate_values(interface_ids):
        report.add_error(
            "duplicate_interface_id",
            f"duplicate interface id: {duplicate}",
            interface_id=duplicate,
        )

    known = set(package_ids)
    for package in plan.work_packages:
        for duplicate in _duplicate_values([instance.id for instance in package.instances]):
            report.add_error(
                "duplicate_instance_id",
                f"work package {package.id} has duplicate instance id: {duplicate}",
                package_ids=(package.id,),
            )
        for duplicate in _duplicate_values(package.depends_on):
            report.add_error(
                "duplicate_dependency",
                f"work package {package.id} repeats dependency {duplicate}",
                package_ids=(package.id,),
            )
        for dependency in package.depends_on:
            if dependency not in known:
                report.add_error(
                    "unknown_dependency",
                    f"work package {package.id} depends on unknown package {dependency}",
                    package_ids=(package.id,),
                )
            elif dependency == package.id:
                report.add_error(
                    "self_dependency",
                    f"work package {package.id} cannot depend on itself",
                    package_ids=(package.id,),
                )

    if not _duplicate_values(package_ids) and not any(
        issue.code in {"unknown_dependency", "self_dependency"} for issue in report.errors
    ):
        _, cycle_ids = _dependency_order(plan)
        if cycle_ids:
            report.add_error(
                "dependency_cycle",
                f"dependency cycle involves: {', '.join(cycle_ids)}",
                package_ids=tuple(cycle_ids),
            )


def _check_extents(plan: ProjectPlan, report: PlanValidationReport) -> None:
    site_width = plan.site.max_x - plan.site.min_x + 1
    site_depth = plan.site.max_z - plan.site.min_z + 1
    if site_width > MAX_EXTENT:
        report.add_error(
            "site_extent_limit",
            f"project site x extent {site_width} exceeds VoxelGrid limit {MAX_EXTENT}",
            bounds=plan.site.bounds,
        )
    if site_depth > MAX_EXTENT:
        report.add_error(
            "site_extent_limit",
            f"project site z extent {site_depth} exceeds VoxelGrid limit {MAX_EXTENT}",
            bounds=plan.site.bounds,
        )

    min_y = min([plan.site.base_y, *(package.responsibility.min_y for package in plan.work_packages)])
    max_y = max([plan.site.base_y, *(package.responsibility.max_y for package in plan.work_packages)])
    height = max_y - min_y + 1
    if height > MAX_EXTENT:
        report.add_error(
            "project_height_limit",
            f"project y extent {height} exceeds VoxelGrid limit {MAX_EXTENT}",
            min_y=min_y,
            max_y=max_y,
        )

    conservative_volume = 0
    for package in plan.work_packages:
        bounds = package.responsibility.allowed_bounds()
        if bounds is not None:
            conservative_volume += _bounds_area(bounds) * (
                package.responsibility.max_y - package.responsibility.min_y + 1
            )
    if conservative_volume > MAX_BLOCKS:
        report.add_warning(
            "potential_block_limit",
            f"conservative responsibility volume {conservative_volume:,} exceeds VoxelGrid block limit {MAX_BLOCKS:,}",
            voxel_count=conservative_volume,
        )


def _check_packages(plan: ProjectPlan, report: PlanValidationReport) -> None:
    for package in plan.work_packages:
        responsibility = package.responsibility
        _check_region_within_site(
            responsibility.core,
            plan,
            report,
            code="core",
            label=f"work package {package.id} core",
            package_ids=(package.id,),
        )
        if responsibility.halo is not None:
            _check_region_within_site(
                responsibility.halo,
                plan,
                report,
                code="halo",
                label=f"work package {package.id} halo",
                package_ids=(package.id,),
            )
        for instance in package.instances:
            x, y, z = instance.anchor
            if not plan.site.contains(x, z):
                report.add_error(
                    "instance_outside_site",
                    f"instance {package.id}/{instance.id} anchor is outside the project site",
                    package_ids=(package.id,),
                    bounds=(x, x, z, z),
                    min_y=y,
                    max_y=y,
                )
            if not responsibility.contains(x, y, z):
                report.add_error(
                    "instance_outside_core",
                    f"instance {package.id}/{instance.id} anchor is outside its core responsibility",
                    package_ids=(package.id,),
                    bounds=(x, x, z, z),
                    min_y=y,
                    max_y=y,
                )


def _check_core_overlaps(plan: ProjectPlan, report: PlanValidationReport) -> None:
    for left, right in combinations(plan.work_packages, 2):
        heights = _height_intersection(left, right)
        if heights is None:
            continue
        cells = _matching_cells(left.responsibility.core, right.responsibility.core)
        if cells is None:
            report.add_error(
                "overlap_scan_limit",
                f"core overlap envelope for {left.id} and {right.id} is too large to validate",
                package_ids=(left.id, right.id),
            )
            continue
        if not cells:
            continue
        height = heights[1] - heights[0] + 1
        count = len(cells) * height
        report.add_error(
            "core_overlap",
            f"work packages {left.id} and {right.id} overlap in {count} core voxel(s)",
            package_ids=(left.id, right.id),
            voxel_count=count,
            bounds=_cell_bounds(cells),
            min_y=heights[0],
            max_y=heights[1],
        )


def _check_interfaces(plan: ProjectPlan, report: PlanValidationReport) -> None:
    package_map = plan.work_package_map
    for zone in plan.interfaces:
        if zone.merge_policy is not MergePolicy.PRESERVE_EXISTING:
            report.add_error(
                "unsupported_interface_policy",
                f"interface {zone.id} must use preserve_existing",
                interface_id=zone.id,
            )
        missing = [participant for participant in zone.participants if participant not in package_map]
        if missing:
            report.add_error(
                "unknown_interface_participant",
                f"interface {zone.id} references unknown participant(s): {', '.join(missing)}",
                package_ids=zone.participants,
                interface_id=zone.id,
            )
            continue
        left = package_map[zone.participants[0]]
        right = package_map[zone.participants[1]]
        heights = _height_intersection(left, right)
        if heights is None:
            report.add_error(
                "interface_height_mismatch",
                f"interface {zone.id} participants have disjoint height ranges",
                package_ids=zone.participants,
                interface_id=zone.id,
            )
            continue

        _check_region_within_site(
            zone.region,
            plan,
            report,
            code="interface",
            label=f"interface {zone.id}",
            package_ids=zone.participants,
            interface_id=zone.id,
        )
        bounds = zone.region.bounds()
        if bounds is None or _bounds_area(bounds) > _MAX_VALIDATION_CELLS:
            continue
        interface_cells = list(zone.region.iter_cells())
        outside_participants = [
            cell
            for cell in interface_cells
            if not left.responsibility.planar_contains(*cell, include_halo=True)
            or not right.responsibility.planar_contains(*cell, include_halo=True)
        ]
        if outside_participants:
            count = len(outside_participants) * (heights[1] - heights[0] + 1)
            report.add_error(
                "interface_outside_participants",
                f"interface {zone.id} has {count} voxel(s) outside participant allowed volumes",
                package_ids=zone.participants,
                interface_id=zone.id,
                voxel_count=count,
                bounds=_cell_bounds(outside_participants),
                min_y=heights[0],
                max_y=heights[1],
            )

        for third in plan.work_packages:
            if third.id in zone.participants:
                continue
            third_min_y = max(heights[0], third.responsibility.min_y)
            third_max_y = min(heights[1], third.responsibility.max_y)
            if third_min_y > third_max_y:
                continue
            used = [cell for cell in interface_cells if third.responsibility.planar_contains(*cell, include_halo=True)]
            if used:
                count = len(used) * (third_max_y - third_min_y + 1)
                report.add_error(
                    "interface_used_by_nonparticipant",
                    f"interface {zone.id} is occupied by non-participant {third.id} in {count} voxel(s)",
                    package_ids=(*zone.participants, third.id),
                    interface_id=zone.id,
                    voxel_count=count,
                    bounds=_cell_bounds(used),
                    min_y=third_min_y,
                    max_y=third_max_y,
                )


def _check_halo_core_contracts(plan: ProjectPlan, report: PlanValidationReport) -> None:
    package_map = plan.work_package_map
    zones_by_pair: dict[frozenset[str], list[RegionExpr]] = {}
    for zone in plan.interfaces:
        if all(participant in package_map for participant in zone.participants):
            zones_by_pair.setdefault(frozenset(zone.participants), []).append(zone.region)

    for halo_owner in plan.work_packages:
        halo = halo_owner.responsibility.halo
        if halo_owner.responsibility.boundary_kind is not BoundaryKind.SOFT or halo is None:
            continue
        for core_owner in plan.work_packages:
            if halo_owner.id == core_owner.id:
                continue
            heights = _height_intersection(halo_owner, core_owner)
            if heights is None:
                continue
            cells = _matching_cells(halo, core_owner.responsibility.core)
            if cells is None:
                report.add_error(
                    "overlap_scan_limit",
                    f"halo/core overlap envelope for {halo_owner.id} and {core_owner.id} is too large to validate",
                    package_ids=(halo_owner.id, core_owner.id),
                )
                continue
            if not cells:
                continue
            interfaces = zones_by_pair.get(frozenset((halo_owner.id, core_owner.id)), [])
            uncovered = [cell for cell in cells if not any(zone.contains(*cell) for zone in interfaces)]
            if uncovered:
                count = len(uncovered) * (heights[1] - heights[0] + 1)
                report.add_error(
                    "halo_core_without_interface",
                    f"halo of {halo_owner.id} overlaps core of {core_owner.id} "
                    f"in {count} voxel(s) outside an interface",
                    package_ids=(halo_owner.id, core_owner.id),
                    voxel_count=count,
                    bounds=_cell_bounds(uncovered),
                    min_y=heights[0],
                    max_y=heights[1],
                )


def validate_project_plan(plan: ProjectPlan, max_components: int = 8) -> PlanValidationReport:
    """Validate all first-milestone plan invariants before worker execution.

    Core overlap counts use true 2.5D integer voxel volume.  Interface height is
    derived from the inclusive intersection of its two participants' y ranges.
    """
    if not isinstance(plan, ProjectPlan):
        raise TypeError("plan must be a ProjectPlan")
    if type(max_components) is not int or max_components <= 0:
        raise ValueError("max_components must be a positive integer")

    report = PlanValidationReport()
    if len(plan.work_packages) > max_components:
        report.add_error(
            "max_components_exceeded",
            f"plan has {len(plan.work_packages)} work packages; maximum is {max_components}",
        )
    _check_identifiers_and_dependencies(plan, report)
    _check_extents(plan, report)
    _check_packages(plan, report)
    _check_core_overlaps(plan, report)
    _check_interfaces(plan, report)
    _check_halo_core_contracts(plan, report)
    return report
