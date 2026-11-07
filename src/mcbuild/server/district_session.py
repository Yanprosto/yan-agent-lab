"""District mission (mode B, M3 step 3): shops + freight trunk + one power backbone, live.

Command spec: ``<target item> <count> [sources] [gap=N] [break=0|1]`` (break defaults to 1).

1. Plan the district from the best catalog chain (one shop per stage) and check it (T0).
2. Build it on a clear site: chests, machines, one charged power source, the cable
   backbone, shop transporters and the freight trunk(s).
3. Verify every machine is powered through the backbone.
4. With break=1, remove one backbone cell that only a downstream shop depends on
   (simulated damage), then start production.
5. When production stalls, diagnose by comparing the planned backbone with a scan of the
   world, re-place only the missing cells (local repair), verify power, and continue.
6. Check the exact contract across every buffer: source empty, intermediate chests,
   machines and transporters empty, final sink == planned output. Roll back.
"""

from __future__ import annotations

import contextlib
from collections import deque
from typing import Any

from mcbuild.catalog import load_catalog
from mcbuild.planner.chain_layout import CABLE, CHEST, TRANSPORTER
from mcbuild.planner.district import District, DistrictError, plan_district, validate_district
from mcbuild.planner.layout3d import direction, neighbours
from mcbuild.planner.process_graph import rank_chains
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


def _p(pos: tuple[int, int, int]) -> P:
    return P(*pos)


async def _build(connection, d: District, *, omit: tuple[int, int, int] | None = None) -> None:
    for i, chest in enumerate(d.chests, start=1):
        await _place(connection, f"d-chest{i}", _p(chest), CHEST)
    for i, m in enumerate(d.machines, start=1):
        await _place(connection, f"d-m{i}", _p(m.pos), m.machine)
    await _action(connection, "d-power", "place_mekanism_filled_energy_cube", _p(d.power_source).args())
    for i, cell in enumerate(d.backbone, start=1):
        if cell == omit:
            continue  # generated damage: this backbone cell is missing from the start
        await _place(connection, f"d-cable{i}", _p(cell), CABLE)
    for i, cell in enumerate(d.transporters, start=1):
        await _place(connection, f"d-t{i}", _p(cell), TRANSPORTER)
    await _wait(connection, "d-build-settle", 20, 8.0)

    for i, m in enumerate(d.machines, start=1):
        pos = _p(m.pos)
        await _configure_side(connection, f"d-m{i}-in", pos, transmission="ITEM", side=m.in_face, mode="INPUT")
        await _configure_side(connection, f"d-m{i}-out", pos, transmission="ITEM", side=str(m.out_face), mode="OUTPUT")
        await _configure_side(
            connection, f"d-m{i}-energy", pos, transmission="ENERGY", side=m.energy_face, mode="INPUT"
        )
    pull_cell, pull_face = d.backbone_pull
    await _configure_side(
        connection,
        "d-power-out",
        _p(d.power_source),
        transmission="ENERGY",
        side=direction(d.power_source, pull_cell),
        mode="OUTPUT",
    )
    await _action(
        connection,
        "d-backbone-pull",
        "mek_set_transmitter_mode",
        {**_p(pull_cell).args(), "side": pull_face, "mode": "PULL"},
    )
    k = 0
    for shop in d.shops:
        for seg in shop.layout.segments:
            k += 1
            await _configure_transporter_pull(connection, f"d-pull{k}", _p(seg.cells[0]), seg.pull_face)
    for i, trunk in enumerate(d.trunks, start=1):
        await _configure_transporter_pull(connection, f"d-trunk{i}-pull", _p(trunk.cells[0]), trunk.pull_face)


async def _energy(connection, d: District, label: str) -> list[int]:
    values = []
    for i, m in enumerate(d.machines, start=1):
        row = await _action(connection, f"{label}-e{i}", "read_energy", {**_p(m.pos).args(), "side": m.energy_face})
        values.append(int(row.get("energy") or 0))
    return values


