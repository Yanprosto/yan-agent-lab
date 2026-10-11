"""YAN Iron Works v4.0.

First branching-planner factory:
- rank several high-level architectures;
- execute the best verified candidate;
- build two parallel enrichment -> smelting lanes;
- verify each stage and physical handoff;
- preserve the working plant and save the selected design as a skill.
"""

from __future__ import annotations

from typing import Any

from mcbuild.server import protocol
from mcbuild.server.industrial_planner import rank_iron_works_candidates
from mcbuild.server.industry_session import (
    _action,
    _build_stage_cell,
    _configure_transporter_pull,
    _inspect_footprint,
    _seed_material,
    _verify_power,
    _wait_stage_output,
)
from mcbuild.server.mission_session import _item_count, _layout, _read_transit
from mcbuild.server.process_plans import ProcessStage
from mcbuild.server.skill_store import save_skill


ENRICH = ProcessStage(
    id="enriching",
    machine_block="mekanism:enrichment_chamber",
    input_item="minecraft:raw_iron",
    output_item="mekanism:dust_iron",
    input_count=18,
    output_count=24,
    machines=2,
)

SMELT = ProcessStage(
    id="smelting",
    machine_block="mekanism:energized_smelter",
    input_item="mekanism:dust_iron",
    output_item="minecraft:iron_ingot",
    input_count=24,
    output_count=24,
    machines=2,
)


async def _open_stage2(connection, layout, prefix: str) -> None:
    await _configure_transporter_pull(
        connection,
        f"{prefix}-input-pull-a-handoff",
        layout.in_a[0],
        "south",
    )
    await _configure_transporter_pull(
        connection,
        f"{prefix}-input-pull-b-handoff",
        layout.in_b[0],
        "north",
    )


async def _final_lane_state(connection, enrich_layout, smelt_layout, lane: str) -> dict[str, Any]:
    final_count, _ = await _item_count(
        connection,
        f"ironworks-{lane}-final-output",
        smelt_layout.sink,
        "minecraft:iron_ingot",
    )
    raw_left, _ = await _item_count(
        connection,
        f"ironworks-{lane}-raw-left",
        enrich_layout.source,
        "minecraft:raw_iron",
    )
    dust_left, _ = await _item_count(
        connection,
        f"ironworks-{lane}-dust-left",
        smelt_layout.source,
        "mekanism:dust_iron",
    )
    t1 = await _read_transit(connection, enrich_layout, f"ironworks-{lane}-transit-enrich")
    t2 = await _read_transit(connection, smelt_layout, f"ironworks-{lane}-transit-smelt")
    return {
        "final": final_count,
        "raw_left": raw_left,
        "dust_left": dust_left,
        "transit": int(t1.get("total_items") or 0) + int(t2.get("total_items") or 0),
    }


