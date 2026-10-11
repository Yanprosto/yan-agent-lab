"""Place the reviewed models through the existing mod; no Java rebuild or LLM."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from websockets.asyncio.server import serve
from build import OUT
from mcbuild.dsl.sandbox import run_blueprint
from mcbuild.server import protocol
from mcbuild.server.delta import compute_block_delta
from mcbuild.server.ws_server import _action
from mcbuild.voxel import VoxelGrid

BATCH = 1024
OFFSETS = {'well': (-160, 0, 16), 'canyon': (-32, 0, 16), 'shaft': (96, 0, 16)}
PROMPT = 'yan-sector-preview'

def load_models():
    models = []
    for name, (dx, dy, dz) in OFFSETS.items():
        grid = VoxelGrid()
        run_blueprint((OUT/name/'blueprint.py').read_text(), grid, max_seconds=60, max_lines=5000000)
        expected = json.loads((OUT/name/'report.json').read_text())
        if len(grid) != expected['blocks'] or grid.palette_warnings:
            raise RuntimeError(f'{name}: artifact validation failed')
        changes = compute_block_delta(None, grid)
        for cell in changes:
            cell['x'] += dx; cell['y'] += dy; cell['z'] += dz
        changes.sort(key=lambda p: (p['y'], p['z']//16, p['x']//16, p['z'], p['x']))
        models.append((name, changes))
    return models

def positions(cells):
    return [{k: c[k] for k in ('x','y','z')} for c in cells]

def checked_rows(result, requested):
    rows = result.get('blocks', [])
    lookup = {(r.get('x'), r.get('y'), r.get('z')): r for r in rows}
    if len(rows) != len(requested) or len(lookup) != len(requested):
        raise RuntimeError('Incomplete or duplicate world observation')
    keys = {(p['x'],p['y'],p['z']) for p in requested}
    if set(lookup) != keys:
        raise RuntimeError('World observation coordinates mismatch')
    return lookup

async def place_preview(connection, models, report):
    await connection.send(protocol.hello('yan-sector-preview-v1'))
    anchor = await _action(connection,'anchor','inspect_blocks',{'positions':[{'x':0,'y':0,'z':0}]})
    rows = checked_rows(anchor,[{'x':0,'y':0,'z':0}])
    origin = rows[(0,0,0)]
    if origin.get('world_y') != 180:
        raise RuntimeError('Fly/teleport to Y=180, then run /build yan-sector-preview again. No blocks placed.')
    report['origin'] = {k:origin[k] for k in ('world_x','world_y','world_z')}
    await connection.send(protocol.chat('[YAN] Checking all destination blocks before placement; no terrain clearing.'))
    # Preflight every destination across ALL models before the first write.
    for name, cells in models:
        for start in range(0,len(cells),BATCH):
            chunk = cells[start:start+BATCH]; pos = positions(chunk)
            result = await _action(connection,f'pre-{name}-{start}','inspect_blocks',{'positions':pos},timeout=60)
            rows = checked_rows(result,pos)
            occupied = [r for r in rows.values() if r.get('is_air') is not True]
            if occupied:
                r = occupied[0]
                raise RuntimeError(f"Site occupied at {r.get('world_x')},{r.get('world_y')},{r.get('world_z')}. Move to another site; nothing placed.")
        await connection.send(protocol.chat(f'[YAN] {name}: site clear ({len(cells)} block destinations).'))
    report['preflight'] = 'all_destinations_air'
    for name,cells in models:
        report['active_model'] = name
        await connection.send(protocol.chat(f'[YAN] Placing {name}: {len(cells)} blocks.'))
        for start in range(0,len(cells),BATCH):
            chunk = cells[start:start+BATCH]
            # Acknowledged inspection forms a server-thread barrier after each packet.
            await connection.send(protocol.blocks(start//BATCH+1,chunk))
            report['sent_blocks'] += len(chunk)
            pos = positions(chunk)
            result = await _action(connection,f'verify-{name}-{start}','inspect_blocks',{'positions':pos},timeout=60)
            rows = checked_rows(result,pos)
            for p in chunk:
                row = rows[(p['x'],p['y'],p['z'])]
                if row.get('block') != p['block']:
                    raise RuntimeError(f"Placement mismatch at {p}: observed {row.get('block')}")
            report['verified_blocks'] += len(chunk)
        report['completed_models'].append(name)
        await connection.send(protocol.chat(f'[YAN] {name}: every placed block verified.'))
    report['status'] = 'placed_and_verified'
    await connection.send(protocol.finish('Three sectors ready. Left: WELL, centre: CANYON, right: SHAFT (+X). Fly toward +Z.'))

async def main_async():
    models = load_models()
    busy = False
    async def handler(connection):
        nonlocal busy
        report = None
        try:
            request = json.loads(await asyncio.wait_for(connection.recv(),timeout=15))
            if not isinstance(request,dict) or request.get('cmd') != 'build' or request.get('prompt','').strip() != PROMPT:
                await connection.send(protocol.error('Preview-only server: use /build yan-sector-preview'))
                return
            if busy:
                await connection.send(protocol.error('Preview placement already running.'))
                return
            busy = True
            report = {'status':'started','started_utc':datetime.now(timezone.utc).isoformat(),'sent_blocks':0,'verified_blocks':0,'completed_models':[],'offsets':OFFSETS}
            start = time.monotonic()
            try:
                await place_preview(connection,models,report)
            except Exception as exc:
                report.update(status='failed',error=f'{type(exc).__name__}: {exc}')
                suffix = ' Partial build retained; do not rerun at the same site.' if report['sent_blocks'] else ' Nothing placed.'
                await connection.send(protocol.error(str(exc)+suffix))
            finally:
                report['elapsed_seconds'] = round(time.monotonic()-start,2)
                logs = Path('runs/sector-preview'); logs.mkdir(parents=True,exist_ok=True)
                path = logs/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.json')
                path.write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(f'[YAN] {report["status"]}; report: {path}',flush=True)
                busy = False
        except Exception as exc:
            print(f'[YAN] connection error: {exc}',flush=True)
    print('[YAN] Ready on 127.0.0.1:8765. Creative test world: /tp @s ~ 180 ~ then /build yan-sector-preview',flush=True)
    async with serve(handler,'127.0.0.1',8765,max_size=4*1024*1024):
        await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main_async())
