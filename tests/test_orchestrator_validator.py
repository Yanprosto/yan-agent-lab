import pytest

from mcbuild.orchestrator.models import ProjectPlan
from mcbuild.orchestrator.validator import (
    PlanValidationError,
    stable_topological_order,
    validate_project_plan,
)
from mcbuild.voxel import MAX_EXTENT


def rect(min_x, max_x, min_z=-2, max_z=2):
    return {
        "op": "shape",
        "shape": {
            "kind": "axis_aligned_rectangle",
            "min_x": min_x,
            "max_x": max_x,
            "min_z": min_z,
            "max_z": max_z,
        },
    }


def package(
    package_id,
    core,
    *,
    halo=None,
    boundary="hard",
    min_y=0,
    max_y=8,
    depends_on=None,
    anchor=None,
):
    if anchor is None:
        bounds = core["shape"]
        anchor = [bounds.get("min_x", 0), min_y, bounds.get("min_z", 0)]
    return {
        "id": package_id,
        "name": package_id.replace("_", " ").title(),
        "semantic_type": "structure",
        "objective": f"Build {package_id}.",
        "instances": [{"id": "main", "anchor": anchor, "rotation": 0}],
        "responsibility": {
            "boundary_kind": boundary,
            "core": core,
            "halo": halo,
            "min_y": min_y,
            "max_y": max_y,
            "write_policy": "preserve_existing",
        },
        "depends_on": depends_on or [],
        "neighbor_context": [],
        "worker_brief": "Build only this semantic package.",
        "acceptance_criteria": ["fits its responsibility"],
        "requested_views": [{"yaw": 0}],
    }


def style_bible():
    return {
        "architectural_style": "medieval",
        "scale_and_massing": "compact",
        "primary_palette": "stone",
        "secondary_palette": "wood",
        "accent_palette": "copper",
        "roof_language": "gabled",
        "opening_language": "arched",
        "detail_language": "restrained",
        "landscape_language": "worn paths",
        "global_constraints": "project coordinates",
    }


def plan(packages, interfaces=None, site=None):
    return ProjectPlan.from_dict(
        {
            "schema_version": 1,
            "title": "Test project",
            "project_summary": "Validator fixture.",
            "site": site or {"min_x": -30, "max_x": 30, "min_z": -20, "max_z": 20, "base_y": 0},
            "style_bible": style_bible(),
            "work_packages": packages,
            "interfaces": interfaces or [],
        }
    )


def interface(interface_id, left, right, region):
    return {
        "id": interface_id,
        "participants": [left, right],
        "region": region,
        "description": "A deliberate connection band.",
        "merge_policy": "preserve_existing",
    }


def codes(report):
    return [issue.code for issue in report.errors]


def test_valid_plan_with_covered_soft_halo_core_overlap_passes():
    packages = [
        package("left", rect(-10, -2), halo=rect(-11, 0), boundary="soft", anchor=[-5, 0, 0]),
        package("right", rect(0, 8), anchor=[3, 0, 0]),
    ]
    report = validate_project_plan(plan(packages, [interface("joint", "left", "right", rect(0, 0))]))
    assert report.valid
    assert report.to_dict() == {"valid": True, "errors": [], "warnings": []}


def test_core_overlap_is_rejected_with_2_5d_count_and_bounds():
    packages = [
        package("first", rect(0, 2, 0, 2), min_y=0, max_y=2, anchor=[0, 0, 0]),
        package("second", rect(1, 3, 1, 3), min_y=1, max_y=3, anchor=[3, 1, 3]),
    ]
    report = validate_project_plan(plan(packages))
    issue = next(issue for issue in report.errors if issue.code == "core_overlap")
    assert not report.valid
    assert issue.package_ids == ("first", "second")
    assert issue.voxel_count == 8  # 2x2 cells across two shared y layers
    assert issue.bounds == (1, 2, 1, 2)
    assert (issue.min_y, issue.max_y) == (1, 2)


def test_core_overlap_at_disjoint_heights_is_allowed():
    packages = [
        package("lower", rect(0, 4), min_y=0, max_y=3, anchor=[0, 0, 0]),
        package("upper", rect(0, 4), min_y=4, max_y=8, anchor=[0, 4, 0]),
    ]
    assert validate_project_plan(plan(packages)).valid


def test_soft_halo_to_halo_overlap_needs_no_interface():
    packages = [
        package("west", rect(-10, -5), halo=rect(-11, 0), boundary="soft", anchor=[-8, 0, 0]),
        package("east", rect(5, 10), halo=rect(0, 11), boundary="soft", anchor=[8, 0, 0]),
    ]
    assert validate_project_plan(plan(packages)).valid


