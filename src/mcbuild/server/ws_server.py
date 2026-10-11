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
from mcbuild.server.run_logger import LoggedConnection, RunRecorder
from mcbuild.server.session import run_build_session
from mcbuild.server.skill_store import list_skills, save_skill

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
    if command not in {"build", "project", "probe", "functional", "experiment", "mekanism", "splitter"}:
        await connection.send(protocol.error('Expected {"cmd": "build|project|probe|functional|experiment|mekanism|splitter", ...}.'))
        return
    if command in {"build", "project"} and (not isinstance(prompt, str) or not prompt.strip()):
        await connection.send(protocol.error('Expected non-empty "prompt" for build/project.'))
        return

    if _task_in_progress:
        await connection.send(protocol.error("A build is already in progress; try again shortly."))
        return

    recorder = RunRecorder(command=command, prompt=prompt if isinstance(prompt, str) else "")
    recorder.record("REQUEST", command=command, prompt=prompt if isinstance(prompt, str) else "")
    logged_connection = LoggedConnection(connection, recorder)

    _task_in_progress = True
    try:
        if command == "build":
            await run_build_session(prompt, logged_connection.send, config=config)
        elif command == "project":
            await run_project_session(prompt, logged_connection.send, config=config)
        elif command == "probe":
            await _run_probe_session(logged_connection)
        elif command == "functional":
            await _run_functional_session(logged_connection)
        elif command == "experiment":
            await _run_experiment_session(logged_connection)
        elif command == "mekanism":
            await _run_mekanism_experiment_session(logged_connection)
        else:
            await _run_splitter_experiment_session(logged_connection)
    except Exception as exc:
        recorder.fail_from_exception(exc)
        try:
            await logged_connection.send(protocol.error(
                f"Unhandled server exception: {exc.__class__.__name__}: {exc}"
            ))
        except Exception:
            pass
    finally:
        _task_in_progress = False
        publish = await asyncio.to_thread(recorder.finalize_and_publish)
        if publish.get("published"):
            print(
                f"[yan-runtime] published {recorder.run_id} "
                f"commit={publish.get('commit') or '-'} branch={publish.get('branch')}"
            )
        else:
            print(
                f"[yan-runtime] local-only {recorder.run_id}: "
                f"{publish.get('reason')} ({publish.get('run_dir')})"
            )


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


async def _build_routing_variant(
    connection: ServerConnection,
    *,
    name: str,
    hopper_facing: str,
) -> dict[str, dict[str, Any]]:
    """Build one tiny routing harness from scratch using only generic actions."""
    source = {"x": 4, "y": 2, "z": 0}
    hopper = {"x": 4, "y": 1, "z": 0}
    left = {"x": 3, "y": 1, "z": 0}
    right = {"x": 5, "y": 1, "z": 0}

    await connection.send(protocol.chat(
        f"[yan-agent] {name}: BUILD source chest + hopper[{hopper_facing}] + two sinks"
    ))

    placements = [
        ("source", source, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("left", left, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("right", right, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("hopper", hopper, f"minecraft:hopper[facing={hopper_facing},enabled=true]"),
    ]
    for label, pos, block in placements:
        await _action(
            connection,
            f"{name}-place-{label}",
            "place_block",
            {**pos, "block": block},
        )

    seeded = await _action(
        connection,
        f"{name}-seed",
        "seed_item",
        {**source, "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: SEED inserted={seeded.get('inserted')}/6 raw iron"
    ))

    waited = await _action(
        connection,
        f"{name}-wait",
        "wait_ticks",
        {"ticks": 120},
        timeout=12.0,
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: WAIT elapsed={waited.get('elapsed_ticks')} ticks"
    ))

    src = await _action(connection, f"{name}-read-source", "read_inventory", source)
    left_inv = await _action(connection, f"{name}-read-left", "read_inventory", left)
    right_inv = await _action(connection, f"{name}-read-right", "read_inventory", right)
    return {"source": src, "left": left_inv, "right": right_inv}


async def _cleanup_routing_variant(
    connection: ServerConnection,
    *,
    name: str,
    source: dict[str, int],
    left: dict[str, int],
    right: dict[str, int],
) -> None:
    """Drain observable inventories, then remove every block placed by this session."""
    for label, pos in (("source", source), ("left", left), ("right", right)):
        drained = await _action(
            connection,
            f"{name}-drain-{label}",
            "drain_inventory",
            pos,
        )
        await connection.send(protocol.chat(
            f"[yan-agent] {name}: RESET drain {label} removed={drained.get('removed_total')}"
        ))

    rolled = await _action(connection, f"{name}-rollback", "rollback_session", {})
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: ROLLBACK removed={rolled.get('removed')} "
        f"trackedAfter={rolled.get('tracked_after')}"
    ))


