"""Parallel machines per stage: fan-out layouts, the T1-lite model and deadline planning."""

from __future__ import annotations

import pytest

from mcbuild.catalog import load_catalog
from mcbuild.planner.district import MAX_PARALLEL, DistrictError, plan_district, validate_district
from mcbuild.planner.estimate import estimate_ticks, plan_to_deadline, simulate, stage_load
from mcbuild.planner.layout3d import LayoutError, Solver, validate
from mcbuild.planner.process_graph import rank_chains


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def scored24(catalog):
    return rank_chains(catalog, "minecraft:iron_ingot", 24, {"minecraft:raw_iron"})[0]


@pytest.mark.parametrize("machines", [2, 3])
def test_fan_layout_gives_each_machine_its_own_segments(scored24, machines):
    stage = scored24.chain.stages[-1]
    box = (9, 3 if machines == 3 else 2, 5)
    free = {(x, y, z) for x in range(box[0]) for y in range(box[1]) for z in range(box[2])}
    layout = Solver(free, (0, 0, 2), (box[0] - 1, 0, 2)).solve_fan(stage, machines)
    assert layout.fan_out and len(layout.machines) == machines
    assert len(layout.segments) == 2 * machines
    assert validate(layout, free) == []
    # every input segment starts at the shared source chest with its own PULL
    firsts = [layout.segments[2 * j].cells[0] for j in range(machines)]
    assert len(set(firsts)) == machines


def test_fan_layout_reports_when_it_does_not_fit(scored24):
    stage = scored24.chain.stages[-1]
    free = {(x, 0, z) for x in range(5) for z in range(3)}
    with pytest.raises(LayoutError):
        Solver(free, (0, 0, 1), (4, 0, 1)).solve_fan(stage, 3)


@pytest.mark.parametrize("counts", [[1, 1], [1, 2], [1, 3], [2, 3]])
def test_parallel_districts_pass_static_checks(scored24, counts):
    district = plan_district(scored24.chain, counts, gap=24)
    assert [s.machines for s in district.shops] == counts
    assert validate_district(district) == []


def test_machine_counts_are_bounded(scored24):
    with pytest.raises(DistrictError):
        plan_district(scored24.chain, [1, MAX_PARALLEL + 1])
    with pytest.raises(DistrictError):
        plan_district(scored24.chain, [1])


def test_model_matches_recorded_live_run(catalog):
    """Layout run 20261107T125819Z_layout_d289189a: segments 2/6/8 cells, 6 raw -> 8 ingots,
    first poll with the exact result at 2160 ticks (60-tick polls): the true time is in (2100, 2160]."""
    chain = rank_chains(catalog, "minecraft:iron_ingot", 8, {"minecraft:raw_iron"})[0].chain
    predicted = simulate(list(chain.stages), 6, [[2], [0]], [[0], [8]], [6], ticks_per_op=[200, 200])
    assert 2100 < predicted <= 2160


def test_more_machines_on_the_bottleneck_stage_are_faster(catalog, scored24):
    times = [
        estimate_ticks(catalog, plan_district(scored24.chain, c), scored24.source_needed)
        for c in ([1, 1], [1, 2], [1, 3])
    ]
    assert times[0] > times[1] > times[2]
    loads = stage_load(catalog, scored24.chain, scored24.source_needed, [1, 1])
    assert loads[1] > loads[0]  # smelting is the bottleneck


def test_deadline_planning_grows_only_the_bottleneck(catalog, scored24):
    _d, counts, estimate = plan_to_deadline(catalog, scored24, 3000)
    assert counts == [1, 3] and estimate <= 3000
    _d, counts, _ = plan_to_deadline(catalog, scored24, 4500)
    assert counts == [1, 2]
    _d, counts, _ = plan_to_deadline(catalog, scored24, 99999)
    assert counts == [1, 1]
    with pytest.raises(DistrictError):
        plan_to_deadline(catalog, scored24, 2000)
