"""Mode A, live: fit a process chain into a scanned volume and verify it.

Command spec: ``<volume> <target item> <count> [source item[,...]]``. The volume shell
must already exist at the anchor (the lab builds it with ``fill``; see
``mcbuild.planner.volumes``). The session never edits the shell: it scans the interior,
plans only on air cells, and rolls back everything it placed.

Candidates are (chain, layout) pairs: chains ranked from the catalog, up to three 3D
layouts each. Every layout passes the static check (T0) before a block is placed; the
first one that passes live is saved as a verified skill. A failed candidate is rolled
back with a diagnosis, then the next one is tried.
"""

from __future__ import annotations

import contextlib
from typing import Any

from mcbuild.catalog import load_catalog
from mcbuild.planner.chain_layout import CABLE, CHEST, TRANSPORTER
from mcbuild.planner.layout3d import Layout3D, LayoutError, Solver, direction, validate
from mcbuild.planner.process_graph import ScoredChain, rank_chains
from mcbuild.planner.volumes import VOLUMES, Volume
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
SCAN_BATCH = 300


def _p(pos: tuple[int, int, int]) -> P:
    return P(*pos)


async def scan_free(connection, volume: Volume) -> set[tuple[int, int, int]]:
    cells = volume.cells()
    free: set[tuple[int, int, int]] = set()
    for start in range(0, len(cells), SCAN_BATCH):
        batch = cells[start : start + SCAN_BATCH]
        seen = await _action(
            connection, f"layout-scan-{start}", "inspect_blocks", {"positions": [_p(c).args() for c in batch]}
        )
        for cell, row in zip(batch, seen.get("blocks") or [], strict=False):
            if row.get("is_air"):
                free.add(cell)
    return free


async def _build(connection, layout: Layout3D, label: str) -> None:
    await _place(connection, f"{label}-source", _p(layout.source), CHEST)
    await _place(connection, f"{label}-sink", _p(layout.sink), CHEST)
    for i, m in enumerate(layout.machines, start=1):
        await _place(connection, f"{label}-m{i}", _p(m.pos), m.machine)
        await _action(connection, f"{label}-m{i}-cube", "place_mekanism_filled_energy_cube", _p(m.cube).args())
        await _place(connection, f"{label}-m{i}-cable", _p(m.cable), CABLE)
    for i, cell in enumerate(layout.transporters, start=1):
        await _place(connection, f"{label}-t{i}", _p(cell), TRANSPORTER)
    await _wait(connection, f"{label}-build-settle", 20, 8.0)
    for i, m in enumerate(layout.machines, start=1):
        pos = _p(m.pos)
        await _configure_side(connection, f"{label}-m{i}-in", pos, transmission="ITEM", side=m.in_face, mode="INPUT")
        await _configure_side(
            connection, f"{label}-m{i}-out", pos, transmission="ITEM", side=str(m.out_face), mode="OUTPUT"
        )
        await _configure_side(
            connection, f"{label}-m{i}-energy", pos, transmission="ENERGY", side=m.energy_face, mode="INPUT"
        )
        cube_face = _face(m.cube, m.cable)
        await _configure_side(
            connection, f"{label}-m{i}-cube-out", _p(m.cube), transmission="ENERGY", side=cube_face, mode="OUTPUT"
        )
        await _action(
            connection,
            f"{label}-m{i}-cable-pull",
            "mek_set_transmitter_mode",
            {**_p(m.cable).args(), "side": _face(m.cable, m.cube), "mode": "PULL"},
        )
    for i, seg in enumerate(layout.segments, start=1):
        await _configure_transporter_pull(connection, f"{label}-pull{i}", _p(seg.cells[0]), seg.pull_face)


def _face(frm: tuple[int, int, int], to: tuple[int, int, int]) -> str:
    return direction(frm, to)


async def _read(connection, layout: Layout3D, source_item: str, target_item: str, label: str) -> dict[str, Any]:
    source_n, _ = await _item_count(connection, f"{label}-source", _p(layout.source), source_item)
    sink_n, _ = await _item_count(connection, f"{label}-sink", _p(layout.sink), target_item)
    machines = []
    for i, m in enumerate(layout.machines, start=1):
        inv = await _action(connection, f"{label}-m{i}-inv", "read_inventory", _p(m.pos).args())
        machines.append(sum(int(row.get("count") or 0) for row in (inv.get("items") or [])))
    transit = await _action(
        connection, f"{label}-transit", "mek_read_transit", {"positions": [_p(c).args() for c in layout.transporters]}
    )
    return {"source": source_n, "sink": sink_n, "machines": machines, "transit": int(transit.get("total_items") or 0)}


def _diagnose(state: dict[str, Any], layout: Layout3D, expected: int) -> str:
    if state["source"]:
        return f"{state['source']} items never left the source (first segment pull or machine 1 intake)"
    for i, (count, m) in enumerate(zip(state["machines"], layout.machines, strict=False), start=1):
        if count:
            return f"machine {i} ({m.machine}, out {m.out_face}) still holds {count} items"
    if state["transit"]:
        return f"{state['transit']} items still in transporters"
    return f"sink has {state['sink']} of {expected} with nothing upstream"


