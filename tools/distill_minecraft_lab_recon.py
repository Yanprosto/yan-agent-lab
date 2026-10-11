from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

SIG_RE = re.compile(r"^\s{2}(.+;\s*)$")
OFFSET_RE = re.compile(r"^\s*\d+:\s")

CAPS = {
    "logistics": ("transporter","sorter","inventory","ejector","hopper","chest","barrel","storage"),
    "energy": ("energy","cable","generator","solar","wind","turbine","reactor","fission","fusion"),
    "processing": ("smelter","crusher","enrichment","infuser","factory","furnace","recipe","machine"),
    "fluids_chemicals": ("fluid","chemical","gas","slurry","pigment","infusion","tank","pipe","tube"),
    "multiblock": ("multiblock","controller","valve","boiler","turbine","reactor"),
    "tools_armor": ("tool","armor","paxel","pickaxe","axe","shovel","hoe","sword","shield"),
    "building_decor": ("block","slab","stairs","fence","wall","plastic","glow","light","glass"),
    "vanilla_redstone": ("redstone","piston","comparator","repeater","observer","dispenser","dropper"),
    "vanilla_interaction": ("anvil","crafting","grindstone","smithing","stonecutter","enchant","brewing"),
}

RES_PATTERNS = {
    "blockstates": re.compile(r"^assets/([^/]+)/blockstates/(.+)\.json$"),
    "block_models": re.compile(r"^assets/([^/]+)/models/block/(.+)\.json$"),
    "recipes": re.compile(r"^data/([^/]+)/(?:recipe|recipes)/(.+)\.json$"),
    "loot_tables": re.compile(r"^data/([^/]+)/(?:loot_table|loot_tables)/(.+)\.json$"),
    "block_tags": re.compile(r"^data/([^/]+)/tags/(?:block|blocks)/(.+)\.json$"),
    "item_tags": re.compile(r"^data/([^/]+)/tags/(?:item|items)/(.+)\.json$"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_recon(root: Path) -> Path:
    runs = sorted(
        [p for p in root.glob("minecraft_lab_*") if p.is_dir() and (p / "manifest.json").exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        raise SystemExit(f"No minecraft_lab runs under {root}")
    return runs[0]


def selected_classes(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [x.strip() for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]


def compact_signatures(javap_dir: Path, classes: list[str], max_per_class: int = 24) -> dict[str, list[str]]:
    files = {p.stem: p for p in javap_dir.glob("*.txt")}
    result = {}
    for cls in classes:
        safe = cls.replace(".", "_").replace("$", "__")
        p = files.get(safe)
        if not p:
            continue
        sigs = []
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if OFFSET_RE.match(raw):
                continue
            m = SIG_RE.match(raw)
            if not m:
                continue
            sig = " ".join(m.group(1).split())
            if sig.startswith(("descriptor:", "Compiled from", "Code:")):
                continue
            if len(sig) > 300:
                sig = sig[:297] + "..."
            sigs.append(sig)
            if len(sigs) >= max_per_class:
                break
        if sigs:
            result[cls] = sigs
    return result


def resource_ids(base: Path) -> dict[str, list[str]]:
    out = {k: set() for k in RES_PATTERNS}
    if not base.exists():
        return {k: [] for k in out}
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        for kind, pat in RES_PATTERNS.items():
            m = pat.match(rel)
            if m:
                ns, rid = m.groups()
                out[kind].add(f"{ns}:{rid}")
                break
    return {k: sorted(v) for k, v in out.items()}


def capability_index(classes: list[str], resources: dict[str, list[str]]) -> dict:
    pairs = [(kind, rid) for kind, ids in resources.items() for rid in ids]
    result = {}
    for cap, kws in CAPS.items():
        ch = [c for c in classes if any(k in c.lower() for k in kws)]
        rh = [{"kind": kind, "id": rid} for kind, rid in pairs if any(k in rid.lower() for k in kws)]
        result[cap] = {
            "class_count": len(ch),
            "resource_count": len(rh),
            "classes": ch[:120],
            "resources": rh[:180],
        }
    return result


def previous_oracle(repo: Path) -> dict:
    p = repo / "docs" / "recon" / "mekanism" / "oracle_defaults.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build_oracle(recon: Path, repo: Path) -> dict:
    manifest = json.loads((recon / "manifest.json").read_text(encoding="utf-8"))
    systems = {}
    for row in manifest["jars"]:
        label = row["label"]
        section = recon / label
        classes = selected_classes(section / "selected_classes.txt")
        resources = resource_ids(section / "semantic_resources")
        jar_path = Path(row["path"])
        systems[label] = {
            "jar": {
                "file": jar_path.name,
                "sha256": sha256(jar_path) if jar_path.exists() else None,
                "bytes": row["size"],
                "namespaces": row.get("namespaces", []),
            },
            "counts": {
                "classes_in_jar": row["classes"],
                "selected_classes": len(classes),
                "javap_ok": manifest.get("javap", {}).get(label, {}).get("ok"),
                "blockstates": row["blockstates"],
                "block_models": row["block_models"],
                "recipes": row["recipes"],
                "loot_tables": row["loot_tables"],
                "block_tags": row["block_tags"],
                "item_tags": row["item_tags"],
            },
            "selected_classes": classes,
            "public_private_signatures": compact_signatures(section / "javap", classes),
            "resource_ids": resources,
            "capability_index": capability_index(classes, resources),
        }

    um = {}
    um_dir = recon / "universal_modder"
    if um_dir.exists():
        for p in sorted(um_dir.glob("*.txt")):
            txt = p.read_text(encoding="utf-8", errors="replace")
            um[p.stem] = {
                "bytes": len(txt.encode("utf-8")),
                "nonempty": bool(txt.strip()),
                "preview": txt[:1800],
            }

    return {
        "schema_version": 1,
        "kind": "yan_minecraft_lab_oracle",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_recon_run": manifest["run_id"],
        "scope": {
            "minecraft": "1.21.1",
            "mekanism_family": ["core","generators","tools","additions"],
            "palette_ready": False,
            "note": "Recon oracle only. Keyword indexes are retrieval aids, not verified capabilities.",
        },
        "verified_mekanism_core_defaults": previous_oracle(repo),
        "systems": systems,
        "universal_modder": um,
        "evidence_policy": {
            "raw_recon_location": str(recon),
            "raw_javap_committed": False,
            "decompiled_source_committed": False,
            "semantic_resources_committed": False,
            "derived_indexes_only": True,
        },
    }


def write_md(path: Path, oracle: dict) -> None:
    lines = [
        "# Minecraft 1.21.1 + Mekanism family compact recon oracle",
        "",
        "Source run: " + oracle["source_recon_run"],
        "",
        "Raw javap/resources stay local. Git stores only derived memory.",
        "",
        "| system | classes | selected | blockstates | recipes | javap ok |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, data in oracle["systems"].items():
        c = data["counts"]
        lines.append(
            f"| {label} | {c['classes_in_jar']} | {c['selected_classes']} | "
            f"{c['blockstates']} | {c['recipes']} | {c['javap_ok']} |"
        )
    lines += [
        "",
        "Use minecraft_lab_oracle.json as machine-readable project memory.",
        "For deeper proof, return to the local raw run named by source_recon_run.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recon", type=Path)
    ap.add_argument("--recon-root", type=Path, default=Path(r"D:\YAN_RECON"))
    ap.add_argument("--repo", type=Path, default=Path(r"D:\YAN_AGENT_LAB"))
    args = ap.parse_args()

    recon = args.recon or latest_recon(args.recon_root)
    oracle = build_oracle(recon, args.repo)
    out = args.repo / "docs" / "recon" / "generated"
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "minecraft_lab_oracle.json"
    md_path = out / "minecraft_lab_oracle.md"
    json_path.write_text(json.dumps(oracle, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(md_path, oracle)

    print("=" * 80)
    print("YAN RECON DISTILLER COMPLETE")
    print("=" * 80)
    print(f"source: {recon}")
    print(f"oracle: {json_path}")
    print(f"index:  {md_path}")
    print(f"oracle bytes: {json_path.stat().st_size:,}")


if __name__ == "__main__":
    main()
