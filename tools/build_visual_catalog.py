from __future__ import annotations

import argparse
import io
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from statistics import mean

from PIL import Image, ImageFilter, ImageStat


def load_json_bytes(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode('utf-8'))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def texture_features(raw: bytes) -> dict | None:
    try:
        image = Image.open(io.BytesIO(raw)).convert('RGBA')
    except Exception:
        return None
    image.thumbnail((96, 96), Image.Resampling.LANCZOS)
    pixels = list(image.getdata())
    visible = [(r, g, b, a) for r, g, b, a in pixels if a >= 24]
    if not visible:
        return None
    r = mean(p[0] for p in visible)
    g = mean(p[1] for p in visible)
    b = mean(p[2] for p in visible)
    alpha = mean(p[3] for p in visible) / 255.0
    maxc, minc = max(r, g, b), min(r, g, b)
    value = maxc / 255.0
    saturation = 0.0 if maxc == 0 else (maxc - minc) / maxc
    if maxc == minc:
        hue = 0.0
    elif maxc == r:
        hue = ((g - b) / (maxc - minc)) % 6 / 6.0
    elif maxc == g:
        hue = (((b - r) / (maxc - minc)) + 2) / 6.0
    else:
        hue = (((r - g) / (maxc - minc)) + 4) / 6.0
    lum_values = [0.2126*p[0] + 0.7152*p[1] + 0.0722*p[2] for p in visible]
    luminance = mean(lum_values) / 255.0
    variance = mean((x / 255.0 - luminance) ** 2 for x in lum_values)
    gray = image.convert('L').filter(ImageFilter.FIND_EDGES)
    edge_density = float(ImageStat.Stat(gray).mean[0]) / 255.0
    return {
        'mean_rgb': [round(r), round(g), round(b)],
        'mean_hsv': [round(hue, 4), round(saturation, 4), round(value, 4)],
        'luminance': round(luminance, 4),
        'contrast': round(math.sqrt(variance), 4),
        'saturation': round(saturation, 4),
        'edge_density': round(edge_density, 4),
        'opacity': round(alpha, 4),
    }


def merge_features(samples: list[dict]) -> dict | None:
    if not samples:
        return None
    keys = ('luminance','contrast','saturation','edge_density','opacity')
    result = {k: round(mean(x[k] for x in samples), 4) for k in keys}
    result['mean_rgb'] = [round(mean(x['mean_rgb'][i] for x in samples)) for i in range(3)]
    result['mean_hsv'] = [round(mean(x['mean_hsv'][i] for x in samples), 4) for i in range(3)]
    return result


class AssetStore:
    def __init__(self) -> None:
        self.raw: dict[str, bytes] = {}
        self.source: dict[str, str] = {}

    def add(self, name: str, data: bytes, source: str) -> None:
        self.raw[name] = data
        self.source[name] = source

    def get_json(self, name: str) -> dict:
        raw = self.raw.get(name)
        return load_json_bytes(raw) if raw is not None else {}

    def get(self, name: str) -> bytes | None:
        return self.raw.get(name)


def add_jar_assets(store: AssetStore, jar: Path) -> None:
    try:
        with zipfile.ZipFile(jar) as zf:
            for name in zf.namelist():
                if not name.startswith('assets/'):
                    continue
                if not (name.endswith('.json') or name.endswith('.png')):
                    continue
                try:
                    store.add(name, zf.read(name), jar.name)
                except Exception:
                    pass
    except zipfile.BadZipFile:
        pass


def find_real_vanilla_asset_jar(launcher_root: Path) -> Path | None:
    candidates = []
    for p in launcher_root.rglob('*.jar'):
        low = p.name.lower()
        if '1.21.1' not in low and 'client' not in low and 'minecraft' not in low:
            continue
        candidates.append(p)
    candidates.sort(key=lambda p: -p.stat().st_size)
    needle = 'assets/minecraft/blockstates/stone.json'
    for p in candidates:
        try:
            with zipfile.ZipFile(p) as zf:
                if needle in set(zf.namelist()):
                    return p
        except Exception:
            pass
    return None


