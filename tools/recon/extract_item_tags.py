"""Extract and flatten item tags from one or more jars.

Usage:
    python tools/recon/extract_item_tags.py A.jar B.jar ... --out yan_knowledge/catalog/tags/x.json

Reads ``data/<namespace>/tags/item/**.json`` from every jar, merges entries of the same
tag across jars (``replace: true`` resets earlier entries), and resolves nested
``#tag`` references into plain item ids. Like recipes, these are shipped defaults
(evidence ``source_default``); a world's datapacks may change them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def _entries(raw: Any) -> list[tuple[str, bool]]:
    """Return (value, required) pairs from a tag file's values list."""
    out = []
    for value in raw.get("values", []):
        if isinstance(value, str):
            out.append((value, True))
        elif isinstance(value, dict) and "id" in value:
            out.append((value["id"], bool(value.get("required", True))))
    return out


def collect(jars: list[Path]) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    raw_tags: dict[str, list[str]] = {}
    sources = []
    for jar in jars:
        sources.append({"jar": jar.name, "sha256": hashlib.sha256(jar.read_bytes()).hexdigest()})
        with zipfile.ZipFile(jar) as archive:
            for name in sorted(archive.namelist()):
                parts = name.split("/")
                if len(parts) < 5 or parts[0] != "data" or parts[2:4] != ["tags", "item"]:
                    continue
                if not name.endswith(".json"):
                    continue
                tag = f"{parts[1]}:{'/'.join(parts[4:]).removesuffix('.json')}"
                try:
                    data = json.loads(archive.read(name))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                values = [value for value, _required in _entries(data)]
                if data.get("replace"):
                    raw_tags[tag] = values
                else:
                    raw_tags.setdefault(tag, []).extend(values)
    return raw_tags, sources


def flatten(raw_tags: dict[str, list[str]]) -> dict[str, list[str]]:
    resolved: dict[str, list[str]] = {}

    def resolve(tag: str, stack: frozenset[str]) -> list[str]:
        if tag in resolved:
            return resolved[tag]
        items: set[str] = set()
        for value in raw_tags.get(tag, []):
            if value.startswith("#"):
                inner = value[1:]
                if inner not in stack:
                    items.update(resolve(inner, stack | {inner}))
            else:
                items.add(value)
        resolved[tag] = sorted(items)
        return resolved[tag]

    for tag in raw_tags:
        resolve(tag, frozenset({tag}))
    return {tag: resolved[tag] for tag in sorted(resolved)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jars", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw_tags, sources = collect(args.jars)
    tags = flatten(raw_tags)
    payload = {"evidence": "source_default", "sources": sources, "tag_count": len(tags), "tags": tags}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(tags)} tags -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
