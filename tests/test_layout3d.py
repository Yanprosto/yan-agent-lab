"""3D layout: every test volume gets a valid layout, and volumes yield different ones."""

from __future__ import annotations

import pytest

from mcbuild.catalog import load_catalog
from mcbuild.planner.layout3d import DIRS, LayoutError, Solver, add, validate
from mcbuild.planner.process_graph import rank_chains
from mcbuild.planner.volumes import VOLUMES, Volume


@pytest.fixture(scope="module")
def iron_chain():
    return rank_chains(load_catalog(), "minecraft:iron_ingot", 8, {"minecraft:raw_iron"})[0].chain


@pytest.mark.parametrize("name", sorted(VOLUMES))
def test_each_volume_gets_valid_layouts(name, iron_chain):
    volume = VOLUMES[name]
    free = volume.expected_free()
    layouts = Solver(free, volume.source, volume.sink).solve(iron_chain)
    assert layouts
    for layout in layouts:
        assert validate(layout, free) == []
        assert len(layout.machines) == len(iron_chain.stages)


def test_volumes_yield_different_layouts(iron_chain):
    shapes = set()
    for volume in VOLUMES.values():
        best = Solver(volume.expected_free(), volume.source, volume.sink).solve(iron_chain)[0]
        shapes.add(tuple((m.pos, m.in_face, m.out_face) for m in best.machines))
    assert len(shapes) == len(VOLUMES)


def test_shaft_layout_climbs(iron_chain):
    volume = VOLUMES["shaft"]
    best = Solver(volume.expected_free(), volume.source, volume.sink).solve(iron_chain)[0]
    heights = [m.pos[1] for m in best.machines]
    assert heights == sorted(heights) and heights[-1] > heights[0]


def test_validator_catches_touching_segments(iron_chain):
    volume = VOLUMES["low_hall"]
    free = volume.expected_free()
    layout = Solver(free, volume.source, volume.sink).solve(iron_chain)[0]
    first, second = layout.segments[0], layout.segments[1]
    # Move a cell of the second segment next to the first one: must be reported.
    bad_cell = next(add(c, d) for c in first.cells for d in DIRS.values() if add(c, d) in free)
    broken = type(second)((bad_cell, *second.cells[1:]), second.pull_face)
    from dataclasses import replace

    problems = validate(replace(layout, segments=(first, broken, *layout.segments[2:])), free)
    assert problems


def test_impossible_volume_is_reported(iron_chain):
    tiny = Volume("tiny", size=(3, 1, 1), source=(0, 0, 0), sink=(2, 0, 0))
    with pytest.raises(LayoutError):
        Solver(tiny.expected_free(), tiny.source, tiny.sink).solve(iron_chain)


def test_fault_injection_is_off_by_default(monkeypatch):
    from mcbuild.server import layout_session

    monkeypatch.delenv("YAN_LAYOUT_FAULT", raising=False)
    assert layout_session._fault_attempt() == 0
    monkeypatch.setenv("YAN_LAYOUT_FAULT", "1")
    assert layout_session._fault_attempt() == 1
