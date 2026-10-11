from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

SOURCE_BY_NAMESPACE = {
    "minecraft": "vanilla",
    "mekanism": "mekanism_core",
    "mekanismgenerators": "mekanism_generators",
    "mekanismadditions": "mekanism_additions",
    "mekanismtools": "mekanism_tools",
}

SYSTEM_BY_SOURCE = {
    "vanilla": "vanilla",
    "mekanism_core": "core",
    "mekanism_generators": "generators",
    "mekanism_additions": "additions",
    "mekanism_tools": "tools",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_runtime(instance: Path) -> Path:
    roots = [instance / "yan_recon", instance.parent / "yan_recon", Path(r"D:\\YAN_AGENT_LAB\\mod\\yan_recon")]
    files = [p for root in roots if root.exists() for p in root.glob("runtime_registry_*.json")]
    if not files:
        raise SystemExit("No runtime_registry_*.json found")
    return max(files, key=lambda p: p.stat().st_mtime)


def resource_sets(system: dict) -> dict[str, set[str]]:
    return {key: set(values) for key, values in system.get("resource_ids", {}).items()}


def evidence_hits(block_id: str, values: set[str], limit: int = 12) -> list[str]:
    ns, path = block_id.split(":", 1)
    exact = f"{ns}:{path}"
    hits = [exact] if exact in values else []
    for value in sorted(values):
        if value == exact:
            continue
        vpath = value.split(":", 1)[-1]
        if vpath == path or vpath.endswith("/" + path) or vpath.endswith("_" + path) or path.endswith("_" + vpath):
            hits.append(value)
            if len(hits) >= limit:
                break
    return hits[:limit]


def make_descriptor(row: dict, oracle: dict) -> dict:
    block_id = row["id"]
    source = SOURCE_BY_NAMESPACE.get(row["namespace"], "other")
    system_name = SYSTEM_BY_SOURCE.get(source)
    system = oracle.get("systems", {}).get(system_name, {}) if system_name else {}
    resources = resource_sets(system) if system else {}

    static_evidence = {}
    for kind in ("blockstates", "block_models", "recipes", "loot_tables", "block_tags", "item_tags"):
        hits = evidence_hits(block_id, resources.get(kind, set()))
        if hits:
            static_evidence[kind] = hits

    be = row.get("block_entity") if isinstance(row.get("block_entity"), dict) else None
    physical = {
        key: row.get(key)
        for key in ("is_air", "light_emission", "destroy_speed", "explosion_resistance",
                    "can_occlude", "replaceable", "collision_empty", "has_fluid_state")
    }
    state_properties = {
        p["name"]: p.get("values", [])
        for p in row.get("state_properties", [])
        if p.get("name")
    }

    facts = []
    if row.get("block_entity_provider"):
        facts.append("has_block_entity_provider")
    if row.get("light_emission", 0):
        facts.append("emits_light")
    if row.get("collision_empty"):
        facts.append("empty_collision")
    if row.get("replaceable"):
        facts.append("replaceable")
    if row.get("has_fluid_state"):
        facts.append("contains_fluid_state")
    tags_text = " ".join(row.get("block_tags", [])).lower()
    if ":ores/" in tags_text or "c:ores" in tags_text or "forge:ores" in tags_text:
        facts.append("tagged_ore")
    if "storage_blocks" in tags_text:
        facts.append("tagged_storage_block")

    return {
        "id": block_id,
        "namespace": row["namespace"],
        "source": source,
        "runtime": {
            "default_state": row.get("default_state"),
            "block_class": row.get("block_class"),
            "block_class_hierarchy": row.get("block_class_hierarchy", []),
            "state_properties": state_properties,
            "block_tags": row.get("block_tags", []),
            "has_item": bool(row.get("has_item")),
            "item_id": row.get("item_id"),
            "item_max_stack_size": row.get("item_max_stack_size"),
            "item_tags": row.get("item_tags", []),
            "physical": physical,
            "block_entity_provider": bool(row.get("block_entity_provider")),
            "block_entity": be,
        },
        "static_evidence": static_evidence,
        "derived_facts": facts,
    }


def build_catalog(runtime: dict, oracle: dict, runtime_path: Path) -> dict:
    blocks = sorted((make_descriptor(row, oracle) for row in runtime.get("blocks", [])), key=lambda x: x["id"])
    source_counts = Counter(x["source"] for x in blocks)
    fact_counts = Counter(f for x in blocks for f in x["derived_facts"])
    return {
        "schema_version": 2,
        "kind": "yan_semantic_block_catalog",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_source": {
            "file": runtime_path.name,
            "generated_at": runtime.get("generated_at"),
            "minecraft_version": runtime.get("minecraft_version"),
            "level": runtime.get("level"),
        },
        "static_source": {
            "kind": oracle.get("kind"),
            "source_recon_run": oracle.get("source_recon_run"),
        },
        "scope": {
            "mods": runtime.get("mods", []),
            "palette_ready": False,
            "note": "Factual unified catalog only; no palette permission/classification yet.",
        },
        "summary": {
            "blocks": len(blocks),
            "source_counts": dict(sorted(source_counts.items())),
            "derived_fact_counts": dict(sorted(fact_counts.items())),
        },
        "blocks": blocks,
    }


def write_md(path: Path, catalog: dict) -> None:
    lines = [
        "# Unified vanilla + Mekanism semantic catalog v1",
        "",
        "Runtime source: " + catalog["runtime_source"]["file"],
        "Static source: " + str(catalog["static_source"]["source_recon_run"]),
        "",
        "This is not a palette yet. It is the factual substrate used to build one.",
        "",
        "| source | blocks |",
        "|---|---:|",
    ]
    for source, count in catalog["summary"]["source_counts"].items():
        lines.append(f"| {source} | {count} |")
    lines += ["", "| fact | blocks |", "|---|---:|"]
    for fact, count in catalog["summary"]["derived_fact_counts"].items():
        lines.append(f"| {fact} | {count} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", type=Path, default=Path(r"C:\\Users\\yan\\AppData\\Roaming\\ElyPrismLauncher\\instances\\1.21.1(1)\\minecraft"))
    ap.add_argument("--runtime", type=Path)
    ap.add_argument("--oracle", type=Path, default=Path(r"D:\\YAN_AGENT_LAB\\docs\\recon\\generated\\minecraft_lab_oracle.json"))
    ap.add_argument("--repo", type=Path, default=Path(r"D:\\YAN_AGENT_LAB"))
    args = ap.parse_args()

    runtime_path = args.runtime or latest_runtime(args.instance)
    runtime = load(runtime_path)
    oracle = load(args.oracle)
    catalog = build_catalog(runtime, oracle, runtime_path)

    out = args.repo / "docs" / "recon" / "generated"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "semantic_block_catalog.json"
    md_path = out / "semantic_block_catalog.md"
    json_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(md_path, catalog)

    print("=" * 80)
    print("YAN SEMANTIC CATALOG COMPLETE")
    print("=" * 80)
    print(f"runtime: {runtime_path}")
    print(f"catalog: {json_path}")
    print(f"index:   {md_path}")
    print(f"blocks:  {catalog['summary']['blocks']}")
    print(f"bytes:   {json_path.stat().st_size:,}")


if __name__ == "__main__":
    main()
