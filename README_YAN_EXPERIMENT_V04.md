# YAN Experiment Loop v0.4

Branch: `yan-experiment-v0.4`

This iteration proves the autonomous experiment lifecycle independently of Mekanism-specific configuration.

## New command

```
/yanexperiment
```

Stand in a clear area with roughly 7x4x3 blocks free to the EAST. The agent builds a tiny routing harness, seeds 6 raw iron, waits for real server ticks, observes inventories, scores the result, rolls back failures, mutates the topology, retries, and finally cleans the world.

## Experiment

Objective:

```
source=0
left=6
right=0
total=6
```

Variant A deliberately uses a hopper facing EAST and should fail the LEFT-sink objective.
Variant B mutates the hopper to face WEST and should pass.

Expected visible lifecycle:

```
TRY variant-A
BUILD
SEED
WAIT
OBSERVE source=0 left=0 right=6
REJECT
ROLLBACK
TRY variant-B
BUILD
SEED
WAIT
OBSERVE source=0 left=6 right=0
ACCEPT
ROLLBACK
PASS
```

## New generic actions

```
seed_item
drain_inventory
rollback_session
```

v0.3 actions remain available:

```
inspect_target
inspect_blocks
read_inventory
read_energy
wait_ticks
place_block
remove_block
```

## Safety

- `place_block` still refuses to overwrite non-air blocks.
- the complete test footprint is inspected before mutation.
- `rollback_session` only removes blocks placed by the current agent session.
- inventories are drained before rollback.
- an emergency rollback is attempted if the experiment fails mid-run.
- accepted test variants are also rolled back; a successful v0.4 leaves the world clean.

## Local test

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-experiment-v0.4
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft only. In another PowerShell:

```powershell
$p = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
if ($p) { Stop-Process -Id $p.OwningProcess -Force }

cd D:\YAN_AGENT_LAB
uv run mcbuild-server
```

Then in game:

```
/yanexperiment
```

This is deliberately a vanilla routing harness. The next layer will apply the proven lifecycle to Mekanism and UniversalMods-derived controls.
