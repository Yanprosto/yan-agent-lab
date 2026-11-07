"""Process planner: chains from the catalog, exact seed amounts and line layout."""

from __future__ import annotations

from fractions import Fraction

from mcbuild.catalog import load_catalog
from mcbuild.planner.chain_layout import compile_line
from mcbuild.planner.process_graph import enumerate_chains, rank_chains

IRON = "minecraft:iron_ingot"


def _ids(chains):
    return {c.id for c in chains}


def test_raw_iron_offers_direct_and_enriched_routes():
    chains = enumerate_chains(load_catalog(), IRON, {"minecraft:raw_iron"})
    assert _ids(chains) == {
        "minecraft:raw_iron -> energized_smelter:minecraft:iron_ingot",
        "minecraft:raw_iron -> enrichment_chamber:mekanism:dust_iron -> energized_smelter:minecraft:iron_ingot",
    }


def test_chains_never_loop_through_the_target():
    chains = enumerate_chains(load_catalog(), IRON, {"minecraft:iron_ingot", "minecraft:raw_iron"})
    assert all(c.source_item != IRON for c in chains)


def test_enriched_route_ranks_first_and_seeds_exactly():
    best = rank_chains(load_catalog(), IRON, 8, {"minecraft:raw_iron"})[0]
    assert best.machines == 2
    assert best.chain.yield_per_source == Fraction(4, 3)
    assert best.chain.exact_seed_unit() == 3
    assert (best.source_needed, best.output) == (6, 8)


def test_seed_rounds_up_to_whole_units():
    best = rank_chains(load_catalog(), IRON, 9, {"minecraft:raw_iron"})[0]
    assert best.source_needed % 3 == 0
    assert best.output >= 9


def test_line_layout_matches_probe_cell_pattern():
    chain = rank_chains(load_catalog(), IRON, 8, {"minecraft:raw_iron"})[0].chain
    layout = compile_line(chain)
    assert layout.source == (0, 0, 0)
    assert [s.pos for s in layout.machines] == [(3, 0, 0), (6, 0, 0)]
    assert layout.pull_transporters == [(1, 0, 0), (4, 0, 0), (7, 0, 0)]
    assert layout.sink == (9, 0, 0)
    cells = layout.footprint
    assert len(cells) == len(set(cells))
