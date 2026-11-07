"""Goal-driven process planning, live: rank catalog chains, build the best, fall back.

Command spec: ``<target item> <count> [source item[,source item...]]``
(default source: minecraft:raw_iron).

1. Enumerate and score process chains from the catalog (``mcbuild.planner``).
2. Compile the best chain into a line of verified cells and build it.
3. Seed the exact source amount, observe until the output settles, check the contract:
   source empty, sink == planned output, every machine and transporter empty.
4. Roll back. On failure, report where material stopped (diagnosis) and try the next
   candidate (beam fallback). On success, save the chain as a verified skill.
"""

from __future__ import annotations

import contextlib
from typing import Any

from mcbuild.catalog import load_catalog
from mcbuild.planner.chain_layout import CABLE, CHEST, TRANSPORTER, LineLayout, compile_line
from mcbuild.planner.process_graph import ScoredChain, rank_chains
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

POLL_TICKS = 60
DEFAULT_SOURCES = ("minecraft:raw_iron",)


def _p(pos: tuple[int, int, int]) -> P:
    return P(*pos)


async def _build_line(connection, layout: LineLayout, label: str) -> None:
    await _place(connection, f"{label}-source", _p(layout.source), CHEST)
    await _place(connection, f"{label}-sink", _p(layout.sink), CHEST)
    for index, slot in enumerate(layout.machines, start=1):
        await _place(connection, f"{label}-m{index}", _p(slot.pos), slot.machine)
        await _action(connection, f"{label}-m{index}-cube", "place_mekanism_filled_energy_cube", _p(slot.cube).args())
        await _place(connection, f"{label}-m{index}-cable", _p(slot.cable), CABLE)
    for index, pos in enumerate(layout.transporters, start=1):
        await _place(connection, f"{label}-t{index}", _p(pos), TRANSPORTER)
    await _wait(connection, f"{label}-build-settle", 20, 8.0)

    for index, slot in enumerate(layout.machines, start=1):
        m = _p(slot.pos)
        await _configure_side(connection, f"{label}-m{index}-in", m, transmission="ITEM", side="west", mode="INPUT")
        await _configure_side(connection, f"{label}-m{index}-out", m, transmission="ITEM", side="east", mode="OUTPUT")
        await _configure_side(
            connection, f"{label}-m{index}-energy", m, transmission="ENERGY", side="south", mode="INPUT"
        )
        await _configure_side(
            connection, f"{label}-m{index}-cube-out", _p(slot.cube), transmission="ENERGY", side="north", mode="OUTPUT"
        )
        await _action(
            connection,
            f"{label}-m{index}-cable-pull",
            "mek_set_transmitter_mode",
            {**_p(slot.cable).args(), "side": "south", "mode": "PULL"},
        )
    for index, pos in enumerate(layout.pull_transporters, start=1):
        await _configure_transporter_pull(connection, f"{label}-pull{index}", _p(pos), "west")


async def _read_line(connection, layout: LineLayout, source_item: str, target_item: str, label: str) -> dict[str, Any]:
    source_n, _ = await _item_count(connection, f"{label}-source", _p(layout.source), source_item)
    sink_n, _ = await _item_count(connection, f"{label}-sink", _p(layout.sink), target_item)
    machines = []
    for index, slot in enumerate(layout.machines, start=1):
        inv = await _action(connection, f"{label}-m{index}-inv", "read_inventory", _p(slot.pos).args())
        machines.append(sum(int(row.get("count") or 0) for row in (inv.get("items") or [])))
    transit = await _action(
        connection, f"{label}-transit", "mek_read_transit", {"positions": [_p(p).args() for p in layout.transporters]}
    )
    return {
        "source": source_n,
        "sink": sink_n,
        "machines": machines,
        "transit": int(transit.get("total_items") or 0),
    }


def _diagnose(state: dict[str, Any], scored: ScoredChain) -> str:
    """Name the first place where material stopped."""
    if state["source"]:
        return f"{state['source']} source items never left the source chest (input pull or first machine intake)"
    for index, (count, stage) in enumerate(zip(state["machines"], scored.chain.stages, strict=False), start=1):
        if count:
            return f"stage {index} ({stage.machine}) still holds {count} items (power, recipe or output hand-off)"
    if state["transit"]:
        return f"{state['transit']} items still in transporters (route too slow or blocked)"
    return f"sink has {state['sink']} of {scored.output} with nothing left upstream (recipe ratio differs from catalog)"


