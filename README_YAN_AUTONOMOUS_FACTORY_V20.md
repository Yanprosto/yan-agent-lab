# YAN Autonomous Factory v2.0

Branch: `yan-autonomous-factory-v2.0`

This milestone stops requiring hand-built test fixtures.

## Mission

Run:

```text
/yanmission
```

The agent receives one integrated goal:

```text
12 raw iron
   ↓
2 parallel Energized Smelters
   ↓
12 iron ingots in one output buffer
```

No source chest, sink chest, machine, cable or transporter needs to be placed by the player.

## What the mission does

1. searches several candidate footprints near the player and selects the first fully free site;
2. provisions its own input/output buffers;
3. places two Energized Smelters;
4. places one Creative Energy Cube and two Universal Cable links;
5. builds two independent input transporter branches;
6. builds two machine-output extractor branches and one shared collection network;
7. configures real Mekanism machine side data:
   - ITEM INPUT;
   - ITEM OUTPUT;
   - ENERGY INPUT;
   - ENERGY OUTPUT;
8. configures transporter PULL sides;
9. verifies both smelters are actually powered;
10. stages 12 raw iron automatically;
11. verifies neither processing line is starved;
12. polls production every 200 ticks instead of waiting blindly;
13. if machine output accumulates, repairs only the output interfaces/extractors;
14. checks transporter transit state during production;
15. accepts only when all 12 ingots reached the output buffer and all raw/transit/machine buffers are empty;
16. leaves the commissioned factory standing in the world.

## New bridge capability

`mek_set_side_config` is a generic reflection adapter for Mekanism configurable machines.

Arguments:

```text
position
transmission = ITEM | ENERGY | ...
world side
mode = INPUT | OUTPUT | INPUT_OUTPUT | NONE | ...
```

It resolves the machine's actual facing to Mekanism `RelativeSide`, changes the real `ConfigInfo`, calls `sideChanged`, and verifies readback.

This is intentionally generic so future missions can reuse it for Crusher, Enrichment Chamber, factories, chemical machines, energy cubes, etc.

## Current topology

```text
                         [Smelter A]
                        /     |power
[12 raw] -- independent       |
 source         feeds      [Creative
                        \   Energy Cube]
                         [Smelter B]
                               |
                         merged output
                               |
                         [12 ingots]
```

The exact block paths are generated from a selected site shift and are persisted in the runtime skill after success.

## Success contract

```text
output iron_ingot == 12
source raw_iron == 0
smelter A raw/output == 0
smelter B raw/output == 0
transit == 0
both smelters powered
both processing lines participated
worldPreserved == true
```

Successful knowledge is saved as:

```text
autonomous_parallel_smelting_factory_v1
```

## Install

Java changed, so rebuild once:

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-autonomous-factory-v2.0
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft once after replacing the JAR.

Then stand in a reasonably open area and run:

```text
/yanmission
```

The mission can take roughly a minute because real Energized Smelter recipes take 200 ticks per item and two lines process the batch in parallel.

After completion just say:

```text
смотри последний run
```