def add_launcher_asset_index(store: AssetStore, launcher_root: Path) -> int:
    indexes = list(launcher_root.rglob('assets/indexes/*.json'))
    indexes += list(launcher_root.rglob('indexes/*.json'))
    seen = set()
    loaded = 0
    for index in sorted(set(indexes), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = load(index)
        except Exception:
            continue
        objects = data.get('objects')
        if not isinstance(objects, dict):
            continue
        assets_root = index.parent.parent
        object_root = assets_root / 'objects'
        for key, meta in objects.items():
            if not isinstance(meta, dict) or 'hash' not in meta:
                continue
            if key in seen:
                continue
            digest = meta['hash']
            obj = object_root / digest[:2] / digest
            if not obj.exists():
                continue
            # Asset indexes mainly provide textures/sounds; take only Minecraft block textures.
            if key.startswith('minecraft/textures/block/') and key.endswith('.png'):
                store.add('assets/' + key, obj.read_bytes(), 'launcher_asset_index')
                seen.add(key)
                loaded += 1
        if loaded:
            break
    return loaded


def normalize_ref(ref: str, default_ns: str, kind: str) -> str:
    if ':' in ref:
        ns, path = ref.split(':', 1)
    else:
        ns, path = default_ns, ref
    if kind == 'model':
        return f'assets/{ns}/models/{path}.json'
    return f'assets/{ns}/textures/{path}.png'


def model_refs(blockstate: dict) -> list[str]:
    refs = []
    def add(value):
        if isinstance(value, dict):
            model = value.get('model')
            if isinstance(model, str):
                refs.append(model)
        elif isinstance(value, list):
            for item in value:
                add(item)
    variants = blockstate.get('variants')
    if isinstance(variants, dict):
        for value in variants.values():
            add(value)
    multipart = blockstate.get('multipart')
    if isinstance(multipart, list):
        for part in multipart:
            if isinstance(part, dict):
                add(part.get('apply'))
    return sorted(set(refs))


def resolve_model_textures(store: AssetStore, model_ref: str, default_ns: str, depth: int = 0) -> list[str]:
    if depth > 8:
        return []
    model_path = normalize_ref(model_ref, default_ns, 'model')
    model = store.get_json(model_path)
    if not model:
        return []
    refs = []
    textures = model.get('textures')
    if isinstance(textures, dict):
        for value in textures.values():
            if isinstance(value, str) and not value.startswith('#'):
                refs.append(value)
    parent = model.get('parent')
    if isinstance(parent, str):
        refs.extend(resolve_model_textures(store, parent, default_ns, depth + 1))
    return sorted(set(refs))


def visual_for_block(store: AssetStore, block_id: str) -> dict:
    ns, path = block_id.split(':', 1)
    blockstate_path = f'assets/{ns}/blockstates/{path}.json'
    state = store.get_json(blockstate_path)
    models = model_refs(state) if state else []
    texture_refs = []
    for model in models:
        texture_refs.extend(resolve_model_textures(store, model, ns))
    texture_refs = sorted(set(texture_refs))

    samples = []
    used = []
    for ref in texture_refs:
        tex_path = normalize_ref(ref, ns, 'texture')
        raw = store.get(tex_path)
        if raw is None:
            continue
        feat = texture_features(raw)
        if feat:
            samples.append(feat)
            used.append({'ref': ref, 'source': store.source.get(tex_path)})

    # Strong fallback: common cube naming.
    if not samples:
        fallback = f'assets/{ns}/textures/block/{path}.png'
        raw = store.get(fallback)
        if raw is not None:
            feat = texture_features(raw)
            if feat:
                samples.append(feat)
                used.append({'ref': f'{ns}:block/{path}', 'source': store.source.get(fallback)})

    return {
        'blockstate_found': bool(state),
        'model_refs': models,
        'texture_refs': texture_refs,
        'used_textures': used,
        'features': merge_features(samples),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, default=Path(r'D:\YAN_AGENT_LAB'))
    ap.add_argument('--launcher-root', type=Path, default=Path(r'C:\Users\yan\AppData\Roaming\ElyPrismLauncher'))
    ap.add_argument('--mods-dir', type=Path, default=Path(r'C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods'))
    ap.add_argument('--semantic', type=Path, default=Path(r'D:\YAN_AGENT_LAB\docs\recon\generated\semantic_block_catalog.json'))
    args = ap.parse_args()

    semantic = load(args.semantic)
    store = AssetStore()

    vanilla_jar = find_real_vanilla_asset_jar(args.launcher_root)
    if vanilla_jar:
        print(f'[YAN] vanilla assets jar: {vanilla_jar}')
        add_jar_assets(store, vanilla_jar)
    else:
        print('[YAN] vanilla asset jar not found; using launcher asset-index texture fallback')

    index_textures = add_launcher_asset_index(store, args.launcher_root)
    print(f'[YAN] launcher block textures loaded: {index_textures}')

    mod_jars = sorted(args.mods_dir.glob('Mekanism*.jar'))
    for jar in mod_jars:
        print(f'[YAN] mod assets: {jar.name}')
        add_jar_assets(store, jar)

    rows = []
    for block in semantic.get('blocks', []):
        visual = visual_for_block(store, block['id'])
        rows.append({
            'id': block['id'],
            'source': block.get('source'),
            **visual,
        })

    found = sum(1 for x in rows if x['features'] is not None)
    by_source = Counter(x['source'] for x in rows if x['features'] is not None)
    result = {
        'schema_version': 1,
        'kind': 'yan_visual_block_catalog',
        'semantic_catalog': args.semantic.name,
        'vanilla_asset_jar': str(vanilla_jar) if vanilla_jar else None,
        'launcher_index_textures': index_textures,
        'summary': {
            'blocks': len(rows),
            'with_visual_features': found,
            'coverage': round(found / max(1, len(rows)), 4),
            'features_by_source': dict(sorted(by_source.items())),
        },
        'blocks': rows,
    }

    out = args.repo / 'docs' / 'recon' / 'generated'
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / 'visual_block_catalog.json'
    md_path = out / 'visual_block_catalog.md'
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        '# Visual block catalog v1',
        '',
        f"Blocks: {len(rows)}",
        f"With visual features: {found}",
        f"Coverage: {result['summary']['coverage']:.1%}",
        '',
        '| source | visual blocks |',
        '|---|---:|',
    ]
    for source, count in result['summary']['features_by_source'].items():
        lines.append(f'| {source} | {count} |')
    lines += ['', 'This file contains visual evidence only. It does not grant building permission.', '']
    md_path.write_text('\n'.join(lines), encoding='utf-8')

    print('=' * 80)
    print('YAN VISUAL CATALOG COMPLETE')
    print('=' * 80)
    print(f'blocks:   {len(rows)}')
    print(f'features: {found}')
    print(f'coverage: {result["summary"]["coverage"]:.1%}')
    print(f'catalog:  {json_path}')


if __name__ == '__main__':
    main()
