"""YAN autonomous factory mission v2.0.

A first integrated maintenance-engineer mission:
- find a free site near the player;
- provision input/output buffers automatically;
- build two parallel Energized Smelter lines;
- configure Mekanism item and energy sides;
- power both machines from one creative energy cube;
- route raw iron in and ingots out;
- verify both lines participate and exact conservation holds;
- leave the working factory in the world.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from mcbuild.server import protocol
from mcbuild.server.skill_store import save_skill


@dataclass(frozen=True)
class P:
    x: int
    y: int
    z: int

    def args(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "z": self.z}

    def shifted(self, dx: int, dz: int) -> "P":
        return P(self.x + dx, self.y, self.z + dz)


@dataclass
class FactoryLayout:
    shift_x: int
    shift_z: int
    source: P
    sink: P
    smelter_a: P
    smelter_b: P
    cube: P
    energy_a: P
    energy_b: P
    in_a: list[P]
    in_b: list[P]
    out_a: list[P]
    out_b: list[P]
    out_shared: list[P]

    @property
    def all_transporters(self) -> list[P]:
        seen: set[tuple[int, int, int]] = set()
        result: list[P] = []
        for path in (self.in_a, self.in_b, self.out_a, self.out_b, self.out_shared):
            for p in path:
                key = (p.x, p.y, p.z)
                if key not in seen:
                    seen.add(key)
                    result.append(p)
        return result

    @property
    def footprint(self) -> list[P]:
        cells = [
            self.source,
            self.sink,
            self.smelter_a,
            self.smelter_b,
            self.cube,
            self.energy_a,
            self.energy_b,
            *self.all_transporters,
        ]
        seen: set[tuple[int, int, int]] = set()
        result: list[P] = []
        for p in cells:
            key = (p.x, p.y, p.z)
            if key not in seen:
                seen.add(key)
                result.append(p)
        return result


def _layout(dx: int, dz: int) -> FactoryLayout:
    def q(x: int, y: int, z: int) -> P:
        return P(x + dx, y, z + dz)

    return FactoryLayout(
        shift_x=dx,
        shift_z=dz,
        source=q(4, 1, 0),
        sink=q(12, 1, 0),
        smelter_a=q(8, 1, -2),
        smelter_b=q(8, 1, 2),
        cube=q(8, 1, 0),
        energy_a=q(8, 1, -1),
        energy_b=q(8, 1, 1),
        in_a=[q(4, 1, -1), q(5, 1, -1), q(6, 1, -1), q(6, 1, -2), q(7, 1, -2)],
        in_b=[q(4, 1, 1), q(5, 1, 1), q(6, 1, 1), q(6, 1, 2), q(7, 1, 2)],
        out_a=[q(9, 1, -2), q(10, 1, -2), q(10, 1, -1)],
        out_b=[q(9, 1, 2), q(10, 1, 2), q(10, 1, 1)],
        out_shared=[q(10, 1, 0), q(11, 1, 0)],
    )


async def _action(connection, request_id: str, action: str, args: dict[str, Any] | None = None, *, timeout: float = 20.0) -> dict[str, Any]:
    await connection.send(protocol.action(request_id, action, args or {}))
    raw = await asyncio.wait_for(connection.recv(), timeout=timeout)
    message = json.loads(raw)
    if message.get("type") != "observation" or message.get("id") != request_id:
        raise RuntimeError(f"{action}: unexpected response {message}")
    if not message.get("ok", False):
        raise RuntimeError(f"{action}: {message.get('error') or message}")
    return message.get("result") or {}


async def _wait(connection, label: str, ticks: int, timeout: float) -> None:
    result = await _action(connection, label, "wait_ticks", {"ticks": ticks}, timeout=timeout)
    await connection.send(protocol.chat(
        f"[yan-agent] WAIT {label}: {result.get('elapsed_ticks')} ticks"
    ))


async def _find_site(connection) -> FactoryLayout:
    candidates = [
        _layout(0, 0),
        _layout(0, 8),
        _layout(0, -8),
        _layout(-16, 0),
        _layout(-16, 8),
        _layout(-16, -8),
    ]
    for index, layout in enumerate(candidates, start=1):
        observed = await _action(
            connection,
            f"mission-site-{index}",
            "inspect_blocks",
            {"positions": [p.args() for p in layout.footprint]},
        )
        occupied = [row for row in (observed.get("blocks") or []) if not row.get("is_air", False)]
        if not occupied:
            await connection.send(protocol.chat(
                f"[yan-agent] SITE selected candidate={index} shift=({layout.shift_x},{layout.shift_z}) "
                f"footprint={len(layout.footprint)} cells"
            ))
            return layout

    raise RuntimeError(
        "no free factory footprint found in six candidate sites; move to a more open area and retry"
    )


async def _place(connection, label: str, p: P, block: str) -> None:
    await _action(connection, label, "place_block", {**p.args(), "block": block})


async def _configure_side(connection, label: str, p: P, *, transmission: str, side: str, mode: str) -> None:
    result = await _action(
        connection,
        label,
        "mek_set_side_config",
        {**p.args(), "transmission": transmission, "side": side, "mode": mode},
    )
    if not result.get("verified", False):
        raise RuntimeError(f"{label}: side config readback failed: {result}")


async def _configure_transporter_pull(connection, label: str, p: P, side: str) -> None:
    result = await _action(
        connection,
        label,
        "mek_set_transporter_mode",
        {**p.args(), "side": side, "mode": "PULL"},
    )
    if not result.get("verified", False):
        raise RuntimeError(f"{label}: transporter PULL readback failed: {result}")


async def _build_factory(connection, layout: FactoryLayout) -> None:
    await connection.send(protocol.chat(
        "[yan-agent] BUILD: provisioning autonomous 2-line Mekanism smelting cell."
    ))

    await _place(connection, "mission-source", layout.source, "minecraft:chest[facing=north,type=single,waterlogged=false]")
    await _place(connection, "mission-sink", layout.sink, "minecraft:chest[facing=north,type=single,waterlogged=false]")
    await _place(connection, "mission-smelter-a", layout.smelter_a, "mekanism:energized_smelter")
    await _place(connection, "mission-smelter-b", layout.smelter_b, "mekanism:energized_smelter")
    cube = await _action(
        connection,
        "mission-cube",
        "place_mekanism_filled_energy_cube",
        layout.cube.args(),
    )
    await connection.send(protocol.chat(
        f"[yan-agent] POWER SOURCE: placed precharged creative-tab cube "
        f"energy={cube.get('internal_energy')} variant={cube.get('variant')}"
    ))
    await _place(connection, "mission-energy-a", layout.energy_a, "mekanism:basic_universal_cable")
    await _place(connection, "mission-energy-b", layout.energy_b, "mekanism:basic_universal_cable")

    for prefix, path in (
        ("mission-in-a", layout.in_a),
        ("mission-in-b", layout.in_b),
        ("mission-out-a", layout.out_a),
        ("mission-out-b", layout.out_b),
        ("mission-out-shared", layout.out_shared),
    ):
        for i, p in enumerate(path, start=1):
            await _place(connection, f"{prefix}-{i}", p, "mekanism:basic_logistical_transporter")

    await _wait(connection, "mission-build-settle", 20, 6.0)

    # Smelter input from west, output to east. Energy enters from cube-facing side.
    await _configure_side(connection, "mission-a-item-in", layout.smelter_a, transmission="ITEM", side="west", mode="INPUT")
    await _configure_side(connection, "mission-a-item-out", layout.smelter_a, transmission="ITEM", side="east", mode="OUTPUT")
    await _configure_side(connection, "mission-a-energy", layout.smelter_a, transmission="ENERGY", side="south", mode="INPUT")

    await _configure_side(connection, "mission-b-item-in", layout.smelter_b, transmission="ITEM", side="west", mode="INPUT")
    await _configure_side(connection, "mission-b-item-out", layout.smelter_b, transmission="ITEM", side="east", mode="OUTPUT")
    await _configure_side(connection, "mission-b-energy", layout.smelter_b, transmission="ENERGY", side="north", mode="INPUT")

    await _configure_side(connection, "mission-cube-out-a", layout.cube, transmission="ENERGY", side="north", mode="OUTPUT")
    await _configure_side(connection, "mission-cube-out-b", layout.cube, transmission="ENERGY", side="south", mode="OUTPUT")

    # Universal Cable does not actively pull from adjacent energy providers while NORMAL.
    # Make the cable faces toward the cube explicit PULL sides; the network then emits to
    # the smelter acceptors on its NORMAL consumer faces.
    await _action(
        connection,
        "mission-energy-pull-a",
        "mek_set_transmitter_mode",
        {**layout.energy_a.args(), "side": "south", "mode": "PULL"},
    )
    await _action(
        connection,
        "mission-energy-pull-b",
        "mek_set_transmitter_mode",
        {**layout.energy_b.args(), "side": "north", "mode": "PULL"},
    )

    await _configure_transporter_pull(connection, "mission-input-pull-a", layout.in_a[0], "south")
    await _configure_transporter_pull(connection, "mission-input-pull-b", layout.in_b[0], "north")
    await _configure_transporter_pull(connection, "mission-output-pull-a", layout.out_a[0], "west")
    await _configure_transporter_pull(connection, "mission-output-pull-b", layout.out_b[0], "west")

    await connection.send(protocol.chat(
        "[yan-agent] CONFIG: item INPUT/OUTPUT, dual source PULL, output PULL, and shared energy node configured."
    ))


async def _item_count(connection, label: str, p: P, item: str, side: str | None = None) -> tuple[int, dict[str, Any]]:
    args = p.args()
    if side is not None:
        args = {**args, "side": side}
    inv = await _action(connection, label, "read_inventory", args)
    count = sum(
        int(row.get("count") or 0)
        for row in (inv.get("items") or [])
        if row.get("item") == item
    )
    return count, inv


async def _read_transit(connection, layout: FactoryLayout, label: str) -> dict[str, Any]:
    return await _action(
        connection,
        label,
        "mek_read_transit",
        {"positions": [p.args() for p in layout.all_transporters]},
    )


async def _verify_power(connection, layout: FactoryLayout) -> dict[str, int]:
    await _wait(connection, "mission-power-settle", 40, 8.0)
    a = await _action(connection, "mission-energy-read-a", "read_energy", {**layout.smelter_a.args(), "side": "south"})
    b = await _action(connection, "mission-energy-read-b", "read_energy", {**layout.smelter_b.args(), "side": "north"})
    ea = int(a.get("energy") or 0)
    eb = int(b.get("energy") or 0)

    if ea <= 0:
        await connection.send(protocol.chat(
            "[yan-agent] REPAIR power-A: no stored energy; reapplying cube NORTH output and smelter SOUTH input."
        ))
        await _configure_side(connection, "mission-repair-cube-a", layout.cube, transmission="ENERGY", side="north", mode="OUTPUT")
        await _configure_side(connection, "mission-repair-energy-a", layout.smelter_a, transmission="ENERGY", side="south", mode="INPUT")
    if eb <= 0:
        await connection.send(protocol.chat(
            "[yan-agent] REPAIR power-B: no stored energy; reapplying cube SOUTH output and smelter NORTH input."
        ))
        await _configure_side(connection, "mission-repair-cube-b", layout.cube, transmission="ENERGY", side="south", mode="OUTPUT")
        await _configure_side(connection, "mission-repair-energy-b", layout.smelter_b, transmission="ENERGY", side="north", mode="INPUT")

    if ea <= 0 or eb <= 0:
        await _wait(connection, "mission-power-repair-settle", 40, 8.0)
        a = await _action(connection, "mission-energy-reread-a", "read_energy", {**layout.smelter_a.args(), "side": "south"})
        b = await _action(connection, "mission-energy-reread-b", "read_energy", {**layout.smelter_b.args(), "side": "north"})
        ea = int(a.get("energy") or 0)
        eb = int(b.get("energy") or 0)

    if ea <= 0 or eb <= 0:
        raise RuntimeError(f"power subsystem failed: smelterA={ea} smelterB={eb}")

    await connection.send(protocol.chat(
        f"[yan-agent] VERIFY POWER: smelterA={ea} smelterB={eb}"
    ))
    return {"a": ea, "b": eb}


async def _seed_source(connection, layout: FactoryLayout) -> None:
    seeded = await _action(
        connection,
        "mission-seed",
        "seed_item",
        {**layout.source.args(), "item": "minecraft:raw_iron", "count": 12},
    )
    if int(seeded.get("inserted") or 0) != 12:
        raise RuntimeError(f"failed to stage 12 raw iron: {seeded}")
    await connection.send(protocol.chat(
        "[yan-agent] MATERIAL: staged 12 raw iron in autonomous input buffer."
    ))


async def _verify_distribution(connection, layout: FactoryLayout) -> dict[str, Any]:
    await _wait(connection, "mission-distribute", 120, 12.0)
    raw_source, _ = await _item_count(connection, "mission-source-after-distribution", layout.source, "minecraft:raw_iron")
    raw_a, inv_a = await _item_count(connection, "mission-a-after-distribution", layout.smelter_a, "minecraft:raw_iron", "west")
    raw_b, inv_b = await _item_count(connection, "mission-b-after-distribution", layout.smelter_b, "minecraft:raw_iron", "west")
    transit = await _read_transit(connection, layout, "mission-transit-after-distribution")
    t = int(transit.get("total_items") or 0)

    await connection.send(protocol.chat(
        f"[yan-agent] VERIFY FEED: sourceRaw={raw_source} smelterAraw={raw_a} smelterBraw={raw_b} transit={t}"
    ))

    # The machines may already have converted some raw iron by this point, so participation
    # is inferred from either raw input still present or iron output already present.
    ingot_a, _ = await _item_count(connection, "mission-a-output-after-distribution", layout.smelter_a, "minecraft:iron_ingot", "east")
    ingot_b, _ = await _item_count(connection, "mission-b-output-after-distribution", layout.smelter_b, "minecraft:iron_ingot", "east")
    if raw_a + ingot_a == 0 or raw_b + ingot_b == 0:
        raise RuntimeError(
            f"input distribution starved a processing line: A(raw={raw_a},ingot={ingot_a}) "
            f"B(raw={raw_b},ingot={ingot_b})"
        )
    return {
        "source_raw": raw_source,
        "a_raw": raw_a,
        "b_raw": raw_b,
        "transit": t,
    }


async def _wait_for_output(connection, layout: FactoryLayout) -> dict[str, Any]:
    # Six items per smelter at 200 ticks each is ~1200 ticks. Poll instead of one blind wait
    # so the mission can stop early when the contract is satisfied.
    history: list[dict[str, Any]] = []
    for cycle in range(1, 8):
        await _wait(connection, f"mission-process-{cycle}", 200, 16.0)

        sink_ingots, _ = await _item_count(connection, f"mission-sink-cycle-{cycle}", layout.sink, "minecraft:iron_ingot")
        raw_source, _ = await _item_count(connection, f"mission-source-cycle-{cycle}", layout.source, "minecraft:raw_iron")
        raw_a, _ = await _item_count(connection, f"mission-a-cycle-{cycle}", layout.smelter_a, "minecraft:raw_iron", "west")
        raw_b, _ = await _item_count(connection, f"mission-b-cycle-{cycle}", layout.smelter_b, "minecraft:raw_iron", "west")
        transit = await _read_transit(connection, layout, f"mission-transit-cycle-{cycle}")
        t = int(transit.get("total_items") or 0)

        ingot_a, _ = await _item_count(connection, f"mission-a-out-cycle-{cycle}", layout.smelter_a, "minecraft:iron_ingot", "east")
        ingot_b, _ = await _item_count(connection, f"mission-b-out-cycle-{cycle}", layout.smelter_b, "minecraft:iron_ingot", "east")
        remaining_raw = raw_source + raw_a + raw_b
        visible_ingots = sink_ingots + ingot_a + ingot_b

        row = {
            "cycle": cycle,
            "sink_ingots": sink_ingots,
            "machine_a_ingots": ingot_a,
            "machine_b_ingots": ingot_b,
            "remaining_raw": remaining_raw,
            "transit": t,
        }
        history.append(row)
        await connection.send(protocol.chat(
            f"[yan-agent] PROGRESS {cycle}: sink={sink_ingots} machineOut={ingot_a}/{ingot_b} "
            f"rawRemaining={remaining_raw} transit={t}"
        ))

        if sink_ingots == 12 and remaining_raw == 0 and ingot_a == 0 and ingot_b == 0 and t == 0:
            return {"history": history, "cycles": cycle, "sink_ingots": sink_ingots}

        # If machine output is accumulating, repair output interfaces without touching inputs/power.
        if cycle >= 2 and (ingot_a > 0 or ingot_b > 0):
            await connection.send(protocol.chat(
                f"[yan-agent] DIAGNOSE OUTPUT: machine buffers hold {ingot_a}/{ingot_b}; "
                "reasserting OUTPUT sides and extractor PULL only."
            ))
            await _configure_side(connection, f"mission-output-repair-a-{cycle}", layout.smelter_a, transmission="ITEM", side="east", mode="OUTPUT")
            await _configure_side(connection, f"mission-output-repair-b-{cycle}", layout.smelter_b, transmission="ITEM", side="east", mode="OUTPUT")
            await _configure_transporter_pull(connection, f"mission-output-pull-repair-a-{cycle}", layout.out_a[0], "west")
            await _configure_transporter_pull(connection, f"mission-output-pull-repair-b-{cycle}", layout.out_b[0], "west")

    raise RuntimeError(f"production timeout; history={history}")


async def run_mission_session(connection) -> None:
    await connection.send(protocol.hello("yan-autonomous-factory-v2.0"))
    await connection.send(protocol.chat(
        "[yan-agent] MISSION: autonomously build and commission a two-line powered Mekanism factory. "
        "Goal: 12 raw iron -> 12 iron ingots. No hand-built fixture required."
    ))

    layout: FactoryLayout | None = None
    try:
        layout = await _find_site(connection)
        await _build_factory(connection, layout)
        power = await _verify_power(connection, layout)
        await _seed_source(connection, layout)
        distribution = await _verify_distribution(connection, layout)
        production = await _wait_for_output(connection, layout)

        sink_ingots, _ = await _item_count(connection, "mission-final-sink", layout.sink, "minecraft:iron_ingot")
        raw_source, _ = await _item_count(connection, "mission-final-source", layout.source, "minecraft:raw_iron")
        raw_a, _ = await _item_count(connection, "mission-final-a", layout.smelter_a, "minecraft:raw_iron", "west")
        raw_b, _ = await _item_count(connection, "mission-final-b", layout.smelter_b, "minecraft:raw_iron", "west")
        out_a, _ = await _item_count(connection, "mission-final-out-a", layout.smelter_a, "minecraft:iron_ingot", "east")
        out_b, _ = await _item_count(connection, "mission-final-out-b", layout.smelter_b, "minecraft:iron_ingot", "east")
        transit = await _read_transit(connection, layout, "mission-final-transit")
        t = int(transit.get("total_items") or 0)

        machine_a_items = raw_a + out_a
        machine_b_items = raw_b + out_b
        passed = (
            sink_ingots == 12
            and raw_source == 0
            and raw_a == 0
            and raw_b == 0
            and machine_a_items == 0
            and machine_b_items == 0
            and t == 0
        )
        if not passed:
            raise RuntimeError(
                "final production contract failed: "
                f"sink={sink_ingots} sourceRaw={raw_source} machineRaw={raw_a}/{raw_b} "
                f"machineItems={machine_a_items}/{machine_b_items} transit={t}"
            )

        skill_path = save_skill(
            "autonomous_parallel_smelting_factory_v1",
            description=(
                "Autonomously provisioned two-line Mekanism smelting factory with generated site, "
                "item routing, generic machine side configuration, shared power and production verification."
            ),
            implementation={
                "mission": "12 raw iron -> 12 iron ingots",
                "machines": 2,
                "site_shift": [layout.shift_x, layout.shift_z],
                "source": [layout.source.x, layout.source.y, layout.source.z],
                "sink": [layout.sink.x, layout.sink.y, layout.sink.z],
                "smelters": [
                    [layout.smelter_a.x, layout.smelter_a.y, layout.smelter_a.z],
                    [layout.smelter_b.x, layout.smelter_b.y, layout.smelter_b.z],
                ],
                "energy_source": [layout.cube.x, layout.cube.y, layout.cube.z],
                "transporters": len(layout.all_transporters),
                "world_preserved": True,
            },
            verification={
                "sink_ingots": sink_ingots,
                "transit": t,
                "power": power,
                "distribution": distribution,
                "production": production,
            },
            source_experiment="yan-autonomous-factory-v2.0",
        )

        await connection.send(protocol.chat(
            f"[yan-agent] ACCEPT MISSION: factory commissioned, output=12 iron ingots, "
            f"machines=2 transporters={len(layout.all_transporters)} skill={skill_path.name}"
        ))
        await connection.send(protocol.finish(
            "autonomous factory v2.0 PASS: "
            f"raw=12 ingots={sink_ingots} machines=2 powerA={power['a']} powerB={power['b']} "
            f"transporters={len(layout.all_transporters)} transit={t} "
            "worldPreserved=true skill=autonomous_parallel_smelting_factory_v1"
        ))

    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        try:
            rolled = await _action(connection, "mission-emergency-rollback", "rollback_session", {})
            await connection.send(protocol.chat(
                f"[yan-agent] MISSION ROLLBACK: removed={rolled.get('removed')} trackedAfter={rolled.get('tracked_after')}"
            ))
        except RuntimeError:
            pass
        await connection.send(protocol.error(f"autonomous factory v2.0 FAIL: {exc}"))
