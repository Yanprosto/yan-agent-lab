"""Environment-aware routing planner for YAN v1.0.

The planner reasons over observed world cells, existing endpoints and obstacles. It does
not place blocks itself; it returns relative-coordinate paths for the live action layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from itertools import permutations
from typing import Iterable


Pos = tuple[int, int, int]

# Prefer horizontal routing, but allow climbing over/around obstacles.
DIRS: tuple[Pos, ...] = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 0, 1),
    (0, 0, -1),
    (0, 1, 0),
    (0, -1, 0),
)

SIDE_FROM_DELTA: dict[Pos, str] = {
    (1, 0, 0): "east",
    (-1, 0, 0): "west",
    (0, 1, 0): "up",
    (0, -1, 0): "down",
    (0, 0, 1): "south",
    (0, 0, -1): "north",
}


@dataclass(frozen=True)
class BranchRoute:
    sink: Pos
    path: tuple[Pos, ...]
    source_side: str

    def as_dict(self) -> dict:
        return {
            "sink": list(self.sink),
            "path": [list(p) for p in self.path],
            "source_side": self.source_side,
            "length": len(self.path),
        }


@dataclass(frozen=True)
class RoutePlan:
    plan_id: str
    mode: str
    branches: tuple[BranchRoute, BranchRoute]
    cost: int

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "mode": self.mode,
            "cost": self.cost,
            "branches": [b.as_dict() for b in self.branches],
        }


def add(a: Pos, b: Pos) -> Pos:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def sub(a: Pos, b: Pos) -> Pos:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def neighbors(pos: Pos) -> Iterable[Pos]:
    for delta in DIRS:
        yield add(pos, delta)


def _horizontal_or_up_neighbors(endpoint: Pos) -> list[Pos]:
    # Do not route down through the floor in the first environment-aware version.
    deltas = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0))
    return [add(endpoint, d) for d in deltas]


def _within(pos: Pos, bounds: tuple[Pos, Pos]) -> bool:
    lo, hi = bounds
    return (
        lo[0] <= pos[0] <= hi[0]
        and lo[1] <= pos[1] <= hi[1]
        and lo[2] <= pos[2] <= hi[2]
    )


def _path_cost(path: list[Pos]) -> int:
    if not path:
        return 10**9
    bends = 0
    vertical = 0
    prev_delta: Pos | None = None
    for a, b in zip(path, path[1:]):
        delta = sub(b, a)
        if delta[1]:
            vertical += 1
        if prev_delta is not None and delta != prev_delta:
            bends += 1
        prev_delta = delta
    return len(path) + bends * 2 + vertical * 3


def _astar(
    start: Pos,
    goals: set[Pos],
    *,
    blocked: set[Pos],
    bounds: tuple[Pos, Pos],
) -> list[Pos] | None:
    if start in blocked or not _within(start, bounds):
        return None

    queue: list[tuple[int, int, Pos]] = []
    heapq.heappush(queue, (min(manhattan(start, g) for g in goals), 0, start))
    came_from: dict[Pos, Pos] = {}
    best_g: dict[Pos, int] = {start: 0}

    while queue:
        _, g, current = heapq.heappop(queue)
        if current in goals:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        if g != best_g.get(current):
            continue

        for nxt in neighbors(current):
            if not _within(nxt, bounds) or nxt in blocked:
                continue
            step = 4 if nxt[1] != current[1] else 1
            new_g = g + step
            if new_g >= best_g.get(nxt, 10**9):
                continue
            best_g[nxt] = new_g
            came_from[nxt] = current
            h = min(manhattan(nxt, goal) for goal in goals)
            heapq.heappush(queue, (new_g + h, new_g, nxt))
    return None


def _source_side(source: Pos, start: Pos) -> str:
    delta = sub(source, start)
    side = SIDE_FROM_DELTA.get(delta)
    if side is None:
        raise ValueError(f"start {start} is not adjacent to source {source}")
    return side


def _clearance_cells(path: Iterable[Pos]) -> set[Pos]:
    cells: set[Pos] = set()
    for p in path:
        cells.add(p)
        cells.update(neighbors(p))
    return cells


def generate_route_plans(
    *,
    source: Pos,
    sinks: tuple[Pos, Pos],
    occupied: set[Pos],
    bounds: tuple[Pos, Pos],
    max_plans: int = 6,
) -> list[RoutePlan]:
    """Generate a naive shortest plan plus skill-informed network-separated plans."""

    endpoint_blocks = {source, *sinks}
    blocked_base = set(occupied) | endpoint_blocks
    starts = [p for p in _horizontal_or_up_neighbors(source) if p not in blocked_base and _within(p, bounds)]
    if len(starts) < 2:
        return []

    plans: list[RoutePlan] = []
    seen: set[tuple] = set()

    for sink_order in permutations(sinks):
        for start1 in starts:
            for start2 in starts:
                if start1 == start2:
                    continue

                goals1 = {
                    p for p in _horizontal_or_up_neighbors(sink_order[0])
                    if p not in blocked_base and _within(p, bounds)
                }
                goals2 = {
                    p for p in _horizontal_or_up_neighbors(sink_order[1])
                    if p not in blocked_base and _within(p, bounds)
                }
                if not goals1 or not goals2:
                    continue

                # First make a naive plan. The second route may run next to the first,
                # which can accidentally merge Mekanism networks and gives the repair
                # layer something real to diagnose when the environment forces it.
                path1 = _astar(start1, goals1, blocked=blocked_base | {start2}, bounds=bounds)
                if not path1:
                    continue
                path2 = _astar(
                    start2,
                    goals2,
                    blocked=blocked_base | set(path1),
                    bounds=bounds,
                )
                if path2:
                    key = ("naive", tuple(path1), tuple(path2))
                    if key not in seen:
                        seen.add(key)
                        branches = (
                            BranchRoute(sink_order[0], tuple(path1), _source_side(source, start1)),
                            BranchRoute(sink_order[1], tuple(path2), _source_side(source, start2)),
                        )
                        plans.append(RoutePlan(
                            plan_id=f"naive-{len(plans)+1}",
                            mode="naive",
                            branches=branches,
                            cost=_path_cost(path1) + _path_cost(path2),
                        ))

                # Then generate a skill-informed plan that keeps the two transporter
                # networks face-disconnected everywhere except through the source chest.
                separated_blocked = blocked_base | _clearance_cells(path1)
                separated_blocked.discard(start2)
                path2_sep = _astar(start2, goals2, blocked=separated_blocked, bounds=bounds)
                if path2_sep:
                    key = ("separated", tuple(path1), tuple(path2_sep))
                    if key not in seen:
                        seen.add(key)
                        branches = (
                            BranchRoute(sink_order[0], tuple(path1), _source_side(source, start1)),
                            BranchRoute(sink_order[1], tuple(path2_sep), _source_side(source, start2)),
                        )
                        plans.append(RoutePlan(
                            plan_id=f"separated-{len(plans)+1}",
                            mode="separated",
                            branches=branches,
                            cost=_path_cost(path1) + _path_cost(path2_sep),
                        ))

    # Try one cheap naive plan first, then prefer separated plans by route cost.
    naive = sorted((p for p in plans if p.mode == "naive"), key=lambda p: p.cost)
    separated = sorted((p for p in plans if p.mode == "separated"), key=lambda p: p.cost)
    ordered = (naive[:1] + separated)[:max_plans]
    return ordered


def replan_failed_branch(
    *,
    source: Pos,
    sink: Pos,
    occupied: set[Pos],
    working_path: set[Pos],
    bounds: tuple[Pos, Pos],
    avoid_paths: list[set[Pos]] | None = None,
) -> list[BranchRoute]:
    """Generate alternative routes for one failed branch while preserving the working one."""

    blocked_base = set(occupied) | {source, sink}
    blocked_base |= _clearance_cells(working_path)
    starts = [
        p for p in _horizontal_or_up_neighbors(source)
        if p not in blocked_base and _within(p, bounds)
    ]
    goals = {
        p for p in _horizontal_or_up_neighbors(sink)
        if p not in blocked_base and _within(p, bounds)
    }
    if not starts or not goals:
        return []

    avoided = avoid_paths or []
    options: list[tuple[int, BranchRoute]] = []
    for start in starts:
        for extra_avoid in [set(), *avoided]:
            path = _astar(
                start,
                goals,
                blocked=blocked_base | extra_avoid,
                bounds=bounds,
            )
            if not path:
                continue
            route = BranchRoute(sink, tuple(path), _source_side(source, start))
            if any(route.path == existing.path for _, existing in options):
                continue
            options.append((_path_cost(path), route))

    options.sort(key=lambda row: row[0])
    return [route for _, route in options[:4]]
