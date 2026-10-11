from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from mcbuild import palette


@dataclass(frozen=True)
class SectorMaterials:
    dark_structure: str
    structure: str
    wall: str
    floor: str
    warm_accent: str
    warning: str
    light: str
    dark_fill: str
    secondary_floor: str

    def to_dict(self) -> dict:
        return asdict(self)


REJECT_CLASS_SUFFIXES = (
    '.FallingBlock', '.CarpetBlock', '.LeavesBlock', '.BaseRailBlock', '.WaterlilyBlock',
)

REJECT_CLASS_FRAGMENTS = ('Coral', 'RailBlock', 'Waterlily')

DYE_PREFIXES = (
    'light_gray_', 'light_blue_', 'dark_red_', 'aqua_', 'black_', 'blue_', 'brown_',
    'cyan_', 'gray_', 'green_', 'lime_', 'magenta_', 'orange_', 'pink_', 'purple_',
    'red_', 'white_', 'yellow_',
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _by_id(rows: Iterable[dict]) -> dict[str, dict]:
    return {row['id']: row for row in rows}


def _family(block_id: str) -> str:
    ns, path = block_id.split(':', 1)
    for prefix in DYE_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    return f'{ns}:{path}'


def _runtime_reject(block: dict) -> bool:
    rt = block['runtime']
    hierarchy = rt.get('block_class_hierarchy', [])
    return any(
        any(cls.endswith(suffix) for suffix in REJECT_CLASS_SUFFIXES)
        or any(fragment in cls for fragment in REJECT_CLASS_FRAGMENTS)
        for cls in hierarchy
    )


def _candidate_rows(role: str, palette_data: dict, semantic_by_id: dict[str, dict], visual_by_id: dict[str, dict]) -> list[dict]:
    rows = []
    seen_families = set()
    for item in palette_data.get('slots', {}).get(role, []):
        block_id = item['id']
        block = semantic_by_id.get(block_id)
        visual = visual_by_id.get(block_id)
        if not block or not visual or not visual.get('features'):
            continue
        if _runtime_reject(block):
            continue
        fam = _family(block_id)
        if fam in seen_families:
            continue
        seen_families.add(fam)
        rows.append({**item, 'features': visual['features'], 'family': fam})
    return rows


def _pick(rows: list[dict], *, darkest: bool = False, lightest: bool = False, prefer_modded: bool = False, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    pool = [r for r in rows if r['id'] not in exclude]
    if not pool:
        raise RuntimeError('No material candidates left after filtering')

    def key(row: dict):
        lum = float(row['features']['luminance'])
        score = float(row.get('score', 0.0))
        mod_bonus = 1.0 if row['source'].startswith('mekanism_') else 0.0
        if darkest:
            return (lum, -mod_bonus if prefer_modded else 0.0, -score, row['id'])
        if lightest:
            return (-lum, -mod_bonus if prefer_modded else 0.0, -score, row['id'])
        return (-mod_bonus if prefer_modded else 0.0, -score, abs(lum - 0.45), row['id'])

    return sorted(pool, key=key)[0]


def _register(block_id: str, visual_by_id: dict[str, dict]) -> None:
    if block_id.startswith('minecraft:'):
        return
    visual = visual_by_id[block_id]['features']
    rgb = tuple(int(x) for x in visual['mean_rgb'])
    transparent = float(visual.get('opacity', 1.0)) < 0.92
    palette.register_external_block(block_id, rgb, transparent=transparent)


def resolve_sector_materials(
    *,
    semantic_path: Path,
    visual_path: Path,
    palette_path: Path,
) -> SectorMaterials:
    semantic = _load(semantic_path)
    visual = _load(visual_path)
    palette_data = _load(palette_path)

    semantic_by_id = _by_id(semantic['blocks'])
    visual_by_id = _by_id(visual['blocks'])

    structural = _candidate_rows('structural', palette_data, semantic_by_id, visual_by_id)
    floor = _candidate_rows('floor', palette_data, semantic_by_id, visual_by_id)
    lights = _candidate_rows('light', palette_data, semantic_by_id, visual_by_id)

    dark = _pick(structural, darkest=True, prefer_modded=True)
    main = _pick(structural, prefer_modded=False, exclude={dark['id']})
    wall = _pick(structural, lightest=True, prefer_modded=False, exclude={dark['id'], main['id']})
    secondary = _pick(floor, prefer_modded=True, exclude={dark['id'], main['id'], wall['id']})

    # Functional-looking visual accents are deliberately constrained to architecture-allowed
    # full blocks; real machines remain planner-only and are not selected here.
    warm_pool = [r for r in structural if 0.02 <= float(r['features']['mean_hsv'][0]) <= 0.16]
    warm = _pick(warm_pool or structural, prefer_modded=True, exclude={dark['id'], main['id'], wall['id'], secondary['id']})

    light = _pick(lights, prefer_modded=True)

    mats = SectorMaterials(
        dark_structure=dark['id'],
        structure=main['id'],
        wall=wall['id'],
        floor=secondary['id'],
        warm_accent=warm['id'],
        warning='minecraft:yellow_concrete',
        light=light['id'],
        dark_fill='minecraft:black_concrete',
        secondary_floor='minecraft:smooth_stone',
    )

    for block_id in mats.to_dict().values():
        if block_id in visual_by_id:
            _register(block_id, visual_by_id)

    return mats


def apply_to_industrial_study(mats: SectorMaterials, target: dict[str, str]) -> None:
    target.clear()
    target.update({
        'D': mats.dark_structure,
        'M': mats.floor,
        'C': mats.wall,
        'R': mats.warm_accent,
        'W': mats.structure,
        'Y': mats.warning,
        'L': mats.light,
        'B': mats.dark_fill,
        'S': mats.secondary_floor,
    })
