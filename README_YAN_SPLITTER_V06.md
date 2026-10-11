# YAN Splitter + Skill Memory v0.6

Branch: `yan-splitter-v0.6`

## What this proves

1. Verified knowledge survives outside chat in `yan_knowledge/skills/*.json`.
2. The agent can reject a working-but-bad Mekanism topology because one branch starves.
3. The agent can structurally mutate the topology, rebuild it, retest it, and admit the successful topology as a reusable skill.

## Command

```
/yansplitexperiment
```

Keep roughly an 11x5x5 area EAST of the player clear.

## Variant A

One PULL extractor feeds a shared T-shaped logistical transporter network with two sinks.

Goal:

```
source=0
left>0
right>0
total=6
```

If Mekanism starves one branch, Variant A is rejected even if all six items moved somewhere.

## Variant B

The agent mutates the structure into two independent PULL extractors, both reading the same source chest and each feeding its own sink.

This is a topology mutation, not just a mode change.

## Skill memory

v0.6 writes verified skills to:

```
yan_knowledge/
  skills/
    mekanism_single_extractor_v1.json
    mekanism_two_branch_distribution_v1.json
```

`mekanism_single_extractor_v1` records the already live-validated v0.5 discovery.

`mekanism_two_branch_distribution_v1` is written only if v0.6 actually observes both branches receiving items with conservation intact.

## Local test

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-splitter-v0.6
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft because Java changed.

If `mcbuild-server-dev` is already running, the Python side reloads itself when you switch/pull this branch. Otherwise:

```powershell
cd D:\YAN_AGENT_LAB
uv run mcbuild-server-dev
```

Then:

```
/yansplitexperiment
```

Expected successful ending:

```
REJECT variant-A ...
ROLLBACK ...
TRY variant-B ...
OBSERVE ... left>0 right>0 conserved=True
ACCEPT variant-B
MEMORY: saved verified skill mekanism_two_branch_distribution_v1.json
splitter experiment v0.6 PASS
worldClean=true
```
