# mcbuild

**Turn a sentence into a Minecraft build.** A from-scratch LLM agent that writes
a blueprint program in a sandboxed Python DSL, interprets it into voxel data,
renders labeled multi-view screenshots with a pure-software isometric renderer,
and lets a vision-capable LLM critique its own renders and iterate via tool
calls — until it produces a WorldEdit-ready `.schem` file, or (via a NeoForge
mod + WebSocket server) builds live inside a running Minecraft world.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![uv](https://img.shields.io/badge/managed%20with-uv-de5fe9)
![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-8a2be2)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

![Multi-view isometric render of an agent-built mansion](docs/images/mansion-hero.png)

*Four rotations of a mansion built end-to-end from the prompt `"make a mansion"` —
one of the agent's own self-critique renders, unedited.*

## How it works

```
prompt ──▶ LLM writes a blueprint (sandboxed Python DSL)
             │
             ▼
        DSL interpreter ──▶ sparse voxel grid
             │
             ▼
     isometric renderer ──▶ contact-sheet PNG of the views the LLM requested (rotations / top-down / cutaways)
             │
             ▼
   vision LLM critiques the render, calls a tool to edit/query/finish
             │
             └──── loop until finish() ────▶ WorldEdit .schem + full run directory
```

## Examples

Unedited iso-view renders from the agent's own run directories under `runs/`:

<table>
<tr>
<td align="center" width="33%">
<img src="docs/images/example-shrine.png" alt="A traditional Japanese shrine with a torii gate"><br>
<sub><code>"a traditional japanese shrine with a torii gate"</code></sub>
</td>
<td align="center" width="33%">
<img src="docs/images/example-castle.png" alt="A medieval castle"><br>
<sub><code>"a medival castle"</code></sub>
</td>
<td align="center" width="33%">
<img src="docs/images/example-oasis.png" alt="A small lake in a desert"><br>
<sub><code>"a small lake in a desert"</code></sub>
</td>
</tr>
</table>

## Install

```bash
uv sync --extra dev
```

Set your OpenRouter key:

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY=...
```

## Usage

```bash
uv run mcbuild "a medieval watchtower with interior spiral stairs"
```

<details>
<summary><strong>All options</strong></summary>

```
mcbuild PROMPT
  --model TEXT                 Vision-capable OpenRouter model id [default: anthropic/claude-sonnet-5]
  --max-iters INTEGER          [default: 6]
  --seed INTEGER                [default: 0]
  --display TEXT                auto|sixel|ansi|off  [default: auto]
  --out TEXT                    Run directory base  [default: runs]
  --reference/--no-reference    Generate a concept-reference image first  [default: no-reference]
  --ref-model TEXT              [default: openai/gpt-image-2]
  --reasoning TEXT              off|low|medium|high  [default: medium]
  --stream/--no-stream          Stream reasoning/completion text live  [default: stream]
  --cost-ceiling FLOAT          Abort (keeping the best build so far) once usage cost reaches this many USD
```

`--display auto` probes the terminal for sixel support (via a DA1 query) and
falls back to ANSI half-block rendering (`rich-pixels`) if unavailable.

</details>

Each run writes to `runs/<timestamp>-<slug>/`:

```
prompt.txt
reference.png          (if --reference)
iter_NN/blueprint.py
iter_NN/render.png
iter_NN/stats.json
final.schem
final_blueprint.py
session.json            (full message log, for debugging)
```

### Offline demo (no API key / no network)

```bash
uv run mcbuild "a tiny stone hut" --fake-llm --max-iters 3
```

Runs the full pipeline against a scripted stand-in LLM (broken blueprint ->
line-mapped error -> fixed blueprint -> render -> finish) so you can see the
whole loop and artifact layout without hitting the network.

## Large projects / multi-agent orchestrator

`mcbuild` and Minecraft's `/build <prompt>` keep the original single-building
agent behavior. For a town, castle complex, harbor district, or another build
that should be split into semantic components, use the independent project CLI:

```bash
uv run mcbuild-project "build a fortified medieval town"
```

The planner submits a structured `ProjectPlan`, receives runtime validation plus
a deterministic top-down plan PNG, and must explicitly approve that rendered
plan before any worker starts. Work packages then execute in stable dependency
order. A repeated family (for example four matching towers) remains one work
package with multiple instances and receives exactly one call to the existing
mcbuild worker.

Useful options include `--model`, `--planner-model`, `--max-iters`,
`--planner-max-iters`, `--max-components`, `--seed`, `--display`, `--out`,
`--reasoning`, and `--cost-ceiling`. The cost ceiling is global: planner and all
workers draw from the same USD budget. The complete offline path needs no API
key or network:

```bash
uv run mcbuild-project "a small fortified settlement" --fake-llm --display off
```

A project run keeps planner, worker, and merge artifacts separate:

```text
runs/<timestamp>-<slug>/
  prompt.txt
  project_config.json
  project/
    plan_v01.json
    plan_v01.png
    plan_v01_validation.json
    approved_plan.json
    approved_plan.png
    planner_session.json
  components/
    01_<work-package-id>/
      worker_prompt.txt
      worker_result.json
      patch_validation.json
      accepted_patch.schem
      merged_after_component.schem
  merge_reports/component_01.json
  final.schem                 # successful projects
  partial.schem               # preserved merged work after an abort, when non-empty
  project_events.jsonl
  project_result.json
```

Responsibilities are 2.5D: a two-dimensional `RegionExpr` plus an inclusive Y
range. A hard package may write only in its core; any stored voxel intent outside
it (including explicit air) rejects the complete patch. A soft package may write
in core plus halo; outside intents are clipped and reported. Declared two-party
interface zones always preserve existing non-air blocks. Core write policies are
`preserve_existing`, `additive`, `overwrite`, and `carve`; overwrite and carve
are restricted to the core.

## Live building in Minecraft

Instead of (or alongside) a `.schem` file, mcbuild can build directly inside a running
world. The NeoForge mod provides `/build <prompt>` for the unchanged single-agent loop
and `/project <prompt>` for the multi-component orchestrator. Both reuse the same
WebSocket response protocol and player-position anchor.

Start the server:

```bash
uv run mcbuild-server --model anthropic/claude-sonnet-5 --max-iters 8
```

<details>
<summary><strong>All options</strong></summary>

```
mcbuild-server
  --host TEXT           [default: 127.0.0.1]
  --port INTEGER        [default: 8765]
  --model TEXT          Vision-capable OpenRouter model id [default: anthropic/claude-sonnet-5]
  --max-iters INTEGER   [default: 6]
  --reasoning TEXT      off|low|medium|high  [default: medium]
  --cost-ceiling FLOAT  Abort a build (keeping its best build so far) once usage cost reaches this many USD
```

These apply server-wide to every task that connects. Project requests use the selected
model for both planner and workers; the mod sends only `cmd` (`build` or `project`) and
the prompt.

</details>

Build and run the mod (`mod/`, a NeoForge 1.21.1 project):

```bash
cd mod
./gradlew runClient   # or runServer; or `./gradlew build` and drop the jar in a world's mods/
```

Then use `/build a small stone hut` or `/project a fortified riverside town`. Chat shows
safe progress and block stats as the task works; planner/worker hidden reasoning is not
forwarded. Blocks appear near the player after each successful iteration or component.
Only one build or project runs at a time, and there's no
authentication by design — this targets a local/trusted world, not a public server.
Run artifacts (`runs/<timestamp>-<slug>/`, including `final.schem`) are still written
for debugging, same as the CLI.

## The blueprint DSL

Blueprints are sandboxed Python — no imports, no `_`-prefixed attribute access,
no dangerous builtins, and a line-count + wall-clock execution budget. See
[`src/mcbuild/dsl/REFERENCE.md`](src/mcbuild/dsl/REFERENCE.md) for the full
primitive/transform reference and worked examples.

## Capabilities

- **Incremental editing**: `submit_blueprint` (full rebuild), `str_replace` (find/replace against
  the accumulated blueprint source, then rerun it whole), `edit_region` (rebuild one bounding box,
  freeze the rest).
- **Bulk + detail primitives**: `set_blocks`, `weighted_block`, `scatter`, `frame`, `window_grid`.
- **`get_block(x, y, z)`**: reads back whatever the blueprint has placed at a cell so far (or
  `None`), so later code can react to earlier code — skip already-weathered cells, check a
  neighbor before placing trim, etc.
- **Block states**: `"oak_stairs[facing=north,half=top]"` etc. render with true geometry (stairs,
  slabs, walls, fences, fence gates, trapdoors, doors, panes) and export with the state suffix.
- **Free 3D camera** for `inspect` (arbitrary position + look-at, orthographic z-buffer), plus
  arbitrary/y-axis slices and a lossless text `query` tool (ASCII floor plans, point lookups,
  material histograms).
- **`'air'`** is placeable — carves/erases and is exported as `minecraft:air`.

Every build call names the views it wants back (up to 8 per build — isometric
yaws, top-down, cutaways/slices), and the self-critique render is a contact
sheet of exactly those views, with dimensions/block-count/top-materials stats
reported alongside:

![Contact sheet: iso rotations, top-down, and cutaways](docs/images/mansion-contact-sheet.png)

## Project layout

```
src/mcbuild/
  cli.py             typer CLI, rich progress feed, sixel/ANSI display
  config.py          run configuration
  voxel.py           sparse VoxelGrid
  palette.py         curated block palette + fuzzy suggestions
  rundir.py          runs/<timestamp>-<slug>/ artifact management
  dsl/                sandbox, stdlib primitives, errors, REFERENCE.md
  render/             mesh rasterizer + free camera, iso contact sheet, sixel encoder,
                      block geometry (blockmodel/blockstate), textures
  llm/                OpenRouter client, scripted offline FakeLLM
  agent/              orchestration loop, prompts, tool schemas, text query views
  orchestrator/       project contracts, planner, 2.5D regions, serial workers, merge logic
  export/             Sponge Schematic v3 (.schem) export
  server/             WebSocket entry point, build/project sessions + grid diffing

mod/                  NeoForge 1.21.1 mod: /build + /project, shared WS client, block placement
```

## Development

```bash
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run ty check            # type check
```

Tests cover: project models/regions/validation/planning/merge/offline E2E, sandbox security,
DSL shape primitives,
palette lookup + suggestions, isometric renderer output, sixel encoding,
Sponge Schematic v2 round-trip via `nbtlib`, and an offline agent-loop
integration test (scripted LLM: error -> fix -> finish) via the CLI's
`--fake-llm` path.

CI runs all four (lint, format check, type check, tests) on every push/PR.

## Notes / limitations

- Accurate geometry covers the core architectural shape families; other stateful blocks fall
  back to full cubes, and blocks with no resolvable texture (e.g. `air`, `barrier`) don't render.
- Block geometry is paired from bundled vanilla blockstate JSON + hardcoded shape templates
  (the vanilla model JSONs are not shipped); silhouettes are correct, not pixel-exact-vanilla.
- No cross-run memory / few-shot retrieval of past builds.
- Project workers are serial; responsibilities are 2.5D and do not inspect real terrain.
- There is no pause/resume queue, worker-to-worker free conversation, automatic component retry,
  or final global architectural critic in this milestone.
- Live building (`mod/` + `mcbuild-server`) is NeoForge-only, single-task-at-a-time, and has
  no authentication — meant for a local/trusted world, not a public server.

## Future work (backlog)

- Iteration diffs (blocks added/removed vs. the previous iteration) and richer stats
  (per-storey counts, interior air volume, mirror-symmetry score).

## Acknowledgments

This project was inspired by [*APT: Architectural Planning and Text-to-Blueprint
Construction Using Large Language Models for Open-World Agents*](https://arxiv.org/pdf/2411.17255)
(Chen & Gao, 2024), which explores LLM-driven blueprint construction for
Minecraft agents. mcbuild is an independent, from-scratch implementation and
is not affiliated with or derived from that paper's code.

## AI disclosure

This project was built with significant AI assistance (Claude): most of the
codebase, this README, and much of the iterative design work were written or
co-written by an LLM agent under human direction and review. The renders
throughout this README are unedited output from the agent described above,
not hand-picked or touched-up examples.

## License

[MIT](LICENSE), except for the bundled Minecraft block textures/blockstates —
see [`src/mcbuild/assets/NOTICE.md`](src/mcbuild/assets/NOTICE.md). Minecraft
is a trademark of Mojang Studios / Microsoft; this project is not affiliated
with or endorsed by them.
