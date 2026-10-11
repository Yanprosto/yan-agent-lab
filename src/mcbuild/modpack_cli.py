"""CLI for the local YAN modpack palette compiler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcbuild.modpack_catalog import catalog_fingerprint, compile_sector_palette, scan_mod_jars


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan local mod JAR assets and compile a sector palette for YAN Builder."
    )
    parser.add_argument("--mods", type=Path, required=True, help="Minecraft instance mods directory")
    parser.add_argument("--out", type=Path, default=Path("runs/modpack-catalog"))
    parser.add_argument("--anchor-mod", action="append", default=[], help="Mod namespace that defines the sector's visual/functional language")
    parser.add_argument("--anchor-block", action="append", default=[], help="Exact block id used as a visual/functional anchor")
    parser.add_argument("--per-role", type=int, default=12)
    args = parser.parse_args()

    if not args.mods.is_dir():
        raise SystemExit(f"mods directory not found: {args.mods}")

    args.out.mkdir(parents=True, exist_ok=True)
    records = scan_mod_jars(args.mods)

    catalog = {
        "schema_version": 1,
        "mods_dir": str(args.mods),
        "block_count": len(records),
        "fingerprint": catalog_fingerprint(records),
        "blocks": [record.to_dict() for record in records],
    }
    (args.out / "catalog.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    palette = compile_sector_palette(
        records,
        anchor_mods=args.anchor_mod,
        anchor_blocks=args.anchor_block,
        per_role=args.per_role,
    )
    palette["catalog_fingerprint"] = catalog["fingerprint"]
    (args.out / "palette.json").write_text(
        json.dumps(palette, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"YAN modpack catalog: {len(records)} blocks")
    print(f"fingerprint: {catalog['fingerprint']}")
    print(f"catalog: {args.out / 'catalog.json'}")
    print(f"palette: {args.out / 'palette.json'}")
    for role, items in palette["slots"].items():
        top = ", ".join(item["block_id"] for item in items[:5])
        print(f"{role:10s}: {top}")


if __name__ == "__main__":
    main()
