# YAN Functional API v0.3

Branch: `yan-functional-v0.3`

This iteration extends the proven v0.2 bidirectional probe into a generic live-world functional API.

## New command

```
/yanfunctional
```

Keep the crosshair on a block (Mekanism block recommended) and run the command while
`uv run mcbuild-server` is listening on port 8765.

The deterministic Python session performs:

1. `inspect_target`
2. `read_inventory`
3. `read_energy`
4. `wait_ticks(20)` using real Minecraft server ticks
5. `inspect_blocks` around the target
6. `place_block minecraft:glass` into a verified AIR cell
7. verify placement
8. `remove_block` (only blocks placed by this same agent session are removable)
9. verify removal

A successful run ends with:

```
[yan-agent] functional v0.3 PASS: ... placeVerified=true; removeVerified=true
```

## Safety rules

- `place_block` refuses to overwrite any non-air block.
- `remove_block` refuses to remove blocks that were not placed by the current agent session.
- World access is executed on the Minecraft server thread.
- `wait_ticks` never sleeps or blocks the server thread.
- Only one live mcbuild/YAN session may run at once.

## New generic actions

```
read_inventory
read_energy
wait_ticks
place_block
remove_block
```

Existing actions remain:

```
inspect_target
inspect_blocks
```

Coordinates for functional actions are relative to the player's position when the session starts.

## Local test

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-functional-v0.3
git pull

cd mod
.\gradlew.bat build

Copy-Item `
  ".\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart only Minecraft, then in a separate PowerShell:

```powershell
cd D:\YAN_AGENT_LAB
uv run mcbuild-server
```

In game, point at a block and run:

```
/yanfunctional
```

This v0.3 self-test is deliberately deterministic and does not use an LLM.
