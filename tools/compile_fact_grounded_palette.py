from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean

FORBIDDEN_IDS = {
    'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air',
    'minecraft:bedrock', 'minecraft:barrier', 'minecraft:structure_void',
    'minecraft:structure_block', 'minecraft:jigsaw', 'minecraft:command_block',
    'minecraft:chain_command_block', 'minecraft:repeating_command_block',
    'minecraft:end_portal', 'minecraft:end_gateway', 'minecraft:nether_portal',
    'minecraft:spawner',
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def visual_map(visual: dict) -> dict[str, dict]:
    return {row['id']: row for row in visual.get('blocks', [])}


def safety(block: dict) -> dict:
    rid = block['id']
    rt = block['runtime']
    facts = set(block.get('derived_facts', []))
    physical = rt['physical']
    reasons = []

    if rid in FORBIDDEN_IDS or physical.get('is_air'):
        return {'class': 'forbidden', 'architecture_allowed': False, 'mass_use_allowed': False,
                'progression': 'forbidden', 'budget_class': 'forbidden', 'reasons': ['forbidden runtime/id']}

    if physical.get('replaceable') or physical.get('has_fluid_state'):
        reasons.append('replaceable/fluid runtime state')
        return {'class': 'forbidden', 'architecture_allowed': False, 'mass_use_allowed': False,
                'progression': 'forbidden', 'budget_class': 'forbidden', 'reasons': reasons}

    if 'tagged_ore' in facts:
        return {'class': 'resource', 'architecture_allowed': False, 'mass_use_allowed': False,
                'progression': 'resource', 'budget_class': 'resource', 'reasons': ['runtime ore tag']}

    if rt.get('block_entity_provider'):
        be = rt.get('block_entity') or {}
        reason = 'runtime BlockEntity provider'
        if be.get('type_id'):
            reason += ': ' + str(be['type_id'])
        return {'class': 'functional', 'architecture_allowed': False, 'mass_use_allowed': False,
                'progression': 'planner_only', 'budget_class': 'functional', 'reasons': [reason]}

    if 'tagged_storage_block' in facts:
        return {'class': 'prestige', 'architecture_allowed': False, 'mass_use_allowed': False,
                'progression': 'budgeted_resource', 'budget_class': 'prestige',
                'reasons': ['runtime storage-block tag; recipe cost not yet resolved']}

    if not rt.get('has_item'):
        return {'class': 'restricted', 'architecture_allowed': False, 'mass_use_allowed': False,
                'progression': 'explicit_only', 'budget_class': 'restricted', 'reasons': ['no item counterpart']}

    mass = bool(physical.get('can_occlude')) and not bool(physical.get('collision_empty'))
    if physical.get('light_emission', 0):
        mass = False
        reasons.append('emits light; detail use only')
    if not physical.get('can_occlude'):
        reasons.append('non-occluding; detail use only')
    if physical.get('collision_empty'):
        reasons.append('empty collision; detail use only')
    if not reasons:
        reasons.append('plain runtime building candidate')

    return {'class': 'architecture', 'architecture_allowed': True, 'mass_use_allowed': mass,
            'progression': 'common_candidate', 'budget_class': 'common' if mass else 'detail', 'reasons': reasons}


def roles(block: dict, visual: dict | None, safe: dict) -> list[str]:
    if safe['class'] != 'architecture':
        return []
    rt = block['runtime']
    p = rt['physical']
    props = rt.get('state_properties', {})
    tags = set(rt.get('block_tags', []))
    features = visual.get('features') if visual else None
    out = set()

    if safe['mass_use_allowed']:
        out.update(('structural', 'floor'))
    if p.get('light_emission', 0) > 0:
        out.add('light')
    if features and features.get('opacity', 1.0) < 0.92 and not p.get('collision_empty'):
        out.add('glass')
    if not safe['mass_use_allowed']:
        out.add('decor')

    # Shape/state evidence: this is stronger than substring role guessing.
    if any(tag.endswith(':stairs') or '/stairs' in tag for tag in tags) or 'half' in props and 'shape' in props:
        out.add('stairs')
    if any(tag.endswith(':slabs') or '/slabs' in tag for tag in tags) or ('type' in props and set(props['type']) >= {'top','bottom'}):
        out.add('slab')
    if any('walls' in tag for tag in tags):
        out.add('wall')
    if any('fences' in tag for tag in tags):
        out.add('fence')
    if any('doors' in tag for tag in tags) or {'open','hinge'} <= set(props):
        out.add('door')
    return sorted(out)


def feature_distance(a: dict, b: dict) -> float:
    ah, ass, av = a['mean_hsv']
    bh, bss, bv = b['mean_hsv']
    hue = min(abs(ah - bh), 1.0 - abs(ah - bh))
    return (hue * 1.4 + abs(ass-bss)*0.8 + abs(av-bv)*1.15 +
            abs(a['contrast']-b['contrast'])*0.65 + abs(a['edge_density']-b['edge_density'])*0.45)


def merge_features(samples: list[dict]) -> dict | None:
    if not samples:
        return None
    return {
        'mean_rgb': [round(mean(x['mean_rgb'][i] for x in samples)) for i in range(3)],
        'mean_hsv': [round(mean(x['mean_hsv'][i] for x in samples), 4) for i in range(3)],
        'luminance': round(mean(x['luminance'] for x in samples), 4),
        'contrast': round(mean(x['contrast'] for x in samples), 4),
        'saturation': round(mean(x['saturation'] for x in samples), 4),
        'edge_density': round(mean(x['edge_density'] for x in samples), 4),
        'opacity': round(mean(x['opacity'] for x in samples), 4),
    }


def build_palette(semantic: dict, visual: dict, per_role: int) -> dict:
    visuals = visual_map(visual)
    rows = []
    anchor_samples = []

    for block in semantic.get('blocks', []):
        v = visuals.get(block['id'])
        safe = safety(block)
        rs = roles(block, v, safe)
        features = v.get('features') if v else None
        row = {
            'id': block['id'],
            'source': block['source'],
            'safety': safe,
            'roles': rs,
            'visual': features,
            'block_tags': block['runtime'].get('block_tags', []),
            'block_entity': block['runtime'].get('block_entity'),
        }
        rows.append(row)
        if features and block['source'].startswith('mekanism_'):
            anchor_samples.append(features)

    anchor = merge_features(anchor_samples)
    role_names = ('structural','floor','decor','light','glass','stairs','slab','wall','fence','door')
    slots = {}
    for role in role_names:
        scored = []
        for row in rows:
            if role not in row['roles'] or not row['visual']:
                continue
            score = 50.0
            if anchor:
                score += max(0.0, 40.0 - feature_distance(row['visual'], anchor) * 28.0)
            # Favor real cross-mod mixing without allowing the mod family to monopolize the palette.
            if row['source'].startswith('mekanism_'):
                score += 6.0
            if row['source'] == 'vanilla':
                score += 2.0
            if row['safety']['mass_use_allowed'] and role in ('structural','floor'):
                score += 8.0
            score += min(5.0, float(row['visual'].get('opacity', 0.0)) * 5.0)
            scored.append({
                'id': row['id'],
                'source': row['source'],
                'score': round(score, 3),
                'roles': row['roles'],
                'mean_rgb': row['visual']['mean_rgb'],
                'safety_class': row['safety']['class'],
                'budget_class': row['safety']['budget_class'],
            })
        scored.sort(key=lambda x: (-x['score'], x['id']))
        slots[role] = scored[:per_role]

    restricted = {}
    for cls in ('functional','prestige','resource','restricted','forbidden'):
        restricted[cls] = [
            {'id': r['id'], 'source': r['source'], 'reasons': r['safety']['reasons'], 'block_entity': r['block_entity']}
            for r in rows if r['safety']['class'] == cls
        ]

    class_counts = Counter(r['safety']['class'] for r in rows)
    arch_source_counts = Counter(r['source'] for r in rows if r['safety']['architecture_allowed'])
    return {
        'schema_version': 1,
        'kind': 'yan_fact_grounded_palette',
        'policy': {
            'source_of_truth': 'semantic runtime facts + visual catalog',
            'token_classifier_used': False,
            'block_entity_default': 'planner_only',
            'ores': 'never architecture',
            'storage_blocks': 'budgeted explicit use until recipe-cost graph exists',
            'forbidden': 'never auto-place',
        },
        'anchor_profile': anchor,
        'budgets': {
            'common': 1000000,
            'detail': 12000,
            'prestige': 8,
            'functional': 0,
            'resource': 0,
            'restricted': 0,
            'forbidden': 0,
        },
        'summary': {
            'blocks': len(rows),
            'safety_classes': dict(sorted(class_counts.items())),
            'architecture_by_source': dict(sorted(arch_source_counts.items())),
        },
        'slots': slots,
        'restricted_pools': restricted,
    }


def write_md(path: Path, palette: dict) -> None:
    lines = [
        '# Fact-grounded palette v1',
        '',
        'Token classifier used: **no**',
        '',
        '## Safety classes',
        '',
        '| class | blocks |',
        '|---|---:|',
    ]
    for cls, count in palette['summary']['safety_classes'].items():
        lines.append(f'| {cls} | {count} |')
    lines += ['', '## Architecture candidates by source', '', '| source | blocks |', '|---|---:|']
    for source, count in palette['summary']['architecture_by_source'].items():
        lines.append(f'| {source} | {count} |')
    lines += ['', '## Slots', '']
    for role, items in palette['slots'].items():
        lines.append(f'### {role}')
        lines.append('')
        for item in items[:12]:
            lines.append(f"- `{item['id']}` — score {item['score']} — {item['source']}")
        lines.append('')
    path.write_text('\n'.join(lines), encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, default=Path(r'D:\YAN_AGENT_LAB'))
    ap.add_argument('--semantic', type=Path, default=Path(r'D:\YAN_AGENT_LAB\docs\recon\generated\semantic_block_catalog.json'))
    ap.add_argument('--visual', type=Path, default=Path(r'D:\YAN_AGENT_LAB\docs\recon\generated\visual_block_catalog.json'))
    ap.add_argument('--per-role', type=int, default=32)
    args = ap.parse_args()

    palette = build_palette(load(args.semantic), load(args.visual), args.per_role)
    out = args.repo / 'docs' / 'recon' / 'generated'
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / 'fact_grounded_palette.json'
    md_path = out / 'fact_grounded_palette.md'
    json_path.write_text(json.dumps(palette, ensure_ascii=False, indent=2), encoding='utf-8')
    write_md(md_path, palette)

    print('=' * 80)
    print('YAN FACT-GROUNDED PALETTE COMPLETE')
    print('=' * 80)
    print(f"blocks: {palette['summary']['blocks']}")
    print('safety:', palette['summary']['safety_classes'])
    print('architecture:', palette['summary']['architecture_by_source'])
    print(f'palette: {json_path}')


if __name__ == '__main__':
    main()
