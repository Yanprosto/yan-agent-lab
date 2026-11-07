"""District planning: shops, freight trunk, one power backbone, and the damage point."""

from __future__ import annotations

from collections import deque

import pytest

from mcbuild.catalog import load_catalog
from mcbuild.planner.district import plan_district, validate_district
from mcbuild.planner.layout3d import neighbours
from mcbuild.planner.process_graph import rank_chains
from mcbuild.server.district_session import _break_cell


@pytest.fixture(scope="module")
def district():
    chain = rank_chains(load_catalog(), "minecraft:iron_ingot", 8, {"minecraft:raw_iron"})[0].chain
    return plan_district(chain, gap=24)


def test_one_shop_per_stage_with_a_trunk_between(district):
    assert [s.stage.machine for s in district.shops] == ["mekanism:enrichment_chamber", "mekanism:energized_smelter"]
    assert len(district.trunks) == 1
    trunk = district.trunks[0]
    assert district.shops[0].layout.sink in neighbours(trunk.cells[0])
    assert district.shops[1].layout.source in neighbours(trunk.cells[-1])
    assert district.shops[1].layout.source[0] - district.shops[0].layout.sink[0] >= 20


def test_district_passes_static_checks(district):
    assert validate_district(district) == []


def test_single_power_source_and_no_lab_cubes(district):
    """The only cube is the district power source; former shop cube cells are empty or cable."""
    assert district.power_source not in district.backbone
    occupied_not_cable = set(district.footprint) - set(district.backbone)
    for machine in district.machines:
        assert machine.cube not in occupied_not_cable or machine.cube == district.power_source


def _reachable(cells: set, start) -> set:
    seen = {start}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        for n in neighbours(cell):
            if n in cells and n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


def test_break_cell_cuts_only_the_downstream_shop(district):
    cell, cut = _break_cell(district)
    assert cell in district.backbone
    remaining = _reachable(set(district.backbone) - {cell}, district.backbone_pull[0])
    powered = [m.cable in remaining for m in district.machines]
    assert powered[0] is True
    assert powered[-1] is False
    assert cut == [len(district.machines) - 1]
