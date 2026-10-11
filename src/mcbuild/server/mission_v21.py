"""YAN v2.1 powered multi-cell mission.

Reuses the validated v2.0 production-cell implementation as a module and orchestrates
two cells (four smelters total) with explicit energy provisioning and observability.
"""

from __future__ import annotations

from typing import Any

from mcbuild.server import protocol
from mcbuild.server.mission_session import (
    FactoryLayout,
    _action,
    _build_factory,
    _item_count,
    _layout,
    _read_transit,
    _seed_source,
    _verify_distribution,
    _verify_power,
    _wait_for_output,
)
from mcbuild.server.skill_store import save_skill


async def _find_pair(connection) -> tuple[FactoryLayout, FactoryLayout]:
    pairs = [
        (_layout(0, 0), _layout(0, 10)),
        (_layout(0, 0), _layout(0, -10)),
        (_layout(-16, 0), _layout(-16, 10)),
        (_layout(-16, 0), _layout(-16, -10)),
    ]
    for index, (a, b) in enumerate(pairs, start=1):
        positions = [p.args() for p in [*a.footprint, *b.footprint]]
        observed = await _action(
            connection,
            f"v21-site-pair-{index}",
            "inspect_blocks",
            {"positions": positions},
        )
        occupied = [row for row in (observed.get("blocks") or []) if not row.get("is_air", False)]
        if not occupied:
            await connection.send(protocol.chat(
                f"[yan-agent] SITE PAIR selected={index} cells=2 footprint={len(positions)}"
            ))
            return a, b
    raise RuntimeError("no free two-cell footprint found; move to a more open area")


async def _provision_power(connection, layout: FactoryLayout, cell: str) -> dict[str, Any]:
    source = await _action(
        connection,
        f"{cell}-cube-energy",
        "read_energy",
        layout.cube.args(),
    )
    source_n = int(source.get("energy") or 0)
    if source_n <= 0:
        raise RuntimeError(
            f"{cell}: precharged Creative Energy Cube is unexpectedly empty"
        )

    cable_a = await _action(
        connection,
        f"{cell}-cable-a-energy",
        "read_energy",
        layout.energy_a.args(),
    )
    cable_b = await _action(
        connection,
        f"{cell}-cable-b-energy",
        "read_energy",
        layout.energy_b.args(),
    )

    await connection.send(protocol.chat(
        f"[yan-agent] POWER SOURCE {cell}: prechargedCube={source_n} "
        f"cableA={cable_a.get('energy')} cableB={cable_b.get('energy')}"
    ))

    consumers = await _verify_power(connection, layout)
    return {
        "source": source_n,
        "cable_a": int(cable_a.get("energy") or 0),
        "cable_b": int(cable_b.get("energy") or 0),
        "smelter_a": consumers["a"],
        "smelter_b": consumers["b"],
    }


async def _final_cell_state(connection, layout: FactoryLayout, cell: str) -> dict[str, Any]:
    sink, _ = await _item_count(
        connection, f"{cell}-final-sink", layout.sink, "minecraft:iron_ingot"
    )
    src, _ = await _item_count(
        connection, f"{cell}-final-source", layout.source, "minecraft:raw_iron"
    )
    transit = await _read_transit(connection, layout, f"{cell}-final-transit")
    return {
        "sink_ingots": sink,
        "source_raw": src,
        "transit": int(transit.get("total_items") or 0),
    }


async def run_powered_mission_session(connection) -> None:
    await connection.send(protocol.hello("yan-powered-factory-v2.1"))
    await connection.send(protocol.chat(
        "[yan-agent] MISSION v2.1: autonomously commission TWO production cells "
        "(4 Energized Smelters total), provision their energy sources, and produce "
        "24 iron ingots from 24 raw iron."
    ))

    try:
        cell_a, cell_b = await _find_pair(connection)

        await connection.send(protocol.chat("[yan-agent] BUILD CELL A"))
        await _build_factory(connection, cell_a)
        await connection.send(protocol.chat("[yan-agent] BUILD CELL B"))
        await _build_factory(connection, cell_b)

        power_a = await _provision_power(connection, cell_a, "cell-a")
        power_b = await _provision_power(connection, cell_b, "cell-b")

        # Both cells are started before waiting for either one to complete.
        await _seed_source(connection, cell_a)
        await _seed_source(connection, cell_b)

        feed_a = await _verify_distribution(connection, cell_a)
        feed_b = await _verify_distribution(connection, cell_b)

        production_a = await _wait_for_output(connection, cell_a)
        production_b = await _wait_for_output(connection, cell_b)

        final_a = await _final_cell_state(connection, cell_a, "cell-a")
        final_b = await _final_cell_state(connection, cell_b, "cell-b")

        total_ingots = final_a["sink_ingots"] + final_b["sink_ingots"]
        total_raw = final_a["source_raw"] + final_b["source_raw"]
        total_transit = final_a["transit"] + final_b["transit"]

        if total_ingots != 24 or total_raw != 0 or total_transit != 0:
            raise RuntimeError(
                f"v2.1 final contract failed: ingots={total_ingots}/24 "
                f"raw={total_raw} transit={total_transit}"
            )

        skill_path = save_skill(
            "autonomous_multi_cell_factory_v1",
            description=(
                "Verified autonomous orchestration of two reusable powered production cells "
                "(four Energized Smelters total) with explicit source-energy provisioning."
            ),
            implementation={
                "cells": 2,
                "machines": 4,
                "raw_input": 24,
                "iron_ingot_output": 24,
                "power_provisioning": "read -> seed if empty -> source/cable/consumer verify",
                "world_preserved": True,
            },
            verification={
                "power": {"cell_a": power_a, "cell_b": power_b},
                "feed": {"cell_a": feed_a, "cell_b": feed_b},
                "production": {"cell_a": production_a, "cell_b": production_b},
                "final": {"cell_a": final_a, "cell_b": final_b},
            },
            source_experiment="yan-powered-factory-v2.1",
        )

        await connection.send(protocol.chat(
            f"[yan-agent] ACCEPT v2.1: cells=2 machines=4 ingots={total_ingots} "
            f"rawRemaining={total_raw} transit={total_transit} skill={skill_path.name}"
        ))
        await connection.send(protocol.finish(
            "powered multi-cell factory v2.1 PASS: "
            f"cells=2 machines=4 raw=24 ingots={total_ingots} transit={total_transit} "
            "worldPreserved=true skill=autonomous_multi_cell_factory_v1"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            rolled = await _action(connection, "v21-emergency-rollback", "rollback_session", {})
            await connection.send(protocol.chat(
                f"[yan-agent] v2.1 ROLLBACK removed={rolled.get('removed')} "
                f"trackedAfter={rolled.get('tracked_after')}"
            ))
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"powered multi-cell factory v2.1 FAIL: {exc}"))
