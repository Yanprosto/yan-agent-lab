"""WebSocket server entry point for single builds, projects, and YAN live functional sessions."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
from typing import Any

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
    if command not in {"build", "project", "probe", "functional"}:
        await connection.send(protocol.error('Expected {"cmd": "build|project|probe|functional", ...}.'))
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
        elif command == "probe":
            await _run_probe_session(connection)
        else:
            await _run_functional_session(connection)
    finally:
        _task_in_progress = False


async def _action(
    connection: ServerConnection,
    request_id: str,
    action_name: str,
    args: dict[str, Any] | None = None,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Send one world action and require its matching observation."""
    await connection.send(protocol.action(request_id, action_name, args or {}))
    try:
        raw = await asyncio.wait_for(connection.recv(), timeout=timeout)
        message = json.loads(raw)
    except TimeoutError as exc:
        raise RuntimeError(f"{action_name} timed out after {timeout:.1f}s") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{action_name} returned malformed JSON") from exc

    if message.get("type") != "observation":
        raise RuntimeError(f"{action_name} expected observation, got {message.get('type')!r}")
    if message.get("id") != request_id:
        raise RuntimeError(
            f"{action_name} observation id mismatch: expected {request_id!r}, got {message.get('id')!r}"
        )
    if not message.get("ok", False):
        raise RuntimeError(f"{action_name} failed: {message.get('error') or message}")
    return message.get("result") or {}


async def _run_probe_session(connection: ServerConnection) -> None:
    """Two-step live observation: target under crosshair, then its 6-neighbourhood."""
    await connection.send(protocol.hello("yan-probe-v0.2"))
    await connection.send(protocol.chat("[yan-agent] probe v0.2: looking at the block under your crosshair..."))

    try:
        first = await _action(connection, "target-1", "inspect_target", {"reach": 12.0})
    except RuntimeError as exc:
        await connection.send(protocol.error(f"Target probe failed: {exc}"))
        return

    target = first.get("target") or {}
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
    try:
        second = await _action(connection, "neighbours-1", "inspect_blocks", {"positions": positions})
    except RuntimeError as exc:
        await connection.send(protocol.error(f"Neighbourhood probe failed: {exc}"))
        return

    blocks = second.get("blocks") or []
    non_air = [b for b in blocks if not b.get("is_air", False)]
    summary = "; ".join(
        f"({b.get('x')},{b.get('y')},{b.get('z')})={b.get('block')} be={b.get('block_entity') or '-'}"
        for b in blocks
    )
    await connection.send(protocol.chat(f"[yan-agent] neighbourhood: {summary}"))
    await connection.send(protocol.finish(
        f"probe v0.2 PASS: 2 ACTION/OBSERVATION rounds, target={target.get('block')}, nonAir={len(non_air)}/7"
    ))


async def _run_functional_session(connection: ServerConnection) -> None:
    """Deterministic v0.3 self-test for the generic functional world API."""
    await connection.send(protocol.hello("yan-functional-v0.3"))
    await connection.send(protocol.chat(
        "[yan-agent] functional v0.3: inspect -> inventory -> energy -> wait -> safe place/remove"
    ))

    rounds = 0
    try:
        target_result = await _action(connection, "f-target", "inspect_target", {"reach": 12.0})
        rounds += 1
        target = target_result.get("target") or {}
        rx, ry, rz = int(target["x"]), int(target["y"]), int(target["z"])
        await connection.send(protocol.chat(
            f"[yan-agent] target={target.get('block')} world=({target.get('world_x')},{target.get('world_y')},{target.get('world_z')}) "
            f"be={target.get('block_entity') or '-'}"
        ))

        inv = await _action(
            connection,
            "f-inventory",
            "read_inventory",
            {"x": rx, "y": ry, "z": rz},
        )
        rounds += 1
        await connection.send(protocol.chat(
            f"[yan-agent] inventory: available={inv.get('available')} slots={inv.get('slots')} "
            f"totalItems={inv.get('total_items')}"
        ))

        energy = await _action(
            connection,
            "f-energy",
            "read_energy",
            {"x": rx, "y": ry, "z": rz},
        )
        rounds += 1
        await connection.send(protocol.chat(
            f"[yan-agent] energy: available={energy.get('available')} "
            f"stored={energy.get('energy')}/{energy.get('capacity')} "
            f"extract={energy.get('can_extract')} receive={energy.get('can_receive')}"
        ))

        waited = await _action(
            connection,
            "f-wait",
            "wait_ticks",
            {"ticks": 20},
            timeout=5.0,
        )
        rounds += 1
        await connection.send(protocol.chat(
            f"[yan-agent] wait: requested={waited.get('requested_ticks')} "
            f"elapsed={waited.get('elapsed_ticks')} real server ticks"
        ))

        neighbours = [
            {"x": rx + 1, "y": ry, "z": rz},
            {"x": rx - 1, "y": ry, "z": rz},
            {"x": rx, "y": ry + 1, "z": rz},
            {"x": rx, "y": ry - 1, "z": rz},
            {"x": rx, "y": ry, "z": rz + 1},
            {"x": rx, "y": ry, "z": rz - 1},
        ]
        neighbourhood = await _action(
            connection,
            "f-neighbours",
            "inspect_blocks",
            {"positions": neighbours},
        )
        rounds += 1
        air_cells = [b for b in (neighbourhood.get("blocks") or []) if b.get("is_air", False)]
        if not air_cells:
            raise RuntimeError(
                "No adjacent air cell available for safe place/remove self-test; point at a less enclosed block"
            )

        cell = air_cells[0]
        pos = {"x": int(cell["x"]), "y": int(cell["y"]), "z": int(cell["z"])}
        placed = await _action(
            connection,
            "f-place",
            "place_block",
            {**pos, "block": "minecraft:glass"},
        )
        rounds += 1
        await connection.send(protocol.chat(
            f"[yan-agent] place: {placed.get('placed')} at rel=({pos['x']},{pos['y']},{pos['z']})"
        ))

        verify_place = await _action(
            connection,
            "f-verify-place",
            "inspect_blocks",
            {"positions": [pos]},
        )
        rounds += 1
        placed_row = (verify_place.get("blocks") or [{}])[0]
        if placed_row.get("block") != "minecraft:glass":
            raise RuntimeError(f"place verification failed: {placed_row}")

        removed = await _action(
            connection,
            "f-remove",
            "remove_block",
            pos,
        )
        rounds += 1
        if not removed.get("is_air", False):
            raise RuntimeError(f"remove action did not leave air: {removed}")

        verify_remove = await _action(
            connection,
            "f-verify-remove",
            "inspect_blocks",
            {"positions": [pos]},
        )
        rounds += 1
        removed_row = (verify_remove.get("blocks") or [{}])[0]
        if not removed_row.get("is_air", False):
            raise RuntimeError(f"remove verification failed: {removed_row}")

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        await connection.send(protocol.error(f"functional v0.3 FAIL after {rounds} rounds: {exc}"))
        return

    await connection.send(protocol.finish(
        "functional v0.3 PASS: "
        f"{rounds} ACTION/OBSERVATION rounds; "
        f"inventoryAvailable={inv.get('available')}; "
        f"energyAvailable={energy.get('available')}; "
        f"waitTicks={waited.get('elapsed_ticks')}; "
        "placeVerified=true; removeVerified=true"
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
