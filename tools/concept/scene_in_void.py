"""Concept pictures for WORLD §3d: a ~100-block "scene" inside a vast "mass".

A mock-up for judging the look, **not** generator output: vanilla blocks stand in for machines
(orange = Mekanism machines, cyan = power cable, dark = freight trunk). Deterministic.

    uv run python tools/concept/scene_in_void.py --out docs/images

Writes ``concept-scene-in-void.png`` (overview) and ``concept-mass-interior.png`` (cutaway of one
enterable giant form, with something to find inside).
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image

from mcbuild.palette import get_block
from mcbuild.render.iso import render_iso
from mcbuild.voxel import VoxelGrid

Pos = tuple[int, int, int]
BACKGROUND = (22, 26, 36)

DARK = "black_concrete"
MASS = "light_gray_concrete"
RIB = "gray_concrete"
LIGHT = "sea_lantern"
WARM = "shroomlight"


class Canvas:
    def __init__(self) -> None:
        self.grid = VoxelGrid()
        self._index: dict[str, int] = {}

    def _idx(self, name: str) -> int:
        if name not in self._index:
            self._index[name] = get_block(name).index
        return self._index[name]

    def put(self, x: int, y: int, z: int, name: str) -> None:
        self.grid.set(x, y, z, self._idx(name))

    def clear(self, a: Pos, b: Pos) -> None:
        for x in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
            for y in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
                for z in range(min(a[2], b[2]), max(a[2], b[2]) + 1):
                    self.grid.clear_block(x, y, z)

    def box(self, a: Pos, b: Pos, name: str) -> None:
        for x in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
            for y in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
                for z in range(min(a[2], b[2]), max(a[2], b[2]) + 1):
                    self.put(x, y, z, name)

    def shell(self, a: Pos, b: Pos, name: str, wall: int = 2) -> None:
        (x0, y0, z0), (x1, y1, z1) = (min(a[i], b[i]) for i in range(3)), (max(a[i], b[i]) for i in range(3))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    inner = x0 + wall <= x <= x1 - wall and y0 + wall <= y <= y1 - wall and z0 + wall <= z <= z1 - wall
                    if not inner:
                        self.put(x, y, z, name)

    def line(self, a: Pos, b: Pos, name: str) -> None:
        steps = max(abs(b[i] - a[i]) for i in range(3)) or 1
        for s in range(steps + 1):
            x, y, z = (round(a[i] + (b[i] - a[i]) * s / steps) for i in range(3))
            self.put(x, y, z, name)


def lattice_pillar(c: Canvas, x: int, z: int, y0: int, y1: int, size: int = 12, ring_every: int = 30) -> None:
    """Open truss tower: corner posts, rings with lamps, X braces. You can walk through it."""
    far = size - 1
    for dx in (0, far - 1):
        for dz in (0, far - 1):
            c.box((x + dx, y0, z + dz), (x + dx + 1, y1, z + dz + 1), RIB)
    ys = list(range(y0, y1 + 1, ring_every))
    for y in ys:
        c.box((x, y, z), (x + far, y + 1, z + far), MASS)
        c.clear((x + 2, y, z + 2), (x + far - 2, y + 1, z + far - 2))
        for k in range(2, far - 1, 3):
            for px, pz in ((x + k, z), (x + k, z + far), (x, z + k), (x + far, z + k)):
                c.put(px, y + 1, pz, LIGHT)
    for lo, hi in zip(ys, ys[1:], strict=False):
        c.line((x, lo, z), (x + far, hi, z), RIB)
        c.line((x + far, lo, z), (x, hi, z), RIB)
        c.line((x, lo, z + far), (x + far, hi, z + far), RIB)
        c.line((x, lo, z), (x, hi, z + far), RIB)


def ragged_slab(c: Canvas, x0: int, x1: int, z0: int, z1: int, y: int, thick: int, rng: random.Random) -> None:
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            edge = min(x - x0, x1 - x, z - z0, z1 - z)
            if edge < 7 and rng.random() < (7 - edge) * 0.11:
                continue
            for dy in range(thick):
                c.put(x, y + dy, z, MASS if dy < thick - 1 else "stone_bricks")
    for x in range(x0 + 8, x1 - 8, 14):  # lit seams
        c.put(x, y + thick - 1, z0 + 8, LIGHT)
        c.put(x, y + thick - 1, z1 - 8, LIGHT)


def ring(c: Canvas, cx: int, cy: int, z: int, radius: int, thick: int = 4) -> None:
    n = int(2 * math.pi * radius * 1.4)
    for i in range(n):
        a = 2 * math.pi * i / n
        x, y = round(cx + radius * math.cos(a)), round(cy + radius * math.sin(a))
        c.box((x, y, z), (x + thick - 1, y + thick - 1, z + thick - 1), MASS)
        if i % 9 == 0:
            c.box((x + 1, y + 1, z + thick), (x + 2, y + 2, z + thick), LIGHT)


def giant_box(c: Canvas, a: Pos, b: Pos, opening: tuple[Pos, Pos], find: Pos) -> None:
    """Hollow form with a floor, an opening on one side and something glowing to find inside."""
    c.shell(a, b, MASS, wall=2)
    mid = (a[1] + b[1]) // 2
    c.box((a[0] + 2, mid, a[2] + 2), (b[0] - 2, mid, b[2] - 2), DARK)
    c.clear(*opening)
    fx, fy, fz = find
    c.box((fx, fy, fz), (fx + 2, fy + 1, fz + 2), "amethyst_block")
    c.put(fx + 1, fy + 2, fz + 1, "glowstone")
    for dx, dz in ((-1, -1), (3, -1), (-1, 3), (3, 3)):
        c.put(fx + dx, fy, fz + dz, WARM)


def district(c: Canvas, y: int) -> None:
    """The verified district at stage scale: two shops, freight trunk, one power backbone."""
    c.shell((66, y, 88), (80, y + 7, 100), "orange_concrete", wall=1)
    c.box((66, y + 7, 88), (80, y + 7, 100), MASS)
    c.shell((110, y, 86), (126, y + 8, 102), "orange_concrete", wall=1)
    c.box((110, y + 8, 86), (126, y + 8, 102), MASS)
    for x in (113, 118, 123):  # three smelters: roof stacks
        c.box((x, y + 9, 92), (x + 1, y + 12, 93), DARK)
        c.put(x, y + 13, 92, WARM)
    for x0, x1 in ((66, 80), (110, 126)):
        for x in range(x0 + 2, x1 - 1, 3):
            c.put(x, y + 4, 88, LIGHT)
            c.put(x, y + 4, 100 if x1 == 80 else 102, LIGHT)
    for x in range(81, 110):  # freight trunk
        c.put(x, y, 94, "iron_block")
        if x % 4 == 0:
            c.put(x, y + 1, 94, WARM)
    c.box((95, y, 106), (97, y + 18, 108), "light_blue_concrete")  # power source tower
    c.box((95, y + 19, 106), (97, y + 19, 108), LIGHT)
    for x in range(81, 96):  # backbone
        c.put(x, y, 107, "cyan_concrete")
    for x in range(98, 110):
        c.put(x, y, 107, "cyan_concrete")
    for z in range(95, 107):
        c.put(73, y, z - 6 if z < 100 else 100, "cyan_concrete")
    c.shell((133, y, 114), (147, y, 128), "purple_concrete", wall=0)  # teleport pad
    c.box((139, y + 1, 120), (141, y + 52, 122), "light_blue_stained_glass")
    for x, z in ((60, 84), (84, 84), (104, 82), (130, 84), (132, 108), (86, 110)):  # warm lamp posts
        c.box((x, y, z), (x, y + 4, z), DARK)
        c.box((x, y + 5, z), (x + 1, y + 6, z + 1), WARM)


def debris(c: Canvas, rng: random.Random, count: int = 28) -> None:
    for _ in range(count):
        x, y, z = rng.randrange(10, 190), rng.randrange(20, 170), rng.randrange(10, 190)
        sx, sy, sz = rng.randrange(1, 6), rng.randrange(1, 4), rng.randrange(1, 6)
        c.box((x, y, z), (x + sx, y + sy, z + sz), rng.choice([MASS, DARK, RIB]))


def overview() -> Image.Image:
    rng = random.Random(7)
    c = Canvas()
    ragged_slab(c, 35, 175, 55, 150, 0, 3, rng)
    c.clear((46, 0, 62), (74, 3, 84))  # a shaft in the floor
    ragged_slab(c, 70, 160, 40, 130, -70, 3, rng)  # the tier below
    for px, pz in ((14, 18), (182, 24), (20, 168), (176, 164)):
        lattice_pillar(c, px, pz, -70, 175)
    ring(c, 100, 118, 98, 68)
    giant_box(c, (112, 100, 22), (160, 126, 52), ((120, 104, 50), (134, 118, 53)), (150, 104, 30))
    giant_box(c, (30, 60, 100), (62, 82, 138), ((58, 64, 108), (63, 76, 124)), (36, 64, 112))
    c.line((24, 127, 28), (112, 126, 30), RIB)  # a truss to the hanging form
    c.line((24, 119, 28), (112, 118, 30), RIB)
    district(c, 3)
    debris(c, rng)
    return _compose(render_iso(c.grid, yaw=0))


def interior() -> Image.Image:
    """One giant form cut open: storeys, a way in, a lift and a find in the vault."""
    c = Canvas()
    a, b = (0, 0, 0), (59, 33, 43)
    c.shell(a, b, MASS, wall=2)
    c.clear((2, 32, 2), (57, 33, 41))  # open top, like a dollhouse cutaway
    for y in (11, 22):  # storeys
        c.box((2, y, 2), (57, y, 41), "stone_bricks")
        c.clear((24, y, 14), (35, y, 29))  # a light well through the floors
    for x in (12, 47):  # columns
        for z in (10, 32):
            c.box((x, 1, z), (x + 1, 32, z + 1), RIB)
    c.clear((0, 1, 15), (3, 9, 24))  # entrance
    for z in range(15, 25, 3):
        c.box((1, 10, z), (2, 11, z + 1), LIGHT)
    for x in range(8, 52, 6):  # lamps under the storeys
        c.box((x, 10, 8), (x + 1, 10, 9), LIGHT)
        c.box((x, 21, 36), (x + 1, 21, 37), LIGHT)
    for y in range(1, 32):  # lift shaft beside the well
        c.put(23, y, 22, "iron_bars")
        if y % 6 == 0:
            c.box((22, y, 21), (23, y, 22), WARM)
    c.shell((36, 23, 27), (56, 27, 40), RIB, wall=1)  # low-walled vault on the top storey (far half of the cut)
    c.clear((42, 24, 27), (46, 26, 27))  # its door, facing the cut
    c.clear((37, 27, 28), (55, 27, 39))  # open roof
    c.box((42, 24, 31), (50, 24, 36), "amethyst_block")
    c.box((44, 25, 32), (48, 26, 35), "glowstone")
    for dx, dz in ((38, 29), (54, 29), (38, 38), (54, 38)):
        c.put(dx, 24, dz, WARM)
    c.box((6, 2, 18), (6, 3, 18), "white_concrete")  # a person, for scale
    return _compose(render_iso(c.grid, yaw=2, clip="z"))


def _compose(img: Image.Image) -> Image.Image:
    pad = 40
    canvas = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (*BACKGROUND, 255))
    canvas.alpha_composite(img, (pad, pad))
    return canvas.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("docs/images"))
    parser.add_argument("--only", choices=["overview", "interior"])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.only != "overview":
        interior().save(args.out / "concept-mass-interior.png")
        print("wrote concept-mass-interior.png")
    if args.only != "interior":
        overview().save(args.out / "concept-scene-in-void.png")
        print("wrote concept-scene-in-void.png")


if __name__ == "__main__":
    main()