async def _read(connection, d: District, label: str) -> dict[str, Any]:
    chests = []
    for i, shop in enumerate(d.shops):
        src, _ = await _item_count(connection, f"{label}-s{i}-in", _p(shop.layout.source), shop.stage.input_item)
        out, _ = await _item_count(connection, f"{label}-s{i}-out", _p(shop.layout.sink), shop.stage.output_item)
        chests += [src, out]
    machines = []
    for i, m in enumerate(d.machines, start=1):
        inv = await _action(connection, f"{label}-m{i}-inv", "read_inventory", _p(m.pos).args())
        machines.append(sum(int(row.get("count") or 0) for row in (inv.get("items") or [])))
    transit = await _action(
        connection, f"{label}-transit", "mek_read_transit", {"positions": [_p(c).args() for c in d.transporters]}
    )
    moving = sorted(
        (row.get("x"), row.get("y"), row.get("z"), row.get("progress")) for row in transit.get("items") or []
    )
    return {
        "chests": chests,
        "machines": machines,
        "transit": int(transit.get("total_items") or 0),
        "moving": moving,
    }


def _break_cell(d: District) -> tuple[tuple[int, int, int], list[int]]:
    """A backbone cell that cuts power to downstream shop(s) but not to the first one."""
    net = set(d.backbone)
    root = d.backbone_pull[0]
    parent: dict = {root: None}
    queue = deque([root])
    while queue:
        cell = queue.popleft()
        for n in neighbours(cell):
            if n in net and n not in parent:
                parent[n] = cell
                queue.append(n)

    def path(cell):
        out = []
        while cell is not None:
            out.append(cell)
            cell = parent[cell]
        return out

    machine_cables = {m.cable for m in d.machines}
    first_path = set(path(d.machines[0].cable))
    last_path = path(d.machines[-1].cable)
    options = [c for c in last_path if c not in first_path and c not in machine_cables and c != root]
    if not options:
        raise DistrictError("no backbone cell isolates the last shop from the first")
    cell = options[len(options) // 2]
    cut = [i for i, m in enumerate(d.machines) if cell in path(m.cable)]
    return cell, cut


async def _diagnose_and_repair(connection, d: District, label: str) -> dict[str, Any]:
    energy = await _energy(connection, d, f"{label}-energy")
    dark = [i for i, e in enumerate(energy) if e <= 0]
    scan = await _action(
        connection, f"{label}-scan", "inspect_blocks", {"positions": [_p(c).args() for c in d.backbone]}
    )
    missing = [
        cell for cell, row in zip(d.backbone, scan.get("blocks") or [], strict=False) if row.get("block") != CABLE
    ]
    await connection.send(
        protocol.chat(
            f"[yan-agent] DIAGNOSE {label}: unpowered machines={dark} energy={energy}; "
            f"backbone planned={len(d.backbone)} missing={missing}"
        )
    )
    for i, cell in enumerate(missing, start=1):
        await _place(connection, f"{label}-repair{i}", _p(cell), CABLE)
    if missing:
        await _wait(connection, f"{label}-repair-settle", 40, 8.0)
    after = await _energy(connection, d, f"{label}-energy-after")
    await connection.send(
        protocol.chat(f"[yan-agent] REPAIR {label}: re-placed {len(missing)} cable cell(s); energy now {after}")
    )
    return {"unpowered": dark, "missing": missing, "energy_after": after}


async def run_district_session(spec: str, connection) -> None:
    await connection.send(protocol.hello("yan-district-v1"))
    parts = spec.split()
    options = dict(p.split("=", 1) for p in parts if "=" in p)
    words = [p for p in parts if "=" not in p]
    if len(words) < 2 or not words[1].isdigit():
        await connection.send(protocol.error("district needs '<target> <count> [sources] [gap=N] [break=0|1]'"))
        return
    target, count = words[0], int(words[1])
    sources = set(words[2].split(",")) if len(words) > 2 else {"minecraft:raw_iron"}
    gap = int(options.get("gap", 24))
    inject = options.get("break", "1") == "1"

    catalog = load_catalog()
    ranked = rank_chains(catalog, target, count, sources)
    if not ranked:
        await connection.send(protocol.error(f"no chain to {target}"))
        return
    scored = ranked[0]
    try:
        d = plan_district(scored.chain, gap=gap)
    except Exception as exc:
        await connection.send(protocol.error(f"district plan failed: {exc}"))
        return
    problems = validate_district(d)
    if problems:
        await connection.send(protocol.error(f"T0 rejected the district: {problems[:3]}"))
        return
    await connection.send(
        protocol.chat(
            f"[yan-agent] DISTRICT chain='{scored.chain.id}' shops={len(d.shops)} gap={gap} "
            f"trunks={[len(t.cells) for t in d.trunks]} backbone={len(d.backbone)} cells power={d.power_source}"
        )
    )
    busy = await _action(connection, "d-site", "inspect_blocks", {"positions": [_p(c).args() for c in d.footprint]})
    if [row for row in (busy.get("blocks") or []) if not row.get("is_air", False)]:
        await connection.send(protocol.error("district site is not clear"))
        return

    result: dict[str, Any] = {}
    passed = False
    try:
        damage, cut = _break_cell(d) if inject else (None, [])
        await _build(connection, d, omit=damage)
        if damage is not None:
            await connection.send(
                protocol.chat(f"[yan-agent] DAMAGE (generated): backbone cell {damage} missing; cuts machines {cut}")
            )
            result["damage"] = {"cell": damage, "cut_machines": cut}
        await _wait(connection, "d-power-settle", 60, 8.0)
        energy = await _energy(connection, d, "d-energy")
        await connection.send(protocol.chat(f"[yan-agent] VERIFY BACKBONE: machine energy={energy}"))
        expected_dark = set(cut)
        wrong = [i for i, e in enumerate(energy) if (e <= 0) != (i in expected_dark)]
        if wrong:
            raise RuntimeError(f"backbone power differs from plan (dark expected {sorted(expected_dark)}): {energy}")

        seed = scored.source_needed
        seeded = await _action(
            connection,
            "d-seed",
            "seed_item",
            {**_p(d.shops[0].layout.source).args(), "item": scored.chain.source_item, "count": seed},
        )
        if int(seeded.get("inserted") or 0) != seed:
            raise RuntimeError(f"seeded {seeded.get('inserted')}/{seed}")

        longest = max(int(catalog.fact(m.machine, "ticks_per_operation") or 200) for m in d.machines)
        budget = 3 * scored.ticks + 40 * len(d.transporters) + 2000
        repairs: list[dict[str, Any]] = []
        waited = last_change = 0
        previous: dict[str, Any] | None = None
        state: dict[str, Any] = {}
        expected = scored.output
        while waited < budget:
            await _action(connection, f"d-flow-{waited}", "wait_ticks", {"ticks": POLL_TICKS}, timeout=20.0)
            waited += POLL_TICKS
            state = await _read(connection, d, f"d-{waited}")
            done = state["chests"][-1] >= expected and not any(state["chests"][:-1])
            if done and state["transit"] == 0 and not any(state["machines"]):
                break
            if state != previous:
                last_change = waited
            elif waited - last_change > longest + POLL_TICKS:
                if len(repairs) >= 2:
                    break
                await connection.send(protocol.chat(f"[yan-agent] STALL at {waited} ticks: {state}"))
                repair = await _diagnose_and_repair(connection, d, f"d-repair{len(repairs) + 1}")
                repairs.append(repair)
                if not repair["missing"]:
                    break
                last_change = waited
            previous = state
        state["waited_ticks"] = waited
        state.pop("moving", None)
        result.update(state)
        result["repairs"] = repairs
        passed = (
            state["chests"][-1] == expected
            and not any(state["chests"][:-1])
            and not any(state["machines"])
            and state["transit"] == 0
            and (not inject or any(r["missing"] for r in repairs))
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    rolled: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        rolled = await _action(connection, "d-rollback", "rollback_session", {})
    result["world_clean"] = int(rolled.get("tracked_after", 1) or 0) == 0
    await connection.send(protocol.chat(f"[yan-agent] OBSERVE district: pass={passed} {result}"))
    if not passed:
        await connection.send(protocol.error(f"district v1 FAIL: {result}"))
        return
    save_skill(
        "district_" + "_".join(s.stage.machine.split(":")[1] for s in d.shops) + "_v1",
        description=f"District: {len(d.shops)} shops, freight trunk, one power backbone; chain {scored.chain.id}",
        implementation={
            "chain": scored.chain.id,
            "gap": gap,
            "shops": [{"machine": s.stage.machine, "source": s.layout.source, "sink": s.layout.sink} for s in d.shops],
            "trunks": [{"cells": t.cells, "pull": t.pull_face} for t in d.trunks],
            "power_source": d.power_source,
            "backbone": d.backbone,
        },
        verification={**result, "source_seeded": scored.source_needed, "output_planned": expected},
        source_experiment="yan-district-v1",
    )
    await connection.send(
        protocol.finish(
            f"district v1 PASS: shops={len(d.shops)} gap={gap} output={result['chests'][-1]}/{expected} "
            f"damage={result.get('damage', {}).get('cell')} repairs={len(result['repairs'])} "
            f"worldClean={str(result['world_clean']).lower()}"
        )
    )
