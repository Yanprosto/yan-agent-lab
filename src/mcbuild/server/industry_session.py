"""YAN v3.0 goal-driven industrial mission.

The first supported goal composes two real Mekanism process stages:
18 raw iron -> 2 Enrichment Chambers -> 24 iron dust
24 iron dust -> 2 Energized Smelters -> 24 iron ingots

The important change is architectural: the session consumes a ProcessPlan instead
of being hard-wired to one machine layout.
"""

from __future__ import annotations

from typing import Any

from mcbuild.server import protocol
from mcbuild.server.mission_session import (
    FactoryLayout,
    _action,
    _configure_side,
    _configure_transporter_pull,
    _item_count,
    _layout,
    _place,
    _read_transit,
    _wait,
)
from mcbuild.server.process_plans import ProcessPlan, ProcessStage, resolve_process_plan
from mcbuild.server.skill_store import save_skill


async def _configure_energy_pull(connection, layout: FactoryLayout, prefix: str) -> None:
    await _action(
        connection,
        f"{prefix}-energy-pull-a",
        "mek_set_transmitter_mode",
        {**layout.energy_a.args(), "side": "south", "mode": "PULL"},
    )
    await _action(
        connection,
        f"{prefix}-energy-pull-b",
        "mek_set_transmitter_mode",
        {**layout.energy_b.args(), "side": "north", "mode": "PULL"},
    )


async def _place_power_module(connection, layout: FactoryLayout, prefix: str) -> None:
    cube = await _action(
        connection,
        f"{prefix}-cube",
        "place_mekanism_filled_energy_cube",
        layout.cube.args(),
    )
    await _place(connection, f"{prefix}-energy-a", layout.energy_a, "mekanism:basic_universal_cable")
    await _place(connection, f"{prefix}-energy-b", layout.energy_b, "mekanism:basic_universal_cable")
    await connection.send(protocol.chat(
        f"[yan-agent] {prefix} POWER: precharged cube energy={cube.get('internal_energy')}"
    ))


async def _place_transport_path(connection, prefix: str, path) -> None:
    for i, p in enumerate(path, start=1):
        await _place(
            connection,
            f"{prefix}-{i}",
            p,
            "mekanism:basic_logistical_transporter",
        )


async def _build_stage_cell(
    connection,
    layout: FactoryLayout,
    stage: ProcessStage,
    *,
    prefix: str,
    create_source: bool,
    create_sink: bool,
) -> None:
    if create_source:
        await _place(
            connection,
            f"{prefix}-source",
            layout.source,
            "minecraft:chest[facing=north,type=single,waterlogged=false]",
        )
    if create_sink:
        await _place(
            connection,
            f"{prefix}-sink",
            layout.sink,
            "minecraft:chest[facing=north,type=single,waterlogged=false]",
        )

    await _place(connection, f"{prefix}-machine-a", layout.smelter_a, stage.machine_block)
    await _place(connection, f"{prefix}-machine-b", layout.smelter_b, stage.machine_block)
    await _place_power_module(connection, layout, prefix)

    for name, path in (
        ("in-a", layout.in_a),
        ("in-b", layout.in_b),
        ("out-a", layout.out_a),
        ("out-b", layout.out_b),
        ("out-shared", layout.out_shared),
    ):
        await _place_transport_path(connection, f"{prefix}-{name}", path)

    await _wait(connection, f"{prefix}-settle", 20, 8.0)

    for suffix, machine, energy_side in (
        ("a", layout.smelter_a, "south"),
        ("b", layout.smelter_b, "north"),
    ):
        await _configure_side(
            connection,
            f"{prefix}-{suffix}-item-in",
            machine,
            transmission="ITEM",
            side="west",
            mode="INPUT",
        )
        await _configure_side(
            connection,
            f"{prefix}-{suffix}-item-out",
            machine,
            transmission="ITEM",
            side="east",
            mode="OUTPUT",
        )
        await _configure_side(
            connection,
            f"{prefix}-{suffix}-energy",
            machine,
            transmission="ENERGY",
            side=energy_side,
            mode="INPUT",
        )

    # Filled creative cube already carries ALL_OUTPUT, but retain explicit read/write
    # configuration so the stage contract remains self-describing and verifiable.
    await _configure_side(
        connection,
        f"{prefix}-cube-out-a",
        layout.cube,
        transmission="ENERGY",
        side="north",
        mode="OUTPUT",
    )
    await _configure_side(
        connection,
        f"{prefix}-cube-out-b",
        layout.cube,
        transmission="ENERGY",
        side="south",
        mode="OUTPUT",
    )
    await _configure_energy_pull(connection, layout, prefix)

    await _configure_transporter_pull(connection, f"{prefix}-input-pull-a", layout.in_a[0], "south")
    await _configure_transporter_pull(connection, f"{prefix}-input-pull-b", layout.in_b[0], "north")
    await _configure_transporter_pull(connection, f"{prefix}-output-pull-a", layout.out_a[0], "west")
    await _configure_transporter_pull(connection, f"{prefix}-output-pull-b", layout.out_b[0], "west")

    await connection.send(protocol.chat(
        f"[yan-agent] STAGE READY {stage.id}: machines=2 input={stage.input_item} output={stage.output_item}"
    ))


