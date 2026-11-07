"""3D layout of a process chain inside a scanned volume (mode A).

Beam search over stages. For each stage the solver picks a machine cell, routes a
transporter segment from the previous inventory to a free face of the machine (3D BFS),
and attaches power (cable on an energy face, charged cube next to the cable). The last
segment runs to the sink.

Mekanism transporters connect to everything around them, so the adjacency rules are
strict:

- a segment's first cell touches only its upstream inventory, its last cell only its
  downstream inventory, every middle cell touches no inventory at all;
- cells of different segments never touch (they would merge into one network);
- inventories are chests, machines and energy cubes (cubes have item slots).

Machine sides follow the actual geometry: item INPUT toward the arriving segment,
OUTPUT toward the leaving one, ENERGY INPUT toward the cable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace

from mcbuild.planner.process_graph import ProcessChain, Stage

Pos = tuple[int, int, int]

DIRS: dict[str, Pos] = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}


def add(a: Pos, b: Pos) -> Pos:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def direction(frm: Pos, to: Pos) -> str:
    delta = (to[0] - frm[0], to[1] - frm[1], to[2] - frm[2])
    for name, vec in DIRS.items():
        if vec == delta:
            return name
    raise ValueError(f"{frm} and {to} are not neighbours")


def neighbours(p: Pos) -> list[Pos]:
    return [add(p, d) for d in DIRS.values()]


@dataclass(frozen=True)
class MachinePlace:
    machine: str
    pos: Pos
    in_face: str
    energy_face: str
    cable: Pos
    cube: Pos
    out_face: str | None = None


@dataclass(frozen=True)
class Segment:
    cells: tuple[Pos, ...]
    pull_face: str  # from cells[0] toward the upstream inventory


@dataclass(frozen=True)
class Layout3D:
    source: Pos
    sink: Pos
    machines: tuple[MachinePlace, ...]
    segments: tuple[Segment, ...]
    # False: a linear chain source -> m1 -> ... -> sink, segment i joins chain_inv[i] and [i + 1].
    # True: one stage with several parallel machines; segments are in_0, out_0, in_1, out_1, ...
    # (source -> m_j and m_j -> sink), every machine fed by its own independent PULL transporter.
    fan_out: bool = False

    def links(self) -> list[tuple[Pos, Pos]]:
        """(upstream inventory, downstream inventory) for every segment, in segment order."""
        if self.fan_out:
            return [pair for m in self.machines for pair in ((self.source, m.pos), (m.pos, self.sink))]
        chain_inv = [self.source, *(m.pos for m in self.machines), self.sink]
        return list(zip(chain_inv, chain_inv[1:], strict=False))

    @property
    def transporters(self) -> list[Pos]:
        return [c for s in self.segments for c in s.cells]

    @property
    def cost(self) -> int:
        return len(self.transporters)

    @property
    def footprint(self) -> list[Pos]:
        cells = [self.source, self.sink, *self.transporters]
        for m in self.machines:
            cells += [m.pos, m.cable, m.cube]
        return cells

    def signature(self) -> tuple:
        """Geometry fingerprint, used to tell layouts apart."""
        return tuple(sorted(self.footprint))


@dataclass(frozen=True)
class _State:
    machines: tuple[MachinePlace, ...]
    segments: tuple[Segment, ...]
    occupied: frozenset[Pos]
    inventories: frozenset[Pos]
    transporters: frozenset[Pos]
    last: Pos
    last_used: frozenset[str] = field(default=frozenset())

    @property
    def cost(self) -> int:
        return len(self.transporters)


class LayoutError(RuntimeError):
    pass


class Solver:
    def __init__(self, free: set[Pos], source: Pos, sink: Pos, *, beam: int = 6, candidates: int = 30):
        if source not in free or sink not in free:
            raise LayoutError("source and sink must be free cells of the volume")
        if sink in neighbours(source):
            raise LayoutError("source and sink chests must not touch (they would merge)")
        self.free = free
        self.source = source
        self.sink = sink
        self.beam = beam
        self.candidates = candidates

    # --- helpers ---
    def _touching(self, cell: Pos, state: _State, extra: frozenset[Pos] = frozenset()) -> set[Pos]:
        inventories = state.inventories | extra
        return {n for n in neighbours(cell) if n in inventories}

    def _cell_ok(self, cell: Pos, state: _State, path: set[Pos]) -> bool:
        if cell not in self.free or cell in state.occupied or cell in path:
            return False
        return not any(n in state.transporters for n in neighbours(cell))

    def route(
        self, state: _State, frm: Pos, frm_faces: set[str], to: Pos, extra_inv: frozenset[Pos] = frozenset()
    ) -> list[Pos] | None:
        """Shortest transporter path from inventory ``frm`` to inventory ``to``."""
        allowed_to = set(DIRS)
        starts = []
        for name in frm_faces:
            cell = add(frm, DIRS[name])
            if not self._cell_ok(cell, state, set()):
                continue
            touch = self._touching(cell, state, extra_inv)
            if touch == {frm} or touch == {frm, to}:
                starts.append(cell)
        parents: dict[Pos, Pos | None] = {}
        queue: deque[Pos] = deque()
        for cell in starts:
            parents[cell] = None
            queue.append(cell)
        while queue:
            cell = queue.popleft()
            touch = self._touching(cell, state, extra_inv)
            if to in touch and direction(to, cell) in allowed_to:
                path = []
                node: Pos | None = cell
                while node is not None:
                    path.append(node)
                    node = parents[node]
                return list(reversed(path))
            for nxt in neighbours(cell):
                if nxt in parents or not self._cell_ok(nxt, state, set()):
                    continue
                touch_next = self._touching(nxt, state, extra_inv)
                if touch_next and touch_next != {to}:
                    continue
                parents[nxt] = cell
                queue.append(nxt)
        return None

    def _power(self, state: _State, m: Pos, path: list[Pos], used: set[str]) -> tuple[str, Pos, Pos] | None:
        blocked = set(path) | {m}
        for face in sorted(set(DIRS) - used, key=lambda f: (f in ("up", "down"), f)):
            cable = add(m, DIRS[face])
            if cable not in self.free or cable in state.occupied or cable in blocked:
                continue
            straight = add(cable, DIRS[face])
            options = [straight] + [n for n in neighbours(cable) if n not in (straight, m)]
            for cube in options:
                if cube not in self.free or cube in state.occupied or cube in blocked or cube == cable:
                    continue
                if any(n in state.transporters or n in path for n in neighbours(cube)):
                    continue
                # keep at least one free face for the output segment
                remaining = set(DIRS) - used - {face}
                if not any(
                    add(m, DIRS[f]) in self.free
                    and add(m, DIRS[f]) not in state.occupied
                    and add(m, DIRS[f]) not in (cable, cube, *path)
                    for f in remaining
                ):
                    continue
                return face, cable, cube
        return None

    def _candidates(self, state: _State, index: int, total: int) -> list[Pos]:
        t = (index + 1) / (total + 1)
        target = tuple(self.source[i] + (self.sink[i] - self.source[i]) * t for i in range(3))
        cells = [
            c for c in self.free if c not in state.occupied and not any(n in state.transporters for n in neighbours(c))
        ]
        cells.sort(key=lambda c: (sum(abs(c[i] - target[i]) for i in range(3)), c))
        return cells[: self.candidates]

    # --- fan-out: one stage, several parallel machines ---
    def solve_fan(self, stage: Stage, count: int, *, attempts: int = 12) -> Layout3D:
        """Place ``count`` parallel machines between ``source`` and ``sink``.

        Every machine gets its own independent segment source -> machine (first cell PULLs
        from the source chest) and machine -> sink (first cell PULLs from the machine).
        This is the live-verified dual-independent-PULL pattern; a shared T-junction would
        starve a branch. Depth-first with backtracking over candidate machine cells.
        """
        xs = [c[0] for c in self.free]
        ys = [c[1] for c in self.free]
        zs = [c[2] for c in self.free]
        mid_x = (min(xs) + max(xs)) / 2
        start = _State(
            machines=(),
            segments=(),
            occupied=frozenset({self.source, self.sink}),
            inventories=frozenset({self.source, self.sink}),
            transporters=frozenset(),
            last=self.source,
        )

        def targets(j: int) -> tuple[float, float, float]:
            span = max(zs) - min(zs)
            return (mid_x, float(min(ys)), min(zs) + span * (j + 0.5) / count)

        def place(j: int, state: _State) -> _State | None:
            if j == count:
                return state
            target = targets(j)
            cells = [
                c
                for c in self.free
                if c not in state.occupied and not any(n in state.transporters for n in neighbours(c))
            ]
            cells.sort(key=lambda c: (sum(abs(c[i] - target[i]) for i in range(3)), c))
            for m in cells[: self.candidates]:
                nxt = self._place_fan_machine(state, stage, m)
                if nxt is None:
                    continue
                done = place(j + 1, nxt)
                if done is not None:
                    return done
                attempts_left[0] -= 1
                if attempts_left[0] <= 0:
                    return None
            return None

        attempts_left = [attempts * count]
        final = place(0, start)
        if final is None:
            raise LayoutError(f"no fan-out placement for {count} x {stage.machine}")
        return Layout3D(self.source, self.sink, final.machines, final.segments, True)

    def _place_fan_machine(self, state: _State, stage: Stage, m: Pos) -> _State | None:
        path_in = self.route(state, self.source, set(DIRS), m, extra_inv=frozenset({m}))
        if not path_in:
            return None
        in_face = direction(m, path_in[-1])
        power = self._power(state, m, path_in, {in_face})
        if not power:
            return None
        energy_face, cable, cube = power
        with_in = _State(
            machines=state.machines,
            segments=state.segments,
            occupied=state.occupied | {m, cable, cube, *path_in},
            inventories=state.inventories | {m, cube},
            transporters=state.transporters | set(path_in),
            last=m,
        )
        path_out = self.route(with_in, m, set(DIRS) - {in_face, energy_face}, self.sink)
        if not path_out:
            return None
        place = MachinePlace(stage.machine, m, in_face, energy_face, cable, cube, direction(m, path_out[0]))
        return _State(
            machines=(*state.machines, place),
            segments=(
                *state.segments,
                Segment(tuple(path_in), direction(path_in[0], self.source)),
                Segment(tuple(path_out), direction(path_out[0], m)),
            ),
            occupied=with_in.occupied | set(path_out),
            inventories=with_in.inventories,
            transporters=with_in.transporters | set(path_out),
            last=m,
        )

    # --- search ---
    def solve(self, chain: ProcessChain, *, limit: int = 3) -> list[Layout3D]:
        start = _State(
            machines=(),
            segments=(),
            occupied=frozenset({self.source, self.sink}),
            inventories=frozenset({self.source, self.sink}),
            transporters=frozenset(),
            last=self.source,
            last_used=frozenset(),
        )
        beam = [start]
        total = len(chain.stages)
        for index, stage in enumerate(chain.stages):
            expanded: list[_State] = []
            for state in beam:
                frm_faces = set(DIRS) - set(state.last_used)
                for m in self._candidates(state, index, total):
                    path = self.route(state, state.last, frm_faces, m, extra_inv=frozenset({m}))
                    if not path:
                        continue
                    in_face = direction(m, path[-1])
                    power = self._power(state, m, path, {in_face})
                    if not power:
                        continue
                    energy_face, cable, cube = power
                    machines = state.machines
                    if machines and state.last == machines[-1].pos:
                        machines = (*machines[:-1], replace(machines[-1], out_face=direction(state.last, path[0])))
                    place = MachinePlace(stage.machine, m, in_face, energy_face, cable, cube)
                    pull_face = direction(path[0], state.last)
                    expanded.append(
                        _State(
                            machines=(*machines, place),
                            segments=(*state.segments, Segment(tuple(path), pull_face)),
                            occupied=state.occupied | {m, cable, cube, *path},
                            inventories=state.inventories | {m, cube},
                            transporters=state.transporters | set(path),
                            last=m,
                            last_used=frozenset({in_face, energy_face}),
                        )
                    )
            expanded.sort(key=lambda s: (s.cost, [mp.pos for mp in s.machines]))
            beam = expanded[: self.beam]
            if not beam:
                raise LayoutError(f"no placement for stage {index + 1} ({stage.machine})")

        layouts: list[Layout3D] = []
        seen: set[tuple] = set()
        for state in beam:
            frm_faces = set(DIRS) - set(state.last_used)
            path = self.route(state, state.last, frm_faces, self.sink)
            if not path:
                continue
            machines = state.machines
            if machines:
                machines = (*machines[:-1], replace(machines[-1], out_face=direction(state.last, path[0])))
            layout = Layout3D(
                source=self.source,
                sink=self.sink,
                machines=machines,
                segments=(*state.segments, Segment(tuple(path), direction(path[0], state.last))),
            )
            if layout.signature() not in seen:
                seen.add(layout.signature())
                layouts.append(layout)
        if not layouts:
            raise LayoutError("no route from the last machine to the sink")
        layouts.sort(key=lambda lay: lay.cost)
        return layouts[:limit]


def validate(layout: Layout3D, free: set[Pos]) -> list[str]:
    """Independent static check of a layout (evaluation tier T0). Empty list = valid."""
    problems: list[str] = []
    cells = layout.footprint
    if len(cells) != len(set(cells)):
        problems.append("overlapping cells")
    problems += [f"cell {c} is not free" for c in cells if c not in free]
    inventories = {layout.source, layout.sink} | {m.pos for m in layout.machines} | {m.cube for m in layout.machines}
    if layout.sink in neighbours(layout.source):
        problems.append("source and sink chests touch")
    links = layout.links()
    if len(layout.segments) != len(links):
        problems.append("segment count does not match the layout")
        return problems
    owner = {c: i for i, s in enumerate(layout.segments) for c in s.cells}
    for i, seg in enumerate(layout.segments):
        up, down = links[i]
        for k, cell in enumerate(seg.cells):
            touch = {n for n in neighbours(cell) if n in inventories}
            allowed: set[Pos] = set()
            if k == 0:
                allowed.add(up)
            if k == len(seg.cells) - 1:
                allowed.add(down)
            if not touch <= allowed:
                problems.append(f"segment {i} cell {cell} touches {sorted(touch - allowed)}")
            for n in neighbours(cell):
                if n in owner and owner[n] != i:
                    problems.append(f"segments {i} and {owner[n]} touch at {cell}")
        if up not in neighbours(seg.cells[0]) or direction(seg.cells[0], up) != seg.pull_face:
            problems.append(f"segment {i} does not start at its upstream inventory")
        if down not in neighbours(seg.cells[-1]):
            problems.append(f"segment {i} does not end at its downstream inventory")
    for i, m in enumerate(layout.machines):
        in_seg = layout.segments[2 * i] if layout.fan_out else layout.segments[i]
        out_seg = layout.segments[2 * i + 1] if layout.fan_out else layout.segments[i + 1]
        faces = [m.in_face, m.out_face, m.energy_face]
        if None in faces or len(set(faces)) != 3:
            problems.append(f"machine {i} faces are not three distinct sides: {faces}")
        if add(m.pos, DIRS[m.in_face]) != in_seg.cells[-1]:
            problems.append(f"machine {i} input face does not meet its incoming segment")
        if m.out_face and add(m.pos, DIRS[m.out_face]) != out_seg.cells[0]:
            problems.append(f"machine {i} output face does not meet its outgoing segment")
        if add(m.pos, DIRS[m.energy_face]) != m.cable or m.cube not in neighbours(m.cable):
            problems.append(f"machine {i} power is not machine-cable-cube")
        if any(n in owner for n in neighbours(m.cube)):
            problems.append(f"machine {i} cube touches a transporter")
    return problems
