"""Shop modules: verified layouts packed as portable bricks with ports (M3 step 2).

A module is a layout that passed live, stored in its own coordinates (bounding box
from the origin) with:

- ports: the input and output buffer chests on its boundary, each with an outward
  face (where a district trunk line will attach later);
- power: currently self-contained (one charged cube per machine; a power port comes
  with the shared backbone in step 3);
- a contract: N source items -> M output items, with the run that verified it.

A module can be rotated around Y in 90-degree steps (face names rotate with it) and
translated; ``place_in`` finds placements that fit a scanned volume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcbuild.planner.layout3d import DIRS, Layout3D, MachinePlace, Segment, add, neighbours

Pos = tuple[int, int, int]

# Rotation by 90 degrees clockwise seen from above: east -> south -> west -> north.
_ROTATE_FACE = {"east": "south", "south": "west", "west": "north", "north": "east", "up": "up", "down": "down"}


@dataclass(frozen=True)
class Port:
    role: str  # "item_in" | "item_out"
    pos: Pos
    outward: str  # face of the port block that points out of the module
    item: str


@dataclass(frozen=True)
class ShopModule:
    id: str
    chain: str
    size: Pos
    layout: Layout3D  # in module coordinates; layout.source / layout.sink are the port chests
    ports: tuple[Port, ...]
    contract: dict[str, Any]
    evidence: dict[str, Any]

    def port(self, role: str) -> Port:
        return next(p for p in self.ports if p.role == role)


def _rotate_pos(p: Pos, size: Pos) -> Pos:
    # (x, z) -> (size_z - 1 - z, x): a clockwise quarter turn keeping coordinates >= 0
    x, y, z = p
    return (size[2] - 1 - z, y, x)


def rotate(module: ShopModule, turns: int) -> ShopModule:
    result = module
    for _ in range(turns % 4):
        size = result.size
        lay = result.layout

        def rp(p: Pos, size: Pos = size) -> Pos:
            return _rotate_pos(p, size)

        machines = tuple(
            MachinePlace(
                machine=m.machine,
                pos=rp(m.pos),
                in_face=_ROTATE_FACE[m.in_face],
                energy_face=_ROTATE_FACE[m.energy_face],
                cable=rp(m.cable),
                cube=rp(m.cube),
                out_face=_ROTATE_FACE[m.out_face] if m.out_face else None,
            )
            for m in lay.machines
        )
        segments = tuple(Segment(tuple(rp(c) for c in s.cells), _ROTATE_FACE[s.pull_face]) for s in lay.segments)
        new_layout = Layout3D(rp(lay.source), rp(lay.sink), machines, segments, lay.fan_out)
        ports = tuple(Port(p.role, rp(p.pos), _ROTATE_FACE[p.outward], p.item) for p in result.ports)
        result = ShopModule(
            result.id, result.chain, (size[2], size[1], size[0]), new_layout, ports, result.contract, result.evidence
        )
    return result


def translate(layout: Layout3D, offset: Pos) -> Layout3D:
    def tp(p: Pos) -> Pos:
        return add(p, offset)

    return Layout3D(
        tp(layout.source),
        tp(layout.sink),
        tuple(
            MachinePlace(m.machine, tp(m.pos), m.in_face, m.energy_face, tp(m.cable), tp(m.cube), m.out_face)
            for m in layout.machines
        ),
        tuple(Segment(tuple(tp(c) for c in s.cells), s.pull_face) for s in layout.segments),
        layout.fan_out,
    )


def _outward(pos: Pos, footprint: set[Pos], size: Pos) -> str:
    """Face of a port block that leads out of the module: prefer faces leaving the box."""
    best = None
    for name, vec in DIRS.items():
        n = add(pos, vec)
        if n in footprint or name in ("up", "down"):
            continue
        outside = not all(0 <= n[i] < size[i] for i in range(3))
        if outside:
            return name
        best = best or name
    if best is None:
        raise ValueError(f"port at {pos} has no free side")
    return best


def from_layout(
    module_id: str, layout: Layout3D, chain: str, contract: dict[str, Any], evidence: dict[str, Any]
) -> ShopModule:
    cells = layout.footprint
    lo = tuple(min(c[i] for c in cells) for i in range(3))
    hi = tuple(max(c[i] for c in cells) for i in range(3))
    norm = translate(layout, (-lo[0], -lo[1], -lo[2]))
    size = (hi[0] - lo[0] + 1, hi[1] - lo[1] + 1, hi[2] - lo[2] + 1)
    footprint = set(norm.footprint)
    ports = (
        Port("item_in", norm.source, _outward(norm.source, footprint, size), contract["source_item"]),
        Port("item_out", norm.sink, _outward(norm.sink, footprint, size), contract["output_item"]),
    )
    return ShopModule(module_id, chain, size, norm, ports, contract, evidence)


def place_in(module: ShopModule, free: set[Pos], *, limit: int = 5) -> list[tuple[int, Pos, ShopModule]]:
    """Placements (turns, offset, rotated module) whose cells and port approaches are free.

    The approach cell in front of each port's outward face must be free and must not
    touch module transporters, so a trunk line can attach there later.
    """
    if not free:
        return []
    lo = tuple(min(c[i] for c in free) for i in range(3))
    hi = tuple(max(c[i] for c in free) for i in range(3))
    found: list[tuple[int, Pos, ShopModule]] = []
    for turns in range(4):
        rotated = rotate(module, turns)
        cells = rotated.layout.footprint
        transporters = set(rotated.layout.transporters)
        for ox in range(lo[0], hi[0] - rotated.size[0] + 2):
            for oy in range(lo[1], hi[1] - rotated.size[1] + 2):
                for oz in range(lo[2], hi[2] - rotated.size[2] + 2):
                    offset = (ox, oy, oz)
                    if not all(add(c, offset) in free for c in cells):
                        continue
                    ok = True
                    for port in rotated.ports:
                        approach = add(add(port.pos, DIRS[port.outward]), offset)
                        shifted_t = {add(t, offset) for t in transporters}
                        if approach not in free or any(n in shifted_t for n in neighbours(approach)):
                            ok = False
                    if ok:
                        found.append((turns, offset, rotated))
                        if len(found) >= limit:
                            return found
    return found


# --- storage ---


def _modules_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "yan_knowledge" / "modules"


def to_json(module: ShopModule) -> dict[str, Any]:
    lay = module.layout
    return {
        "id": module.id,
        "chain": module.chain,
        "size": module.size,
        "ports": [{"role": p.role, "pos": p.pos, "outward": p.outward, "item": p.item} for p in module.ports],
        "power": "self-contained: one charged creative cube per machine (lab); power port comes with the backbone",
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
            for m in lay.machines
        ],
        "segments": [{"cells": s.cells, "pull": s.pull_face} for s in lay.segments],
        "fan_out": lay.fan_out,
        "contract": module.contract,
        "evidence": module.evidence,
    }


def from_json(data: dict[str, Any]) -> ShopModule:
    def t(v: Any) -> Pos:
        return (int(v[0]), int(v[1]), int(v[2]))

    ports = tuple(Port(p["role"], t(p["pos"]), p["outward"], p["item"]) for p in data["ports"])
    source = next(p.pos for p in ports if p.role == "item_in")
    sink = next(p.pos for p in ports if p.role == "item_out")
    machines = tuple(
        MachinePlace(m["machine"], t(m["pos"]), m["in"], m["energy"], t(m["cable"]), t(m["cube"]), m["out"])
        for m in data["machines"]
    )
    segments = tuple(Segment(tuple(t(c) for c in s["cells"]), s["pull"]) for s in data["segments"])
    return ShopModule(
        data["id"],
        data["chain"],
        t(data["size"]),
        Layout3D(source, sink, machines, segments, bool(data.get("fan_out", False))),
        ports,
        data["contract"],
        data["evidence"],
    )


def save_module(module: ShopModule) -> Path:
    directory = _modules_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{module.id}.json"
    path.write_text(json.dumps(to_json(module), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_module(module_id: str) -> ShopModule:
    path = _modules_dir() / f"{module_id}.json"
    return from_json(json.loads(path.read_text(encoding="utf-8")))


def list_modules() -> list[str]:
    directory = _modules_dir()
    return sorted(p.stem for p in directory.glob("*.json")) if directory.is_dir() else []
