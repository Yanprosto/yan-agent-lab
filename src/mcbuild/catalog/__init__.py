"""Mechanism catalog: what blocks can do, as data with evidence levels.

Data lives in ``yan_knowledge/catalog/``:

- ``blocks/*.json``: roles, configurable sides, timing and energy per block, each fact
  with an evidence level (``runtime_observed``, ``source_default``, ``derived``,
  ``vanilla_fact``, ``unverified``);
- ``recipes/*.json``: recipes extracted from mod jars (``tools/recon/extract_mod_recipes.py``);
- ``tags/*.json``: flattened item tags (``tools/recon/extract_item_tags.py``).

Planning code asks this catalog instead of hard-coding block ids, sides and ratios
(ARCHITECTURE §1 L2, invariants I4 and I13).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any

PLANNABLE_EVIDENCE = frozenset({"runtime_observed"})


def _catalog_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "yan_knowledge" / "catalog"


@dataclass(frozen=True)
class Recipe:
    id: str
    type: str
    inputs: tuple[dict[str, Any], ...]
    outputs: tuple[dict[str, Any], ...]
    conditional: bool = False

    @property
    def item_inputs(self) -> tuple[dict[str, Any], ...]:
        return tuple(i for i in self.inputs if i.get("slot") != "chemical_input" and "chemical" not in i)

    @property
    def main_output(self) -> dict[str, Any]:
        return self.outputs[0]


class Catalog:
    def __init__(self, blocks: dict[str, dict[str, Any]], recipes: list[Recipe], tags: dict[str, list[str]]):
        self.blocks = blocks
        self.recipes = recipes
        self.tags = {tag: frozenset(items) for tag, items in tags.items()}

    # --- blocks ---
    def block(self, block_id: str) -> dict[str, Any]:
        try:
            return self.blocks[block_id]
        except KeyError:
            raise KeyError(f"block {block_id!r} is not in the catalog") from None

    def fact(self, block_id: str, name: str) -> Any:
        """The value of one fact, or None when the block does not record it."""
        entry = self.block(block_id).get(name)
        return entry.get("value") if isinstance(entry, dict) else entry

    def evidence(self, block_id: str, name: str) -> str | None:
        entry = self.block(block_id).get(name)
        return entry.get("evidence") if isinstance(entry, dict) else None

    def blocks_with_role(self, role: str) -> list[str]:
        return sorted(b for b, spec in self.blocks.items() if role in spec.get("roles", []))

    def machines_for(self, recipe_type: str) -> list[str]:
        return sorted(b for b, spec in self.blocks.items() if recipe_type in spec.get("recipe_types", []))

    def plannable(self, block_id: str) -> bool:
        """True when the block's port layout was observed live, so a plan may wire it.

        Facts read only from source (or unverified) need a lab check first (I1, I4).
        """
        spec = self.block(block_id)
        if "PROCESSOR" in spec.get("roles", []):
            return self.evidence(block_id, "side_config") in PLANNABLE_EVIDENCE
        return True

    # --- recipes and tags ---
    def matches(self, ingredient: dict[str, Any], item: str) -> bool:
        if "any_of" in ingredient:
            return any(self.matches(option, item) for option in ingredient["any_of"])
        if "item" in ingredient:
            return ingredient["item"] == item
        if "tag" in ingredient:
            return item in self.tags.get(ingredient["tag"], frozenset())
        return False

    def recipes_producing(self, item: str, *, include_conditional: bool = False) -> list[Recipe]:
        return [
            r
            for r in self.recipes
            if r.outputs and r.main_output.get("item") == item and (include_conditional or not r.conditional)
        ]

    def recipes_consuming(self, item: str, *, recipe_type: str | None = None) -> list[Recipe]:
        return [
            r
            for r in self.recipes
            if not r.conditional
            and (recipe_type is None or r.type == recipe_type)
            and any(self.matches(i, item) for i in r.item_inputs)
        ]

    def ratio(self, recipe: Recipe) -> Fraction:
        """Main output items per main item input."""
        inputs = recipe.item_inputs
        if not inputs or not recipe.outputs:
            raise ValueError(f"{recipe.id} has no item input or output")
        return Fraction(int(recipe.main_output.get("count", 1)), int(inputs[0].get("count", 1)))

    def recipe(self, recipe_id: str) -> Recipe:
        for r in self.recipes:
            if r.id == recipe_id:
                return r
        raise KeyError(f"recipe {recipe_id!r} is not in the catalog")


def _load_recipes(directory: Path) -> list[Recipe]:
    recipes = []
    for path in sorted(directory.glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8"))["recipes"]:
            recipes.append(
                Recipe(
                    id=row["id"],
                    type=row["type"],
                    inputs=tuple(row.get("inputs") or ()),
                    outputs=tuple(row.get("outputs") or ()),
                    conditional=bool(row.get("conditional")),
                )
            )
    return recipes


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    root = _catalog_dir()
    blocks: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "blocks").glob("*.json")):
        blocks.update(json.loads(path.read_text(encoding="utf-8"))["blocks"])
    tags: dict[str, list[str]] = {}
    for path in sorted((root / "tags").glob("*.json")):
        tags.update(json.loads(path.read_text(encoding="utf-8"))["tags"])
    return Catalog(blocks, _load_recipes(root / "recipes"), tags)
