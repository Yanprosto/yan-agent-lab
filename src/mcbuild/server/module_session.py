"""Build a shop from its module description in a scanned volume and verify it (M3 step 2).

Command spec: ``<module id> <volume>``. The volume shell must exist at the anchor.
The session scans the interior, finds a placement (rotation + offset) whose cells and
port approaches are free, checks the placed layout statically (T0), builds it, runs the
module's contract (one batch) and rolls back.
"""

from __future__ import annotations

import contextlib
from typing import Any

from mcbuild.catalog import load_catalog
from mcbuild.planner.layout3d import validate
from mcbuild.planner.modules import list_modules, load_module, place_in, translate
from mcbuild.planner.volumes import VOLUMES
from mcbuild.server import protocol
from mcbuild.server.layout_session import scan_free, verify_layout
from mcbuild.server.mission_session import _action
from mcbuild.server.skill_store import save_skill


async def run_module_session(spec: str, connection) -> None:
    await connection.send(protocol.hello("yan-shop-module-v1"))
    parts = spec.split()
    if len(parts) != 2 or parts[0] not in list_modules() or parts[1] not in VOLUMES:
        await connection.send(
            protocol.error(
                f"module needs '<module id> <volume>'; modules: {list_modules()}; volumes: {sorted(VOLUMES)}"
            )
        )
        return
    module = load_module(parts[0])
    volume = VOLUMES[parts[1]]
    free = await scan_free(connection, volume)
    placements = place_in(module, free)
    await connection.send(
        protocol.chat(
            f"[yan-agent] MODULE {module.id}: size={module.size} contract={module.contract['source_per_batch']}x"
            f"{module.contract['source_item']} -> "
            f"{module.contract['output_per_batch']}x{module.contract['output_item']}; "
            f"{volume.name} free={len(free)}; placements={len(placements)}"
        )
    )
    if not placements:
        await connection.send(
            protocol.error(f"module {module.id} does not fit {volume.name} with free port approaches")
        )
        return

    turns, offset, rotated = placements[0]
    layout = translate(rotated.layout, offset)
    problems = validate(layout, free)
    if problems:
        await connection.send(protocol.error(f"T0 rejected the placement: {problems[:3]}"))
        return
    ports = ", ".join(
        f"{p.role}@{tuple(p.pos[i] + offset[i] for i in range(3))} facing {p.outward}" for p in rotated.ports
    )
    await connection.send(
        protocol.chat(f"[yan-agent] PLACE {module.id}: turns={turns} offset={offset} size={rotated.size}; {ports}")
    )

    catalog = load_catalog()
    longest = max(int(catalog.fact(m.machine, "ticks_per_operation") or 200) for m in layout.machines)
    seed = int(module.contract["source_per_batch"])
    expected = int(module.contract["output_per_batch"])
    budget = 2 * seed * longest + 40 * len(layout.transporters) + 600
    state: dict[str, Any]
    try:
        passed, state = await verify_layout(
            connection,
            layout,
            "mod",
            source_item=module.contract["source_item"],
            target_item=module.contract["output_item"],
            seed=seed,
            expected=expected,
            budget=budget,
            longest_op=longest,
        )
    except Exception as exc:
        failure: dict[str, Any] = {"diagnosis": f"{type(exc).__name__}: {exc}"}
        passed, state = False, failure
    rolled: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        rolled = await _action(connection, "mod-rollback", "rollback_session", {})
    state["world_clean"] = int(rolled.get("tracked_after", 1) or 0) == 0
    await connection.send(
        protocol.chat(
            f"[yan-agent] OBSERVE {module.id} in {volume.name}: pass={passed} "
            + " ".join(f"{k}={v}" for k, v in state.items() if k != "diagnosis")
        )
    )
    if not passed:
        await connection.send(protocol.error(f"shop module v1 FAIL: {state.get('diagnosis')}"))
        return
    save_skill(
        f"module_placement_{module.id}_{volume.name}",
        description=f"Shop module {module.id} built from its description in {volume.name}",
        implementation={"module": module.id, "volume": volume.name, "turns": turns, "offset": offset},
        verification={**state, "source_seeded": seed, "output_planned": expected},
        source_experiment="yan-shop-module-v1",
    )
    await connection.send(
        protocol.finish(
            f"shop module v1 PASS: module={module.id} volume={volume.name} turns={turns} offset={offset} "
            f"output={state['sink']}/{expected} worldClean={str(state['world_clean']).lower()}"
        )
    )
