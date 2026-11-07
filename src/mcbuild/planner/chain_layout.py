"""ProcessChain -> concrete line layout (relative block positions and configuration).

The line repeats the machine-probe cell along +x, so every hand-off uses the pattern
already verified live:

    source | T(PULL) T | M1 | T(PULL) T | M2 | ... | T(PULL) T | sink

Machines take items from the west, emit to the east and receive energy from the south
through a cable fed by a charged creative cube (one per machine for now; a shared
power backbone is a later step). Transporters marked PULL extract from their west
neighbour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcbuild.planner.process_graph import ProcessChain

CHEST = "minecraft:chest[facing=north,type=single,waterlogged=false]"
TRANSPORTER = "mekanism:basic_logistical_transporter"
CABLE = "mekanism:basic_universal_cable"

Pos = tuple[int, int, int]


@dataclass(frozen=True)
class MachineSlot:
    machine: str
    pos: Pos
    cable: Pos
    cube: Pos


@dataclass
class LineLayout:
    source: Pos
    sink: Pos
    machines: list[MachineSlot] = field(default_factory=list)
    pull_transporters: list[Pos] = field(default_factory=list)
    feed_transporters: list[Pos] = field(default_factory=list)

    @property
    def transporters(self) -> list[Pos]:
        return sorted(self.pull_transporters + self.feed_transporters)

    @property
    def footprint(self) -> list[Pos]:
        cells = [self.source, self.sink, *self.transporters]
        for slot in self.machines:
            cells += [slot.pos, slot.cable, slot.cube]
        return cells


def compile_line(chain: ProcessChain) -> LineLayout:
    layout = LineLayout(source=(0, 0, 0), sink=(3 * len(chain.stages) + 3, 0, 0))
    for index, stage in enumerate(chain.stages):
        base = 3 * index
        layout.pull_transporters.append((base + 1, 0, 0))
        layout.feed_transporters.append((base + 2, 0, 0))
        x = base + 3
        layout.machines.append(MachineSlot(stage.machine, (x, 0, 0), (x, 0, 1), (x, 0, 2)))
    last = 3 * len(chain.stages)
    layout.pull_transporters.append((last + 1, 0, 0))
    layout.feed_transporters.append((last + 2, 0, 0))
    return layout
