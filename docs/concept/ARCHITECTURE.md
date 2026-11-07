# YAN architecture

This fixes the parts the vision text implies but does not define: the layers, the
intermediate representation the planner searches over, the evaluation tiers, the
skill format and the role of the LLM. Items marked **[proposed]** are not yet decided;
see `OPEN_DECISIONS.md`.

## 0. Generation pipeline

The primary use of the engine is world generation (vision §0):

~~~text
1 DESIGN    goal/brief → Plan IR → candidates → best layout          (L3–L5)
2 VERIFY    build in a lab world, run, check contract and accounting (L0, L5, L6)
3 MODULE    save as parameterised, verified module = skill           (L7)
4 COMPOSE   assemble modules into plants / districts / sectors        (L4, orchestrator)
5 BREAK     choose damage with knowledge of the IR (see §9)
6 AGE       visual decay, debris, palette (environment line)
7 EXPORT    schematics / structure pieces for the in-game generator
~~~

Steps 1–3 are slow and run offline. Steps 4–7 should become fast enough to run per
sector. How step 7 meets Minecraft world generation is decision D8.

The runtime helper mode (player commands an NPC helper) reuses L0–L7 on the live
world with the player's permissions; it is secondary and comes later.

## 1. Layers

~~~text
L7  Memory          skills (parameterised plan fragments) + capability facts
L6  Executor        staged execution, contract checks, scoped rollback, repair
L5  Evaluation      T0 static → T1 simulation → T2 partial live → T3 full live
L4  Planner         hierarchical beam search over the IR levels
L3  Plan IR         Goal → ProcessGraph → Topology → Layout → ActionPlan
L2  Capabilities    block/mod → capabilities, ports, configs, evidence level
L1  World model     observed state with freshness, ownership map, region index
L0  Bridge          NeoForge: authoritative actions, observations, ticks, budget
─────────────────── WebSocket ─────────────────────────────────────────────────
                    Minecraft world
~~~

L0 runs inside Minecraft. L1–L7 run in the external Python server [§29]. Each layer
talks only to its neighbours; the planner never sends raw block actions.

## 2. Plan IR

The planner searches over explicit, serialisable levels. Each level refines the
previous one and every level is a valid place to stop, score and branch [§9, §10].

| Level | Contains | Example |
| --- | --- | --- |
| **Goal** | target resource/state, quantity or rate, region, permissions, contract | "24 iron ingots in chest C, inside region R" |
| **ProcessGraph** | nodes = capability roles with recipes; edges = flows (resource type, amount/rate) | `raw_iron → ENRICH → dust → SMELT → ingot` |
| **Topology** | concrete implementation per node, shared infrastructure, buffers, power plan | 2× Enrichment Chamber, shared cable grid, buffer between stages |
| **Layout** | 3D placement in the region, orientation, ports, routes, clearances | coordinates + facing + route polylines |
| **ActionPlan** | ordered stages; each stage = block/config actions + its contract | stage 1 power backbone, stage 2 input logistics, ... |

Rules:

- Each level is a typed, validated data structure (like the existing `ProjectPlan`),
  not free text.
- Compilation Layout → ActionPlan is deterministic code.
- A skill (§5) is a fragment of this IR, so skills compose by construction.

## 3. Search

Hierarchical beam search first [§10]: at each IR level generate candidates, score,
keep top-K, refine only those. Scores are a vector (functional, spatial, integration,
robustness, construction, aesthetic [§11]) reduced by goal-dependent weights.
MCTS, learned priors and value functions are later additions behind the same
interface.

## 4. Evaluation tiers

Real-world tests are expensive (real ticks, real blocks). Candidates are promoted
through cheaper tiers first:

| Tier | What | Cost | Decides |
| --- | --- | --- | --- |
| **T0 static** | schema validity, permissions, footprint, collisions, port connectivity | ms | discard invalid |
| **T1 simulation** | fast event simulation of flows, rates, buffers, energy from L2 facts | ms–s | rank survivors |
| **T2 partial live** | build one stage / one cell in-world, observe | real ticks | confirm the model |
| **T3 full live** | the complete mission contract | real ticks | final verdict |

Only the top 1–3 candidates reach T2. A T1 prediction that disagrees with a T2/T3
observation is a recorded model error: the capability fact is corrected or its
evidence level is lowered, and the candidate family is penalised [§12].

## 5. Skill format

A skill is a verified, **parameterised** IR fragment, not a snapshot of one run.