async def _try(connection, scored: ScoredChain, layout: Layout3D, attempt: int) -> tuple[bool, dict[str, Any]]:
    catalog = load_catalog()
    chain = scored.chain
    label = f"lay{attempt}"
    await _build(connection, layout, label)
    await _wait(connection, f"{label}-power-settle", 40, 8.0)
    for i, m in enumerate(layout.machines, start=1):
        energy = await _action(
            connection, f"{label}-m{i}-energy-read", "read_energy", {**_p(m.pos).args(), "side": m.energy_face}
        )
        if int(energy.get("energy") or 0) <= 0:
            return False, {"diagnosis": f"machine {i} ({m.machine}) received no energy via {m.energy_face}"}
    seeded = await _action(
        connection,
        f"{label}-seed",
        "seed_item",
        {**_p(layout.source).args(), "item": chain.source_item, "count": scored.source_needed},
    )
    if int(seeded.get("inserted") or 0) != scored.source_needed:
        return False, {"diagnosis": f"seeded {seeded.get('inserted')}/{scored.source_needed}"}

    longest = max(int(catalog.fact(s.machine, "ticks_per_operation") or 200) for s in chain.stages)
    budget = scored.ticks + 40 * len(layout.transporters) + 600
    waited = last_change = 0
    previous: dict[str, Any] | None = None
    state: dict[str, Any] = {}
    while waited < budget:
        await _action(connection, f"{label}-flow-{waited}", "wait_ticks", {"ticks": POLL_TICKS}, timeout=20.0)
        waited += POLL_TICKS
        state = await _read(connection, layout, chain.source_item, chain.target_item, f"{label}-{waited}")
        if state["sink"] >= scored.output and state["transit"] == 0 and not any(state["machines"]):
            break
        if state != previous:
            last_change = waited
        elif waited - last_change > longest + POLL_TICKS:
            break
        previous = state
    state["waited_ticks"] = waited
    passed = (
        state["source"] == 0 and state["sink"] == scored.output and state["transit"] == 0 and not any(state["machines"])
    )
    if not passed:
        state["diagnosis"] = _diagnose(state, layout, scored.output)
    return passed, state


async def run_layout_session(spec: str, connection) -> None:
    await connection.send(protocol.hello("yan-layout-3d-v1"))
    parts = spec.split()
    if len(parts) < 3 or parts[0] not in VOLUMES or not parts[2].isdigit():
        await connection.send(
            protocol.error(f"layout needs '<volume> <target> <count> [sources]'; volumes: {sorted(VOLUMES)}")
        )
        return
    volume = VOLUMES[parts[0]]
    target_item, count = parts[1], int(parts[2])
    sources = set(parts[3].split(",")) if len(parts) > 3 else {"minecraft:raw_iron"}

    free = await scan_free(connection, volume)
    expected = volume.expected_free()
    await connection.send(
        protocol.chat(
            f"[yan-agent] SCAN {volume.name}: free={len(free)} cells (expected {len(expected)}), interior={volume.size}"
        )
    )
    if volume.source not in free or volume.sink not in free:
        await connection.send(protocol.error("volume source/sink cells are not free; build the volume shell first"))
        return

    catalog = load_catalog()
    ranked = rank_chains(catalog, target_item, count, sources)
    candidates: list[tuple[ScoredChain, Layout3D]] = []
    for scored in ranked:
        try:
            layouts = Solver(free, volume.source, volume.sink).solve(scored.chain)
        except LayoutError as exc:
            await connection.send(protocol.chat(f"[yan-agent] NO LAYOUT for {scored.chain.id}: {exc}"))
            continue
        for layout in layouts:
            problems = validate(layout, free)
            if problems:
                await connection.send(protocol.chat(f"[yan-agent] T0 REJECT {scored.chain.id}: {problems[:2]}"))
                continue
            candidates.append((scored, layout))
    if not candidates:
        await connection.send(protocol.error(f"no valid layout in {volume.name} for {target_item}"))
        return
    for i, (scored, layout) in enumerate(candidates, start=1):
        machines = " ".join(f"{m.machine.split(':')[1]}@{m.pos}" for m in layout.machines)
        await connection.send(
            protocol.chat(f"[yan-agent] CANDIDATE {i}: chain='{scored.chain.id}' transporters={layout.cost} {machines}")
        )

    history = []
    for attempt, (scored, layout) in enumerate(candidates[:4], start=1):
        await connection.send(protocol.chat(f"[yan-agent] BUILD candidate {attempt} in {volume.name}"))
        state: dict[str, Any]
        try:
            passed, state = await _try(connection, scored, layout, attempt)
        except Exception as exc:
            failure: dict[str, Any] = {"diagnosis": f"{type(exc).__name__}: {exc}"}
            passed, state = False, failure
        rolled: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            rolled = await _action(connection, f"lay{attempt}-rollback", "rollback_session", {})
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
                f"layout_{volume.name}_" + "_".join(s.machine.split(":")[1] for s in scored.chain.stages) + "_v1",
                description=f"Verified 3D layout of '{scored.chain.id}' in volume {volume.name}",
                implementation={
                    "volume": volume.name,
                    "chain": scored.chain.id,
                    "machines": [
                        {
                            "machine": m.machine,
                            "pos": m.pos,
                            "in": m.in_face,
                            "out": m.out_face,
                            "energy": m.energy_face,
                            "cable": m.cable,
                            "cube": m.cube,
                        }
                        for m in layout.machines
                    ],
                    "segments": [{"cells": s.cells, "pull": s.pull_face} for s in layout.segments],
                },
                verification={"source": scored.source_needed, "output": scored.output, **state},
                source_experiment="yan-layout-3d-v1",
            )
            await connection.send(
                protocol.finish(
                    f"layout 3d v1 PASS: volume={volume.name} chain='{scored.chain.id}' candidate={attempt} "
                    f"transporters={layout.cost} output={state['sink']}/{scored.output} "
                    f"worldClean={str(state['world_clean']).lower()}"
                )
            )
            return
        await connection.send(protocol.chat(f"[yan-agent] DIAGNOSE candidate {attempt}: {state.get('diagnosis')}"))
    await connection.send(protocol.error(f"layout 3d v1 FAIL in {volume.name}: {history}"))
