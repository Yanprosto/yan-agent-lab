import pytest

from mcbuild.config import Config
from mcbuild.llm.client import Usage
from mcbuild.orchestrator.models import (
    BoundaryKind,
    ModelValidationError,
    ProjectConfig,
    ProjectPlan,
    ProjectResult,
    Responsibility,
    WritePolicy,
)
from mcbuild.voxel import VoxelGrid


def plan_dict():
    style = {
        "architectural_style": "medieval",
        "scale_and_massing": ["compact", "two storeys"],
        "primary_palette": ["stone_bricks", "oak_planks"],
        "secondary_palette": "cobblestone",
        "accent_palette": "dark_oak",
        "roof_language": "steep gables",
        "opening_language": "narrow windows",
        "detail_language": "timber braces",
        "landscape_language": "worn paths",
        "global_constraints": ["project-global coordinates", "consistent foundations"],
    }
    core = {
        "op": "shape",
        "shape": {"kind": "axis_aligned_rectangle", "min_x": -8, "max_x": 8, "min_z": -6, "max_z": 6},
    }
    return {
        "schema_version": 1,
        "title": "Gate Complex",
        "project_summary": "A gatehouse and repeated flanking towers.",
        "site": {"min_x": -30, "max_x": 30, "min_z": -20, "max_z": 20, "base_y": 0},
        "style_bible": style,
        "work_packages": [
            {
                "id": "tower_family",
                "name": "Tower family",
                "semantic_type": "defensive_tower_family",
                "objective": "Build four consistent towers.",
                "instances": [
                    {"id": "north_west", "anchor": [-6, 0, -4], "rotation": 0},
                    {"id": "north_east", "anchor": [6, 0, -4], "rotation": 90},
                    {"id": "south_west", "anchor": [-6, 0, 4], "rotation": 270},
                    {"id": "south_east", "anchor": [6, 0, 4], "rotation": 180},
                ],
                "responsibility": {
                    "boundary_kind": "hard",
                    "core": core,
                    "halo": None,
                    "min_y": 0,
                    "max_y": 24,
                    "write_policy": "preserve_existing",
                },
                "depends_on": [],
                "neighbor_context": ["gatehouse occupies the center"],
                "worker_brief": "Define one shared tower helper and instantiate it four times.",
                "acceptance_criteria": ["all four towers share proportions"],
                "requested_views": [{"yaw": 0}, {"mode": "top-down"}],
            }
        ],
        "interfaces": [],
    }


def test_project_plan_strict_round_trip_and_lookup():
    original = plan_dict()
    plan = ProjectPlan.from_dict(original)
    assert len(plan.work_packages[0].instances) == 4
    assert plan.package_by_id("tower_family") is plan.work_packages[0]
    assert plan.work_package_map == {"tower_family": plan.work_packages[0]}
    assert plan.to_dict() == original
    assert ProjectPlan.from_dict(plan.to_dict()) == plan


def test_responsibility_contains_core_halo_and_inclusive_height():
    data = plan_dict()["work_packages"][0]["responsibility"]
    data = dict(data)
    data["boundary_kind"] = "soft"
    data["halo"] = {
        "op": "shape",
        "shape": {"kind": "circle", "center": [0, 0], "radius": 12},
    }
    responsibility = Responsibility.from_dict(data)
    assert responsibility.boundary_kind is BoundaryKind.SOFT
    assert responsibility.write_policy is WritePolicy.PRESERVE_EXISTING
    assert responsibility.contains(0, 0, 0)
    assert responsibility.contains(0, 24, 0)
    assert not responsibility.contains(10, 5, 0)
    assert responsibility.contains(10, 5, 0, include_halo=True)
    assert not responsibility.contains(0, 25, 0, include_halo=True)


def test_model_rejects_unknown_fields_and_reports_full_nested_path():
    data = plan_dict()
    data["work_packages"][0]["responsibility"]["mystery"] = True
    with pytest.raises(ModelValidationError) as exc_info:
        ProjectPlan.from_dict(data)
    assert "$.work_packages[0].responsibility" in str(exc_info.value)
    assert "mystery" in str(exc_info.value)


@pytest.mark.parametrize("bad_id", ["../escape", "UpperCase", "two-parts", "_leading", ""])
def test_model_rejects_unsafe_ids(bad_id):
    data = plan_dict()
    data["work_packages"][0]["id"] = bad_id
    with pytest.raises(ModelValidationError) as exc_info:
        ProjectPlan.from_dict(data)
    assert "$.work_packages[0].id" in str(exc_info.value)


@pytest.mark.parametrize("rotation", [-90, 45, 360, True, "90"])
def test_instance_rotation_is_limited_to_cardinal_degrees(rotation):
    data = plan_dict()
    data["work_packages"][0]["instances"][0]["rotation"] = rotation
    with pytest.raises(ModelValidationError, match="rotation"):
        ProjectPlan.from_dict(data)


def test_hard_responsibility_rejects_halo():
    data = plan_dict()["work_packages"][0]["responsibility"]
    data["halo"] = {
        "op": "shape",
        "shape": {"kind": "circle", "center": [0, 0], "radius": 12},
    }
    with pytest.raises(ModelValidationError, match="hard responsibilities"):
        Responsibility.from_dict(data)


def test_requested_views_are_runtime_validated():
    data = plan_dict()
    data["work_packages"][0]["requested_views"] = [{"yaw": 0, "slice_axis": "x"}]
    with pytest.raises(ModelValidationError, match="provided together"):
        ProjectPlan.from_dict(data)


def test_project_config_round_trip_keeps_worker_config_separate():
    config = ProjectConfig(
        worker_config=Config(model="worker/model", max_iters=4, seed=7),
        planner_model="planner/model",
        planner_max_iters=2,
        max_components=6,
        cost_ceiling=3,
    )
    decoded = ProjectConfig.from_dict(config.to_dict())
    assert decoded == config
    assert decoded.worker_config.model == "worker/model"
    assert decoded.cost_ceiling == 3.0


def test_project_result_serialization_summarizes_grid_instead_of_embedding_it():
    grid = VoxelGrid()
    grid.set(1, 2, 3, 4)
    result = ProjectResult(
        finished=True,
        summary="done",
        plan=ProjectPlan.from_dict(plan_dict()),
        grid=grid,
        completed_packages=["tower_family"],
        failed_package=None,
        validation_reports=[],
        usage=Usage(
            prompt_tokens=10,
            completion_tokens=5,
            reasoning_tokens=2,
            cached_tokens=3,
            cost_usd=0.25,
        ),
    )
    serialized = result.to_dict()
    assert serialized["grid"] == {"block_count": 1, "bounds": ((1, 2, 3), (1, 2, 3))}
    assert serialized["usage"]["cost_usd"] == 0.25