~~~text
id, version
capability signature   inputs/outputs by capability and resource type
parameters             e.g. axis, branch lengths, machine count, with valid ranges
preconditions          checkable against the world model (space, power, mods present)
template               IR fragment (Topology and/or Layout) using the parameters
contract template      verification contract instantiated from the parameters
known failure modes    diagnosis → repair pattern
evidence               run ids per parameter combination actually observed
~~~

A skill applied with parameters never observed live is a T1-level hypothesis until
its own run passes [I1, I4].

## 6. Missions as data

The shared engine runs any mission described as:

~~~text
Mission = goal + region + permissions + contract + candidate generator(s) + budget
~~~

The engine owns the common cycle `plan → stage → build → seed → wait → observe →
score → accept | repair | rollback | next candidate → log → save skill` [I14].

## 7. Role of the LLM [proposed]

~~~text
LLM proposes   deterministic code disposes
~~~

- LLM may: decompose goals, propose candidate process graphs and layouts, suggest
  diagnosis hypotheses, critique aesthetics from renders, write DSL geometry.
- LLM may not: declare success, bypass T0 validation, issue unvalidated world actions,
  edit capability facts without evidence.
- Scoring, contracts, ownership, accounting and verdicts are deterministic code.

## 8. Existing code mapping

| Layer | Existing base to extend first |
| --- | --- |
| L0 | `mod/` (NeoForge bridge, `BuildSessionManager`), WebSocket protocol |
| L1 | functional API from v0.3 (inspect, inventory, energy) |
| L2 | `docs/recon/mekanism/oracle_defaults.json`, `MEKANISM_AUDIT.md` |
| L3/L4 | `orchestrator/` (`ProjectPlan`, `WorkPackage`, permissions, merge), `topology_search.py`, `spatial_search.py` |
| L5 | `render/`, `orchestrator/validator.py`; T1 simulator does not exist yet |
| L6 | experiment loop from v0.4–v0.9 in `server/ws_server.py` (to be extracted) |
| L7 | `server/skill_store.py` (snapshots today, needs §5 format) |
| geometry | `dsl/`, `agent/` (architectural shell, not machinery logic) |

## 9. Damage model

Breaking is generated from the verified IR, not applied at random.

~~~text
Damage = target (IR node/edge) + kind + what it disables + what repairs it + loot left
~~~

Kinds (initial): missing component (looted), severed cable/transporter, unpowered
backbone, wrong side/transmitter config, collapsed or blocked route, hostile/contaminated
zone.

Rules:

- Every damage set must stay **repairable**: the engine can produce a repair plan
  using only items obtainable by the player at the intended stage.
- Each repair has a **payoff** the engine can name (line N produces again, door opens,
  route reconnects).
- Difficulty is controlled by count, depth (backbone vs leaf) and the rarity of the
  repair items.
- Loot left in buffers follows the accounting of the working state (I3).

## 10. Performance in the world

Broken systems do not tick. Only restored parts run; generated plants must not be
placed as kilometres of live machines. Tick-budget rules (I7) apply to placement at
generation time as well as to runtime edits.

## 11. Two generation modes and three scales (decision 2026-11-07)

Factories are generated in two directions; the engine is the same, only the side the
constraints come from differs.

| Mode | Order | Input → output | Lore origin (WORLD §3b) |
| --- | --- | --- | --- |
| **A. Retrofit** | world first, factory later | given volume → layout that fits it | later human workshops inside existing halls |
| **B. Infrastructure** | factory first, world around it | process + site → layout → architecture shell | old machine plants, built by the builders |

In mode B the agent produces the process skeleton (machines, routes, trunk lines) and
the environment line (palettes, sectors, aging) wraps it in architecture.

Three scales, matching the WORLD scale table:

| Scale | Size | What | Needed by |
| --- | --- | --- | --- |
| **Cell** | 3–10 blocks | one machine with its connections | both (machine probe, done) |
| **Shop (module)** | 16–48 blocks, one room | verified machine group with input, output and power ports on its boundary | A: fit into a room; B: brick of a district |
| **Plant / district** | 100–500 blocks, tens of chunks | shops joined by power and freight trunk lines | B |

Build order: 3D layout in a volume → shop modules with ports → districts with trunk
lines (the shared power backbone lives here) → parallel machines per stage. The project
orchestrator from the mcbuild fork (work packages with interfaces) is the first
candidate for composing districts (I6).
