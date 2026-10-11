# YAN Environment Builder v1.0

Branch: `yan-environment-builder-v1.0`

This is the first non-laboratory builder loop. The server no longer creates the source, sinks, or obstacles.

## Scene contract

Before running `/yanenvironment`, build a small scene yourself near the player:

- exactly 3 `minecraft:chest` blocks inside the scan volume;
- one chest contains exactly 6 `minecraft:raw_iron` and nothing else -> SOURCE;
- the other two chests are empty -> SINKS;
- walls, columns, floors and other non-air blocks may remain in place;
- do not place extra chests in the scan volume.

The scan volume is relative to the player's feet:

```text
x: -6 .. +6
y: -1 .. +3
z: -6 .. +6
```

## Command

```text
/yanenvironment
```

## What the agent does

1. scans the existing world;
2. identifies source and two sinks from chest contents;
3. treats every other non-air block as an obstacle;
4. loads `mekanism_two_branch_distribution_v3`;
5. plans two transporter routes with A*;
6. builds only transporters, never moving endpoints or obstacles;
7. configures source-facing transporters as PULL;
8. observes real item flow;
9. if one sink starves, keeps the working branch and removes/replans only the failed branch;
10. if isolated repair is impossible, falls back to a fully separated two-branch plan;
11. on success, LEAVES the working network in the world;
12. on unrecoverable failure, rolls back only agent-placed blocks and restores 6 raw iron to the source.

## Success contract

```text
source == 0
sink1 > 0
sink2 > 0
source + sink1 + sink2 == 6
```

Unlike v0.x benchmark runs, success ends with:

```text
worldPreserved=true
```

The successful run is saved as:

```text
yan_knowledge/skills/environment_aware_two_branch_v1.json
```

and full structured telemetry is auto-pushed to `Yanprosto/yan-runtime-logs`.

## Local update

v1.0 adds a Java command, so rebuild the mod once:

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-environment-builder-v1.0
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft after replacing the JAR.

`mcbuild-server-dev` should reload the Python side automatically after the branch switch. If it is not running:

```powershell
cd D:\YAN_AGENT_LAB
uv run mcbuild-server-dev
```

Then create the scene, stand near its center, and run:

```text
/yanenvironment
```

After completion just say:

```text
смотри последний run
```
