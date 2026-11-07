# YAN roadmap

Status words follow invariant I15:

- **proven** — code on `main` and a passing run log on that code;
- **demonstrated in branch** — passed live in a branch, not merged;
- **planned** — not built.

Live runs below were made on the headless lab (`tools/headless_lab/`: NeoForge 21.1.255
+ Mekanism 10.7.19.85, the audited jar) unless noted.

## Current state (as of 2026-11-07)

### Proven on `main`

| Capability | Where | Live evidence |
| --- | --- | --- |
| Bridge, functional API, experiment loop (v0.1–v0.4) | mod + `server/` | v0.4 PASS |
| Mekanism transporter mode mutation (v0.5) | `server/` | PASS |
| Topology / spatial search, skill memory (v0.6–v0.9) | `server/` | v0.9 PASS (8 candidates, 7 passing, from seed skill) |
| Environment builder, local repair, transit accounting (v1.0–v1.2) | `server/` | PASS first route; PASS with injected fault (one branch rebuilt) |
| Powered multi-cell factory (v2.0–v2.1) | `server/` | PASS 24 raw → 24 ingots |
| Goal-driven industry, iron works, plan compiler (v3.0–v4.1) | `server/` | PASS 18 → 24; PASS 54 → 72 (12 machines) |
| Headless lab, `/yanlab` console command | `tools/headless_lab/`, mod | all rows of this table |
| Skill memory with committed seeds | `skill_store`, `yan_knowledge/seed/` | fresh checkout PASS |
| Mechanism catalog (blocks, 842 recipes, 736 tags, evidence levels) | `mcbuild.catalog`, `yan_knowledge/catalog/` | tests; facts cite runs |
| Green CI (ruff, format, ty, pytest) | `.github/workflows/ci.yml` | 324 tests |
| Mekanism recon audit | `docs/recon/` | docs |

### Demonstrated in branch (PR #30, ready)

| Capability | Live evidence |
| --- | --- |
| Generic machine probe: any catalog processor verified in a minimal cell | smelter, crusher (first ever run), enrichment chamber: PASS |
| Process planner v1: goal → catalog chains → line of verified cells, fallback | 8 ingots from raw iron (enrich → smelt) PASS; 4 dust from ingots (crusher) PASS |

### Known debt against the invariants

- **I14:** v0.4–v4.1 sessions in `server/ws_server.py` and mission modules are still
  hand-written; new work (probe, planner) is data-driven. Port old sessions as needed.
- **Layout:** `/yanlab plan` still lays a straight line; `/yanlab layout` fits a chain into a scanned volume.
- **Power:** one creative cube per machine (no shared backbone).
- **T1 simulation:** absent; the catalog has the numbers it needs.
- Fallback path of the planner not yet exercised live.

## Milestones

### M0 — Concept fixed  ← finishing

- [x] Concept split into vision, invariants, world, gameplay, architecture, roadmap, decisions.
- [x] `AGENTS.md` points to `docs/concept/`.
- [ ] This branch merged to `main`.

### M1 — Consolidation  ✓ done 2026-11-07

Factory chain #9–#17 verified live and merged (#26), skill memory (#27/#28), CI green.

### M2 — Catalog and generic compiler  ✓ done 2026-11-07

- [x] Mechanism catalog with evidence levels (#29).
- [x] Generic machine probe (#30).
- [x] Process planner v1: chains from recipes, verified cell line, fallback (#30).
- [x] Flexible 3D layout in a given volume (M3 step 1).

### M3 — Factories at three scales (decision 2026-11-07, ARCHITECTURE §11)  ← active

Ordered steps:

1. **3D layout in a given volume** (mode A core). ✓ 2026-11-07: low hall, shaft and
   columns hall gave three different layouts, all PASS live first try (runs 20261107T130035Z_layout_ca1b6976, 20261107T125932Z_layout_d81a3fc9, 20261107T125819Z_layout_d289189a). Test volumes: low hall, vertical shaft,
   hall with columns, L corridor. Machines placed in free cells, transporters routed in
   3D, machine sides set from where the routes arrive.
   *Done when:* one goal in three volumes yields three different layouts, all passing
   live with exact accounting, with no volume-specific code.
2. **Shop as a module with ports.** ✓ 2026-11-07: module iron_ingot_enrich_smelt_shop_v1
   built from its description in pillared_hall (no turn, run 20261107T131722Z_module_174c0a54) and narrow_room
   (quarter turn, run 20261107T131821Z_module_4cc7264c), both PASS 6 → 8. A verified group of machines with input, output and
   power ports on its boundary.
   *Done when:* a shop is built from its module description in two different
   volumes and passes; its ports are recorded.
3. **District from shops + trunk lines** (mode B). Shared power backbone and freight
   lines across chunks connect shops; architecture is generated around the layout.
   *Done when:* two shops tens of blocks apart, one power source, one freight trunk,
   pass together; breaking one backbone segment is diagnosed and repaired locally.
4. **Parallel machines per stage** inside a shop when the goal needs throughput.
   *Done when:* a 24-ingot goal with a time limit puts 2–3 machines on the bottleneck
   stage, every machine participates, accounting exact.

### M4 — Verified modules + first broken plant

Compose a small plant from verified shops, then generate a damage set
(ARCHITECTURE §9). *Done when:* a generated plant was verified working, broken in 3+
places, and restored to the same contract using only the planned repair items.

### Later (order not fixed)

T1 event simulation from catalog facts → integration with the in-game world generator
(D8) → sector-scale aging and damage → runtime helper mode via NPCs (vision §0, §21).
