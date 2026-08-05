from typing import cast

from mcbuild.orchestrator.models import ProjectPlan
from mcbuild.orchestrator.plan_render import render_plan


def _rectangle(min_x, max_x, min_z, max_z):
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


def _style_bible():
    return {
        "architectural_style": "medieval",
        "scale_and_massing": "compact",
        "primary_palette": ["stone_bricks", "oak_planks"],
        "secondary_palette": "cobblestone",
        "accent_palette": "copper",
        "roof_language": "steep roofs",
        "opening_language": "narrow windows",
        "detail_language": "timber braces",
        "landscape_language": "native planting",
        "global_constraints": "walkable",
    }


def _package(package_id, name, core, *, boundary="hard", halo=None, anchor=(0, 0, 0), rotation=0):
    return {
        "id": package_id,
        "name": name,
        "semantic_type": "structure",
        "objective": f"Build {name}",
        "instances": [{"id": "main", "anchor": list(anchor), "rotation": rotation}],
        "responsibility": {
            "boundary_kind": boundary,
            "core": core,
            "halo": halo,
            "min_y": 0,
            "max_y": 12,
            "write_policy": "preserve_existing",
        },
        "depends_on": [],
        "neighbor_context": [],
        "worker_brief": f"Construct {name}",
        "acceptance_criteria": ["complete exterior"],
        "requested_views": [{"yaw": 0}],
    }


def _plan(*packages, interfaces=None):
    return ProjectPlan.from_dict(
        {
            "schema_version": 1,
            "title": "Citadel 城",
            "project_summary": "A compact fortified site.",
            "site": {"min_x": -20, "max_x": 20, "min_z": -15, "max_z": 15, "base_y": 0},
            "style_bible": _style_bible(),
            "work_packages": list(packages),
            "interfaces": list(interfaces or []),
        }
    )


def test_plan_render_is_deterministic_and_handles_negative_coordinates():
    plan = _plan(
        _package(
            "tower_family",
            "Four Towers",
            _rectangle(-14, -4, -10, 2),
            boundary="soft",
            halo=_rectangle(-16, -2, -12, 4),
            anchor=(-9, 0, -5),
            rotation=270,
        )
    )

    first = render_plan(plan)
    second = render_plan(plan)

    assert first.mode == "RGBA"
    assert first.size == (1200, 820)
    assert first.tobytes() == second.tobytes()
    assert first.getbbox() is not None


def test_plan_render_draws_interfaces_and_overlap_conflicts():
    overlap = _rectangle(-2, 4, -3, 3)
    plan = _plan(
        _package("keep", "Keep", _rectangle(-8, 4, -6, 6), anchor=(-4, 0, 0)),
        _package("gate", "Gate", overlap, anchor=(1, 0, 0), rotation=90),
        interfaces=[
            {
                "id": "keep_gate_joint",
                "participants": ["keep", "gate"],
                "region": _rectangle(-2, -1, -1, 1),
                "description": "shared threshold",
                "merge_policy": "preserve_existing",
            }
        ],
    )

    image = render_plan(plan)
    pixels = cast(list[tuple[int, int, int, int]], list(image.get_flattened_data()))
    red_conflicts = sum(
        1 for red, green, blue, _alpha in pixels if red > 180 and red > green * 1.4 and red > blue * 1.4
    )
    purple_interfaces = sum(1 for red, green, blue, _alpha in pixels if blue > red and red > green)

    assert red_conflicts > 100
    assert purple_interfaces > 20


def test_plan_render_rejects_too_small_canvas():
    plan = _plan(_package("keep", "Keep", _rectangle(0, 4, 0, 4)))
    try:
        render_plan(plan, width=300, height=200)
    except ValueError as error:
        assert "720x500" in str(error)
    else:
        raise AssertionError("expected small plan canvas to be rejected")
