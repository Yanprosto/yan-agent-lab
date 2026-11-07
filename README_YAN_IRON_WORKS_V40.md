# YAN Iron Works v4.0

Branch: `yan-iron-works-v4.0`

This milestone is the first factory driven by a branching high-level architecture
planner rather than one fixed production script.

## Goal

```text
/yanindustry железный завод
```

## Planner

The planner generates several architecture candidates and scores them across:

- throughput;
- material efficiency;
- robustness;
- compactness;
- reuse of verified primitives;
- implementation risk.

Current candidates include:

- `compact_single_lane`;
- `balanced_parallel_works`;
- `direct_smelting_yard`;
- `dense_factory_future` (currently penalized/excluded because its primitives are not yet verified live).

Only verified candidates enter the execution beam.

The current scoring selects `balanced_parallel_works`.

## Selected plant

```text
RAW A (18)
  -> 2 x Enrichment Chamber
  -> Buffer A (24 iron dust)
  -> 2 x Energized Smelter
  -> Final A (24 ingots)

RAW B (18)
  -> 2 x Enrichment Chamber
  -> Buffer B (24 iron dust)
  -> 2 x Energized Smelter
  -> Final B (24 ingots)
```

Totals:

- 2 parallel production lanes;
- 4 process stages/cells;
- 8 processing machines;
- 4 independently verified power modules;
- 2 real physical intermediate handoff buffers;
- 2 final output stores;
- 36 raw iron;
- 48 iron ingots;
- roughly 98 placed functional blocks.

The intermediate buffers are actual shared chests between upstream and downstream
cells. The downstream intake remains closed until both enrichment contracts pass.

## Search architecture

`industrial_planner.py` represents the first implementation of the long-term
chess-engine idea:

```text
goal
-> generate candidate architectures
-> score
-> keep top-K verified candidates
-> execute best
-> verify in Minecraft
```

Later versions can expand the same contract into topology/layout search, alternative
execution after failure, learned scoring, or MCTS.

## Success contract

```text
selected candidate == balanced_parallel_works
lanes == 2
machines == 8
raw input == 36
iron dust handoff == 24 + 24
final iron ingots == 48
raw remaining == 0
dust remaining == 0
transit == 0
worldPreserved == true
```

Success saves:

```text
branching_iron_works_v1
```

## Run

No Java code changed in v4.0. If `mcbuild-server-dev` is already running, switching
branches/pulling Python is enough.

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-iron-works-v4.0
git pull
```

Then in Minecraft, stand in a large clear area and run:

```text
/yanindustry железный завод
```

After the run:

```text
смотри последний run
```
