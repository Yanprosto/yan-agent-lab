"""Generic machine probe: verify any catalog processor in a minimal live cell.

The cell is derived from the mechanism catalog, not from a hand-written mission:

    source chest -> transporter(PULL) -> transporter -> MACHINE -> transporter(PULL)
        -> transporter -> sink chest,   powered by a charged creative cube + cable

Machine sides: item INPUT west, item OUTPUT east, energy INPUT south. The recipe comes
from the catalog (given, or the simplest single-input recipe of the machine's types);
the contract follows from it: seed inputs for N operations, expect exactly N outputs
in the sink, nothing left in the source, the machine or the transporters. The world
is rolled back afterwards. A PASS is the live evidence that lets the catalog mark the
machine's side config ``runtime_observed`` (and so makes it plannable).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from mcbuild.catalog import Catalog, Recipe, load_catalog
from mcbuild.server import protocol
from mcbuild.server.mission_session import (
    P,
    _action,
    _configure_side,
    _configure_transporter_pull,
    _item_count,
    _place,
    _wait,
)
from mcbuild.server.skill_store import save_skill

CHEST = "minecraft:chest[facing=north,type=single,waterlogged=false]"
TRANSPORTER = "mekanism:basic_logistical_transporter"
CABLE = "mekanism:basic_universal_cable"
OPERATIONS = 4
POLL_TICKS = 60


@dataclass(frozen=True)
class ProbeCell:
    source: P = P(0, 0, 0)
    in_pull: P = P(1, 0, 0)
    in_feed: P = P(2, 0, 0)
    machine: P = P(3, 0, 0)
    out_pull: P = P(4, 0, 0)
    out_feed: P = P(5, 0, 0)
    sink: P = P(6, 0, 0)
    cable: P = P(3, 0, 1)
    cube: P = P(3, 0, 2)

    @property
    def transporters(self) -> list[P]:
        return [self.in_pull, self.in_feed, self.out_pull, self.out_feed]

    @property
    def footprint(self) -> list[P]:
        return [self.source, *self.transporters, self.machine, self.sink, self.cable, self.cube]


def resolve_item(catalog: Catalog, ingredient: dict[str, Any]) -> str | None:
    """A concrete item for an ingredient: the item itself, or a stable member of its tag."""
    if "item" in ingredient:
        return ingredient["item"]
    members = sorted(catalog.tags.get(ingredient.get("tag", ""), ()))
    preferred = [m for m in members if m.startswith(("minecraft:", "mekanism:"))]
    return (preferred or members or [None])[0]


def choose_recipe(catalog: Catalog, machine: str, recipe_id: str | None = None) -> Recipe:
    if recipe_id:
        recipe = catalog.recipe(recipe_id)
        if recipe.type not in catalog.block(machine).get("recipe_types", []):
            raise ValueError(f"{recipe_id} ({recipe.type}) is not handled by {machine}")
        return recipe
    types = catalog.block(machine).get("recipe_types", [])
    candidates = [
        r
        for r in catalog.recipes
        if r.type in types
        and not r.conditional
        and len(r.inputs) == 1
        and len(r.item_inputs) == 1
        and r.outputs
        and resolve_item(catalog, r.item_inputs[0])
        and r.main_output.get("item")
    ]
    if not candidates:
        raise ValueError(f"no simple single-input recipe for {machine}")

    # Prefer iron (the material the lab already knows), then a vanilla input item that is
    # easy to seed and recognise, then the smallest batch.
    def preference(r: Recipe) -> tuple[bool, bool, int, str]:
        item = resolve_item(catalog, r.item_inputs[0]) or ""
        return ("iron" not in r.id, not item.startswith("minecraft:"), int(r.item_inputs[0].get("count", 1)), r.id)

    candidates.sort(key=preference)
    return candidates[0]


async def _sink_state(connection, cell: ProbeCell, input_item: str, output_item: str, label: str) -> dict[str, Any]:
    source_n, _ = await _item_count(connection, f"{label}-source", cell.source, input_item)
    sink_n, _ = await _item_count(connection, f"{label}-sink", cell.sink, output_item)
    machine_inv = await _action(connection, f"{label}-machine", "read_inventory", cell.machine.args())
    machine_items = sum(int(row.get("count") or 0) for row in (machine_inv.get("items") or []))
    transit = await _action(
        connection, f"{label}-transit", "mek_read_transit", {"positions": [p.args() for p in cell.transporters]}
    )
    return {
        "source": source_n,
        "sink": sink_n,
        "machine_items": machine_items,
        "transit": int(transit.get("total_items") or 0),
    }


async def run_machine_probe_session(spec: str, connection) -> None:
    await connection.send(protocol.hello("yan-machine-probe-v1"))
    parts = spec.split()
    if not parts:
        await connection.send(protocol.error("machine probe needs '<machine id> [recipe id]'"))
        return
    machine, recipe_id = parts[0], (parts[1] if len(parts) > 1 else None)
    catalog = load_catalog()
    cell = ProbeCell()
    built = False
    try:
        block = catalog.block(machine)
        if "PROCESSOR" not in block.get("roles", []):
            raise ValueError(f"{machine} is not a PROCESSOR in the catalog")
        recipe = choose_recipe(catalog, machine, recipe_id)
        input_item = resolve_item(catalog, recipe.item_inputs[0])
        output_item = recipe.main_output["item"]
        if input_item is None or output_item is None:
            raise ValueError(f"{recipe.id}: cannot resolve concrete input/output items")
        per_op_in = int(recipe.item_inputs[0].get("count", 1))
        per_op_out = int(recipe.main_output.get("count", 1))
        seed = per_op_in * OPERATIONS
        expected = per_op_out * OPERATIONS
        ticks_per_op = int(catalog.fact(machine, "ticks_per_operation") or 200)
        ticks_per_block = int(catalog.fact(TRANSPORTER, "ticks_per_block") or 20)
        # Operations run one after another; add the 5-block route and a settle margin.
        budget = OPERATIONS * ticks_per_op + 5 * ticks_per_block * 2 + 400
        await connection.send(
            protocol.chat(
                f"[yan-agent] PROBE {machine}: recipe={recipe.id} {seed}x{input_item} -> "
                f"expect {expected}x{output_item}; side_config evidence={catalog.evidence(machine, 'side_config')}; "
                f"budget={budget} ticks"
            )
        )

        occupied = await _action(
            connection, "probe-site", "inspect_blocks", {"positions": [p.args() for p in cell.footprint]}
        )
        busy = [row for row in (occupied.get("blocks") or []) if not row.get("is_air", False)]
        if busy:
            raise RuntimeError(f"probe footprint is not empty ({len(busy)} cells); pick a clear anchor")

        built = True
        await _place(connection, "probe-source", cell.source, CHEST)
        await _place(connection, "probe-sink", cell.sink, CHEST)
        await _place(connection, "probe-machine", cell.machine, machine)
        await _action(connection, "probe-cube", "place_mekanism_filled_energy_cube", cell.cube.args())
        await _place(connection, "probe-cable", cell.cable, CABLE)
        for index, p in enumerate(cell.transporters, start=1):
            await _place(connection, f"probe-transporter-{index}", p, TRANSPORTER)
        await _wait(connection, "probe-build-settle", 20, 8.0)

        await _configure_side(connection, "probe-item-in", cell.machine, transmission="ITEM", side="west", mode="INPUT")
        await _configure_side(
            connection, "probe-item-out", cell.machine, transmission="ITEM", side="east", mode="OUTPUT"
        )
        await _configure_side(
            connection, "probe-energy-in", cell.machine, transmission="ENERGY", side="south", mode="INPUT"
        )
        await _configure_side(
            connection, "probe-cube-out", cell.cube, transmission="ENERGY", side="north", mode="OUTPUT"
        )
        await _action(
            connection,
            "probe-cable-pull",
            "mek_set_transmitter_mode",
            {**cell.cable.args(), "side": "south", "mode": "PULL"},
        )
        await _configure_transporter_pull(connection, "probe-input-pull", cell.in_pull, "west")
        await _configure_transporter_pull(connection, "probe-output-pull", cell.out_pull, "west")

        await _wait(connection, "probe-power-settle", 40, 8.0)
        energy = await _action(connection, "probe-energy", "read_energy", {**cell.machine.args(), "side": "south"})
        machine_energy = int(energy.get("energy") or 0)
        await connection.send(protocol.chat(f"[yan-agent] VERIFY POWER {machine}: energy={machine_energy}"))
        if machine_energy <= 0:
            raise RuntimeError(f"{machine} received no energy through the south side")

        seeded = await _action(
            connection, "probe-seed", "seed_item", {**cell.source.args(), "item": input_item, "count": seed}
        )
        inserted = int(seeded.get("inserted") or 0)
        if inserted != seed:
            raise RuntimeError(f"seeded {inserted}/{seed} {input_item}")

        waited = 0
        last_change = 0
        previous: dict[str, Any] | None = None
        state: dict[str, Any] = {}
        while waited < budget:
            await _action(connection, f"probe-flow-{waited}", "wait_ticks", {"ticks": POLL_TICKS}, timeout=20.0)
            waited += POLL_TICKS
            state = await _sink_state(connection, cell, input_item, output_item, f"probe-{waited}")
            if state["sink"] >= expected and state["transit"] == 0 and state["machine_items"] == 0:
                break
            if state != previous:
                last_change = waited
            # Stuck only if nothing changed for longer than one full operation: polls are
            # shorter than an operation, so equal snapshots in between are normal.
            elif waited - last_change > ticks_per_op + POLL_TICKS:
                break
            previous = state
        state["waited_ticks"] = waited

        passed = (
            state["source"] == 0 and state["sink"] == expected and state["transit"] == 0 and state["machine_items"] == 0
        )
        await connection.send(
            protocol.chat(
                f"[yan-agent] OBSERVE {machine}: source={state['source']} sink={state['sink']}/{expected} "
                f"machine={state['machine_items']} transit={state['transit']} waited={waited} pass={passed}"
            )
        )

        rolled = await _action(connection, "probe-rollback", "rollback_session", {})
        built = False
        world_clean = int(rolled.get("tracked_after") or 0) == 0

        verification = {
            "contract": f"source=0, sink={expected}x{output_item}, machine=0, transit=0",
            "observed": state,
            "world_clean": world_clean,
            "operations": OPERATIONS,
        }
        if not passed:
            raise RuntimeError(f"machine probe failed: {verification}")

        short = machine.split(":", 1)[1]
        save_skill(
            f"machine_cell_{short}_v1",
            description=f"Minimal powered cell for {machine}: item in west, out east, energy south.",
            implementation={
                "machine": machine,
                "recipe": recipe.id,
                "sides": {"ITEM": {"west": "INPUT", "east": "OUTPUT"}, "ENERGY": {"south": "INPUT"}},
                "input_pull_side_from_source": "west",
                "output_pull_side_from_machine": "west",
                "power": "charged creative energy cube + basic universal cable (PULL toward cube)",
            },
            verification=verification,
            source_experiment="yan-machine-probe-v1",
        )
        await connection.send(
            protocol.finish(
                f"machine probe v1 PASS: machine={machine} recipe={recipe.id} "
                f"{seed}x{input_item} -> {state['sink']}x{output_item} waited={waited} "
                f"worldClean={str(world_clean).lower()}"
            )
        )
    except Exception as exc:
        if built:
            with contextlib.suppress(Exception):  # report the original failure below
                await _action(connection, "probe-emergency-rollback", "rollback_session", {})
        await connection.send(protocol.error(f"machine probe v1 FAIL: {exc}"))


__all__ = ["ProbeCell", "choose_recipe", "resolve_item", "run_machine_probe_session"]
