"""Place three 128x128 industrial-sector previews in a creative test world.

Run this server, stand at Y=180 in a very large empty area, then:
/build yan-industrial-sector-preview
"""
from __future__ import annotations
import asyncio, json
from pathlib import Path
from websockets.asyncio.server import serve
from mcbuild.server import protocol
from mcbuild.server.ws_server import _action
from mcbuild.server.delta import compute_block_delta
from build import load_models

BATCH=1024
PROMPT="yan-industrial-sector-preview"

# Spread on a 2D grid rather than putting three models in one straight row.
OFFSETS={
    "vertical_foundry":(-150,0,-20),
    "industrial_canyon":(20,0,-20),
    "terraced_megaforge":(-65,0,150),
}

def positions(cells):
    return [{k:c[k] for k in ("x","y","z")} for c in cells]

def rows_checked(result, requested):
    rows=result.get("blocks",[])
    lookup={(r.get("x"),r.get("y"),r.get("z")):r for r in rows}
    expected={(p["x"],p["y"],p["z"]) for p in requested}
    if len(lookup)!=len(expected) or set(lookup)!=expected:
        raise RuntimeError("Incomplete world observation")
    return lookup

def compile_models():
    out=[]
    for name,grid in load_models().items():
        dx,dy,dz=OFFSETS[name]
        changes=compute_block_delta(None,grid)
        for c in changes:
            c["x"]+=dx; c["y"]+=dy; c["z"]+=dz
        changes.sort(key=lambda p:(p["y"],p["z"]//16,p["x"]//16,p["z"],p["x"]))
        out.append((name,changes))
    return out

async def place(connection):
    models=compile_models()
    await connection.send(protocol.hello("yan-industrial-sector-preview-v1"))
    anchor=await _action(connection,"anchor","inspect_blocks",{"positions":[{"x":0,"y":0,"z":0}]})
    row=rows_checked(anchor,[{"x":0,"y":0,"z":0}])[(0,0,0)]
    if row.get("world_y") != 180:
        raise RuntimeError("Teleport/fly to Y=180, then rerun. Nothing placed.")

    await connection.send(protocol.chat("[YAN] Preflight: checking every destination before first write."))
    for name,cells in models:
        for start in range(0,len(cells),BATCH):
            chunk=cells[start:start+BATCH]; pos=positions(chunk)
            obs=await _action(connection,f"pre-{name}-{start}","inspect_blocks",{"positions":pos},timeout=90)
            lookup=rows_checked(obs,pos)
            occupied=[r for r in lookup.values() if r.get("is_air") is not True]
            if occupied:
                r=occupied[0]
                raise RuntimeError(
                    f"Site occupied for {name} at {r.get('world_x')},{r.get('world_y')},{r.get('world_z')}. Nothing placed."
                )
        await connection.send(protocol.chat(f"[YAN] {name}: clear, {len(cells)} blocks."))

    for name,cells in models:
        await connection.send(protocol.chat(f"[YAN] Placing {name}: {len(cells)} blocks."))
        for start in range(0,len(cells),BATCH):
            chunk=cells[start:start+BATCH]
            await connection.send(protocol.blocks(start//BATCH+1,chunk))
            pos=positions(chunk)
            obs=await _action(connection,f"verify-{name}-{start}","inspect_blocks",{"positions":pos},timeout=90)
            lookup=rows_checked(obs,pos)
            for p in chunk:
                if lookup[(p["x"],p["y"],p["z"])].get("block") != p["block"]:
                    raise RuntimeError(f"Placement mismatch in {name} at {p}")
        await connection.send(protocol.chat(f"[YAN] {name}: placed and verified."))

    await connection.send(protocol.finish(
        "Industrial sector previews ready: vertical foundry NW, canyon NE, terraced megaforge south."
    ))

async def main_async():
    busy=False
    async def handler(connection):
        nonlocal busy
        try:
            request=json.loads(await asyncio.wait_for(connection.recv(),timeout=15))
            if request.get("cmd")!="build" or request.get("prompt","").strip()!=PROMPT:
                await connection.send(protocol.error(f"Preview-only server: use /build {PROMPT}"))
                return
            if busy:
                await connection.send(protocol.error("Preview placement already running."))
                return
            busy=True
            try:
                await place(connection)
            except Exception as exc:
                await connection.send(protocol.error(str(exc)))
            finally:
                busy=False
        except Exception as exc:
            print(f"[YAN] preview connection error: {exc}",flush=True)

    print("[YAN] Industrial preview server on 127.0.0.1:8765")
    print("[YAN] In Minecraft: /tp @s ~ 180 ~  then  /build yan-industrial-sector-preview")
    async with serve(handler,"127.0.0.1",8765,max_size=8*1024*1024):
        await asyncio.Future()

if __name__=="__main__":
    asyncio.run(main_async())