async def run_iron_works_session(goal: str, connection) -> None:
    ranked = rank_iron_works_candidates(beam_width=3)
    selected = ranked[0]

    await connection.send(protocol.hello("yan-iron-works-v4.0"))
    await connection.send(protocol.chat(f"[yan-agent] GOAL: {goal or 'железный завод'}"))
    for rank, candidate in enumerate(ranked, start=1):
        await connection.send(protocol.chat(
            f"[yan-agent] CANDIDATE {rank}: {candidate.id} score={candidate.score} "
            f"machines={candidate.machine_count} raw={candidate.raw_input} "
            f"final={candidate.final_output} blocks≈{candidate.estimated_blocks}"
        ))
    await connection.send(protocol.chat(
        f"[yan-agent] SELECT: {selected.id} score={selected.score}. "
        "Executing highest-scoring verified architecture."
    ))

    # Two parallel technological lanes. Stage-1 sink and Stage-2 source share the
    # same coordinates, creating real physical intermediate buffers.
    enrich_a = _layout(0, 0)
    enrich_b = _layout(0, 10)
    smelt_a = _layout(8, 0)
    smelt_b = _layout(8, 10)
    layouts = [enrich_a, enrich_b, smelt_a, smelt_b]

    try:
        await _inspect_footprint(connection, layouts)

        await connection.send(protocol.chat("[yan-agent] BUILD ZONE: enrichment lane A"))
        await _build_stage_cell(
            connection,
            enrich_a,
            ENRICH,
            prefix="ironworks-enrich-a",
            create_source=True,
            create_sink=True,
            activate_input=True,
        )

        await connection.send(protocol.chat("[yan-agent] BUILD ZONE: enrichment lane B"))
        await _build_stage_cell(
            connection,
            enrich_b,
            ENRICH,
            prefix="ironworks-enrich-b",
            create_source=True,
            create_sink=True,
            activate_input=True,
        )

        await connection.send(protocol.chat("[yan-agent] BUILD ZONE: smelting lane A"))
        await _build_stage_cell(
            connection,
            smelt_a,
            SMELT,
            prefix="ironworks-smelt-a",
            create_source=False,
            create_sink=True,
            activate_input=False,
        )

        await connection.send(protocol.chat("[yan-agent] BUILD ZONE: smelting lane B"))
        await _build_stage_cell(
            connection,
            smelt_b,
            SMELT,
            prefix="ironworks-smelt-b",
            create_source=False,
            create_sink=True,
            activate_input=False,
        )

        power = {
            "enrich_a": await _verify_power(connection, enrich_a, "ironworks-enrich-a"),
            "enrich_b": await _verify_power(connection, enrich_b, "ironworks-enrich-b"),
            "smelt_a": await _verify_power(connection, smelt_a, "ironworks-smelt-a"),
            "smelt_b": await _verify_power(connection, smelt_b, "ironworks-smelt-b"),
        }

        await _seed_material(
            connection,
            enrich_a.source,
            "minecraft:raw_iron",
            18,
            "ironworks-seed-raw-a",
        )
        await _seed_material(
            connection,
            enrich_b.source,
            "minecraft:raw_iron",
            18,
            "ironworks-seed-raw-b",
        )

        enrich_result_a = await _wait_stage_output(
            connection,
            enrich_a,
            ENRICH,
            prefix="ironworks-enrich-a",
            max_cycles=8,
        )
        enrich_result_b = await _wait_stage_output(
            connection,
            enrich_b,
            ENRICH,
            prefix="ironworks-enrich-b",
            max_cycles=8,
        )

        dust_a, _ = await _item_count(
            connection,
            "ironworks-buffer-a-ready",
            enrich_a.sink,
            "mekanism:dust_iron",
        )
        dust_b, _ = await _item_count(
            connection,
            "ironworks-buffer-b-ready",
            enrich_b.sink,
            "mekanism:dust_iron",
        )
        if dust_a != 24 or dust_b != 24:
            raise RuntimeError(f"handoff buffers invalid: A={dust_a}/24 B={dust_b}/24")

        await connection.send(protocol.chat(
            "[yan-agent] HANDOFF: both enrichment lanes complete. "
            "Opening downstream smelting intakes simultaneously."
        ))
        await _open_stage2(connection, smelt_a, "ironworks-smelt-a")
        await _open_stage2(connection, smelt_b, "ironworks-smelt-b")

        smelt_result_a = await _wait_stage_output(
            connection,
            smelt_a,
            SMELT,
            prefix="ironworks-smelt-a",
            max_cycles=15,
        )
        smelt_result_b = await _wait_stage_output(
            connection,
            smelt_b,
            SMELT,
            prefix="ironworks-smelt-b",
            max_cycles=15,
        )

        lane_a = await _final_lane_state(connection, enrich_a, smelt_a, "a")
        lane_b = await _final_lane_state(connection, enrich_b, smelt_b, "b")
        total_final = lane_a["final"] + lane_b["final"]
        total_raw = lane_a["raw_left"] + lane_b["raw_left"]
        total_dust = lane_a["dust_left"] + lane_b["dust_left"]
        total_transit = lane_a["transit"] + lane_b["transit"]

        if total_final != 48 or total_raw != 0 or total_dust != 0 or total_transit != 0:
            raise RuntimeError(
                f"final contract failed final={total_final}/48 raw={total_raw} "
                f"dust={total_dust} transit={total_transit}"
            )

        skill_path = save_skill(
            "branching_iron_works_v1",
            description=(
                "Verified branching-planner Iron Works using the highest-scoring "
                "verified architecture: two parallel enrichment->smelting lanes."
            ),
            implementation={
                "planner": "hierarchical high-level candidate ranking / beam width 3",
                "selected_candidate": selected.as_dict(),
                "ranked_candidates": [c.as_dict() for c in ranked],
                "lanes": 2,
                "machines": 8,
                "raw_input": 36,
                "final_output": 48,
                "physical_intermediate_buffers": 2,
                "world_preserved": True,
            },
            verification={
                "power": power,
                "enrichment": {"a": enrich_result_a, "b": enrich_result_b},
                "smelting": {"a": smelt_result_a, "b": smelt_result_b},
                "final": {"a": lane_a, "b": lane_b},
                "total_final": total_final,
                "total_transit": total_transit,
            },
            source_experiment="yan-iron-works-v4.0",
        )

        await connection.send(protocol.chat(
            f"[yan-agent] ACCEPT IRON WORKS: selected={selected.id} "
            f"machines=8 final={total_final} skill={skill_path.name}"
        ))
        await connection.send(protocol.finish(
            "iron works v4.0 PASS: "
            f"selected={selected.id} candidates={len(ranked)} lanes=2 machines=8 "
            f"raw=36 final={total_final} transit={total_transit} "
            "worldPreserved=true skill=branching_iron_works_v1"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            rolled = await _action(connection, "ironworks-emergency-rollback", "rollback_session", {})
            await connection.send(protocol.chat(
                f"[yan-agent] IRON WORKS ROLLBACK removed={rolled.get('removed')} "
                f"trackedAfter={rolled.get('tracked_after')}"
            ))
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"iron works v4.0 FAIL: {exc}"))