async def _verify_power(connection, layout: FactoryLayout, prefix: str) -> dict[str, int]:
    await _wait(connection, f"{prefix}-power-settle", 40, 8.0)
    cube = await _action(connection, f"{prefix}-cube-energy", "read_energy", layout.cube.args())
    a = await _action(
        connection,
        f"{prefix}-machine-a-energy",
        "read_energy",
        {**layout.smelter_a.args(), "side": "south"},
    )
    b = await _action(
        connection,
        f"{prefix}-machine-b-energy",
        "read_energy",
        {**layout.smelter_b.args(), "side": "north"},
    )
    result = {
        "cube": int(cube.get("energy") or 0),
        "a": int(a.get("energy") or 0),
        "b": int(b.get("energy") or 0),
    }
    if result["cube"] <= 0 or result["a"] <= 0 or result["b"] <= 0:
        raise RuntimeError(f"{prefix}: power contract failed {result}")
    await connection.send(protocol.chat(
        f"[yan-agent] VERIFY POWER {prefix}: cube={result['cube']} machines={result['a']}/{result['b']}"
    ))
    return result


async def _seed_material(connection, pos, item: str, count: int, label: str) -> None:
    seeded = await _action(
        connection,
        label,
        "seed_item",
        {**pos.args(), "item": item, "count": count},
    )
    inserted = int(seeded.get("inserted") or 0)
    if inserted != count:
        raise RuntimeError(f"{label}: inserted {inserted}/{count}")
    await connection.send(protocol.chat(
        f"[yan-agent] MATERIAL {label}: {count} x {item}"
    ))


