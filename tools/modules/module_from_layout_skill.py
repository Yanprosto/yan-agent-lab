"""Pack a live-verified layout skill into a shop module (yan_knowledge/modules/).

Usage:
    python tools/modules/module_from_layout_skill.py SKILL.json --volume low_hall \
        --id iron_ingot_shop_v1 --run RUN_ID

Only layouts that passed live become modules (I16): the skill's verification must show
pass conditions, and the run id is recorded as evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcbuild.planner.layout3d import Layout3D, MachinePlace, Segment
from mcbuild.planner.modules import from_layout, save_module
from mcbuild.planner.volumes import VOLUMES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill", type=Path)
    parser.add_argument("--volume", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--seeded", type=int, help="source items per batch, if the skill predates source_seeded")
    args = parser.parse_args()

    skill = json.loads(args.skill.read_text(encoding="utf-8"))
    impl, ver = skill["implementation"], skill["verification"]
    if not (ver.get("source") == 0 and ver.get("transit") == 0 and not any(ver.get("machines", [1]))):
        raise SystemExit("skill verification does not show a passing run")
    volume = VOLUMES[args.volume]

    def t(v: list[int]) -> tuple[int, int, int]:
        return (int(v[0]), int(v[1]), int(v[2]))

    layout = Layout3D(
        volume.source,
        volume.sink,
        tuple(
            MachinePlace(m["machine"], t(m["pos"]), m["in"], m["energy"], t(m["cable"]), t(m["cube"]), m["out"])
            for m in impl["machines"]
        ),
        tuple(Segment(tuple(t(c) for c in s["cells"]), s["pull"]) for s in impl["segments"]),
    )
    chain = impl["chain"]
    stages = chain.split(" -> ")
    if not (ver.get("source_seeded") or args.seeded):
        raise SystemExit("batch size unknown: pass --seeded")
    contract = {
        "source_item": stages[0],
        "source_per_batch": int(ver.get("source_seeded") or args.seeded or 0),
        "output_item": stages[-1].split(":", 1)[1] if stages[-1].count(":") > 1 else stages[-1],
        "output_per_batch": int(ver.get("output_planned") or ver.get("output") or ver["sink"]),
    }
    evidence = {
        "level": "runtime_observed",
        "run_id": args.run,
        "verified_in_volume": args.volume,
        "lab": "headless NeoForge 21.1.255 + Mekanism 10.7.19.85",
        "skill": skill["skill_id"],
        "verified_at_utc": skill["verified_at_utc"],
    }
    module = from_layout(args.id, layout, chain, contract, evidence)
    path = save_module(module)
    print(f"{module.id}: size={module.size} ports={[(p.role, p.pos, p.outward) for p in module.ports]} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
