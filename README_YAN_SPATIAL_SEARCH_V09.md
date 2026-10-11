# YAN Spatial Search v0.9

Branch: `yan-spatial-search-v0.9`

v0.9 extends the verified two-branch skill into a real spatial search.

## What changes

`/yansplitexperiment` now loads `mekanism_two_branch_distribution_v2` and generates spatial transformations:

```text
control-shared-x
v2-x-flat
rotate-z-flat
x-asym-right
z-asym-left
x-drop
z-drop
x-wide-drop
```

The search space changes:

- axis: X / Z
- left branch length
- right branch length
- sink vertical drop
- extractor count (1-extractor control vs 2-extractor learned family)

## Contract

Every candidate must satisfy:

```text
source == 0
left > 0
right > 0
source + left + right == 6
```

Ranking policy:

```text
correctness
> balance
> material cost
> spatial compactness
```

## Persistent knowledge

Successful search writes:

```text
yan_knowledge/skills/mekanism_two_branch_distribution_v3.json
```

The v3 skill stores:

- the best geometry;
- exact axis / arm lengths / sink drop / extractor count;
- full benchmark results;
- every spatial transform that preserved the functional contract.

That `validated_transforms` list is intended for future environment-aware placement: if one shape collides with a wall/column/floor, the builder can select another already-proven transform.

## Runtime logs

All results are automatically uploaded to:

```text
Yanprosto/yan-runtime-logs/latest/
```

## Test

No Java changed. Minecraft restart is not required.

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-spatial-search-v0.9
git pull
```

`mcbuild-server-dev` should reload Python automatically.

Then:

```text
/yansplitexperiment
```

After completion just say:

```text
смотри последний run
```