async def _try_chain(connection, scored: ScoredChain, attempt: int) -> tuple[bool, dict[str, Any]]:
    catalog = load_catalog()
    chain = scored.chain
    layout = compile_line(chain)
    label = f"plan{attempt}"
    busy = await _action(
        connection, f"{label}-site", "inspect_blocks", {"positions": [_p(p).args() for p in layout.footprint]}
    )
    if [row for row in (busy.get("blocks") or []) if not row.get("is_air", False)]:
        raise RuntimeError("line footprint is not empty; pick a clear anchor")

    await _build_line(connection, layout, label)
    await _wait(connection, f"{label}-power-settle", 40, 8.0)
    for index, slot in enumerate(layout.machines, start=1):
        energy = await _action(
            connection, f"{label}-m{index}-energy-read", "read_energy", {**_p(slot.pos).args(), "side": "south"}
        )
        if int(energy.get("energy") or 0) <= 0:
            return False, {"diagnosis": f"stage {index} ({slot.machine}) received no energy"}

    seeded = await _action(
        connection,
        f"{label}-seed",
        "seed_item",
        {**_p(layout.source).args(), "item": chain.source_item, "count": scored.source_needed},
    )
    if int(seeded.get("inserted") or 0) != scored.source_needed:
        return False, {"diagnosis": f"seeded {seeded.get('inserted')}/{scored.source_needed} source items"}

    longest_op = max(int(catalog.fact(s.machine, "ticks_per_operation") or 200) for s in chain.stages)
    budget = scored.ticks + 40 * len(layout.transporters) + 600
    waited = last_change = 0
    previous: dict[str, Any] | None = None
    state: dict[str, Any] = {}
    while waited < budget:
        await _action(connection, f"{label}-flow-{waited}", "wait_ticks", {"ticks": POLL_TICKS}, timeout=20.0)
        waited += POLL_TICKS
        state = await _read_line(connection, layout, chain.source_item, chain.target_item, f"{label}-{waited}")
        if state["sink"] >= scored.output and state["transit"] == 0 and not any(state["machines"]):
            break
        if state != previous:
            last_change = waited
        elif waited - last_change > longest_op + POLL_TICKS:
            break
        previous = state
    state["waited_ticks"] = waited
    passed = (
        state["source"] == 0 and state["sink"] == scored.output and state["transit"] == 0 and not any(state["machines"])
    )
    if not passed:
        state["diagnosis"] = _diagnose(state, scored)
    return passed, state


async def run_plan_session(spec: str, connection) -> None:
    await connection.send(protocol.hello("yan-process-planner-v1"))
    parts = spec.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await connection.send(protocol.error("plan needs '<target item> <count> [source,...]'"))
        return
    target_item, target_count = parts[0], int(parts[1])
    sources = set(parts[2].split(",")) if len(parts) > 2 else set(DEFAULT_SOURCES)
    catalog = load_catalog()
    ranked = rank_chains(catalog, target_item, target_count, sources)
    if not ranked:
        await connection.send(protocol.error(f"no plannable chain from {sorted(sources)} to {target_item}"))
        return
    for rank, scored in enumerate(ranked, start=1):
        await connection.send(
            protocol.chat(
                f"[yan-agent] CANDIDATE {rank}: score={scored.score} source={scored.source_needed} "
                f"output={scored.output} machines={scored.machines} energy={scored.energy_j}J  {scored.chain.id}"
            )
        )

    history = []
    for attempt, scored in enumerate(ranked, start=1):
        await connection.send(protocol.chat(f"[yan-agent] BUILD candidate {attempt}: {scored.chain.id}"))
        state: dict[str, Any]
        try:
            passed, state = await _try_chain(connection, scored, attempt)
        except Exception as exc:
            failure: dict[str, Any] = {"diagnosis": f"{type(exc).__name__}: {exc}"}
            passed, state = False, failure
        rolled: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            rolled = await _action(connection, f"plan{attempt}-rollback", "rollback_session", {})
        state["world_clean"] = int(rolled.get("tracked_after", 1) or 0) == 0
        history.append({"chain": scored.chain.id, "passed": passed, **state})
        await connection.send(
            protocol.chat(
                f"[yan-agent] OBSERVE candidate {attempt}: pass={passed} "
                + " ".join(f"{k}={v}" for k, v in state.items() if k != "diagnosis")
            )
        )
        if passed:
            save_skill(
                "process_chain_" + "_".join(s.machine.split(":")[1] for s in scored.chain.stages) + "_v1",
                description=f"Verified process chain for {target_item}: {scored.chain.id}",
                implementation={
                    "chain": scored.chain.id,
                    "stages": [
                        {"machine": s.machine, "recipe": s.recipe.id, "in": s.input_item, "out": s.output_item}
                        for s in scored.chain.stages
                    ],
                    "layout": "line of probe cells: item in west, out east, energy south",
                },
                verification={"source": scored.source_needed, "output": scored.output, **state},
                source_experiment="yan-process-planner-v1",
            )
            await connection.send(
                protocol.finish(
                    f"process planner v1 PASS: target={target_count}x{target_item} chain='{scored.chain.id}' "
                    f"candidate={attempt}/{len(ranked)} source={scored.source_needed} output={state['sink']} "
                    f"worldClean={str(state['world_clean']).lower()}"
                )
            )
            return
        await connection.send(protocol.chat(f"[yan-agent] DIAGNOSE candidate {attempt}: {state.get('diagnosis')}"))
    await connection.send(protocol.error(f"process planner v1 FAIL: all {len(ranked)} candidates failed: {history}"))
