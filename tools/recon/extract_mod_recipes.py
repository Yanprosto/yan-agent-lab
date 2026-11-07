"""Extract datapack recipes of chosen types from a mod jar into a normalized JSON file.

Usage:
    python tools/recon/extract_mod_recipes.py MOD.jar \
        --types mekanism:enriching,mekanism:crushing --out yan_knowledge/catalog/recipes/x.json

The result records the jar's SHA-256. Recipes read this way are the mod's shipped
defaults (evidence level ``source_default``): a world's datapacks or config can override
them, which only a runtime registry dump can confirm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def _ingredient(raw: Any) -> dict[str, Any]:
    """Normalize one ingredient/output entry to {item|tag, count, ...extra}."""
    if isinstance(raw, list):
        return {"any_of": [_ingredient(entry) for entry in raw]}
    if not isinstance(raw, dict):
        return {"raw": raw}
    entry: dict[str, Any] = {}
    if "id" in raw:
        entry["item"] = raw["id"]
    if "item" in raw:
        entry["item"] = raw["item"]
    if "tag" in raw:
        entry["tag"] = raw["tag"]
    if "chemical" in raw:
        entry["chemical"] = raw["chemical"]
    entry["count"] = int(raw.get("count", raw.get("amount", 1)))
    return entry


def _normalize(recipe_id: str, data: dict[str, Any]) -> dict[str, Any]:
    kind = data.get("type")
    row: dict[str, Any] = {"id": recipe_id, "type": kind}
    required_mods = [
        c.get("modid")
        for c in data.get("neoforge:conditions") or []
        if isinstance(c, dict) and c.get("type") == "neoforge:mod_loaded"
    ]
    if data.get("neoforge:conditions"):
        # Only active when the condition holds (usually another mod being loaded).
        row["conditional"] = True
        if required_mods:
            row["requires_mods"] = required_mods
    if kind == "minecraft:smelting":
        row["inputs"] = [_ingredient(data.get("ingredient"))]
        row["outputs"] = [_ingredient(data.get("result"))]
        row["cooking_ticks"] = data.get("cookingtime")
        return row
    inputs = []
    for key in ("input", "item_input", "main_input", "extra_input"):
        if key in data:
            inputs.append({"slot": key, **_ingredient(data[key])})
    for key in ("chemical_input", "infusion_input"):
        if key in data:
            inputs.append({"slot": key, **_ingredient(data[key])})
    row["inputs"] = inputs
    outputs = []
    for key in ("output", "item_output"):
        if key in data:
            outputs.append(_ingredient(data[key]))
    row["outputs"] = outputs
    return row


def extract(jar: Path, types: set[str]) -> dict[str, Any]:
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    recipes = []
    with zipfile.ZipFile(jar) as archive:
        for name in sorted(archive.namelist()):
            if "/recipe/" not in name or not name.endswith(".json"):
                continue
            try:
                data = json.loads(archive.read(name))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict) or data.get("type") not in types:
                continue
            namespace = name.split("/")[1]
            path = name.split("/recipe/", 1)[1].removesuffix(".json")
            recipes.append(_normalize(f"{namespace}:{path}", data))
    return {
        "source_jar": jar.name,
        "source_jar_sha256": digest,
        "evidence": "source_default",
        "types": sorted(types),
        "recipe_count": len(recipes),
        "recipes": recipes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jar", type=Path)
    parser.add_argument("--types", required=True, help="comma-separated recipe types")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.jar, {t.strip() for t in args.types.split(",") if t.strip()})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{result['recipe_count']} recipes -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