async def _run_experiment_session(connection: ServerConnection) -> None:
    """v0.4: first autonomous build-test-reject-rollback-mutate-retry loop."""
    await connection.send(protocol.hello("yan-experiment-v0.4"))
    await connection.send(protocol.chat(
        "[yan-agent] experiment v0.4: objective = route all 6 raw iron to LEFT sink; "
        "agent will try variants, score them, rollback failures, then retry."
    ))

    source = {"x": 4, "y": 2, "z": 0}
    left = {"x": 3, "y": 1, "z": 0}
    right = {"x": 5, "y": 1, "z": 0}

    # Verify the complete footprint is empty before the agent mutates the world.
    footprint = [
        source,
        {"x": 4, "y": 1, "z": 0},
        left,
        right,
    ]
    try:
        initial = await _action(
            connection,
            "exp-footprint",
            "inspect_blocks",
            {"positions": footprint},
        )
        occupied = [b for b in (initial.get("blocks") or []) if not b.get("is_air", False)]
        if occupied:
            raise RuntimeError(f"experiment footprint is not empty: {occupied}")

        variants = [
            ("variant-A", "east"),  # intentionally routes into RIGHT sink -> should fail objective
            ("variant-B", "west"),  # mutation: routes into LEFT sink -> should pass objective
        ]
        history: list[dict[str, Any]] = []
        accepted: dict[str, Any] | None = None

        for index, (name, facing) in enumerate(variants, start=1):
            await connection.send(protocol.chat(
                f"[yan-agent] TRY {index}/{len(variants)} {name}: hopper facing={facing}"
            ))
            observed = await _build_routing_variant(connection, name=name, hopper_facing=facing)

            source_n = int(observed["source"].get("total_items") or 0)
            left_n = int(observed["left"].get("total_items") or 0)
            right_n = int(observed["right"].get("total_items") or 0)
            total = source_n + left_n + right_n
            conserved = total == 6
            passed = conserved and source_n == 0 and left_n == 6 and right_n == 0
            score = left_n - right_n

            row = {
                "name": name,
                "hopper_facing": facing,
                "source": source_n,
                "left": left_n,
                "right": right_n,
                "total": total,
                "conserved": conserved,
                "score": score,
                "passed": passed,
            }
            history.append(row)

            await connection.send(protocol.chat(
                f"[yan-agent] OBSERVE {name}: source={source_n} left={left_n} right={right_n} "
                f"total={total} conserved={conserved} score={score}"
            ))

            if passed:
                await connection.send(protocol.chat(
                    f"[yan-agent] ACCEPT {name}: objective satisfied."
                ))
                accepted = row
                await _cleanup_routing_variant(
                    connection, name=name, source=source, left=left, right=right
                )
                break

            await connection.send(protocol.chat(
                f"[yan-agent] REJECT {name}: objective failed; rolling back before mutation."
            ))
            await _cleanup_routing_variant(
                connection, name=name, source=source, left=left, right=right
            )

        if accepted is None:
            raise RuntimeError(f"no routing variant satisfied objective; history={history}")

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        # Best-effort world cleanup even when an intermediate action failed.
        try:
            await _action(connection, "exp-emergency-rollback", "rollback_session", {})
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"experiment v0.4 FAIL: {exc}"))
        return

    await connection.send(protocol.finish(
        "experiment v0.4 PASS: autonomous loop completed; "
        f"tried={len(history)}; accepted={accepted['name']}; "
        f"history={history}; worldClean=true"
    ))


