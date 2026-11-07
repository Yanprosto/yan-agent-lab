"""T1-lite: estimate how long a planned district takes, and pick machine counts for a deadline.

A small event model over the district's real geometry and the catalog's numbers
(evaluation tier T1, ARCHITECTURE §4). It exists to choose how many parallel machines a
stage needs, and its prediction is compared with the live result so model errors are
recorded (I1, I4).

Model:

- an item crosses a transporter cell in ``ticks_per_block`` ticks (catalog, derived from
  the audited tier speed);
- a puller starts at most one item per ``pull_interval`` ticks (a basic transporter pulls
  1 item per extraction);
- items reaching a stage are dealt round-robin to its machines (independent PULL
  transporters pull at equal rates);
- a machine starts an operation once ``input_count`` of its items have arrived and it is
  free, and each operation takes ``ticks_per_operation`` (catalog);
- outputs leave the machine through its out segment, queue in the shop's sink chest, and
  go through one trunk puller to the next shop.
"""

from __future__ import annotations

from math import ceil

from mcbuild.catalog import Catalog
from mcbuild.planner.district import MAX_PARALLEL, District, DistrictError, plan_district
from mcbuild.planner.process_graph import ProcessChain, ScoredChain, Stage

TRANSPORTER = "mekanism:basic_logistical_transporter"
DEFAULT_PULL_INTERVAL = 4


def _paced(times: list[float], interval: float) -> list[float]:
    """Spread item times so that consecutive items are at least ``interval`` apart."""
    out: list[float] = []
    last = -interval
    for t in sorted(times):
        last = max(t, last + interval)
        out.append(last)
    return out


def simulate(
    stages: list[Stage],
    source_amount: int,
    in_lens: list[list[int]],
    out_lens: list[list[int]],
    trunk_lens: list[int],
    *,
    ticks_per_op: list[float],
    per_block: float = 20.0,
    pull_interval: float = DEFAULT_PULL_INTERVAL,
) -> float:
    """Event model over plain numbers: segment lengths per machine and trunk lengths per hop."""
    arrivals = [0.0] * source_amount  # when each item is available in the shop's source chest
    for index, stage in enumerate(stages):
        count = len(in_lens[index])
        per_machine: list[list[float]] = [[] for _ in range(count)]
        for n, t in enumerate(sorted(arrivals)):
            per_machine[n % count].append(t)
        outputs_at_sink: list[float] = []
        for j in range(count):
            pulled = _paced(per_machine[j], pull_interval)
            at_machine = [t + in_lens[index][j] * per_block for t in pulled]
            free_at = 0.0
            for op in range(len(at_machine) // stage.input_count):
                ready = at_machine[(op + 1) * stage.input_count - 1]
                free_at = max(free_at, ready) + ticks_per_op[index]
                leave = _paced([free_at] * stage.output_count, pull_interval)
                outputs_at_sink += [t + out_lens[index][j] * per_block for t in leave]
        outputs_at_sink.sort()
        if index == len(stages) - 1:
            return max(outputs_at_sink) if outputs_at_sink else 0.0
        pulled = _paced(outputs_at_sink, pull_interval)
        arrivals = [t + trunk_lens[index] * per_block for t in pulled]
    return 0.0


def estimate_ticks(
    catalog: Catalog, district: District, source_amount: int, *, pull_interval: float = DEFAULT_PULL_INTERVAL
) -> float:
    """Ticks from seeding the first source chest until the last item reaches the final sink."""
    in_lens, out_lens = [], []
    for shop in district.shops:
        fan = shop.layout.fan_out
        segs = shop.layout.segments
        count = len(shop.layout.machines)
        in_lens.append([len(segs[2 * j if fan else j].cells) for j in range(count)])
        out_lens.append([len(segs[2 * j + 1 if fan else j + 1].cells) for j in range(count)])
    return simulate(
        [s.stage for s in district.shops],
        source_amount,
        in_lens,
        out_lens,
        [len(t.cells) for t in district.trunks],
        ticks_per_op=[float(catalog.fact(s.stage.machine, "ticks_per_operation") or 200) for s in district.shops],
        per_block=float(catalog.fact(TRANSPORTER, "ticks_per_block") or 20),
        pull_interval=pull_interval,
    )


def stage_load(catalog: Catalog, chain: ProcessChain, source_amount: int, counts: list[int]) -> list[float]:
    """Ticks each stage would need on its own with ``counts`` machines (the bottleneck metric)."""
    loads = []
    amount = source_amount
    for stage, machines in zip(chain.stages, counts, strict=True):
        operations = amount // stage.input_count
        tpo = float(catalog.fact(stage.machine, "ticks_per_operation") or 200)
        loads.append(ceil(operations / machines) * tpo)
        amount = amount * stage.output_count // stage.input_count
    return loads


def plan_to_deadline(
    catalog: Catalog, scored: ScoredChain, limit: int, *, gap: int = 24
) -> tuple[District, list[int], float]:
    """Smallest machine counts (grown on the bottleneck stage) whose estimate meets ``limit``."""
    chain = scored.chain
    counts = [1] * len(chain.stages)
    while True:
        district = plan_district(chain, counts, gap=gap)
        estimate = estimate_ticks(catalog, district, scored.source_needed)
        if estimate <= limit:
            return district, counts, estimate
        loads = stage_load(catalog, chain, scored.source_needed, counts)
        growable = [i for i, c in enumerate(counts) if c < MAX_PARALLEL]
        if not growable:
            raise DistrictError(
                f"cannot meet {limit} ticks with at most {MAX_PARALLEL} machines per stage "
                f"(best estimate {estimate:.0f} with {counts})"
            )
        counts[max(growable, key=lambda i: (loads[i], -i))] += 1
