"""District planning (mode B, M3 step 3): shops joined by a freight trunk and one power backbone.

Each stage of a process chain becomes its own shop, laid out by the 3D solver in an open
box. Shops are placed ``gap`` blocks apart along +x. Then:

- the per-machine lab cubes are removed; one power source feeds every machine through a
  single cable network (the backbone), routed cell by cell and reusing laid cable;
- a freight trunk (transporters) runs from each shop's output chest to the next shop's
  input chest; those chests stay as buffers between shops.

The plan records every backbone cell, so a missing cell can later be found by comparing
the plan with a scan of the world (local repair).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from mcbuild.planner.layout3d import DIRS, Layout3D, Segment, Solver, _State, add, direction, neighbours
from mcbuild.planner.modules import translate
from mcbuild.planner.process_graph import ProcessChain, Stage

Pos = tuple[int, int, int]

SHOP_BOX = (9, 2, 5)  # open interior for one single-machine shop


@dataclass(frozen=True)
class Shop:
    stage: Stage
    layout: Layout3D  # district coordinates; machines keep their cable cell, cubes are unused


@dataclass(frozen=True)
class District:
    shops: tuple[Shop, ...]
    trunks: tuple[Segment, ...]  # trunks[i] joins shops[i].sink -> shops[i + 1].source
    power_source: Pos
    backbone: tuple[Pos, ...]  # every cable cell, including each machine's own cable cell
    backbone_pull: tuple[Pos, str]  # cable cell next to the power source and its face toward it

    @property
    def machines(self):
        return [m for s in self.shops for m in s.layout.machines]

    @property
    def chests(self) -> list[Pos]:
        return [c for s in self.shops for c in (s.layout.source, s.layout.sink)]

    @property
    def transporters(self) -> list[Pos]:
        cells = [c for s in self.shops for c in s.layout.transporters]
        return cells + [c for t in self.trunks for c in t.cells]

    @property
    def footprint(self) -> list[Pos]:
        cells = [*self.chests, *self.transporters, *self.backbone, self.power_source]
        cells += [m.pos for m in self.machines]
        return cells


class DistrictError(RuntimeError):
    pass


def _shop_layout(stage: Stage) -> Layout3D:
    sx, sy, sz = SHOP_BOX
    free = {(x, y, z) for x in range(sx) for y in range(sy) for z in range(sz)}
    chain = ProcessChain(stage.input_item, stage.output_item, (stage,))
    return Solver(free, (0, 0, sz // 2), (sx - 1, 0, sz // 2)).solve(chain, limit=1)[0]


def _route_cable(start: Pos, network: set[Pos], blocked: set[Pos], free: set[Pos]) -> list[Pos]:
    """Shortest cable path from ``start`` to any cell of ``network`` (start included)."""
    if start in network:
        return []
    parents: dict[Pos, Pos | None] = {start: None}
    queue: deque[Pos] = deque([start])
    while queue:
        cell = queue.popleft()
        for nxt in neighbours(cell):
            if nxt in network:
                path = []
                node: Pos | None = cell
                while node is not None:
                    path.append(node)
                    node = parents[node]
                return path
            if nxt in parents or nxt not in free or nxt in blocked:
                continue
            parents[nxt] = cell
            queue.append(nxt)
    raise DistrictError(f"no cable route from {start} to the backbone")


def plan_district(chain: ProcessChain, *, gap: int = 24) -> District:
    if not chain.stages:
        raise DistrictError("empty chain")
    shops = []
    for index, stage in enumerate(chain.stages):
        layout = _shop_layout(stage)
        offset = (index * (SHOP_BOX[0] + gap), 0, 0)
        shops.append(Shop(stage, translate(layout, offset)))

    span_x = len(shops) * (SHOP_BOX[0] + gap)
    free = {(x, y, z) for x in range(-2, span_x + 2) for y in range(0, 2) for z in range(-6, SHOP_BOX[2] + 6)}

    occupied: set[Pos] = set()
    inventories: set[Pos] = set()
    transporters: set[Pos] = set()
    for shop in shops:
        lay = shop.layout
        occupied |= {lay.source, lay.sink, *lay.transporters}
        inventories |= {lay.source, lay.sink}
        transporters |= set(lay.transporters)
        for m in lay.machines:
            occupied |= {m.pos, m.cable}
            inventories.add(m.pos)

    # Freight trunks between consecutive shops, with the same adjacency rules as shop segments.
    trunks: list[Segment] = []
    for a, b in zip(shops, shops[1:], strict=False):
        solver = Solver(free, a.layout.sink, b.layout.source)
        state = _State(
            machines=(),
            segments=(),
            occupied=frozenset(occupied),
            inventories=frozenset(inventories),
            transporters=frozenset(transporters),
            last=a.layout.sink,
        )
        path = solver.route(state, a.layout.sink, set(DIRS), b.layout.source)
        if not path:
            raise DistrictError(f"no freight trunk from {a.layout.sink} to {b.layout.source}")
        trunks.append(Segment(tuple(path), direction(path[0], a.layout.sink)))
        occupied |= set(path)
        transporters |= set(path)

    # One power source between the shops, away from transporters, then one cable network.
    mid_x = span_x // 2
    candidates = sorted(
        (c for c in free if c not in occupied and not any(n in transporters for n in neighbours(c))),
        key=lambda c: (abs(c[0] - mid_x) + abs(c[2] - (SHOP_BOX[2] + 3)) + c[1], c),
    )
    if not candidates:
        raise DistrictError("no cell for the power source")
    power = candidates[0]
    occupied.add(power)
    first = next((n for n in neighbours(power) if n in free and n not in occupied), None)
    if first is None:
        raise DistrictError("power source has no free side for the backbone")
    network: set[Pos] = {first}
    blocked = occupied - {m.cable for s in shops for m in s.layout.machines}
    blocked.discard(first)
    for machine in (m for s in shops for m in s.layout.machines):
        path = _route_cable(machine.cable, network, blocked, free | {machine.cable})
        network |= set(path) | {machine.cable}
        blocked -= set(path)
    backbone = tuple(sorted(network))
    return District(tuple(shops), tuple(trunks), power, backbone, (first, direction(first, power)))


def validate_district(district: District) -> list[str]:
    """Static checks (T0) for the cross-shop rules."""
    problems: list[str] = []
    cells = district.footprint
    if len(cells) != len(set(cells)):
        problems.append("overlapping cells")
    trunk_cells = {c for t in district.trunks for c in t.cells}
    inventories = set(district.chests) | {m.pos for m in district.machines} | {district.power_source}
    for i, trunk in enumerate(district.trunks):
        up = district.shops[i].layout.sink
        down = district.shops[i + 1].layout.source
        for k, cell in enumerate(trunk.cells):
            touch = {n for n in neighbours(cell) if n in inventories}
            allowed = ({up} if k == 0 else set()) | ({down} if k == len(trunk.cells) - 1 else set())
            if not touch <= allowed:
                problems.append(f"trunk {i} cell {cell} touches {sorted(touch - allowed)}")
    if any(n in trunk_cells or n in district.transporters for n in neighbours(district.power_source)):
        problems.append("power source touches a transporter")
    # backbone connectivity: every machine cable reaches the power-side cable
    net = set(district.backbone)
    seen = {district.backbone_pull[0]}
    queue = deque(seen)
    while queue:
        cell = queue.popleft()
        for n in neighbours(cell):
            if n in net and n not in seen:
                seen.add(n)
                queue.append(n)
    for m in district.machines:
        if m.cable not in seen:
            problems.append(f"machine at {m.pos} is not on the backbone")
        if add(m.pos, DIRS[m.energy_face]) != m.cable:
            problems.append(f"machine at {m.pos} energy face does not meet its cable")
    return problems