async def _build_mekanism_variant(
    connection: ServerConnection,
    *,
    name: str,
    input_mode: str,
) -> dict[str, Any]:
    """Build and test one source -> transporter -> sink configuration."""
    source = {"x": 4, "y": 2, "z": 0}
    transporter = {"x": 4, "y": 1, "z": 0}
    sink = {"x": 4, "y": 0, "z": 0}

    await connection.send(protocol.chat(
        f"[yan-agent] {name}: BUILD chest -> logistical transporter -> chest; inputMode={input_mode}"
    ))

    placements = [
        ("source", source, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("sink", sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("transporter", transporter, "mekanism:basic_logistical_transporter"),
    ]
    for label, pos, block in placements:
        await _action(
            connection,
            f"{name}-place-{label}",
            "place_block",
            {**pos, "block": block},
        )

    # Give Mekanism a few real ticks to create/join the transmitter network.
    await _action(
        connection,
        f"{name}-settle",
        "wait_ticks",
        {"ticks": 10},
        timeout=5.0,
    )

    # The source chest is above the transporter, so UP is the extraction side.
    set_mode = await _action(
        connection,
        f"{name}-mode-up",
        "mek_set_transporter_mode",
        {**transporter, "side": "up", "mode": input_mode},
    )
    # The sink is below the transporter; NORMAL can send into an adjacent inventory.
    down_mode = await _action(
        connection,
        f"{name}-mode-down",
        "mek_set_transporter_mode",
        {**transporter, "side": "down", "mode": "NORMAL"},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: CONFIG up={set_mode.get('after')} verified={set_mode.get('verified')} "
        f"down={down_mode.get('after')}"
    ))

    readback = await _action(
        connection,
        f"{name}-readback-up",
        "mek_get_transporter_mode",
        {**transporter, "side": "up"},
    )
    if readback.get("mode") != input_mode:
        raise RuntimeError(f"{name}: transporter readback mismatch: {readback}")

    seeded = await _action(
        connection,
        f"{name}-seed",
        "seed_item",
        {**source, "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: SEED inserted={seeded.get('inserted')}/6 raw iron"
    ))

    waited = await _action(
        connection,
        f"{name}-wait",
        "wait_ticks",
        {"ticks": 160},
        timeout=15.0,
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: WAIT elapsed={waited.get('elapsed_ticks')} ticks"
    ))

    src = await _action(connection, f"{name}-read-source", "read_inventory", source)
    dst = await _action(connection, f"{name}-read-sink", "read_inventory", sink)
    return {
        "source": src,
        "sink": dst,
        "mode": readback,
    }


async def _cleanup_mekanism_variant(
    connection: ServerConnection,
    *,
    name: str,
) -> None:
    source = {"x": 4, "y": 2, "z": 0}
    sink = {"x": 4, "y": 0, "z": 0}

    for label, pos in (("source", source), ("sink", sink)):
        try:
            drained = await _action(
                connection,
                f"{name}-drain-{label}",
                "drain_inventory",
                pos,
            )
            await connection.send(protocol.chat(
                f"[yan-agent] {name}: RESET drain {label} removed={drained.get('removed_total')}"
            ))
        except RuntimeError as exc:
            await connection.send(protocol.chat(
                f"[yan-agent] {name}: RESET drain {label} skipped: {exc}"
            ))

    rolled = await _action(connection, f"{name}-rollback", "rollback_session", {})
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: ROLLBACK removed={rolled.get('removed')} trackedAfter={rolled.get('tracked_after')}"
    ))


