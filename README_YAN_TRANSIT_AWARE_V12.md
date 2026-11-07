# YAN Transit-Aware Repair v1.2

Branch: `yan-transit-aware-v1.2`

v1.2 fixes the conservation bug exposed by the v1.1 repair run.

## What v1.1 revealed

The old verifier counted only endpoint inventories:

```text
source + sink1 + sink2
```

During a broken Mekanism route, some raw iron remained inside logistical transporters. Reset drained only the chests, reseeded 6 more items, and the next run observed 9 total.

## New bridge actions

```text
mek_read_transit
mek_clear_transit
```

`mek_read_transit` reads real server-side Mekanism `LogisticalTransporterBase.getTransit()` stacks, including item id, count, progress and path type.

`mek_clear_transit` follows Mekanism's own lifecycle:

```text
TransporterManager.remove(level, stack)
transporter.deleteStack(id)
```

and is hard-limited to transporters placed by the current agent session.

## Conservation

The verifier now uses:

```text
source + sink1 + sink2 + transit == 6
```

A PASS additionally requires:

```text
source == 0
sink1 > 0
sink2 > 0
transit == 0
```

## Reset

Before reseeding, reset now:

1. clears in-transit stacks from all active session-owned transporter paths;
2. drains source and sink inventories;
3. verifies that exactly 6 items were accounted for;
4. only then inserts a fresh 6 raw iron.

If conservation is not exactly 6, reset fails safely instead of injecting more items.

## Expected v1.1 replay

The same continuity-probe should now look like:

```text
OBSERVE initial:
source=0 sink1=2 sink2=0 transit=4 total=6 conserved=true pass=false

RESET TRANSIT-AWARE:
transitItems=4 inventoryItems=2 accounted=6/6 reseeded=6/6

LOCAL REPAIR 1
...

OBSERVE repair-1:
source=0 sink1=3 sink2=3 transit=0 total=6 conserved=true pass=true
```

## Update

Java changed, so rebuild and replace the JAR:

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-transit-aware-v1.2
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft once after replacing the JAR.

Python autoreload should pick up the server changes.

Use a fresh 3-chest scene and run:

```text
/yanenvironment
```

Then: `смотри последний run`.
