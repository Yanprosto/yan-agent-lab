# Tall-world spike: Dynamic Height on the headless lab (2026-11-07)

**Question.** Can the world be made much taller than the vanilla 384 blocks with mods, and
does the YAN stack (bridge, Mekanism machines, rollback) keep working there?

**Short answer.** Yes, on the server side. 4096 blocks cost nothing measurable; about 32,880
blocks cost +37 % memory when idle. Not tested: the client (rendering, singleplayer
world-creation screen, Distant Horizons), elevators and grapples.

## Setup

- Headless lab (`tools/headless_lab/`): NeoForge 21.1.255, Mekanism 10.7.19.85 (audited jar),
  `mcbuild_live`, plus `dynamicheight-0.3.5+neoforge-1.21.1.jar`
  (Modrinth `dynamic-height`, sha512 starts `1f6724b4…`).
- Flat worlds, offline mode, dedicated server (the real game is singleplayer: integrated
  server, not covered here).
- Tool: `tools/headless_lab/tall_world.py`. One run per world; idle server; 9×9 chunks forceloaded
  around the origin; almost empty columns (flat floor + one hollow tower).

## Results

| World | Block range | Height | 81 chunks loaded | Avg tick | Memory | Tower | Machine probes | Reload |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vanilla, fresh | −64 … 319 | 384 | 1.2 s | 0.7 ms | 1042 MB | – | (all earlier runs) | – |
| `tall4k_b` | −128 … 3967 | **4096** | 1.9 s | 0.6 ms | 1057 MB (1084 MB with tower) | 8 fills, 1.0 s | crusher at y=3000 PASS; smelter at y=−100 PASS | markers and tower intact |
| `tall32k` | −128 … 32751 | **32,880** | 1.6 s | 0.7 ms | 1427 MB (1951 MB with tower) | 65 fills, 4.5 s | crusher at **y=30000** PASS; smelter at y=−100 PASS | top block y=32751, tower and bottom intact |

Machine probes: `/yanlab machine` (4 operations, exact output, rollback, world clean).
Reload: `save-all flush`, stop, start, check blocks at the extremes.

## Facts about the mod (0.3.5, NeoForge 1.21.1)

- Config file is `data/dynamic_height_minecraft_overworld.config` in the world folder, content
  `{"format": "dynamicheight-worldheight-v1", "minY": …, "maxY": …}`. **The mod page says `.json`; that
  file is ignored.** Without a config the mod writes defaults: minY −64, maxY 32752.
- Limits in the code (constants of its validator, section size 16): `minY` ≥ **−128**, `maxY` ≤ 32767,
  `maxY` ≥ 384. In practice `maxY` is clamped to 32752 and the highest placeable block is **32751**; the
  mod rewrites the file with the effective values.
- **Depth cannot grow below Y = −128.** Height only grows upwards.
- Does not change generation (flat floor sat at the new bottom: bedrock −128, grass −125).
- Incompatible with Lithium (per the mod page); Axiom only from a newer version.
- **License:** the jar's `neoforge.mods.toml` says `CC-BY-NC-ND-4.0`; the Modrinth page says
  `GPL-3.0-only`. Fine for a private pack; settle it before publishing a pack that contains it.
- Server worlds: the page says to create the world in singleplayer with the wanted height and let it
  generate fully before uploading it to a server.

## Mistakes made on the way (kept, because they change how to read the numbers)

1. The first "4096" run wrote `….json`, which the mod ignores, so it ran the default 32,816-block
   world instead. Its numbers are not used above. Found by probing the real top (`setblock` search).
2. The first 32k run used `maxY` 32767, which the mod clamped to 32752; the top marker and the
   last tower segment were outside the world. Re-checked at y=32751 after a restart: intact.

## What this does not show

- Real content: columns here are almost empty air. Dense megastructure generation will cost far more
  than the height itself; this measures only the overhead of height.
- Client side: rendering, lighting at height, Distant Horizons, the singleplayer creation screen.
- Vertical traversal (elevators, grapples, parachutes): needs a client.
- Behaviour with the full modpack (only Mekanism, our bridge and this mod were loaded).
