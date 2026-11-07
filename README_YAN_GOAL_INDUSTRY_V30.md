# YAN Goal-Driven Industry v3.0

Branch: `yan-goal-industry-v3.0`

This milestone changes the axis of development from "more copies of one machine" to "higher-level production goals".

## Command

```text
/yanindustry переработка железа
```

The command accepts a free-text goal. Goals are resolved through a process-plan registry rather than a dedicated monolithic mission function.

Current registered plan:

```text
iron_processing
```

Aliases include English and Russian forms such as `iron processing`, `железо`, and `переработка железа`.

## Process graph

The first industrial plan uses real Mekanism 1.21.x recipes:

```text
18 minecraft:raw_iron
        |
        v
2 x mekanism:enrichment_chamber
        |
        | 3 raw iron -> 4 iron dust
        v
24 mekanism:dust_iron
        |
        | physical intermediate buffer / stage handoff
        v
2 x mekanism:energized_smelter
        |
        v
24 minecraft:iron_ingot
```

The important milestone is not the four machines; it is the two distinct processing stages, intermediate material, stage contract and controlled handoff.

## Runtime behavior

The agent:

1. resolves the user's goal into a `ProcessPlan`;
2. scans a combined industrial footprint;
3. builds stage 1 and stage 2 from reusable two-line cell geometry;
4. provisions precharged Mekanism creative-tab Energy Cubes;
5. configures real ITEM / ENERGY machine sides;
6. keeps stage 2 intake closed while stage 1 is running;
7. stages 18 raw iron;
8. waits until stage 1 proves exactly 24 iron dust in the shared intermediate buffer;
9. opens stage 2 intake only after the upstream contract passes;
10. waits until exactly 24 iron ingots reach final storage;
11. verifies no intermediate material or item transit remains;
12. saves the successful process graph as a reusable skill;
13. preserves the working industrial line in-world.

Failure rolls back session-owned blocks.

## Architecture

`process_plans.py` contains declarative goal/process definitions:

```text
goal
  -> ProcessPlan
      -> stage[]
          machine type
          input item/count
          output item/count
          machine count
```

`industry_session.py` is the generic executor for this first class of plans.

Future plans should be added to the registry instead of cloning a full mission runner.

## Success contract

```text
plan == iron_processing
stages == 2
machines == 4
raw input == 18
intermediate dust produced == 24
final iron ingots == 24
intermediate remaining == 0
transit == 0
worldPreserved == true
```

Successful knowledge:

```text
goal_driven_iron_processing_district_v1
```

## Install and run

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-goal-industry-v3.0
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft once because Java command registration changed.

Run in a clear area:

```text
/yanindustry переработка железа
```

Then:

```text
смотри последний run
```
