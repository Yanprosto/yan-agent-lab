# YAN roadmap

Status words follow invariant I15:

- **proven** — code on `main` and a passing run log on that code;
- **demonstrated in branch** — passed live in a branch, not merged;
- **planned** — not built.

## Current state (as of 2026-11-06)

### Proven on `main` (up to v0.9)

| Capability | Version |
| --- | --- |
| Bidirectional bridge: action → observation rounds | v0.1–v0.2 |
| Functional API: inspect, inventory, energy, real-tick wait, safe place/remove | v0.3 |
| Experiment lifecycle: build, seed, wait, observe, score, rollback, mutate, retry | v0.4 |
| Mekanism transporter mode mutation judged by live item flow | v0.5 |
| Skill memory (JSON snapshot) + topology mutation | v0.6 |
| Runtime logging to `yan-runtime-logs` | v0.7 |
| Memory-seeded topology candidate search, ranked | v0.8 |
| Spatial candidate search (axis, branch length, drop) | v0.9 |
| Mekanism recon audit (javap, oracle defaults) | docs |
| mcbuild base: DSL, render, single-build agent, project orchestrator | upstream |

*Run-log ids for each row: to be filled during consolidation.*

### Demonstrated in branches, not on `main`

Industrial line (each branch builds on the previous):

| Branch | Claimed capability (vision §19) |
| --- | --- |
| `yan-local-repair-v1.1` | local branch repair, obstacle-aware routing |
| `yan-transit-aware-v1.2` | transit inspection / clearing in accounting |
| `yan-autonomous-factory-v2.0` | production cell |
| `yan-powered-factory-v2.1` | precharged energy cube, powered cells |
| `yan-goal-industry-v3.0` | goal → two-stage process |
| `yan-iron-works-v4.0` | 18 raw iron → 24 dust → 24 ingots, exact accounting |
| `yan-plan-compiler-v4.1` | plan compiler (scope to be confirmed) |

Environment / visual line: `yan-environment-builder-v1.0`, `yan-palette-*`,
`yan-sector-*`, `yan-semantic-catalog-v1`, `yan-visual-catalog-v1`,
`yan-modpack-palette-compiler-v0.1`, `yan-runtime-registry-recon-v1`.

### Known debt against the invariants

- **I14:** each experiment is a hand-written session in `server/ws_server.py`
  (+ a Java command). No shared mission engine yet.
- **L7 skill format:** `skill_store.py` stores run snapshots, not parameterised skills.
- **T1 simulation:** absent; every candidate evaluation costs real ticks.
- **I15:** most of the industrial line lives only in branches.

## Milestones

Only one milestone is active at a time.

### M0 — Concept fixed  ← active

- [ ] Owner reviews `INVARIANTS.md`, `ARCHITECTURE.md`, this file.
- [ ] Every item in `OPEN_DECISIONS.md` is decided or explicitly deferred.
- [ ] `AGENTS.md` points to `docs/concept/`.

### M1 — Consolidation

Merge the industrial line into `main` in order, with a passing live run per merge,
and fill in run-log ids above. Decide which environment/visual branches merge and
which stay experimental.
*Done when:* `main` contains the iron-works capability and the roadmap tables match.

### M2 — Shared mission engine + Plan IR

Extract the common experiment cycle from `ws_server.py` into one engine (ARCHITECTURE
§6). Define the IR levels (§2) as typed data. Re-express at least two existing
experiments (splitter, iron works) as mission data.
*Done when:* the two experiments run through the engine with no experiment-specific
session function, and their logs/verdicts are unchanged.

### M3 — Branching Industrial Planner (vision §20)

Beam search across ProcessGraph → Topology → Layout, with T0 checks and a first T1
event simulator built from L2 facts.
*Done when*, for a goal like "N iron ingots in region R":

- at least 5 process/topology candidates are generated and scored, at least 2
  structurally different ones reach T1;
- the best candidate is built in stages and verified live;
- an injected failure (blocked route / wrong side config) is diagnosed and repaired
  locally, or the next-best candidate is used, with diagnosis in the log;
- T1 predictions vs live observations are logged and discrepancies recorded;
- no goal-specific Python function was written.

### Later (order not fixed)

Shared infrastructure between lines → existing-world reuse → workshop planning →
district planning → sector restoration (vision §21). Each gets done-criteria when it
becomes active.
