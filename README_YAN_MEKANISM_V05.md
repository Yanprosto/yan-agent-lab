# YAN Mekanism Experiment v0.5

Branch: `yan-mekanism-v0.5`

## Goal

Prove that the autonomous experiment loop can mutate a real Mekanism transmitter configuration and judge success from live item flow.

## New command

```
/yanmekexperiment
```

Builds:

```
SOURCE CHEST
    |
    v
BASIC LOGISTICAL TRANSPORTER
    |
    v
SINK CHEST
```

The source is above the transporter. The sink is below.

Variant A:

```
UP=NORMAL
DOWN=NORMAL
```

Expected: source remains full because NORMAL does not actively extract from the source inventory.

Variant B:

```
UP=PULL
DOWN=NORMAL
```

Expected: the transporter actively extracts from the source and moves all 6 raw iron into the sink.

## Runtime Mekanism adapter

New actions:

```
mek_get_transporter_mode
mek_set_transporter_mode
```

The Java bridge intentionally has no compile-time Mekanism dependency. It resolves the live BlockEntity and transporter at runtime, then mirrors Mekanism's real configurator sequence:

```
setConnectionTypeRaw
onModeChange
refreshConnections
notifyTileChange
sendUpdatePacket (when available)
```

Every write is followed by `getConnectionTypeRaw` readback. A mismatch fails the action.

## Expected lifecycle

```
TRY variant-A: UP=NORMAL
BUILD
CONFIG up=NORMAL verified=true
SEED 6
WAIT
OBSERVE source=6 sink=0
REJECT
ROLLBACK

TRY variant-B: UP=PULL
BUILD
CONFIG up=PULL verified=true
SEED 6
WAIT
OBSERVE source=0 sink=6
ACCEPT
ROLLBACK

Mekanism experiment v0.5 PASS
worldClean=true
```

## Local test

Because v0.5 changes both Java and Python:

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-mekanism-v0.5
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft after replacing the JAR.

For Python, if `mcbuild-server-dev` from main is already running, `git switch/pull` will cause the watcher to reload the Python server automatically once the changed files land in the working tree. If not running:

```powershell
cd D:\YAN_AGENT_LAB
uv run mcbuild-server-dev
```

Then stand in a clear area and run:

```
/yanmekexperiment
```
