# Headless lab: live Mekanism checks without a game client

A dedicated NeoForge 1.21.1 server with Mekanism 10.7.19.85 (Core, Generators, Tools,
Additions) and the `mcbuild_live` mod, driven over RCON. It runs the same YAN
experiments as in-game commands, against the real mod code, with no player.

This is evaluation tier T2/T3 from `docs/concept/ARCHITECTURE.md` §4.

## Setup (once per machine)

Needs Java 21, `uv`, and network access to `maven.neoforged.net`,
`mirrors.neoforged.net`, `piston-meta.mojang.com`, `piston-data.mojang.com`,
`launchermeta.mojang.com`, `libraries.minecraft.net`, `cdn.modrinth.com`.

```bash
tools/headless_lab/setup.sh            # default lab dir: ~/mc-lab (or $YAN_LAB_DIR)
```

The script verifies every Mekanism jar by SHA-256; the core jar is the one the
2026-10-11 audit read. It writes `eula=true`: the repository owner accepted the
[Minecraft EULA](https://aka.ms/MinecraftEULA) for this lab.

## Run an experiment

```bash
uv run python tools/headless_lab/run.py experiment   # v0.4 vanilla hopper loop
uv run python tools/headless_lab/run.py mekanism     # v0.5 transporter mode mutation
uv run python tools/headless_lab/run.py splitter     # v0.9 spatial topology search
uv run python tools/headless_lab/run.py machine --spec mekanism:crusher --pos "800 -60 0"
```

`machine` builds a minimal powered cell for any catalog processor (item in west, out
east, energy south), runs 4 operations of a catalog recipe (or the one given after the
block id), checks the exact output and rolls back. A PASS is the evidence that marks the
block's `side_config` `runtime_observed` in `yan_knowledge/catalog/blocks/`.

`run.py` starts the lab server and the agent server when needed, force-loads the
lab area, sends `/yanlab <experiment> 0 -60 0` and exits 0 on PASS, 1 on FAIL, 2 on
timeout. Logs: `~/mc-lab/server.out` (world side), `~/mc-lab/agent.out` (agent).
Runtime-log publishing is off unless `YAN_RUNTIME_LOGS_ENABLED` is set.

Manual commands: `uv run python tools/headless_lab/rcon_client.py "yanlab splitter 0 -60 0"`.

## The `/yanlab` command

`/yanlab <experiment|mekanism|splitter|environment|mission> <x> <y> <z>`, `/yanlab industry <x y z> <goal>`
and `/yanlab machine <x y z> <block id> [recipe id]` (permission level 2) start an
experiment at explicit coordinates. Without a player, session messages go to the
server console. `probe` and `functional` need a player's crosshair and are not
offered headless.

## Lab world

Superflat, peaceful, creative, offline mode, RCON on `127.0.0.1:25575` only
(password `yanlab-local`, local lab use). Surface is at y = -60.
