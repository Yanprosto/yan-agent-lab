from mcbuild.orchestrator.merge import validate_and_merge_patch
from mcbuild.orchestrator.models import (
    BoundaryKind,
    Instance,
    InterfaceZone,
    MergePolicy,
    ProjectPlan,
    Responsibility,
    Site,
    StyleBible,
    WorkPackage,
    WritePolicy,
)
from mcbuild.orchestrator.region import RegionExpr
from mcbuild.palette import get_block, get_block_by_index
from mcbuild.voxel import VoxelGrid


def _rect(min_x, max_x, min_z=0, max_z=0):
    return RegionExpr.from_dict(
        {
            "op": "shape",
            "shape": {
                "kind": "axis_aligned_rectangle",
                "min_x": min_x,
                "max_x": max_x,
                "min_z": min_z,
                "max_z": max_z,
            },
        }
    )


def _style():
    return StyleBible(**{name: "shared" for name in StyleBible.FIELD_NAMES})


def _package(
    package_id="keep",
    *,
    boundary=BoundaryKind.HARD,
    policy=WritePolicy.PRESERVE_EXISTING,
    core=None,
    halo=None,
):
    return WorkPackage(
        id=package_id,
        name=package_id,
        semantic_type="structure",
        objective="Build it",
        instances=[Instance("main", (0, 0, 0), 0)],
        responsibility=Responsibility(boundary, core or _rect(0, 1), 0, 2, halo, policy),
        depends_on=[],
        neighbor_context=[],
        worker_brief="Use the shared style",
        acceptance_criteria=["complete"],
        requested_views=[{"yaw": 0}],
    )


def _plan(packages, interfaces=None):
    return ProjectPlan(1, "Test", "Test plan", Site(-20, 20, -20, 20, 0), _style(), packages, interfaces or [])


def _grid(*entries):
    grid = VoxelGrid()
    for x, y, z, block in entries:
        grid.set(x, y, z, get_block(block).index)
    return grid


def _name(grid, x, y=0, z=0):
    index = grid.get(x, y, z)
    return get_block_by_index(index).name if index is not None else None


def test_hard_boundary_rejects_complete_patch_for_explicit_air_outside():
    package = _package(policy=WritePolicy.OVERWRITE, core=_rect(0, 0))
    plan = _plan([package])
    original = _grid((0, 0, 0, "stone"))
    worker = _grid((0, 0, 0, "glass"), (5, 0, 0, "air"))

    result = validate_and_merge_patch(original, worker, package, plan)

    assert result.validation.accepted is False
    assert result.validation.forbidden_voxels == 1
    assert result.validation.forbidden_bounds == ((5, 0, 0), (5, 0, 0))
    assert _name(original, 0) == "stone"
    assert _name(result.merged_grid, 0) == "stone"
    assert len(result.accepted_patch) == 0


def test_soft_boundary_clips_outside_and_keeps_core_and_halo():
    package = _package(
        boundary=BoundaryKind.SOFT,
        policy=WritePolicy.ADDITIVE,
        core=_rect(0, 0),
        halo=_rect(1, 1),
    )
    plan = _plan([package])
    worker = _grid((0, 0, 0, "stone"), (1, 0, 0, "glass"), (2, 0, 0, "oak_planks"))

    result = validate_and_merge_patch(VoxelGrid(), worker, package, plan)

    report = result.validation
    assert report.accepted is True
    assert (report.core_voxels, report.halo_voxels, report.clipped_voxels) == (1, 1, 1)
    assert report.core_voxels + report.halo_voxels + report.interface_voxels + report.clipped_voxels == 3
    assert _name(result.merged_grid, 0) == "stone"
    assert _name(result.merged_grid, 1) == "glass"
    assert _name(result.merged_grid, 2) is None