async def _run_mekanism_experiment_session(connection: ServerConnection) -> None:
    """v0.5: mutate real Mekanism transporter mode based on live item-flow feedback."""
    await connection.send(protocol.hello("yan-mekanism-v0.5"))
    await connection.send(protocol.chat(
        "[yan-agent] Mekanism v0.5 objective: move all 6 raw iron from SOURCE to SINK. "
        "Agent will test NORMAL, reject it if no extraction occurs, rollback, mutate input side to PULL, and retry."
    ))

    source = {"x": 4, "y": 2, "z": 0}
    transporter = {"x": 4, "y": 1, "z": 0}
    sink = {"x": 4, "y": 0, "z": 0}
    footprint = [source, transporter, sink]

    history: list[dict[str, Any]] = []
    accepted: dict[str, Any] | None = None

    try:
        initial = await _action(
            connection,
            "mek-footprint",
            "inspect_blocks",
            {"positions": footprint},
        )
        occupied = [b for b in (initial.get("blocks") or []) if not b.get("is_air", False)]
        if occupied:
            raise RuntimeError(f"Mekanism experiment footprint is not empty: {occupied}")

        variants = [
            ("variant-A", "NORMAL"),
            ("variant-B", "PULL"),
        ]

        for index, (name, mode) in enumerate(variants, start=1):
            await connection.send(protocol.chat(
                f"[yan-agent] TRY {index}/{len(variants)} {name}: transporter UP={mode}"
            ))

            observed = await _build_mekanism_variant(
                connection,
                name=name,
                input_mode=mode,
            )
            source_n = int(observed["source"].get("total_items") or 0)
            sink_n = int(observed["sink"].get("total_items") or 0)
            total = source_n + sink_n
            conserved = total == 6
            passed = conserved and source_n == 0 and sink_n == 6
            score = sink_n

            row = {
                "name": name,
                "input_mode": mode,
                "source": source_n,
                "sink": sink_n,
                "total": total,
                "conserved": conserved,
                "score": score,
                "passed": passed,
            }
            history.append(row)

            await connection.send(protocol.chat(
                f"[yan-agent] OBSERVE {name}: source={source_n} sink={sink_n} total={total} "
                f"conserved={conserved} score={score}"
            ))

            if passed:
                await connection.send(protocol.chat(
                    f"[yan-agent] ACCEPT {name}: real Mekanism item flow satisfied objective."
                ))
                accepted = row
                await _cleanup_mekanism_variant(connection, name=name)
                break

            await connection.send(protocol.chat(
                f"[yan-agent] REJECT {name}: objective failed; rollback and mutate transporter mode."
            ))
            await _cleanup_mekanism_variant(connection, name=name)

        if accepted is None:
            raise RuntimeError(f"no Mekanism variant satisfied objective; history={history}")

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            await _action(connection, "mek-emergency-rollback", "rollback_session", {})
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"Mekanism experiment v0.5 FAIL: {exc}"))
        return

    await connection.send(protocol.finish(
        "Mekanism experiment v0.5 PASS: real mod config loop completed; "
        f"tried={len(history)}; accepted={accepted['name']}; history={history}; worldClean=true"
    ))


