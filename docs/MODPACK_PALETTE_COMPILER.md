# YAN Modpack Palette Compiler v0.1

The builder must use the user's actual modpack instead of a tiny hard-coded Minecraft
palette.

This tool scans the local `mods/*.jar` files and builds a visual/semantic catalog of
block assets. Heavy work happens on the user's PC; no LLM or web API is required.

## Pipeline

```text
mod JARs
  -> blockstates
  -> block models
  -> block textures
  -> block tags
  -> visual features
  -> semantic roles
  -> sector-specific palette
  -> procedural YAN Builder
```

The palette is compiled around *functional anchors*. If a sector uses Mekanism machines,
the architectural palette should be visually compatible with those machines. A
Create-oriented district may therefore get a different architecture palette from a
Mekanism-oriented district even inside the same world.

## Current visual features

For every resolvable block texture the scanner computes:

- mean RGB / HSV;
- luminance;
- contrast;
- saturation;
- edge density;
- opacity.

It also derives broad roles from block IDs and tags:

- structural;
- floor;
- decor;
- light;
- glass;
- pipe;
- cable;
- rail;
- storage;
- machine.

This is deliberately heuristic v0.1. The next layers are a live registry dump and
resource-pack-resolved client assets.

## Run on the ElyPrism instance

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-modpack-palette-compiler-v0.1
git pull
uv sync --extra dev

uv run yan-modpack-scan `
  --mods "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods" `
  --out "D:\YAN_PALETTE\mekanism_sector" `
  --anchor-mod mekanism `
  --anchor-mod create `
  --anchor-block mekanism:metallurgic_infuser `
  --anchor-block mekanism:energized_smelter
```

Outputs:

```text
D:\YAN_PALETTE\mekanism_sector\catalog.json
D:\YAN_PALETTE\mekanism_sector\palette.json
```

`catalog.json` is the reusable local block catalog. `palette.json` is a much smaller
sector-specific selection suitable for procedural generation.

## Direction

v0.1 is intentionally local and cheap.

Planned layers:

1. static JAR asset scan (this milestone);
2. NeoForge runtime registry export to verify that catalog entries are really registered;
3. resolved client resource scan so active resource packs are reflected;
4. richer material clustering and family detection;
5. procedural sector generator consumes semantic slots rather than hard-coded blocks;
6. functional blocks are placed as graph nodes and architecture grows around them;
7. optional local visual search can use GPU/CPU aggressively without spending LLM tokens.

The goal is not to generate every block with an LLM. The LLM writes and evolves the
generator; the user's machine expands compact rules into hundreds of thousands or
millions of blocks.
