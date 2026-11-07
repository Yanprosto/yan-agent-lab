"""Mechanism catalog: data integrity and agreement with live-verified plans."""

from __future__ import annotations

from fractions import Fraction

import pytest

from mcbuild.catalog import load_catalog
from mcbuild.server.process_plans import PLANS

EVIDENCE = {"runtime_observed", "source_default", "derived", "vanilla_fact", "unverified"}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_every_fact_has_a_known_evidence_level(catalog):
    for block_id, spec in catalog.blocks.items():
        assert spec.get("roles"), block_id
        for name, entry in spec.items():
            if isinstance(entry, dict) and "value" in entry:
                assert entry.get("evidence") in EVIDENCE, (block_id, name)
                if entry["evidence"] == "runtime_observed":
                    assert entry.get("runs"), f"{block_id}.{name} is runtime_observed without runs"


def test_tags_resolve_iron_items(catalog):
    assert catalog.tags["c:raw_materials/iron"] == {"minecraft:raw_iron"}
    assert "mekanism:dust_iron" in catalog.tags["c:dusts/iron"]


def test_iron_recipes_match_observed_ratios(catalog):
    enrich = catalog.recipe("mekanism:processing/iron/dust/from_raw_ore")
    assert enrich.type == "mekanism:enriching"
    assert catalog.matches(enrich.item_inputs[0], "minecraft:raw_iron")
    assert catalog.ratio(enrich) == Fraction(4, 3)
    smelt = catalog.recipe("mekanism:processing/iron/ingot/from_dust_smelting")
    assert catalog.ratio(smelt) == 1
    vanilla = catalog.recipe("minecraft:iron_ingot_from_smelting_raw_iron")
    assert catalog.ratio(vanilla) == 1


def test_conditional_compat_recipes_are_excluded_by_default(catalog):
    produced = {r.id for r in catalog.recipes_producing("biomeswevegone:mossy_stone", include_conditional=True)}
    assert produced, "expected at least one conditional compat recipe"
    assert not catalog.recipes_producing("biomeswevegone:mossy_stone")


def test_machines_for_recipe_types(catalog):
    assert catalog.machines_for("mekanism:enriching") == ["mekanism:enrichment_chamber"]
    assert catalog.machines_for("minecraft:smelting") == ["mekanism:energized_smelter"]
    assert catalog.machines_for("mekanism:crushing") == ["mekanism:crusher"]


def test_only_live_verified_processors_are_plannable(catalog):
    assert catalog.plannable("mekanism:energized_smelter")
    assert catalog.plannable("mekanism:enrichment_chamber")
    assert not catalog.plannable("mekanism:crusher")
    assert not catalog.plannable("mekanism:metallurgic_infuser")


def test_registered_process_plans_agree_with_catalog(catalog):
    """Each stage's machine handles a catalog recipe that turns its input into its output
    at the stage's declared ratio, and the machine is plannable."""
    for plan in PLANS:
        for stage in plan.stages:
            assert catalog.plannable(stage.machine_block), stage.id
            types = catalog.block(stage.machine_block)["recipe_types"]
            candidates = [
                r
                for r in catalog.recipes_consuming(stage.input_item)
                if r.type in types and r.main_output.get("item") == stage.output_item
            ]
            assert candidates, f"{plan.id}/{stage.id}: no catalog recipe"
            assert any(catalog.ratio(r) == Fraction(stage.output_count, stage.input_count) for r in candidates), (
                f"{plan.id}/{stage.id}: declared ratio disagrees with catalog"
            )
