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
from mcbuild.orchestrator.prompt_writer import build_worker_prompt
from mcbuild.orchestrator.region import RegionExpr


def _rect(min_x, max_x, min_z, max_z):
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


def _package(package_id, responsibility, instances):
    return WorkPackage(
        id=package_id,
        name=package_id.replace("_", " ").title(),
        semantic_type="defensive_tower_family" if "tower" in package_id else "gatehouse",
        objective=f"Complete {package_id}",
        instances=instances,
        responsibility=responsibility,
        depends_on=["gatehouse"] if package_id != "gatehouse" else [],
        neighbor_context=["Connect cleanly at the declared interface"],
        worker_brief="Use stone foundations and spruce roofs",
        acceptance_criteria=["All instances are complete", "Entrances remain open"],
        requested_views=[{"mode": "top-down"}, {"yaw": 0}],
    )


def test_tower_family_produces_one_complete_prompt_with_all_instances():
    gatehouse = _package(
        "gatehouse",
        Responsibility(BoundaryKind.HARD, _rect(-5, 5, -2, 2), 0, 12),
        [Instance("main", (0, 0, 0), 0)],
    )
    towers = _package(
        "castle_tower_family",
        Responsibility(
            BoundaryKind.SOFT,
            _rect(-35, 35, -29, 29),
            0,
            20,
            _rect(-37, 37, -31, 31),
            WritePolicy.OVERWRITE,
        ),
        [
            Instance("north_west", (-30, 0, -24), 0),
            Instance("north_east", (30, 0, -24), 90),
            Instance("south_west", (-30, 0, 24), 270),
            Instance("south_east", (30, 0, 24), 180),
        ],
    )
    style = StyleBible(
        architectural_style="late medieval",
        scale_and_massing="monumental",
        primary_palette=["stone_bricks", "cobblestone"],
        secondary_palette="spruce_planks",
        accent_palette="copper_block",
        roof_language="steep roofs",
        opening_language="narrow arches",
        detail_language="crenellations",
        landscape_language="compact",
        global_constraints=["project-global coordinates", "consistent towers"],
    )
    interface = InterfaceZone(
        "tower_gate_join",
        ("castle_tower_family", "gatehouse"),
        _rect(-5, 5, -2, 2),
        "tower family meets gatehouse",
        MergePolicy.PRESERVE_EXISTING,
    )
    plan = ProjectPlan(
        1,
        "Fortified River Town",
        "A compact medieval town",
        Site(-80, 80, -60, 60, 0),
        style,
        [gatehouse, towers],
        [interface],
    )

    prompt = build_worker_prompt("建造一座大型城堡群", plan, towers)

    assert "project-global" in prompt.system_context
    assert "castle_tower_family" in prompt.system_context
    assert "soft boundary" in prompt.system_context
    assert "建造一座大型城堡群" in prompt.user_prompt
    assert "Fortified River Town" in prompt.user_prompt
    assert "late medieval" in prompt.user_prompt
    assert "stone_bricks" in prompt.user_prompt
    for anchor in ("[-30, 0, -24]", "[30, 0, -24]", "[-30, 0, 24]", "[30, 0, 24]"):
        assert anchor in prompt.user_prompt
    for rotation in ("0", "90", "180", "270"):
        assert f'"rotation": {rotation}' in prompt.user_prompt
    assert "shared blueprint helper/construction logic once" in prompt.user_prompt
    assert "Do not turn the instances into separate worker tasks" in prompt.user_prompt
    assert "tower_gate_join" in prompt.user_prompt
    assert "gatehouse" in prompt.user_prompt
    assert '"op": "shape"' in prompt.user_prompt
    assert "All instances are complete" in prompt.user_prompt
    assert '"mode": "top-down"' in prompt.user_prompt
