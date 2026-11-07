"""Test volumes for 3D layout (mode A: fit a factory into a given space).

Each volume is an interior air box with walls, floor and ceiling around it, optional
obstacles inside, and designated source and sink cells (where supply arrives and output
leaves). Coordinates are relative to the anchor; the interior starts at y = 0.

The lab builds the shell with plain ``fill`` commands, like pre-existing world the agent
does not own; the agent then scans the box and plans only on the cells it sees free.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Pos = tuple[int, int, int]
WALL = "minecraft:stone_bricks"


@dataclass(frozen=True)
class Volume:
    name: str
    size: Pos  # interior (x, y, z)
    source: Pos
    sink: Pos
    obstacles: tuple[tuple[Pos, Pos], ...] = field(default=())  # inclusive boxes inside

    @property
    def interior(self) -> tuple[Pos, Pos]:
        sx, sy, sz = self.size
        return (0, 0, 0), (sx - 1, sy - 1, sz - 1)

    def cells(self) -> list[Pos]:
        sx, sy, sz = self.size
        return [(x, y, z) for x in range(sx) for y in range(sy) for z in range(sz)]

    def expected_free(self) -> set[Pos]:
        blocked: set[Pos] = set()
        for (x0, y0, z0), (x1, y1, z1) in self.obstacles:
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    for z in range(z0, z1 + 1):
                        blocked.add((x, y, z))
        return {c for c in self.cells() if c not in blocked}

    def build_commands(self, anchor: Pos) -> list[str]:
        """RCON commands that clear the site and build the shell and obstacles."""
        ax, ay, az = anchor
        sx, sy, sz = self.size

        def box(a: Pos, b: Pos, block: str) -> str:
            return f"fill {ax + a[0]} {ay + a[1]} {az + a[2]} {ax + b[0]} {ay + b[1]} {az + b[2]} {block}"

        commands = [
            box((-3, -1, -3), (sx + 2, sy + 2, sz + 2), "minecraft:air"),
            box((-1, -1, -1), (sx, sy, sz), WALL),
            box((0, 0, 0), (sx - 1, sy - 1, sz - 1), "minecraft:air"),
        ]
        commands += [box(a, b, WALL) for a, b in self.obstacles]
        return commands


VOLUMES: dict[str, Volume] = {
    "low_hall": Volume("low_hall", size=(14, 2, 5), source=(0, 0, 2), sink=(13, 0, 2)),
    "shaft": Volume("shaft", size=(4, 12, 4), source=(0, 0, 0), sink=(3, 11, 3)),
    "columns": Volume(
        "columns",
        size=(14, 3, 9),
        source=(0, 0, 4),
        sink=(13, 0, 4),
        obstacles=(
            ((3, 0, 2), (3, 2, 2)),
            ((3, 0, 6), (3, 2, 6)),
            ((10, 0, 2), (10, 2, 2)),
            ((10, 0, 6), (10, 2, 6)),
            ((6, 0, 0), (6, 2, 5)),  # wall from the north side, gap only at z 6..8
        ),
    ),
}