def test_halo_core_overlap_without_interface_is_rejected():
    packages = [
        package("left", rect(-10, -2), halo=rect(-11, 0), boundary="soft", anchor=[-5, 0, 0]),
        package("right", rect(0, 8), anchor=[3, 0, 0]),
    ]
    report = validate_project_plan(plan(packages))
    issue = next(issue for issue in report.errors if issue.code == "halo_core_without_interface")
    assert issue.package_ids == ("left", "right")
    assert issue.voxel_count == 45  # x=0, five z cells, nine y layers


def test_interface_unknown_participant_is_rejected():
    project = plan(
        [package("known", rect(-3, 3), anchor=[0, 0, 0])],
        [interface("bad_joint", "known", "missing", rect(0, 0))],
    )
    report = validate_project_plan(project)
    assert "unknown_interface_participant" in codes(report)


def test_interface_must_lie_inside_both_allowed_volumes():
    packages = [
        package("left", rect(-10, -5), halo=rect(-11, -3), boundary="soft", anchor=[-8, 0, 0]),
        package("right", rect(3, 10), halo=rect(1, 11), boundary="soft", anchor=[6, 0, 0]),
    ]
    project = plan(packages, [interface("too_wide", "left", "right", rect(-4, 4))])
    assert "interface_outside_participants" in codes(validate_project_plan(project))


def test_nonparticipant_cannot_occupy_interface_volume():
    packages = [
        package("left", rect(-10, -2), halo=rect(-11, 0), boundary="soft", anchor=[-5, 0, 0]),
        package("right", rect(0, 8), anchor=[3, 0, 0]),
        package("third", rect(0, 0), min_y=0, max_y=8, anchor=[0, 0, 0]),
    ]
    project = plan(packages, [interface("joint", "left", "right", rect(0, 0))])
    report = validate_project_plan(project)
    assert "interface_used_by_nonparticipant" in codes(report)


def test_dependency_cycle_and_unknown_dependency_are_rejected():
    cyclic = plan(
        [
            package("a", rect(-10, -8), depends_on=["b"], anchor=[-9, 0, 0]),
            package("b", rect(8, 10), depends_on=["a"], anchor=[9, 0, 0]),
        ]
    )
    assert "dependency_cycle" in codes(validate_project_plan(cyclic))
    with pytest.raises(PlanValidationError) as exc_info:
        stable_topological_order(cyclic)
    assert exc_info.value.report is not None
    assert not exc_info.value.report.valid

    unknown = plan([package("a", rect(-1, 1), depends_on=["missing"], anchor=[0, 0, 0])])
    assert "unknown_dependency" in codes(validate_project_plan(unknown))


def test_duplicate_ids_and_component_cap_are_rejected():
    duplicate = plan(
        [
            package("same", rect(-10, -8), anchor=[-9, 0, 0]),
            package("same", rect(8, 10), anchor=[9, 0, 0]),
        ]
    )
    report = validate_project_plan(duplicate, max_components=1)
    assert "duplicate_package_id" in codes(report)
    assert "max_components_exceeded" in codes(report)


def test_stable_topological_order_preserves_plan_order_within_layers():
    project = plan(
        [
            package("c", rect(-15, -13), depends_on=["a"], anchor=[-14, 0, 0]),
            package("b", rect(-8, -6), anchor=[-7, 0, 0]),
            package("a", rect(0, 2), anchor=[1, 0, 0]),
            package("d", rect(8, 10), depends_on=["b"], anchor=[9, 0, 0]),
        ]
    )
    assert [item.id for item in stable_topological_order(project)] == ["b", "a", "c", "d"]


def test_instance_anchor_must_be_inside_site_and_its_core():
    project = plan([package("building", rect(-2, 2), anchor=[20, 0, 0])])
    report = validate_project_plan(project)
    assert "instance_outside_core" in codes(report)


def test_site_and_project_height_respect_voxelgrid_extent():
    wide_site = {"min_x": 0, "max_x": MAX_EXTENT, "min_z": -5, "max_z": 5, "base_y": 0}
    project = plan([package("building", rect(0, 2), min_y=0, max_y=MAX_EXTENT, anchor=[1, 0, 0])], site=wide_site)
    report = validate_project_plan(project)
    assert "site_extent_limit" in codes(report)
    assert "project_height_limit" in codes(report)