def test_preserve_existing_counts_conflict_but_fills_explicit_air_target():
    package = _package(core=_rect(0, 1))
    plan = _plan([package])
    original = _grid((0, 0, 0, "stone"), (1, 0, 0, "air"))
    worker = _grid((0, 0, 0, "glass"), (1, 0, 0, "oak_planks"))

    result = validate_and_merge_patch(original, worker, package, plan)

    assert result.validation.conflict_voxels == 1
    assert result.validation.applied_voxels == 1
    assert _name(result.merged_grid, 0) == "stone"
    assert _name(result.merged_grid, 1) == "oak_planks"


def test_overwrite_only_overwrites_core_while_halo_preserves():
    package = _package(
        boundary=BoundaryKind.SOFT,
        policy=WritePolicy.OVERWRITE,
        core=_rect(0, 0),
        halo=_rect(1, 1),
    )
    plan = _plan([package])
    original = _grid((0, 0, 0, "stone"), (1, 0, 0, "stone"))
    worker = _grid((0, 0, 0, "glass"), (1, 0, 0, "glass"))

    result = validate_and_merge_patch(original, worker, package, plan)

    assert _name(result.merged_grid, 0) == "glass"
    assert _name(result.merged_grid, 1) == "stone"
    assert result.validation.conflict_voxels == 1


def test_carve_air_only_applies_in_core():
    package = _package(
        boundary=BoundaryKind.SOFT,
        policy=WritePolicy.CARVE,
        core=_rect(0, 0),
        halo=_rect(1, 1),
    )
    plan = _plan([package])
    original = _grid((0, 0, 0, "stone"), (1, 0, 0, "stone"))
    worker = _grid((0, 0, 0, "air"), (1, 0, 0, "air"))

    result = validate_and_merge_patch(original, worker, package, plan)

    assert _name(result.merged_grid, 0) == "air"
    assert _name(result.merged_grid, 1) == "stone"
    assert result.validation.ignored_air_voxels == 1


def test_interface_precedes_halo_and_preserves_existing():
    left = _package(
        "left",
        boundary=BoundaryKind.SOFT,
        policy=WritePolicy.OVERWRITE,
        core=_rect(0, 0),
        halo=_rect(1, 1),
    )
    right = _package("right", core=_rect(1, 1))
    interface = InterfaceZone(
        "join",
        ("left", "right"),
        _rect(1, 1),
        "intentional join",
        MergePolicy.PRESERVE_EXISTING,
    )
    plan = _plan([left, right], [interface])
    original = _grid((1, 0, 0, "stone"))
    worker = _grid((1, 0, 0, "glass"))

    result = validate_and_merge_patch(original, worker, left, plan)

    assert result.validation.interface_voxels == 1
    assert result.validation.halo_voxels == 0
    assert result.validation.conflict_voxels == 1
    assert _name(result.merged_grid, 1) == "stone"


def test_affected_bounds_are_recomputed_from_actual_worker_items():
    package = _package(core=_rect(0, 10))
    plan = _plan([package])
    worker = _grid((10, 0, 0, "stone"))
    worker.clear_block(10, 0, 0)
    worker.set(1, 0, 0, get_block("stone").index)
    assert worker.bounds == ((1, 0, 0), (10, 0, 0))  # intentionally conservative after clear

    result = validate_and_merge_patch(VoxelGrid(), worker, package, plan)

    assert result.validation.affected_bounds == ((1, 0, 0), (1, 0, 0))


def test_voxel_limit_failure_does_not_leak_partial_merge(monkeypatch):
    package = _package(policy=WritePolicy.OVERWRITE, core=_rect(0, 1))
    plan = _plan([package])
    original = _grid((0, 0, 0, "stone"))
    worker = _grid((1, 0, 0, "glass"))
    monkeypatch.setattr("mcbuild.voxel.MAX_BLOCKS", 1)

    result = validate_and_merge_patch(original, worker, package, plan)

    assert result.validation.accepted is False
    assert _name(result.merged_grid, 0) == "stone"
    assert _name(result.merged_grid, 1) is None
    assert len(result.accepted_patch) == 0
