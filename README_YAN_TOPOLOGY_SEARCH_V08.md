# YAN Topology Search v0.8

Branch: `yan-topology-search-v0.8`

v0.8 upgrades `/yansplitexperiment` from a fixed A/B script into a memory-seeded candidate search.

## Candidate generation

The server loads `mekanism_two_branch_distribution_v1` from `yan_knowledge/skills/`.
If the verified skill family is `dual_independent_pull`, it generates:

```text
control-shared-t   -> known shared-network control
skill-compact      -> mutate verified skill: remove intermediate arms
skill-exact        -> reproduce verified v0.6 geometry
skill-expanded     -> mutate verified skill: add one arm block per side
```

If memory is missing, the generator falls back to exploration candidates and marks them as fallback.

## Search policy

The agent benchmarks every candidate. It does NOT stop at the first PASS.

Hard correctness contract:

```text
source == 0
left > 0
right > 0
source + left + right == 6
```

Then candidates are ranked by:

```text
correctness > balance > compactness
```

Passing score:

```text
1000 - abs(left-right)*100 - block_count
```

Every failed candidate scores below every valid candidate.

## Skill admission

After all candidates are benchmarked, the best result is saved as:

```text
yan_knowledge/skills/mekanism_two_branch_distribution_v2.json
```

The v2 skill includes exact family, arm count, block count, selected candidate, score, and the full benchmark table.

## Runtime logs

v0.7 logging is already in main, so the entire search is automatically published to:

```text
Yanprosto/yan-runtime-logs/latest/
```

After the run just tell ChatGPT: `смотри последний run`.

## Test

No Java changed in v0.8. Minecraft does NOT need a restart.

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-topology-search-v0.8
git pull
```

If `mcbuild-server-dev` is running, autoreload should restart Python automatically.

Then in Minecraft:

```text
/yansplitexperiment
```

Expected high-level flow:

```text
GENERATED ...
BENCHMARK 1/4 ...
RESULT ...
ROLLBACK ...
...
BENCHMARK 4/4 ...
SELECT BEST ...
MEMORY: saved optimized skill mekanism_two_branch_distribution_v2.json
topology search v0.8 PASS
```