async def _wait_stage_output(
    connection,
    layout: FactoryLayout,
    stage: ProcessStage,
    *,
    prefix: str,
    max_cycles: int,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    for cycle in range(1, max_cycles + 1):
        await _wait(connection, f"{prefix}-process-{cycle}", 200, 16.0)

        output_count, _ = await _item_count(
            connection,
            f"{prefix}-sink-{cycle}",
            layout.sink,
            stage.output_item,
        )
        source_count, _ = await _item_count(
            connection,
            f"{prefix}-source-{cycle}",
            layout.source,
            stage.input_item,
        )
        in_a, _ = await _item_count(
            connection,
            f"{prefix}-a-in-{cycle}",
            layout.smelter_a,
            stage.input_item,
            "west",
        )
        in_b, _ = await _item_count(
            connection,
            f"{prefix}-b-in-{cycle}",
            layout.smelter_b,
            stage.input_item,
            "west",
        )
        out_a, _ = await _item_count(
            connection,
            f"{prefix}-a-out-{cycle}",
            layout.smelter_a,
            stage.output_item,
            "east",
        )
        out_b, _ = await _item_count(
            connection,
            f"{prefix}-b-out-{cycle}",
            layout.smelter_b,
            stage.output_item,
            "east",
        )
        transit = await _read_transit(connection, layout, f"{prefix}-transit-{cycle}")
        transit_count = int(transit.get("total_items") or 0)

        row = {
            "cycle": cycle,
            "sink": output_count,
            "source": source_count,
            "machine_input": [in_a, in_b],
            "machine_output": [out_a, out_b],
            "transit": transit_count,
        }
        history.append(row)
        await connection.send(protocol.chat(
            f"[yan-agent] STAGE {stage.id} {cycle}: sink={output_count}/{stage.output_count} "
            f"source={source_count} machineIn={in_a}/{in_b} machineOut={out_a}/{out_b} transit={transit_count}"
        ))

        if (
            output_count == stage.output_count
            and source_count == 0
            and in_a == 0
            and in_b == 0
            and out_a == 0
            and out_b == 0
            and transit_count == 0
        ):
            return {"cycles": cycle, "history": history}

    raise RuntimeError(f"{prefix}: stage timeout history={history}")


async def _inspect_footprint(connection, layouts: list[FactoryLayout]) -> None:
    positions = []
    seen: set[tuple[int, int, int]] = set()
    for layout in layouts:
        for p in layout.footprint:
            key = (p.x, p.y, p.z)
            if key not in seen:
                seen.add(key)
                positions.append(p.args())

    observed = await _action(
        connection,
        "industry-site-scan",
        "inspect_blocks",
        {"positions": positions},
    )
    occupied = [row for row in (observed.get("blocks") or []) if not row.get("is_air", False)]
    if occupied:
        sample = occupied[:5]
        raise RuntimeError(
            f"industrial footprint occupied: {len(occupied)} cells; sample={sample}"
        )
    await connection.send(protocol.chat(
        f"[yan-agent] SITE: industrial footprint clear, cells={len(positions)}"
    ))


async def run_industry_session(goal: str, connection) -> None:
    plan: ProcessPlan
    try:
        plan = resolve_process_plan(goal)
    except ValueError as exc:
        await connection.send(protocol.error(str(exc)))
        return

    await connection.send(protocol.hello("yan-goal-industry-v3.0"))
    await connection.send(protocol.chat(
        f"[yan-agent] GOAL: {goal or plan.title}"
    ))
    await connection.send(protocol.chat(
        f"[yan-agent] PLAN {plan.id}: "
        + " -> ".join(
            f"{stage.machines}x {stage.machine_block.split(':')[-1]}"
            for stage in plan.stages
        )
        + f" | {plan.source_count} {plan.source_item} -> {plan.final_count} {plan.final_item}"
    ))

    stage1 = _layout(0, 0)
    stage2 = _layout(8, 0)

    try:
        await _inspect_footprint(connection, [stage1, stage2])

        await _build_stage_cell(
            connection,
            stage1,
            plan.stages[0],
            prefix="industry-enrich",
            create_source=True,
            create_sink=True,
        )
        await _build_stage_cell(
            connection,
            stage2,
            plan.stages[1],
            prefix="industry-smelt",
            create_source=False,
            create_sink=True,
        )

        power1 = await _verify_power(connection, stage1, "industry-enrich")
        power2 = await _verify_power(connection, stage2, "industry-smelt")

        await _seed_material(
            connection,
            stage1.source,
            plan.source_item,
            plan.source_count,
            "industry-seed-raw",
        )

        first = await _wait_stage_output(
            connection,
            stage1,
            plan.stages[0],
            prefix="industry-enrich",
            max_cycles=8,
        )

        intermediate, _ = await _item_count(
            connection,
            "industry-intermediate-ready",
            stage1.sink,
            plan.stages[0].output_item,
        )
        if intermediate != plan.stages[0].output_count:
            raise RuntimeError(
                f"intermediate buffer mismatch {intermediate}/{plan.stages[0].output_count}"
            )
        await connection.send(protocol.chat(
            f"[yan-agent] HANDOFF: stage1 complete; intermediate={intermediate} {plan.stages[0].output_item}. "
            "Stage2 consumes the same physical buffer."
        ))

        second = await _wait_stage_output(
            connection,
            stage2,
            plan.stages[1],
            prefix="industry-smelt",
            max_cycles=15,
        )

        final_count, _ = await _item_count(
            connection,
            "industry-final-output",
            stage2.sink,
            plan.final_item,
        )
        intermediate_left, _ = await _item_count(
            connection,
            "industry-final-intermediate",
            stage2.source,
            plan.stages[1].input_item,
        )
        transit1 = await _read_transit(connection, stage1, "industry-final-transit-1")
        transit2 = await _read_transit(connection, stage2, "industry-final-transit-2")
        transit_total = int(transit1.get("total_items") or 0) + int(transit2.get("total_items") or 0)

        if final_count != plan.final_count or intermediate_left != 0 or transit_total != 0:
            raise RuntimeError(
                f"final contract failed output={final_count}/{plan.final_count} "
                f"intermediateLeft={intermediate_left} transit={transit_total}"
            )

        skill_path = save_skill(
            "goal_driven_iron_processing_district_v1",
            description=(
                "Goal-resolved two-stage Mekanism industrial process graph: "
                "raw iron -> enrichment -> iron dust -> smelting -> iron ingots."
            ),
            implementation={
                "goal": goal or plan.title,
                "plan_id": plan.id,
                "stages": [
                    {
                        "id": stage.id,
                        "machine_block": stage.machine_block,
                        "machines": stage.machines,
                        "input": [stage.input_item, stage.input_count],
                        "output": [stage.output_item, stage.output_count],
                    }
                    for stage in plan.stages
                ],
                "shared_intermediate_buffer": True,
                "world_preserved": True,
            },
            verification={
                "power": {"stage1": power1, "stage2": power2},
                "stage1": first,
                "stage2": second,
                "final_output": final_count,
                "transit": transit_total,
            },
            source_experiment="yan-goal-industry-v3.0",
        )

        await connection.send(protocol.chat(
            f"[yan-agent] ACCEPT INDUSTRY: plan={plan.id} output={final_count} "
            f"skill={skill_path.name}"
        ))
        await connection.send(protocol.finish(
            f"goal industry v3.0 PASS: plan={plan.id} stages=2 machines=4 "
            f"raw={plan.source_count} final={final_count} transit={transit_total} "
            "worldPreserved=true skill=goal_driven_iron_processing_district_v1"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            rolled = await _action(connection, "industry-emergency-rollback", "rollback_session", {})
            await connection.send(protocol.chat(
                f"[yan-agent] INDUSTRY ROLLBACK removed={rolled.get('removed')} "
                f"trackedAfter={rolled.get('tracked_after')}"
            ))
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"goal industry v3.0 FAIL: {exc}"))
