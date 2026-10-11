"""WebSocket server entry point for single builds and multi-component projects."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json

from dotenv import load_dotenv
from websockets.asyncio.server import ServerConnection, serve

from mcbuild.config import Config
from mcbuild.server import protocol
from mcbuild.server.project_session import run_project_session
from mcbuild.server.session import run_build_session

# Only one task runs at a time in this version; a second connection while a task is in
# flight is rejected outright rather than queued.
_task_in_progress = False


async def _handler(connection: ServerConnection, config: Config) -> None:
    global _task_in_progress

    raw = await connection.recv()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        await connection.send(protocol.error("Malformed request: expected JSON."))
        return

    command = request.get("cmd")
    prompt = request.get("prompt", "")
    if command not in {"build", "project", "probe"}:
        await connection.send(protocol.error('Expected {"cmd": "build|project|probe", ...}.'))
        return
    if command in {"build", "project"} and (not isinstance(prompt, str) or not prompt.strip()):
        await connection.send(protocol.error('Expected non-empty "prompt" for build/project.'))
        return

    if _task_in_progress:
        await connection.send(protocol.error("A build is already in progress; try again shortly."))
        return

    _task_in_progress = True
    try:
        if command == "build":
            await run_build_session(prompt, connection.send, config=config)
        elif command == "project":
            await run_project_session(prompt, connection.send, config=config)
        else:
            await _run_probe_session(connection)
    finally:
        _task_in_progress = False


async def _run_probe_session(connection: ServerConnection) -> None:
    """Two-step live observation: target under crosshair, then its 6-neighbourhood."""
    await connection.send(protocol.hello("yan-probe-v0.2"))
    await connection.send(protocol.chat("[yan-agent] probe v0.2: looking at the block under your crosshair..."))

    await connection.send(protocol.action("target-1", "inspect_target", {"reach": 12.0}))
    try:
        raw = await asyncio.wait_for(connection.recv(), timeout=10.0)
        first = json.loads(raw)
    except TimeoutError:
        await connection.send(protocol.error("Probe timed out waiting for target observation."))
        return
    except json.JSONDecodeError:
        await connection.send(protocol.error("Probe received malformed target observation JSON."))
        return
    if first.get("type") != "observation" or first.get("id") != "target-1" or not first.get("ok", False):
        await connection.send(protocol.error(f"Target probe failed: {first}"))
        return

    target = (first.get("result") or {}).get("target") or {}
    rx, ry, rz = int(target.get("x", 0)), int(target.get("y", 0)), int(target.get("z", 0))
    await connection.send(protocol.chat(
        f"[yan-agent] target: {target.get('block')} world=({target.get('world_x')},{target.get('world_y')},{target.get('world_z')}) "
        f"be={target.get('block_entity') or '-'} face={target.get('hit_face') or '-'}"
    ))

    positions = [
        {"x": rx, "y": ry, "z": rz},
        {"x": rx + 1, "y": ry, "z": rz},
        {"x": rx - 1, "y": ry, "z": rz},
        {"x": rx, "y": ry + 1, "z": rz},
        {"x": rx, "y": ry - 1, "z": rz},
        {"x": rx, "y": ry, "z": rz + 1},
        {"x": rx, "y": ry, "z": rz - 1},
    ]
    await connection.send(protocol.chat("[yan-agent] decision: target acquired; requesting its 6-neighbourhood..."))
    await connection.send(protocol.action("neighbours-1", "inspect_blocks", {"positions": positions}))
    try:
        raw = await asyncio.wait_for(connection.recv(), timeout=10.0)
        second = json.loads(raw)
    except TimeoutError:
        await connection.send(protocol.error("Probe timed out waiting for neighbourhood observation."))
        return
    except json.JSONDecodeError:
        await connection.send(protocol.error("Probe received malformed neighbourhood observation JSON."))
        return
    if second.get("type") != "observation" or second.get("id") != "neighbours-1" or not second.get("ok", False):
        await connection.send(protocol.error(f"Neighbourhood probe failed: {second}"))
        return

    blocks = (second.get("result") or {}).get("blocks") or []
    non_air = [b for b in blocks if not b.get("is_air", False)]
    summary = "; ".join(
        f"({b.get('x')},{b.get('y')},{b.get('z')})={b.get('block')} be={b.get('block_entity') or '-'}"
        for b in blocks
    )
    await connection.send(protocol.chat(f"[yan-agent] neighbourhood: {summary}"))
    await connection.send(protocol.finish(
        f"probe v0.2 PASS: 2 ACTION/OBSERVATION rounds, target={target.get('block')}, nonAir={len(non_air)}/7"
    ))


async def _serve(host: str, port: int, config: Config) -> None:
    handler = functools.partial(_handler, config=config)
    async with serve(handler, host, port) as server:
        print(f"mcbuild server listening on ws://{host}:{port} (model={config.model})")
        await server.serve_forever()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="mcbuild live-build WebSocket server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=Config.model, help="Vision-capable OpenRouter model id.")
    parser.add_argument("--max-iters", type=int, default=Config.max_iters)
    parser.add_argument("--reasoning", default=Config.reasoning, help="off|low|medium|high")
    parser.add_argument(
        "--cost-ceiling",
        type=float,
        default=None,
        help="Abort a build (keeping its best build so far) once usage cost reaches this many USD.",
    )
    args = parser.parse_args()

    config = Config(
        model=args.model,
        max_iters=args.max_iters,
        reasoning=args.reasoning,
        cost_ceiling=args.cost_ceiling,
    )
    asyncio.run(_serve(args.host, args.port, config))


if __name__ == "__main__":
    main()
