"""Machine probe: recipe choice and ingredient resolution from the catalog."""

from __future__ import annotations

import pytest

from mcbuild.catalog import load_catalog
from mcbuild.server.machine_probe import ProbeCell, choose_recipe, resolve_item


def test_resolve_item_prefers_stable_tag_member():
    catalog = load_catalog()
    assert resolve_item(catalog, {"tag": "c:raw_materials/iron"}) == "minecraft:raw_iron"
    assert resolve_item(catalog, {"item": "mekanism:dust_iron"}) == "mekanism:dust_iron"


@pytest.mark.parametrize(
    ("machine", "recipe_type"),
    [
        ("mekanism:energized_smelter", "minecraft:smelting"),
        ("mekanism:enrichment_chamber", "mekanism:enriching"),
        ("mekanism:crusher", "mekanism:crushing"),
    ],
)
def test_default_recipe_is_a_simple_iron_recipe(machine, recipe_type):
    recipe = choose_recipe(load_catalog(), machine)
    assert recipe.type == recipe_type
    assert "iron" in recipe.id
    assert len(recipe.item_inputs) == 1


def test_explicit_recipe_must_match_machine():
    with pytest.raises(ValueError):
        choose_recipe(load_catalog(), "mekanism:crusher", "mekanism:processing/iron/dust/from_raw_ore")


def test_infuser_has_no_single_input_recipe_yet():
    with pytest.raises(ValueError):
        choose_recipe(load_catalog(), "mekanism:metallurgic_infuser")


def test_probe_cell_footprint_is_unique():
    cells = [(p.x, p.y, p.z) for p in ProbeCell().footprint]
    assert len(cells) == len(set(cells)) == 9