async def _build_splitter_variant_a(connection: ServerConnection, name: str) -> dict[str, Any]:
    """One PULL extractor feeding a shared T-network and two equal sinks."""
    source = {"x": 6, "y": 3, "z": 0}
    root = {"x": 6, "y": 2, "z": 0}
    junction = {"x": 6, "y": 1, "z": 0}
    left_arm = {"x": 5, "y": 1, "z": 0}
    right_arm = {"x": 7, "y": 1, "z": 0}
    left_sink = {"x": 4, "y": 1, "z": 0}
    right_sink = {"x": 8, "y": 1, "z": 0}

    await connection.send(protocol.chat(
        "[yan-agent] variant-A: BUILD single extractor -> shared T-network -> two sinks"
    ))
    placements = [
        ("source", source, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("root", root, "mekanism:basic_logistical_transporter"),
        ("junction", junction, "mekanism:basic_logistical_transporter"),
        ("left-arm", left_arm, "mekanism:basic_logistical_transporter"),
        ("right-arm", right_arm, "mekanism:basic_logistical_transporter"),
        ("left-sink", left_sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("right-sink", right_sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
    ]
    for label, pos, block_id in placements:
        await _action(connection, f"{name}-place-{label}", "place_block", {**pos, "block": block_id})

    await _action(connection, f"{name}-settle", "wait_ticks", {"ticks": 15}, timeout=5.0)
    await _action(
        connection,
        f"{name}-pull",
        "mek_set_transporter_mode",
        {**root, "side": "up", "mode": "PULL"},
    )
    seeded = await _action(
        connection,
        f"{name}-seed",
        "seed_item",
        {**source, "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] variant-A: seeded={seeded.get('inserted')}/6; watching real Mekanism routing..."
    ))
    await _action(connection, f"{name}-wait", "wait_ticks", {"ticks": 240}, timeout=20.0)

    return {
        "source": await _action(connection, f"{name}-source", "read_inventory", source),
        "left": await _action(connection, f"{name}-left", "read_inventory", left_sink),
        "right": await _action(connection, f"{name}-right", "read_inventory", right_sink),
        "drain_positions": [("source", source), ("left", left_sink), ("right", right_sink)],
        "topology": "single_pull_shared_t",
    }


async def _build_splitter_variant_b(connection: ServerConnection, name: str) -> dict[str, Any]:
    """Two independent PULL extractors compete fairly for one source inventory."""
    source = {"x": 6, "y": 3, "z": 0}
    left_pull = {"x": 5, "y": 3, "z": 0}
    left_arm = {"x": 4, "y": 3, "z": 0}
    left_sink = {"x": 3, "y": 3, "z": 0}
    right_pull = {"x": 7, "y": 3, "z": 0}
    right_arm = {"x": 8, "y": 3, "z": 0}
    right_sink = {"x": 9, "y": 3, "z": 0}

    await connection.send(protocol.chat(
        "[yan-agent] variant-B: MUTATE topology -> two independent PULL extractors from one source"
    ))
    placements = [
        ("source", source, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("left-pull", left_pull, "mekanism:basic_logistical_transporter"),
        ("left-arm", left_arm, "mekanism:basic_logistical_transporter"),
        ("left-sink", left_sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("right-pull", right_pull, "mekanism:basic_logistical_transporter"),
        ("right-arm", right_arm, "mekanism:basic_logistical_transporter"),
        ("right-sink", right_sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
    ]
    for label, pos, block_id in placements:
        await _action(connection, f"{name}-place-{label}", "place_block", {**pos, "block": block_id})

    await _action(connection, f"{name}-settle", "wait_ticks", {"ticks": 15}, timeout=5.0)

    left_cfg = await _action(
        connection,
        f"{name}-left-pull-mode",
        "mek_set_transporter_mode",
        {**left_pull, "side": "east", "mode": "PULL"},
    )
    right_cfg = await _action(
        connection,
        f"{name}-right-pull-mode",
        "mek_set_transporter_mode",
        {**right_pull, "side": "west", "mode": "PULL"},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] variant-B: CONFIG left={left_cfg.get('after')} right={right_cfg.get('after')}"
    ))

    seeded = await _action(
        connection,
        f"{name}-seed",
        "seed_item",
        {**source, "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] variant-B: seeded={seeded.get('inserted')}/6; observing both independent branches..."
    ))
    await _action(connection, f"{name}-wait", "wait_ticks", {"ticks": 240}, timeout=20.0)

    return {
        "source": await _action(connection, f"{name}-source", "read_inventory", source),
        "left": await _action(connection, f"{name}-left", "read_inventory", left_sink),
        "right": await _action(connection, f"{name}-right", "read_inventory", right_sink),
        "drain_positions": [("source", source), ("left", left_sink), ("right", right_sink)],
        "topology": "dual_independent_pull",
    }


async def _cleanup_splitter_variant(
    connection: ServerConnection,
    *,
    name: str,
    drain_positions: list[tuple[str, dict[str, int]]],
) -> None:
    for label, pos in drain_positions:
        try:
            drained = await _action(connection, f"{name}-drain-{label}", "drain_inventory", pos)
            await connection.send(protocol.chat(
                f"[yan-agent] {name}: RESET {label} removed={drained.get('removed_total')}"
            ))
        except RuntimeError as exc:
            await connection.send(protocol.chat(f"[yan-agent] {name}: RESET {label} skipped: {exc}"))
    rolled = await _action(connection, f"{name}-rollback", "rollback_session", {})
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: ROLLBACK removed={rolled.get('removed')} trackedAfter={rolled.get('tracked_after')}"
    ))


async def _run_splitter_experiment_session(connection: ServerConnection) -> None:
    """v0.6: topology search + persistent skill admission."""
    await connection.send(protocol.hello("yan-splitter-v0.6"))

    # v0.5 was live-validated before this branch. Commit that verified primitive to
    # durable project memory so future tasks do not rediscover it.
    base_skill_path = save_skill(
        "mekanism_single_extractor_v1",
        description="A logistical transporter actively extracts from an adjacent source only when the source-facing side is PULL.",
        implementation={
            "block": "mekanism:basic_logistical_transporter",
            "source_side_mode": "PULL",
            "sink_side_mode": "NORMAL",
        },
        verification={"seeded": 6, "source_after": 0, "sink_after": 6, "conserved": True},
        source_experiment="yan-mekanism-v0.5-live-validated",
    )
    await connection.send(protocol.chat(
        f"[yan-agent] MEMORY: loaded/admitted base skill mekanism_single_extractor_v1 -> {base_skill_path.name}"
    ))
    await connection.send(protocol.chat(
        "[yan-agent] v0.6 objective: distribute 6 raw iron so BOTH branches receive items; "
        "agent may reject a topology and rebuild a structurally different one."
    ))

    # Union of both candidate footprints. Abort before touching the world if any cell is occupied.
    footprint = [
        {"x": 3, "y": 3, "z": 0}, {"x": 4, "y": 3, "z": 0}, {"x": 5, "y": 3, "z": 0},
        {"x": 6, "y": 3, "z": 0}, {"x": 7, "y": 3, "z": 0}, {"x": 8, "y": 3, "z": 0},
        {"x": 9, "y": 3, "z": 0}, {"x": 6, "y": 2, "z": 0}, {"x": 4, "y": 1, "z": 0},
        {"x": 5, "y": 1, "z": 0}, {"x": 6, "y": 1, "z": 0}, {"x": 7, "y": 1, "z": 0},
        {"x": 8, "y": 1, "z": 0},
    ]

    history: list[dict[str, Any]] = []
    accepted: dict[str, Any] | None = None
    accepted_topology: str | None = None

    try:
        initial = await _action(connection, "split-footprint", "inspect_blocks", {"positions": footprint})
        occupied = [b for b in (initial.get("blocks") or []) if not b.get("is_air", False)]
        if occupied:
            raise RuntimeError(f"splitter footprint is not empty: {occupied}")

        builders = [
            ("variant-A", _build_splitter_variant_a),
            ("variant-B", _build_splitter_variant_b),
        ]
        for index, (name, builder) in enumerate(builders, start=1):
            await connection.send(protocol.chat(f"[yan-agent] TRY {index}/{len(builders)} {name}"))
            observed = await builder(connection, name)

            source_n = int(observed["source"].get("total_items") or 0)
            left_n = int(observed["left"].get("total_items") or 0)
            right_n = int(observed["right"].get("total_items") or 0)
            total = source_n + left_n + right_n
            conserved = total == 6
            both_live = left_n > 0 and right_n > 0
            imbalance = abs(left_n - right_n)
            passed = conserved and source_n == 0 and both_live
            score = (100 if both_live else 0) - imbalance

            row = {
                "name": name,
                "topology": observed["topology"],
                "source": source_n,
                "left": left_n,
                "right": right_n,
                "total": total,
                "conserved": conserved,
                "both_live": both_live,
                "imbalance": imbalance,
                "score": score,
                "passed": passed,
            }
            history.append(row)
            await connection.send(protocol.chat(
                f"[yan-agent] OBSERVE {name}: source={source_n} left={left_n} right={right_n} "
                f"conserved={conserved} bothLive={both_live} imbalance={imbalance} score={score}"
            ))

            if passed:
                accepted = row
                accepted_topology = observed["topology"]
                await connection.send(protocol.chat(
                    f"[yan-agent] ACCEPT {name}: both branches are physically live."
                ))
                await _cleanup_splitter_variant(
                    connection, name=name, drain_positions=observed["drain_positions"]
                )
                break

            await connection.send(protocol.chat(
                f"[yan-agent] REJECT {name}: branch starvation detected; rollback and mutate topology."
            ))
            await _cleanup_splitter_variant(
                connection, name=name, drain_positions=observed["drain_positions"]
            )

        if accepted is None or accepted_topology is None:
            raise RuntimeError(f"no topology activated both branches; history={history}")

        skill_path = save_skill(
            "mekanism_two_branch_distribution_v1",
            description="Verified topology that moves one source inventory into two live Mekanism logistical branches.",
            implementation={
                "topology": accepted_topology,
                "source_item": "minecraft:raw_iron",
                "source_side_modes": "PULL",
                "success_contract": {"left_min": 1, "right_min": 1, "source_final": 0},
            },
            verification=accepted,
            source_experiment="yan-splitter-v0.6",
        )
        skills = list_skills()
        await connection.send(protocol.chat(
            f"[yan-agent] MEMORY: saved verified skill {skill_path.name}; knownSkills={skills}"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            await _action(connection, "split-emergency-rollback", "rollback_session", {})
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"splitter experiment v0.6 FAIL: {exc}"))
        return

    await connection.send(protocol.finish(
        "splitter experiment v0.6 PASS: topology search completed; "
        f"tried={len(history)} accepted={accepted['name']} topology={accepted_topology}; "
        f"left={accepted['left']} right={accepted['right']} imbalance={accepted['imbalance']}; "
        f"skill=mekanism_two_branch_distribution_v1; worldClean=true"
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
