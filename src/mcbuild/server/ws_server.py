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
from mcbuild.server.environment_planner import BranchRoute, RoutePlan, generate_route_plans, replan_failed_branch
from mcbuild.server.project_session import run_project_session
from mcbuild.server.mission_session import run_mission_session
from mcbuild.server.mission_v21 import run_powered_mission_session
from mcbuild.server.industry_session import run_industry_session
from mcbuild.server.iron_works_session import run_iron_works_session
from mcbuild.server.run_logger import LoggedConnection, RunRecorder
from mcbuild.server.session import run_build_session
from mcbuild.server.skill_store import list_skills, load_skill, save_skill
from mcbuild.server.spatial_search import SpatialCandidate, generate_spatial_candidates
from mcbuild.server.topology_search import TopologyCandidate, generate_two_branch_candidates

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
    if command not in {"build", "project", "probe", "functional", "experiment", "mekanism", "splitter", "environment", "mission", "industry"}:
        await connection.send(protocol.error('Expected {"cmd": "build|project|probe|functional|experiment|mekanism|splitter|environment|mission|industry", ...}.'))
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
        elif command == "splitter":
            await _run_spatial_search_session(logged_connection)
        elif command == "environment":
            await _run_environment_build_session(logged_connection)
        elif command == "mission":
            await run_powered_mission_session(logged_connection)
        else:
            normalized_goal = " ".join(str(prompt).lower().strip().split())
            iron_works_aliases = (
                "железный завод",
                "большой железный завод",
                "iron works",
                "ironworks",
                "iron factory",
            )
            if any(alias in normalized_goal for alias in iron_works_aliases):
                await run_iron_works_session(prompt, logged_connection)
            else:
                await run_industry_session(prompt, logged_connection)
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


