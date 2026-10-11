"""Execute the compiled architecture, rather than a fixed four-cell mission."""

import contextlib
import json

from mcbuild.server import protocol
from mcbuild.server.industrial_build_plan import compile_industrial_plan
from mcbuild.server.industrial_planner import rank_iron_works_candidates
from mcbuild.server.industry_session import (
    _action,
    _build_stage_cell,
    _configure_transporter_pull,
    _seed_material,
    _verify_power,
    _wait_stage_output,
)
from mcbuild.server.mission_session import _item_count, _read_transit
from mcbuild.server.skill_store import save_skill


async def select_build_plan(connection, candidates):
    """Reject occupied layouts before mutation; try other sites and architectures."""
    for candidate in candidates:
        for dx, dz in ((0, 0), (0, 30), (-24, 0), (-24, 30)):
            plan = compile_industrial_plan(candidate, dx, dz)
            result = await _action(
                connection,
                f"scan-{candidate.id}-{dx}-{dz}",
                "inspect_blocks",
                {"positions": [p.args() for p in plan.footprint]},
            )
            rows = result.get("blocks") or []
            # Missing observations must never be treated as empty space.
            observed = {(r.get("x"), r.get("y"), r.get("z")) for r in rows if r.get("is_air") is True}
            expected = {(p.x, p.y, p.z) for p in plan.footprint}
            if expected <= observed:
                return plan
            await connection.send(protocol.chat(f"[yan-agent] REJECT SITE {candidate.id} offset={dx}/{dz}"))
    raise RuntimeError("no fully observed free layout among candidate sites")


async def run_iron_works_session(goal, connection):
    await connection.send(protocol.hello("yan-plan-compiler-v4.1"))
    mutated = False
    try:
        candidates = rank_iron_works_candidates(goal=goal)
        for c in candidates:
            await connection.send(protocol.chat(f"[yan-agent] CANDIDATE {c.id}: score={c.score}"))
        plan = await select_build_plan(connection, candidates)
        await connection.send(protocol.chat("[yan-agent] BUILD PLAN " + json.dumps(plan.as_dict())))
        power, production = {}, {}
        for cell in plan.cells:
            mutated = True
            await _build_stage_cell(
                connection,
                cell.layout,
                cell.stage,
                prefix=cell.id,
                create_source=cell.upstream is None,
                create_sink=True,
                activate_input=cell.upstream is None,
            )
            power[cell.id] = await _verify_power(connection, cell.layout, cell.id)
        pending = {cell.id: cell for cell in plan.cells}
        completed = set()
        while pending:
            wave = [cell for cell in pending.values() if cell.upstream is None or cell.upstream in completed]
            if not wave:
                raise ValueError("cyclic or unresolved process dependency")
            # Start every independent cell before waiting for any production.
            # Bridge requests remain serial: a single WebSocket has one observation stream.
            for cell in wave:
                if cell.upstream:
                    await _configure_transporter_pull(connection, f"{cell.id}-handoff-a", cell.layout.in_a[0], "south")
                    await _configure_transporter_pull(connection, f"{cell.id}-handoff-b", cell.layout.in_b[0], "north")
                else:
                    await _seed_material(
                        connection, cell.layout.source, cell.stage.input_item, cell.stage.input_count, f"{cell.id}-seed"
                    )
            await connection.send(protocol.chat(f"[yan-agent] PRODUCTION WAVE: {[c.id for c in wave]}"))
            for cell in wave:
                production[cell.id] = await _wait_stage_output(
                    connection,
                    cell.layout,
                    cell.stage,
                    prefix=cell.id,
                    max_cycles=30,
                    check_before_wait=True,
                )
                completed.add(cell.id)
                del pending[cell.id]
        final, transit, remaining = 0, 0, 0
        for cell in plan.cells:
            if cell.stage.output_item == "minecraft:iron_ingot":
                count, _ = await _item_count(connection, f"{cell.id}-final", cell.layout.sink, cell.stage.output_item)
                final += count
            count, _ = await _item_count(connection, f"{cell.id}-remaining", cell.layout.source, cell.stage.input_item)
            remaining += count
            transit += int((await _read_transit(connection, cell.layout, f"{cell.id}-transit")).get("total_items") or 0)
        if final != plan.candidate.final_output or remaining or transit:
            raise RuntimeError(f"final balance: output={final} remaining={remaining} transit={transit}")
        save_skill(
            "compiled_iron_works_v1",
            description="Compiled architecture verified in Minecraft",
            implementation=plan.as_dict(),
            verification={"power": power, "production": production, "final": final, "transit": transit},
            source_experiment="yan-plan-compiler-v4.1",
        )
        await connection.send(
            protocol.finish(
                f"compiled factory PASS: candidate={plan.candidate.id} "
                f"machines={plan.candidate.machine_count} final={final} worldPreserved=true"
            )
        )
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        if mutated:
            with contextlib.suppress(RuntimeError):
                await _action(connection, "compiled-factory-rollback", "rollback_session", {})
        await connection.send(protocol.error(f"compiled factory FAIL: {exc}"))
