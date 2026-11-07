"""Shop modules: committed module integrity, rotation, placement in volumes."""

from __future__ import annotations

import pytest

from mcbuild.planner.layout3d import validate
from mcbuild.planner.modules import from_json, list_modules, load_module, place_in, rotate, to_json, translate
from mcbuild.planner.volumes import VOLUMES

SHOP = "iron_ingot_enrich_smelt_shop_v1"


@pytest.fixture(scope="module")
def shop():
    return load_module(SHOP)


def test_committed_modules_have_live_evidence():
    assert SHOP in list_modules()
    for module_id in list_modules():
        module = load_module(module_id)
        assert module.evidence["level"] == "runtime_observed"
        assert module.evidence["run_id"]
        assert {p.role for p in module.ports} == {"item_in", "item_out"}
        assert module.contract["source_per_batch"] > 0 and module.contract["output_per_batch"] > 0


def test_json_round_trip(shop):
    assert from_json(to_json(shop)) == shop


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_rotation_keeps_layout_valid(shop, turns):
    rotated = rotate(shop, turns)
    box = {(x, y, z) for x in range(rotated.size[0]) for y in range(rotated.size[1]) for z in range(rotated.size[2])}
    assert validate(rotated.layout, box) == []


def test_four_quarter_turns_are_identity(shop):
    assert rotate(shop, 4) == shop


def test_quarter_turn_rotates_faces(shop):
    turned = rotate(shop, 1)
    assert turned.port("item_in").outward == "north"  # west -> north
    assert turned.port("item_out").outward == "south"  # east -> south
    assert turned.size == (shop.size[2], shop.size[1], shop.size[0])


def test_pillared_hall_fits_without_rotation_and_narrow_room_needs_it(shop):
    hall = place_in(shop, VOLUMES["pillared_hall"].expected_free())
    narrow = place_in(shop, VOLUMES["narrow_room"].expected_free())
    assert hall and hall[0][0] == 0
    assert narrow and all(turns % 2 == 1 for turns, _offset, _module in narrow)
    for volume, placements in (("pillared_hall", hall), ("narrow_room", narrow)):
        _turns, offset, rotated = placements[0]
        assert validate(translate(rotated.layout, offset), VOLUMES[volume].expected_free()) == []


def test_no_placement_without_room_for_port_approaches(shop):
    assert place_in(shop, VOLUMES["low_hall"].expected_free()) == []
