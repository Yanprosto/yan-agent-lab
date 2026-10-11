from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcbuild.export.schem import export_schem
from mcbuild.render.camera import render_isometric
from mcbuild.sector_materials import apply_to_industrial_study, resolve_sector_materials

from examples.industrial_sector_study import build as study


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / 'examples' / 'industrial_sector_study' / 'palette_output'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', choices=sorted(study.MODELS), default='vertical_foundry')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--no-render', action='store_true')
    args = ap.parse_args()

    generated = ROOT / 'docs' / 'recon' / 'generated'
    mats = resolve_sector_materials(
        semantic_path=generated / 'semantic_block_catalog.json',
        visual_path=generated / 'visual_block_catalog.json',
        palette_path=generated / 'fact_grounded_palette.json',
    )

    apply_to_industrial_study(mats, study.MATS)
    study._IDX.clear()

    grid = study.MODELS[args.kind]()
    out = args.out / args.kind
    out.mkdir(parents=True, exist_ok=True)

    (out / 'materials.json').write_text(
        json.dumps(mats.to_dict(), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    export_schem(grid, str(out / 'sector.schem'))

    report = {
        'kind': args.kind,
        'blocks': len(grid),
        'bounds': grid.bounds,
        'materials': mats.to_dict(),
        'palette_warnings': list(grid.palette_warnings),
    }
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    if not args.no_render:
        img = render_isometric(grid, yaw=0, width=1200, height=1000, shadows=False)
        img.save(out / 'overview.png')

    print('=' * 80)
    print('YAN MIXED SECTOR BUILD COMPLETE')
    print('=' * 80)
    print('kind:', args.kind)
    print('blocks:', len(grid))
    print('bounds:', grid.bounds)
    print('materials:')
    for key, value in mats.to_dict().items():
        print(f'  {key}: {value}')
    print('schem:', out / 'sector.schem')
    if not args.no_render:
        print('preview:', out / 'overview.png')


if __name__ == '__main__':
    main()
