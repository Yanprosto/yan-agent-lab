# YAN Industrial Sector Preview

Three real 128×128 voxel macro-architecture studies:

- Vertical Foundry Shaft
- Industrial Canyon Works
- Terraced Megaforge

They are deliberately arranged as a triangular cluster, not three blocks in one row.

## Height

Use **Y=180** in a clean creative test area.

The tallest design is ~99 blocks above the anchor, so its top is around Y=278.
That leaves comfortable room below vanilla 1.21.1's upper build limit.

## Run

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-industrial-sector-previews
git pull

cd D:\YAN_AGENT_LAB
uv run python examples/industrial_sector_study/live_preview.py
```

Then in Minecraft:

```text
/tp @s ~ 180 ~
/build yan-industrial-sector-preview
```

The preview server preflights every destination before writing any block. If one
destination is occupied, it aborts before placement.

Placement layout relative to the player:

```text
VERTICAL FOUNDRY        INDUSTRIAL CANYON
        \                 /
         \               /
          player / anchor
                |
                |
       TERRACED MEGAFORGE
```

The models are preserved after placement for creative fly-through comparison.