async def _build_generated_dual_pull_candidate(
    connection: ServerConnection,
    candidate: TopologyCandidate,
) -> dict[str, Any]:
    """Materialize one generated dual-independent-PULL candidate."""
    name = candidate.candidate_id
    source = {"x": 6, "y": 3, "z": 0}
    left_pull = {"x": 5, "y": 3, "z": 0}
    right_pull = {"x": 7, "y": 3, "z": 0}

    left_arms = [
        {"x": 4 - i, "y": 3, "z": 0}
        for i in range(candidate.arm_blocks)
    ]
    right_arms = [
        {"x": 8 + i, "y": 3, "z": 0}
        for i in range(candidate.arm_blocks)
    ]
    left_sink = {"x": 4 - candidate.arm_blocks, "y": 3, "z": 0}
    right_sink = {"x": 8 + candidate.arm_blocks, "y": 3, "z": 0}

    await connection.send(protocol.chat(
        f"[yan-agent] CANDIDATE {name}: family={candidate.family} source={candidate.source} "
        f"armBlocks={candidate.arm_blocks} estimatedBlocks={candidate.estimated_blocks}"
    ))
    await connection.send(protocol.chat(f"[yan-agent] {name}: {candidate.description}"))

    placements: list[tuple[str, dict[str, int], str]] = [
        ("source", source, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("left-pull", left_pull, "mekanism:basic_logistical_transporter"),
        ("right-pull", right_pull, "mekanism:basic_logistical_transporter"),
    ]
    placements.extend(
        (f"left-arm-{i + 1}", pos, "mekanism:basic_logistical_transporter")
        for i, pos in enumerate(left_arms)
    )
    placements.extend(
        (f"right-arm-{i + 1}", pos, "mekanism:basic_logistical_transporter")
        for i, pos in enumerate(right_arms)
    )
    placements.extend(
        [
            ("left-sink", left_sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
            ("right-sink", right_sink, "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ]
    )

    for label, pos, block_id in placements:
        await _action(connection, f"{name}-place-{label}", "place_block", {**pos, "block": block_id})

    await _action(connection, f"{name}-settle", "wait_ticks", {"ticks": 15}, timeout=5.0)

    left_cfg = await _action(
        connection,
        f"{name}-left-mode",
        "mek_set_transporter_mode",
        {**left_pull, "side": "east", "mode": "PULL"},
    )
    right_cfg = await _action(
        connection,
        f"{name}-right-mode",
        "mek_set_transporter_mode",
        {**right_pull, "side": "west", "mode": "PULL"},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: CONFIG left={left_cfg.get('after')} right={right_cfg.get('after')}"
    ))

    seeded = await _action(
        connection,
        f"{name}-seed",
        "seed_item",
        {**source, "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: seeded={seeded.get('inserted')}/6; benchmarking live flow..."
    ))

    await _action(connection, f"{name}-wait", "wait_ticks", {"ticks": 200}, timeout=18.0)

    return {
        "source": await _action(connection, f"{name}-source", "read_inventory", source),
        "left": await _action(connection, f"{name}-left", "read_inventory", left_sink),
        "right": await _action(connection, f"{name}-right", "read_inventory", right_sink),
        "drain_positions": [("source", source), ("left", left_sink), ("right", right_sink)],
        "topology": candidate.family,
        "candidate": candidate.as_dict(),
        "actual_blocks": len(placements),
    }


async def _build_generated_candidate(
    connection: ServerConnection,
    candidate: TopologyCandidate,
) -> dict[str, Any]:
    if candidate.family == "shared_t":
        observed = await _build_splitter_variant_a(connection, candidate.candidate_id)
        observed["candidate"] = candidate.as_dict()
        observed["actual_blocks"] = 7
        return observed
    if candidate.family == "dual_independent_pull":
        return await _build_generated_dual_pull_candidate(connection, candidate)
    raise RuntimeError(f"unsupported generated topology family: {candidate.family}")


def _score_topology_result(
    *,
    source_n: int,
    left_n: int,
    right_n: int,
    block_count: int,
) -> tuple[bool, int, int]:
    """Hard correctness first, then balance, then compactness."""
    total = source_n + left_n + right_n
    conserved = total == 6
    both_live = left_n > 0 and right_n > 0
    passed = conserved and source_n == 0 and both_live
    imbalance = abs(left_n - right_n)
    if not passed:
        # Keep failed candidates far below every valid candidate.
        return False, -1000 - imbalance - block_count, imbalance
    # Fairness is much more important than saving a block; compactness breaks ties.
    score = 1000 - imbalance * 100 - block_count
    return True, score, imbalance


async def _run_topology_search_session(connection: ServerConnection) -> None:
    """v0.8: generate candidates from memory, benchmark all, select the best, save v2 skill."""
    await connection.send(protocol.hello("yan-topology-search-v0.8"))

    candidates, source_skill = generate_two_branch_candidates()
    memory_status = "loaded" if source_skill is not None else "missing"
    await connection.send(protocol.chat(
        f"[yan-agent] v0.8 MEMORY: mekanism_two_branch_distribution_v1={memory_status}; "
        f"generatedCandidates={len(candidates)}"
    ))
    await connection.send(protocol.chat(
        "[yan-agent] v0.8 objective: benchmark ALL generated candidates; "
        "correctness > balance > compactness. Do not stop at first PASS."
    ))

    for candidate in candidates:
        await connection.send(protocol.chat(
            f"[yan-agent] GENERATED {candidate.candidate_id}: family={candidate.family} "
            f"source={candidate.source} armBlocks={candidate.arm_blocks} "
            f"estimatedBlocks={candidate.estimated_blocks}"
        ))

    # Union footprint for all generated candidates.
    footprint = [
        *({"x": x, "y": 3, "z": 0} for x in range(2, 11)),
        {"x": 6, "y": 2, "z": 0},
        *({"x": x, "y": 1, "z": 0} for x in range(4, 9)),
    ]

    history: list[dict[str, Any]] = []
    try:
        initial = await _action(
            connection,
            "search-footprint",
            "inspect_blocks",
            {"positions": footprint},
        )
        occupied = [b for b in (initial.get("blocks") or []) if not b.get("is_air", False)]
        if occupied:
            raise RuntimeError(f"topology-search footprint is not empty: {occupied}")

        for index, candidate in enumerate(candidates, start=1):
            await connection.send(protocol.chat(
                f"[yan-agent] BENCHMARK {index}/{len(candidates)} {candidate.candidate_id}"
            ))
            observed = await _build_generated_candidate(connection, candidate)

            source_n = int(observed["source"].get("total_items") or 0)
            left_n = int(observed["left"].get("total_items") or 0)
            right_n = int(observed["right"].get("total_items") or 0)
            total = source_n + left_n + right_n
            conserved = total == 6
            block_count = int(observed.get("actual_blocks") or candidate.estimated_blocks)
            passed, score, imbalance = _score_topology_result(
                source_n=source_n,
                left_n=left_n,
                right_n=right_n,
                block_count=block_count,
            )

            row = {
                **candidate.as_dict(),
                "source_items": source_n,
                "left_items": left_n,
                "right_items": right_n,
                "total": total,
                "conserved": conserved,
                "both_live": left_n > 0 and right_n > 0,
                "imbalance": imbalance,
                "actual_blocks": block_count,
                "score": score,
                "passed": passed,
            }
            history.append(row)
            await connection.send(protocol.chat(
                f"[yan-agent] RESULT {candidate.candidate_id}: source={source_n} left={left_n} "
                f"right={right_n} conserved={conserved} blocks={block_count} "
                f"imbalance={imbalance} score={score} pass={passed}"
            ))

            await _cleanup_splitter_variant(
                connection,
                name=candidate.candidate_id,
                drain_positions=observed["drain_positions"],
            )

        passing = [row for row in history if row["passed"]]
        if not passing:
            raise RuntimeError(f"all generated topology candidates failed: {history}")

        best = max(passing, key=lambda row: row["score"])
        await connection.send(protocol.chat(
            f"[yan-agent] SELECT BEST {best['candidate_id']}: score={best['score']} "
            f"left={best['left_items']} right={best['right_items']} "
            f"blocks={best['actual_blocks']} source={best['source']}"
        ))

        skill_path = save_skill(
            "mekanism_two_branch_distribution_v2",
            description=(
                "Best live-benchmarked two-branch Mekanism distribution topology selected "
                "from generated candidates using correctness, balance and compactness."
            ),
            implementation={
                "family": best["family"],
                "arm_blocks": best["arm_blocks"],
                "actual_blocks": best["actual_blocks"],
                "source_mode": "PULL",
                "selection_policy": "correctness > balance > compactness",
                "candidate_id": best["candidate_id"],
            },
            verification={
                "source": best["source_items"],
                "left": best["left_items"],
                "right": best["right_items"],
                "conserved": best["conserved"],
                "imbalance": best["imbalance"],
                "score": best["score"],
                "candidate_count": len(history),
                "all_results": history,
            },
            source_experiment="yan-topology-search-v0.8",
        )
        await connection.send(protocol.chat(
            f"[yan-agent] MEMORY: saved optimized skill {skill_path.name}; knownSkills={list_skills()}"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            await _action(connection, "search-emergency-rollback", "rollback_session", {})
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"topology search v0.8 FAIL: {exc}"))
        return

    await connection.send(protocol.finish(
        "topology search v0.8 PASS: "
        f"generated={len(candidates)} benchmarked={len(history)} "
        f"best={best['candidate_id']} family={best['family']} armBlocks={best['arm_blocks']} "
        f"left={best['left_items']} right={best['right_items']} "
        f"blocks={best['actual_blocks']} score={best['score']} "
        "skill=mekanism_two_branch_distribution_v2 worldClean=true"
    ))


def _axis_geometry(
    candidate: SpatialCandidate,
) -> dict[str, Any]:
    """Resolve one spatial candidate into exact relative coordinates and source-facing sides."""
    source = {"x": 6, "y": 4, "z": 0}
    if candidate.axis == "x":
        neg = (-1, 0)
        pos = (1, 0)
        neg_pull_side = "east"
        pos_pull_side = "west"
    elif candidate.axis == "z":
        neg = (0, -1)
        pos = (0, 1)
        neg_pull_side = "south"
        pos_pull_side = "north"
    else:
        raise RuntimeError(f"unsupported axis: {candidate.axis}")

    def point(dx: int, dz: int, distance: int, y: int = 4) -> dict[str, int]:
        return {
            "x": source["x"] + dx * distance,
            "y": y,
            "z": source["z"] + dz * distance,
        }

    left_pull = point(*neg, 1)
    right_pull = point(*pos, 1)
    left_arms = [point(*neg, distance) for distance in range(2, 2 + candidate.left_arm)]
    right_arms = [point(*pos, distance) for distance in range(2, 2 + candidate.right_arm)]

    left_end_distance = 1 + candidate.left_arm
    right_end_distance = 1 + candidate.right_arm

    if candidate.sink_drop:
        left_sink = point(*neg, left_end_distance, y=4 - candidate.sink_drop)
        right_sink = point(*pos, right_end_distance, y=4 - candidate.sink_drop)
    else:
        left_sink = point(*neg, left_end_distance + 1)
        right_sink = point(*pos, right_end_distance + 1)

    return {
        "source": source,
        "left_pull": left_pull,
        "right_pull": right_pull,
        "left_arms": left_arms,
        "right_arms": right_arms,
        "left_sink": left_sink,
        "right_sink": right_sink,
        "left_pull_side": neg_pull_side,
        "right_pull_side": pos_pull_side,
    }


async def _build_spatial_candidate(
    connection: ServerConnection,
    candidate: SpatialCandidate,
) -> dict[str, Any]:
    """Build one geometry mutation from the v2 primitive and observe real item flow."""
    if candidate.family == "shared_t":
        observed = await _build_splitter_variant_a(connection, candidate.candidate_id)
        observed["candidate"] = candidate.as_dict()
        observed["actual_blocks"] = 7
        return observed

    if candidate.family != "dual_independent_pull":
        raise RuntimeError(f"unsupported spatial family: {candidate.family}")

    name = candidate.candidate_id
    g = _axis_geometry(candidate)
    await connection.send(protocol.chat(
        f"[yan-agent] SPATIAL {name}: axis={candidate.axis} "
        f"leftArm={candidate.left_arm} rightArm={candidate.right_arm} "
        f"sinkDrop={candidate.sink_drop} extractors={candidate.extractor_count}"
    ))
    await connection.send(protocol.chat(f"[yan-agent] {name}: {candidate.description}"))

    placements: list[tuple[str, dict[str, int], str]] = [
        ("source", g["source"], "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ("left-pull", g["left_pull"], "mekanism:basic_logistical_transporter"),
        ("right-pull", g["right_pull"], "mekanism:basic_logistical_transporter"),
    ]
    placements.extend(
        (f"left-arm-{i + 1}", pos, "mekanism:basic_logistical_transporter")
        for i, pos in enumerate(g["left_arms"])
    )
    placements.extend(
        (f"right-arm-{i + 1}", pos, "mekanism:basic_logistical_transporter")
        for i, pos in enumerate(g["right_arms"])
    )
    placements.extend(
        [
            ("left-sink", g["left_sink"], "minecraft:chest[facing=north,type=single,waterlogged=false]"),
            ("right-sink", g["right_sink"], "minecraft:chest[facing=north,type=single,waterlogged=false]"),
        ]
    )

    for label, pos, block_id in placements:
        await _action(connection, f"{name}-place-{label}", "place_block", {**pos, "block": block_id})

    await _action(connection, f"{name}-settle", "wait_ticks", {"ticks": 15}, timeout=5.0)

    left_cfg = await _action(
        connection,
        f"{name}-left-mode",
        "mek_set_transporter_mode",
        {**g["left_pull"], "side": g["left_pull_side"], "mode": "PULL"},
    )
    right_cfg = await _action(
        connection,
        f"{name}-right-mode",
        "mek_set_transporter_mode",
        {**g["right_pull"], "side": g["right_pull_side"], "mode": "PULL"},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: CONFIG left={left_cfg.get('after')}({g['left_pull_side']}) "
        f"right={right_cfg.get('after')}({g['right_pull_side']})"
    ))

    seeded = await _action(
        connection,
        f"{name}-seed",
        "seed_item",
        {**g["source"], "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {name}: seeded={seeded.get('inserted')}/6; observing transformed geometry..."
    ))
    await _action(connection, f"{name}-wait", "wait_ticks", {"ticks": 140}, timeout=15.0)

    return {
        "source": await _action(connection, f"{name}-source", "read_inventory", g["source"]),
        "left": await _action(connection, f"{name}-left", "read_inventory", g["left_sink"]),
        "right": await _action(connection, f"{name}-right", "read_inventory", g["right_sink"]),
        "drain_positions": [
            ("source", g["source"]),
            ("left", g["left_sink"]),
            ("right", g["right_sink"]),
        ],
        "topology": candidate.family,
        "candidate": candidate.as_dict(),
        "actual_blocks": len(placements),
        "geometry": g,
    }


def _score_spatial_result(
    *,
    source_n: int,
    left_n: int,
    right_n: int,
    candidate: SpatialCandidate,
    block_count: int,
) -> tuple[bool, int, int]:
    """Correctness first, then fairness, material cost, then spatial compactness."""
    total = source_n + left_n + right_n
    conserved = total == 6
    both_live = left_n > 0 and right_n > 0
    passed = conserved and source_n == 0 and both_live
    imbalance = abs(left_n - right_n)
    if not passed:
        return False, -10000 - imbalance * 100 - block_count * 10, imbalance

    spatial_penalty = candidate.horizontal_span * 2 + max(0, candidate.vertical_span - 1) * 3
    score = 10000 - imbalance * 1000 - block_count * 20 - spatial_penalty
    return True, score, imbalance


async def _run_spatial_search_session(connection: ServerConnection) -> None:
    """v0.9: search rotations, asymmetric lengths and vertical forms from the v2 skill."""
    await connection.send(protocol.hello("yan-spatial-search-v0.9"))

    candidates, source_skill = generate_spatial_candidates()
    await connection.send(protocol.chat(
        f"[yan-agent] v0.9 MEMORY: mekanism_two_branch_distribution_v2="
        f"{'loaded' if source_skill else 'missing'}; spatialCandidates={len(candidates)}"
    ))
    await connection.send(protocol.chat(
        "[yan-agent] v0.9 objective: test geometric transformations of a verified skill. "
        "Priority = correctness > balance > material cost > spatial compactness."
    ))

    for candidate in candidates:
        await connection.send(protocol.chat(
            f"[yan-agent] GENERATED {candidate.candidate_id}: family={candidate.family} "
            f"axis={candidate.axis} arms={candidate.left_arm}/{candidate.right_arm} "
            f"drop={candidate.sink_drop} extractors={candidate.extractor_count} "
            f"blocks~{candidate.estimated_blocks}"
        ))

    # Broad union envelope for all v0.9 forms plus the old shared-T control.
    footprint = [
        {"x": x, "y": y, "z": z}
        for x in range(2, 11)
        for y in range(1, 5)
        for z in range(-4, 5)
    ]

    history: list[dict[str, Any]] = []
    try:
        initial = await _action(
            connection,
            "spatial-footprint",
            "inspect_blocks",
            {"positions": footprint},
        )
        occupied = [b for b in (initial.get("blocks") or []) if not b.get("is_air", False)]
        if occupied:
            raise RuntimeError(
                f"spatial-search footprint is not empty; occupied_count={len(occupied)} "
                f"sample={occupied[:8]}"
            )

        for index, candidate in enumerate(candidates, start=1):
            await connection.send(protocol.chat(
                f"[yan-agent] BENCHMARK {index}/{len(candidates)} {candidate.candidate_id}"
            ))
            observed = await _build_spatial_candidate(connection, candidate)

            source_n = int(observed["source"].get("total_items") or 0)
            left_n = int(observed["left"].get("total_items") or 0)
            right_n = int(observed["right"].get("total_items") or 0)
            total = source_n + left_n + right_n
            block_count = int(observed.get("actual_blocks") or candidate.estimated_blocks)
            passed, score, imbalance = _score_spatial_result(
                source_n=source_n,
                left_n=left_n,
                right_n=right_n,
                candidate=candidate,
                block_count=block_count,
            )

            row = {
                **candidate.as_dict(),
                "source_items": source_n,
                "left_items": left_n,
                "right_items": right_n,
                "total": total,
                "conserved": total == 6,
                "both_live": left_n > 0 and right_n > 0,
                "imbalance": imbalance,
                "actual_blocks": block_count,
                "score": score,
                "passed": passed,
            }
            history.append(row)

            await connection.send(protocol.chat(
                f"[yan-agent] RESULT {candidate.candidate_id}: source={source_n} "
                f"left={left_n} right={right_n} blocks={block_count} "
                f"imbalance={imbalance} score={score} pass={passed}"
            ))

            await _cleanup_splitter_variant(
                connection,
                name=candidate.candidate_id,
                drain_positions=observed["drain_positions"],
            )

        passing = [row for row in history if row["passed"]]
        if not passing:
            raise RuntimeError(f"all spatial candidates failed: {history}")

        best = max(passing, key=lambda row: row["score"])
        validated_transforms = [
            {
                "candidate_id": row["candidate_id"],
                "axis": row["axis"],
                "left_arm": row["left_arm"],
                "right_arm": row["right_arm"],
                "sink_drop": row["sink_drop"],
                "extractor_count": row["extractor_count"],
                "left": row["left_items"],
                "right": row["right_items"],
                "blocks": row["actual_blocks"],
                "score": row["score"],
            }
            for row in passing
        ]

        await connection.send(protocol.chat(
            f"[yan-agent] SELECT BEST {best['candidate_id']}: axis={best['axis']} "
            f"arms={best['left_arm']}/{best['right_arm']} drop={best['sink_drop']} "
            f"left={best['left_items']} right={best['right_items']} "
            f"blocks={best['actual_blocks']} score={best['score']}"
        ))
        await connection.send(protocol.chat(
            f"[yan-agent] ROBUSTNESS: {len(validated_transforms)}/{len(history)} "
            "spatial transforms preserved the functional contract."
        ))

        skill_path = save_skill(
            "mekanism_two_branch_distribution_v3",
            description=(
                "Spatially validated two-branch Mekanism distribution skill. "
                "Includes rotations, asymmetric branch lengths and vertical sink mutations."
            ),
            implementation={
                "family": best["family"],
                "axis": best["axis"],
                "left_arm": best["left_arm"],
                "right_arm": best["right_arm"],
                "sink_drop": best["sink_drop"],
                "extractor_count": best["extractor_count"],
                "actual_blocks": best["actual_blocks"],
                "source_mode": "PULL",
                "selection_policy": (
                    "correctness > balance > material cost > spatial compactness"
                ),
                "candidate_id": best["candidate_id"],
                "validated_transforms": validated_transforms,
            },
            verification={
                "source": best["source_items"],
                "left": best["left_items"],
                "right": best["right_items"],
                "conserved": best["conserved"],
                "imbalance": best["imbalance"],
                "score": best["score"],
                "candidate_count": len(history),
                "passing_count": len(passing),
                "all_results": history,
            },
            source_experiment="yan-spatial-search-v0.9",
        )
        await connection.send(protocol.chat(
            f"[yan-agent] MEMORY: saved spatial skill {skill_path.name}; knownSkills={list_skills()}"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            await _action(connection, "spatial-emergency-rollback", "rollback_session", {})
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"spatial search v0.9 FAIL: {exc}"))
        return

    await connection.send(protocol.finish(
        "spatial search v0.9 PASS: "
        f"generated={len(candidates)} benchmarked={len(history)} passing={len(passing)} "
        f"best={best['candidate_id']} axis={best['axis']} "
        f"arms={best['left_arm']}/{best['right_arm']} drop={best['sink_drop']} "
        f"left={best['left_items']} right={best['right_items']} "
        f"blocks={best['actual_blocks']} score={best['score']} "
        "skill=mekanism_two_branch_distribution_v3 worldClean=true"
    ))


def _pos_tuple(row: dict[str, Any]) -> tuple[int, int, int]:
    return int(row["x"]), int(row["y"]), int(row["z"])


def _pos_args(pos: tuple[int, int, int]) -> dict[str, int]:
    return {"x": pos[0], "y": pos[1], "z": pos[2]}


async def _scan_environment_scene(connection: ServerConnection) -> dict[str, Any]:
    """Discover the user's existing three-chest scene and all obstacles around it."""
    lo = (-6, -1, -6)
    hi = (6, 3, 6)
    positions = [
        {"x": x, "y": y, "z": z}
        for x in range(lo[0], hi[0] + 1)
        for y in range(lo[1], hi[1] + 1)
        for z in range(lo[2], hi[2] + 1)
    ]
    observed = await _action(
        connection,
        "env-scan",
        "inspect_blocks",
        {"positions": positions},
        timeout=20.0,
    )
    blocks = observed.get("blocks") or []
    chest_rows = [row for row in blocks if row.get("block") == "minecraft:chest"]
    if len(chest_rows) != 3:
        raise RuntimeError(
            f"scene requires exactly 3 minecraft:chest blocks inside scan volume; found {len(chest_rows)}"
        )

    inventories: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for index, row in enumerate(chest_rows, start=1):
        pos = _pos_tuple(row)
        inv = await _action(
            connection,
            f"env-identify-chest-{index}",
            "read_inventory",
            _pos_args(pos),
        )
        inventories.append((pos, inv))

    source_candidates: list[tuple[int, int, int]] = []
    empty: list[tuple[int, int, int]] = []
    for pos, inv in inventories:
        items = inv.get("items") or []
        raw_iron = sum(
            int(item.get("count") or 0)
            for item in items
            if item.get("item") == "minecraft:raw_iron"
        )
        total = int(inv.get("total_items") or 0)
        if total == 6 and raw_iron == 6:
            source_candidates.append(pos)
        elif total == 0:
            empty.append(pos)

    if len(source_candidates) != 1 or len(empty) != 2:
        raise RuntimeError(
            "scene contract not satisfied: need one chest containing exactly 6 raw iron "
            f"and two empty chests; sourceCandidates={source_candidates}, empty={empty}"
        )

    source = source_candidates[0]
    sinks = (empty[0], empty[1])
    endpoints = {source, *sinks}
    occupied = {
        _pos_tuple(row)
        for row in blocks
        if not row.get("is_air", False) and _pos_tuple(row) not in endpoints
    }

    return {
        "source": source,
        "sinks": sinks,
        "occupied": occupied,
        "bounds": (lo, hi),
        "scan_blocks": len(blocks),
        "obstacle_count": len(occupied),
    }


async def _place_environment_branch(
    connection: ServerConnection,
    *,
    branch: BranchRoute,
    label: str,
) -> None:
    for index, pos in enumerate(branch.path, start=1):
        await _action(
            connection,
            f"{label}-place-{index}",
            "place_block",
            {**_pos_args(pos), "block": "mekanism:basic_logistical_transporter"},
        )

    await _action(connection, f"{label}-settle", "wait_ticks", {"ticks": 10}, timeout=5.0)
    start = branch.path[0]
    configured = await _action(
        connection,
        f"{label}-pull",
        "mek_set_transporter_mode",
        {**_pos_args(start), "side": branch.source_side, "mode": "PULL"},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {label}: built length={len(branch.path)} "
        f"sourceSide={branch.source_side} mode={configured.get('after')}"
    ))


async def _remove_environment_branch(
    connection: ServerConnection,
    *,
    branch: BranchRoute,
    label: str,
) -> None:
    # Remove from the sink end backwards so the source extractor remains live until last.
    removed = 0
    for index, pos in enumerate(reversed(branch.path), start=1):
        try:
            result = await _action(
                connection,
                f"{label}-remove-{index}",
                "remove_block",
                _pos_args(pos),
            )
            if result.get("is_air"):
                removed += 1
        except RuntimeError as exc:
            await connection.send(protocol.chat(
                f"[yan-agent] {label}: remove warning at {pos}: {exc}"
            ))
    await connection.send(protocol.chat(
        f"[yan-agent] {label}: LOCAL REMOVE removed={removed}/{len(branch.path)}"
    ))


def _transit_positions(branches: list[BranchRoute]) -> list[dict[str, int]]:
    seen: set[tuple[int, int, int]] = set()
    result: list[dict[str, int]] = []
    for branch in branches:
        for pos in branch.path:
            if pos in seen:
                continue
            seen.add(pos)
            result.append(_pos_args(pos))
    return result


async def _read_environment_result(
    connection: ServerConnection,
    *,
    source: tuple[int, int, int],
    sinks: tuple[tuple[int, int, int], tuple[int, int, int]],
    branches: list[BranchRoute],
    label: str,
) -> dict[str, Any]:
    src = await _action(connection, f"{label}-read-source", "read_inventory", _pos_args(source))
    left = await _action(connection, f"{label}-read-sink-1", "read_inventory", _pos_args(sinks[0]))
    right = await _action(connection, f"{label}-read-sink-2", "read_inventory", _pos_args(sinks[1]))
    positions = _transit_positions(branches)
    transit = (
        await _action(
            connection,
            f"{label}-read-transit",
            "mek_read_transit",
            {"positions": positions},
        )
        if positions
        else {"total_items": 0, "stack_count": 0, "items": []}
    )

    source_n = int(src.get("total_items") or 0)
    left_n = int(left.get("total_items") or 0)
    right_n = int(right.get("total_items") or 0)
    transit_n = int(transit.get("total_items") or 0)
    total = source_n + left_n + right_n + transit_n
    passed = (
        source_n == 0
        and left_n > 0
        and right_n > 0
        and transit_n == 0
        and total == 6
    )
    return {
        "source": source_n,
        "left": left_n,
        "right": right_n,
        "transit": transit_n,
        "transit_stacks": int(transit.get("stack_count") or 0),
        "transit_items": transit.get("items") or [],
        "total": total,
        "conserved": total == 6,
        "passed": passed,
        "imbalance": abs(left_n - right_n),
    }


async def _reset_environment_items(
    connection: ServerConnection,
    *,
    source: tuple[int, int, int],
    sinks: tuple[tuple[int, int, int], tuple[int, int, int]],
    branches: list[BranchRoute],
    label: str,
) -> None:
    positions = _transit_positions(branches)
    cleared_transit = 0
    cleared_stacks = 0
    if positions:
        cleared = await _action(
            connection,
            f"{label}-clear-transit",
            "mek_clear_transit",
            {"positions": positions},
        )
        cleared_transit = int(cleared.get("cleared_items") or 0)
        cleared_stacks = int(cleared.get("cleared_stacks") or 0)

    drained_items = 0
    for role, pos in (("source", source), ("sink-1", sinks[0]), ("sink-2", sinks[1])):
        drained = await _action(
            connection,
            f"{label}-drain-{role}",
            "drain_inventory",
            {**_pos_args(pos), "item": "minecraft:raw_iron"},
        )
        drained_items += int(drained.get("removed_total") or 0)

    accounted = cleared_transit + drained_items
    if accounted != 6:
        raise RuntimeError(
            f"{label}: reset conservation failure before reseed: "
            f"transit={cleared_transit} inventories={drained_items} accounted={accounted} expected=6"
        )

    seeded = await _action(
        connection,
        f"{label}-reseed",
        "seed_item",
        {**_pos_args(source), "item": "minecraft:raw_iron", "count": 6},
    )
    await connection.send(protocol.chat(
        f"[yan-agent] {label}: RESET TRANSIT-AWARE "
        f"transitItems={cleared_transit} transitStacks={cleared_stacks} "
        f"inventoryItems={drained_items} accounted={accounted}/6 "
        f"reseeded={seeded.get('inserted')}/6"
    ))


async def _run_environment_build_session(connection: ServerConnection) -> None:
    """v1.2: transit-aware environment repair with exact conservation."""
    await connection.send(protocol.hello("yan-transit-aware-v1.2"))
    await connection.send(protocol.chat(
        "[yan-agent] v1.2: scanning existing world with transporter-transit accounting enabled."
    ))

    skill = load_skill("mekanism_two_branch_distribution_v3")
    if skill is None:
        await connection.send(protocol.error(
            "environment builder v1.0 requires verified skill mekanism_two_branch_distribution_v3"
        ))
        return
    implementation = skill.get("implementation") or {}
    if int(implementation.get("extractor_count") or 0) != 2:
        await connection.send(protocol.error(
            "v3 skill is incompatible: expected extractor_count=2"
        ))
        return

    scene: dict[str, Any] | None = None
    active_branches: list[BranchRoute] = []
    repair_count = 0
    plan_history: list[dict[str, Any]] = []

    try:
        scene = await _scan_environment_scene(connection)
        source = scene["source"]
        sinks = scene["sinks"]
        occupied = scene["occupied"]
        bounds = scene["bounds"]

        await connection.send(protocol.chat(
            f"[yan-agent] SCENE: source={source} sinks={sinks} "
            f"obstacles={scene['obstacle_count']} scanned={scene['scan_blocks']}"
        ))
        await connection.send(protocol.chat(
            "[yan-agent] MEMORY: using v3 primitive = two independent PULL extractors; "
            "geometry will be planned from observed free space."
        ))

        plans = generate_route_plans(
            source=source,
            sinks=sinks,
            occupied=occupied,
            bounds=bounds,
            max_plans=5,
        )
        if not plans:
            raise RuntimeError("planner found no pair of routes from source to both sinks")

        for plan in plans:
            await connection.send(protocol.chat(
                f"[yan-agent] PLAN {plan.plan_id}: mode={plan.mode} cost={plan.cost} "
                f"lengths={[len(branch.path) for branch in plan.branches]}"
            ))

        # Start with the cheapest naive plan so live feedback, not only geometry,
        # determines whether the two Mekanism networks are actually independent.
        current_plan = plans[0]
        await connection.send(protocol.chat(
            f"[yan-agent] BUILD PLAN {current_plan.plan_id}: preserving all existing obstacles/endpoints."
        ))
        for index, branch in enumerate(current_plan.branches, start=1):
            await _place_environment_branch(
                connection,
                branch=branch,
                label=f"{current_plan.plan_id}-branch-{index}",
            )
            active_branches.append(branch)

        await _action(connection, "env-initial-flow", "wait_ticks", {"ticks": 180}, timeout=18.0)
        result = await _read_environment_result(
            connection, source=source, sinks=sinks, branches=active_branches, label="env-initial"
        )
        plan_history.append({"plan": current_plan.as_dict(), "result": result})
        await connection.send(protocol.chat(
            f"[yan-agent] OBSERVE initial: source={result['source']} "
            f"sink1={result['left']} sink2={result['right']} transit={result['transit']} "
            f"total={result['total']} conserved={result['conserved']} pass={result['passed']}"
        ))

        if not result["passed"]:
            starved = [
                index
                for index, count in enumerate((result["left"], result["right"]))
                if count == 0
            ]
            live = [
                index
                for index, count in enumerate((result["left"], result["right"]))
                if count > 0
            ]

            if len(starved) == 1 and len(live) == 1:
                failed_index = starved[0]
                working_index = live[0]
                failed_branch = active_branches[failed_index]
                working_branch = active_branches[working_index]

                await connection.send(protocol.chat(
                    f"[yan-agent] DIAGNOSE: sink{failed_index + 1} starved while "
                    f"sink{working_index + 1} is live. Keeping working branch and repairing only failed branch."
                ))
                await _reset_environment_items(
                    connection, source=source, sinks=sinks, branches=active_branches, label="env-local-repair"
                )
                await _remove_environment_branch(
                    connection,
                    branch=failed_branch,
                    label=f"failed-branch-{failed_index + 1}",
                )

                alternatives = replan_failed_branch(
                    source=source,
                    sink=sinks[failed_index],
                    occupied=occupied,
                    working_path=set(working_branch.path),
                    bounds=bounds,
                    avoid_paths=[set(failed_branch.path)],
                )
                if not alternatives:
                    raise RuntimeError("local repair planner found no alternative route for starved branch")

                repaired = False
                for alt_index, alternative in enumerate(alternatives[:3], start=1):
                    repair_count += 1
                    await connection.send(protocol.chat(
                        f"[yan-agent] LOCAL REPAIR {repair_count}: reroute only sink{failed_index + 1}; "
                        f"newLength={len(alternative.path)} sourceSide={alternative.source_side}"
                    ))
                    await _place_environment_branch(
                        connection,
                        branch=alternative,
                        label=f"repair-{repair_count}",
                    )
                    active_branches[failed_index] = alternative

                    await _action(
                        connection,
                        f"repair-{repair_count}-flow",
                        "wait_ticks",
                        {"ticks": 180},
                        timeout=18.0,
                    )
                    result = await _read_environment_result(
                        connection,
                        source=source,
                        sinks=sinks,
                        branches=active_branches,
                        label=f"repair-{repair_count}",
                    )
                    plan_history.append({
                        "repair": repair_count,
                        "branch": alternative.as_dict(),
                        "result": result,
                    })
                    await connection.send(protocol.chat(
                        f"[yan-agent] OBSERVE repair-{repair_count}: source={result['source']} "
                        f"sink1={result['left']} sink2={result['right']} transit={result['transit']} "
                        f"total={result['total']} conserved={result['conserved']} pass={result['passed']}"
                    ))
                    if result["passed"]:
                        repaired = True
                        break

                    await _reset_environment_items(
                        connection,
                        source=source,
                        sinks=sinks,
                        branches=active_branches,
                        label=f"repair-{repair_count}-reset",
                    )
                    await _remove_environment_branch(
                        connection,
                        branch=alternative,
                        label=f"repair-{repair_count}-failed",
                    )

                if not repaired:
                    raise RuntimeError("local repairs exhausted without activating both sinks")
            else:
                # If the failure is not a single-starved-branch case, use the best
                # skill-informed separated full plan as a fallback.
                await connection.send(protocol.chat(
                    "[yan-agent] DIAGNOSE: failure is not isolated to one branch; "
                    "falling back to a full skill-informed separated plan."
                ))
                await _reset_environment_items(
                    connection, source=source, sinks=sinks, branches=active_branches, label="env-full-replan"
                )
                rolled = await _action(connection, "env-full-rollback", "rollback_session", {})
                active_branches.clear()
                await connection.send(protocol.chat(
                    f"[yan-agent] FULL REPLAN rollback removed={rolled.get('removed')}"
                ))

                fallback = next((p for p in plans if p.mode == "separated"), None)
                if fallback is None:
                    raise RuntimeError("no separated fallback plan available")
                for index, branch in enumerate(fallback.branches, start=1):
                    await _place_environment_branch(
                        connection,
                        branch=branch,
                        label=f"fallback-branch-{index}",
                    )
                    active_branches.append(branch)
                await _action(connection, "env-fallback-flow", "wait_ticks", {"ticks": 180}, timeout=18.0)
                result = await _read_environment_result(
                    connection, source=source, sinks=sinks, branches=active_branches, label="env-fallback"
                )
                plan_history.append({"plan": fallback.as_dict(), "result": result})
                if not result["passed"]:
                    raise RuntimeError(f"separated fallback also failed: {result}")

        # PASS: deliberately preserve the built solution and the item distribution.
        successful_paths = [branch.as_dict() for branch in active_branches]
        skill_path = save_skill(
            "environment_transit_aware_repair_v1",
            description=(
                "Verified environment-aware Mekanism routing over user-provided endpoints and obstacles. "
                "Successful network is preserved in-world instead of rolled back."
            ),
            implementation={
                "base_skill": "mekanism_two_branch_distribution_v3",
                "source": list(source),
                "sinks": [list(s) for s in sinks],
                "paths": successful_paths,
                "repair_count": repair_count,
                "obstacle_count": scene["obstacle_count"],
                "planner": "A* with live-flow validation and local failed-branch repair",
            },
            verification={
                **result,
                "world_preserved": True,
                "plan_history": plan_history,
            },
            source_experiment="yan-transit-aware-v1.2",
        )
        await connection.send(protocol.chat(
            f"[yan-agent] ACCEPT: existing scene solved. Network preserved in world. "
            f"repairCount={repair_count} transitAware=true skill={skill_path.name}"
        ))
        await connection.send(protocol.finish(
            "transit-aware environment builder v1.2 PASS: "
            f"source={result['source']} sink1={result['left']} sink2={result['right']} "
            f"repairs={repair_count} obstacles={scene['obstacle_count']} "
            f"transit={result['transit']} conserved={result['conserved']} "
            "worldPreserved=true skill=environment_transit_aware_repair_v1"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            if scene is not None and active_branches:
                await _reset_environment_items(
                    connection,
                    source=scene["source"],
                    sinks=scene["sinks"],
                    branches=active_branches,
                    label="env-emergency-reset",
                )
            rolled = await _action(connection, "env-emergency-rollback", "rollback_session", {})
            await connection.send(protocol.chat(
                f"[yan-agent] EMERGENCY ROLLBACK removed={rolled.get('removed')}"
            ))
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"transit-aware environment builder v1.2 FAIL: {exc}"))


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
