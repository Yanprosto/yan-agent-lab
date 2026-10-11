# YAN Agent Lab — Project Concept and Long-Term Design

> This document is the durable conceptual source of truth for YAN Agent Lab.
> It exists so the project direction does not get diluted across chats, experiments,
> branches, or temporary implementation details.
>
> If a future implementation choice conflicts with this document, prefer this concept
> unless there is a deliberate, documented decision to change it.

---

## 1. Core vision

YAN Agent Lab is not ultimately a “Minecraft factory builder”.

The long-term goal is an autonomous in-world engineer/builder that can operate at
multiple scales:

~~~text
block
→ connection
→ primitive
→ motif
→ module
→ production cell
→ technological line
→ workshop
→ district
→ infrastructure sector
→ settlement
→ megastructure
~~~

The agent must be able to understand a goal, inspect the actual world, form several
candidate plans, choose between them, build incrementally, observe what really happened,
repair only what failed, preserve what works, and gradually transform a hostile or
abandoned environment into functioning infrastructure and civilization.

The industrial/factory work is a proving ground for this larger capability.

The final target is much closer to an autonomous engineer, systems planner,
construction agent, restoration agent, infrastructure operator and world-transforming
builder than to a macro that places known blocks at known coordinates.

---

## 2. World fantasy and gameplay thesis

The central fantasy is restoring and absorbing abandoned or hostile megastructure into
the player's own civilization.

A sector should not remain a static loot dungeon forever.

The intended progression is physical and systemic:

~~~text
foreign / dark / abandoned / dangerous
→ partially powered
→ traversable
→ logistically connected
→ industrially useful
→ defended
→ inhabited
→ integrated into the player's civilization
~~~

The world itself must visibly change because of the player's and agent's actions.

Examples:

- power returns to previously dark areas;
- lights begin working;
- doors and elevators reopen;
- cargo relays activate;
- rail connections are restored;
- broken logistics become functional;
- unsafe routes become secured;
- contamination or hostile occupation is pushed back;
- abandoned rooms become workshops, depots, housing, clinics, command posts;
- old infrastructure is reused instead of replaced where possible;
- new structures grow around restored old systems;
- connected sectors become parts of one larger network.

A successful sector should feel physically different after restoration.

Avoid the weak loop:

~~~text
go to dungeon
→ loot it
→ dungeon remains unchanged forever
~~~

Prefer:

~~~text
enter sector
→ scavenge
→ understand systems
→ restore utilities
→ reopen routes
→ establish logistics
→ build industry
→ secure area
→ populate / repurpose
→ connect to civilization
~~~

This transformation is one of the most important principles in the project.

---

## 3. Aesthetic direction

Primary visual and atmospheric references:

- BLAME!;
- Peripeteia;
- arcologies;
- brutalism;
- industrial megastructures;
- layered infrastructure;
- abandoned utility architecture;
- cyberpunk / post-industrial interiors;
- giant service corridors;
- verticality;
- rail shafts;
- machine halls;
- maintenance decks;
- partially inhabited ruins;
- architecture that looks larger than the immediate gameplay space.

The target is not generic “sci-fi factory”.

The world should communicate age, mass, infrastructure history, repairs on top of
repairs, repurposed spaces, improvised habitation inside giant old systems, and
human-scale life inside machine-scale architecture.

Visual progression matters:

~~~text
raw abandoned structure
→ emergency repairs
→ temporary cabling / lamps / barriers
→ stable logistics
→ industrial occupation
→ permanent infrastructure
→ inhabited district
~~~

The agent should eventually learn not only whether a build works, but whether it fits
the surrounding structure and visual language.

---

## 4. Reuse before replacement

The agent should behave like an engineer in an existing world.

Preferred order:

1. inspect what already exists;
2. understand whether it can be reused;
3. repair or adapt existing infrastructure;
4. extend it;
5. build an entirely new system only when reuse is inferior.

This applies to power, rails, corridors, shafts, storage, machinery, rooms, transport,
doors, elevators, settlements and defenses.

The agent should not flatten the environment and rebuild everything from zero unless
that is actually the best solution.

---

## 5. Core agent behavior

The agent should operate as a closed-loop system:

~~~text
GOAL
↓
OBSERVE
↓
MODEL CURRENT STATE
↓
GENERATE MULTIPLE CANDIDATES
↓
SCORE / SEARCH
↓
EXECUTE PARTIALLY
↓
OBSERVE REAL RESULT
↓
ACCEPT / REPAIR / ROLLBACK / TRY ALTERNATIVE
↓
LEARN / SAVE VERIFIED SKILL
~~~

The real Minecraft world is the source of truth.

The planner can predict. The simulator can estimate. The skill library can suggest.
But the world decides whether something actually works.

---

## 6. Build a little, inspect, continue

The agent should not blindly emit a huge structure and hope it works.

Preferred pattern:

~~~text
build a little
→ inspect
→ validate
→ continue
~~~

For larger tasks:

~~~text
plan district
→ build power backbone
→ verify
→ build logistics spine
→ verify
→ build first production module
→ verify
→ expand
~~~

This supports local failure detection, local repair, smaller rollback radius,
preservation of healthy subsystems and learning from real feedback.

---

## 7. Local repair over full rebuild

Do not destroy healthy subsystems because one branch failed.

The agent should be able to:

- identify the failed subsystem;
- isolate it;
- preserve working branches;
- remove only the broken part;
- generate alternatives for that region;
- reconnect;
- verify again.

This has already been demonstrated in early Mekanism experiments and should remain a
permanent architectural rule.

---

## 8. Conservation and accounting

Whenever a task involves items, energy, fluids, chemicals, entities, or other countable
resources, the agent should maintain accounting.

For transport:

~~~text
source
+ machine buffers
+ network transit
+ output
= expected total
~~~

For processing:

~~~text
input count
× recipe transformation
= expected intermediate / output count
~~~

A subsystem should not be considered successful if material simply disappears from the
visible source. Transit, machine buffers, intermediate buffers and final storage must be
accounted for.

---

## 9. The “chess engine” planning model

A key planning direction is inspired by chess engines.

Minecraft gives us “pieces”:

- machines;
- cables;
- transporters;
- belts;
- pipes;
- rails;
- storage;
- power sources;
- doors;
- elevators;
- NPC facilities;
- defensive blocks;
- structural modules.

Each piece has capabilities, constraints, footprint, inputs, outputs, orientation,
connectivity rules, throughput, energy/resource cost, compatibility and placement
consequences.

A goal is analogous to a target position.

The planner should not jump directly from goal to one hard-coded solution.

Instead:

~~~text
goal
→ candidate process graphs
→ candidate subsystem topologies
→ candidate layouts
→ candidate routes
→ candidate block actions
~~~

Each level should generate alternatives.

Example:

~~~text
GOAL: process iron

candidate process graph A:
raw iron → smelt

candidate process graph B:
raw iron → enrich → smelt

candidate process graph C:
raw iron → factory enrichment → factory smelting
~~~

Then for one process graph:

~~~text
layout A
layout B
layout C
~~~

Then:

~~~text
shared energy
independent energy
existing grid reuse
~~~

Then:

~~~text
shortest route
maintenance-friendly route
obstacle-avoiding route
existing corridor route
~~~

This is how the project should escape hard-coded factory templates.

---

## 10. Search strategy: hierarchical Beam Search first

Literal exhaustive search at block level will explode combinatorially.

Planning should therefore be hierarchical.

Preferred early strategy: Beam Search.

At each abstraction level:

1. generate several candidates;
2. score them;
3. keep only top-K;
4. expand only those.

Example:

~~~text
5 process graphs
→ keep top 3

3 × 6 topology variants
→ keep top 4

4 × 8 layout variants
→ keep top 4

4 × route variants
→ test best 1–3 in-world
~~~

Possible future additions:

- Monte Carlo Tree Search;
- learned value functions;
- learned policy priors;
- model predictive control;
- cost-to-go estimation;
- failure probability prediction.

The first useful planner should remain interpretable and debuggable.

---

## 11. Candidate scoring

Plans should be evaluated by multiple criteria, not only shortest path or minimum block
count.

Functional:
- can satisfy goal;
- throughput;
- latency;
- capacity;
- stability;
- conservation;
- redundancy.

Spatial:
- footprint;
- obstruction;
- route length;
- vertical complexity;
- accessibility;
- maintenance space.

Integration:
- reuse of existing infrastructure;
- compatibility with current power/logistics;
- low destruction;
- minimal interference with healthy systems.

Robustness:
- number of single points of failure;
- buffer capacity;
- ease of repair;
- observability;
- modularity.

Construction:
- block count;
- rare component cost;
- time to build;
- number of state/config operations;
- risk of unsafe edits.

Aesthetic / architectural:
- alignment with nearby structure;
- visual coherence;
- service access;
- believable industrial layout;
- preservation of strong existing geometry.

Eventually these weights should respond to the user's goal.

---

## 12. Real-world verification as board evaluation

Abstract planning is cheap but imperfect. Minecraft is the real physics.

Therefore:

~~~text
candidate predicted good
→ build small real portion
→ observe
→ compare predicted vs actual
~~~

If actual result differs:

- update model;
- penalize candidate family;
- repair;
- select second-best alternative;
- save the discovered fact.

This is how planning becomes grounded rather than purely symbolic.

---

## 13. Skill memory

Successful behavior should become reusable knowledge.

A useful skill should contain:

- preconditions;
- goal;
- topology;
- relevant configuration;
- assumptions;
- observations;
- verification contract;
- known failure modes;
- successful repair patterns.

Examples already reached or targeted:

- two-branch item splitter;
- transit-aware branch repair;
- environment-aware routing;
- precharged Creative Energy Cube placement;
- powered production cell;
- multi-cell factory;
- goal-driven iron processing district.

Long-term, skills should compose:

~~~text
industrial district
  ├─ power backbone skill
  ├─ input logistics skill
  ├─ enrichment line skill
  ├─ intermediate buffer skill
  ├─ smelting line skill
  └─ output storage skill
~~~

The project should increasingly build from verified skills rather than re-discovering
the same low-level facts every run.

---

## 14. Capability-driven architecture

The system should think in terms of capabilities, not only mod-specific block names.

Examples:

~~~text
POWER_SOURCE
POWER_TRANSMITTER
ITEM_SOURCE
ITEM_TRANSPORT
ITEM_BUFFER
PROCESSOR
STORAGE
RAIL
ELEVATOR
DOOR
LIGHTING
NPC_HOME
DEFENSE
~~~

A specific block is one implementation of a capability.

Example:

~~~text
POWER_TRANSMITTER
  → Mekanism Universal Cable
  → another compatible mod cable
~~~

The long-term planner should choose by capability, world context, constraints and
available mods.

---

## 15. UniversalMods / reconnaissance direction

A dedicated reconnaissance layer should inspect real mod behavior.

Purpose:

- discover APIs;
- detect capabilities;
- understand side configuration;
- understand inventories;
- understand energy/fluid/chemical interfaces;
- generate adapters;
- run controlled experiments;
- record verified behavior.

Preferred loop:

~~~text
inspect source / API
→ form hypothesis
→ live experiment
→ save verified capability
~~~

Avoid guessing when the mod's real behavior can be inspected or tested.

---

## 16. Minecraft as a live engineering laboratory

Useful agent actions include:

- inspect block;
- inspect BlockEntity;
- inspect neighborhood;
- read inventory;
- read energy;
- read network transit;
- place;
- remove;
- configure side;
- configure transmitter connection;
- seed controlled test material;
- wait real ticks;
- rollback session-owned edits.

Every important subsystem should become observable enough to diagnose failures.

The project should continually improve observability rather than adding blind retries.

---

## 17. No manual test-fixture dependence

The user should not repeatedly build chests, pipes, cables, test machines or dummy
structures just to let the agent work.

The agent should provision its own test and production environment whenever safe.

Manual setup should be exceptional, not normal.

---

## 18. Development pace principle

The project should not advance only by multiplying identical machines.

Bad progression:

~~~text
2 smelters
→ 4 smelters
→ 8 smelters
→ 16 smelters
~~~

Better progression:

~~~text
single machine
→ production cell
→ multi-stage process
→ goal-driven process graph
→ branching planner
→ workshop
→ district
→ infrastructure sector
~~~

Scale should increase in abstraction and autonomy, not only block count.

Micro-tests remain useful when isolating a new unknown, but once a primitive is verified,
development should move quickly into larger integrated missions.

---

## 19. Current proven foundations

The project has already demonstrated important primitives.

Generic world bridge:
- block inspection;
- BlockEntity observation;
- neighborhood inspection;
- inventory read;
- energy read;
- real-tick waits;
- safe placement/removal;
- session-owned rollback.

Mekanism behavior:
- logistical transporter connection modes;
- machine side configuration;
- energy side configuration;
- Universal Cable pull configuration;
- transporter transit inspection;
- transit clearing;
- machine energy verification;
- precharged Creative Energy Cube placement using the same filled ItemStack variant
  Mekanism exposes in its creative tab.

Search / planning:
- topology candidate search;
- spatial candidate search;
- obstacle-aware routing;
- local branch repair.

Repair:
- a failed branch has been diagnosed and rebuilt while preserving a healthy branch.

Multi-cell composition:
- two powered production cells have been built and verified together.

Goal-driven industry:
- a goal has been resolved into a real two-stage process:

~~~text
18 raw iron
→ 2 Enrichment Chambers
→ 24 iron dust
→ controlled handoff
→ 2 Energized Smelters
→ 24 iron ingots
~~~

The final run verified exact final output, zero remaining intermediate material, zero
transit, world preservation and reusable skill saving.

---

## 20. Immediate planning milestone

The next major milestone should be a Branching Industrial Planner.

Target behavior:

~~~text
goal
→ generate 5–20 process candidates
→ score
→ beam search top-K
→ generate topology/layout candidates
→ score
→ execute best candidate
→ observe
→ if failure:
     repair or try next-best
→ update knowledge
~~~

This is more valuable than adding another single hard-coded factory recipe.

The first planner can remain deterministic and heuristic. It does not need full MCTS to
be useful.

---

## 21. Medium-term milestones

### 21.1 Multi-recipe industrial planning
Agent can select among several ways to produce a requested resource.

### 21.2 Shared infrastructure
Several production lines use common power, storage and logistics backbone.

### 21.3 Existing-world reuse
Agent detects and integrates with previously built networks.

### 21.4 Workshop planning
Goal becomes “build an iron-processing workshop” rather than “build machine X at Y”.

### 21.5 District planning
Goal becomes “establish an industrial district”, and the agent allocates receiving,
processing, storage, power, maintenance and transport zones.

### 21.6 World restoration
Agent reactivates infrastructure in an existing ruined sector instead of constructing
everything in empty air.

---

## 22. Long-term civilization loop

The industrial system should feed a larger civilization loop:

~~~text
scavenge
→ sort / recover
→ process
→ manufacture
→ build infrastructure
→ arm / supply settlement
→ expand safe territory
→ restore more sectors
~~~

Core fantasy:

~~~text
marauding / scavenging
→ recycling
→ industry
→ infrastructure
→ settlement
→ civilization
~~~

Technology mods are not the goal by themselves. They are tools for making the world
visibly more civilized.

---

## 23. NPCs and settlement direction

NPC systems should eventually interact with infrastructure.

Desired possibilities:

- workers occupy restored facilities;
- guards defend secured routes;
- logistics staff operate hubs;
- residents move into restored districts;
- specialized buildings appear as sector functionality grows;
- NPC presence becomes a visual indicator of stabilization.

Possible mod systems may include Villagers Reborn, maid/helper mods, custom NPC systems
and MineColonies-inspired organizational patterns.

The exact implementation may change, but the intent should remain: a restored sector
should begin to feel inhabited and socially functional.

---

## 24. Transportation and verticality

The final world should not be a flat factory floor.

Important systems:

- rail;
- cargo rail;
- Create trains;
- elevators;
- shafts;
- service ladders;
- bridges;
- vertical freight;
- multi-level logistics;
- doors and checkpoints.

Restoration should often involve reconnecting spatial layers.

A sector can be “won” not because every hostile entity is dead, but because its
transport topology becomes usable.

---

## 25. Structural transformation

The agent should eventually modify topology, not only machinery.

Examples:

- reopen a sealed corridor;
- create a service bypass;
- restore a bridge;
- connect two decks;
- build a freight elevator;
- add a maintenance platform;
- create a rail spur;
- convert a dead-end room into a logistics node.

This is where the project moves from factory automation into world engineering.

---

## 26. Safety and ownership rules

The agent must distinguish:

- blocks it owns;
- blocks it may modify;
- blocks it should preserve;
- unknown player/world infrastructure.

Never casually destroy existing structures simply because a plan wants the space.

Session-owned blocks are safe rollback targets.

Unknown existing world blocks require stronger justification and a future permission
policy.

---

## 27. Tick budget and performance

The agent must respect Minecraft server performance.

Preferred patterns:

- queued construction;
- bounded actions per tick;
- incremental edits;
- no giant synchronous world mutation;
- avoid excessive repeated scans;
- cache observations where valid;
- verify only relevant regions;
- use FAWE-like queued thinking where appropriate.

Large structures should be built as scheduled work, not one catastrophic frame.

---

## 28. External projects and reusable ideas

Useful concepts already identified:

mcbuild:
- external Python agent;
- DSL;
- self-editing builds;
- render/critique/edit loop;
- WebSocket bridge;
- grid diffing.

mcbuild multi-agent fork:
- Planner;
- semantic work packages;
- spatial permissions;
- transactional merge;
- project-level coordination;
- live deltas.

Minecraft Agentic Builder:
- repair;
- world verification;
- visual critic.

Voyager:
- skill library;
- execution feedback;
- iterative behavior learning.

Mindcraft:
- code execution patterns.

MineColonies / Structurize:
- settlement structure organization;
- modular construction patterns.

FAWE:
- queued / performance-conscious world editing ideas.

Reuse permissively licensed implementation where appropriate. GPL code should be treated
as architectural reference unless licensing is deliberately accepted.

---

## 29. External agent architecture

Preferred architecture:

~~~text
external Python planner / agent server
        ↕ WebSocket
NeoForge live bridge
        ↕
real Minecraft world
        ↕
observations / verification
~~~

The external layer handles planning, search, candidate generation, skill memory,
scoring, orchestration and logging.

The Minecraft-side bridge handles authoritative world actions, real tick timing, real
capabilities, safe placement/removal, low-level mod integration and observations.

This separation should remain.

---

## 30. Repository and workflow principles

Primary repository:

~~~text
Yanprosto/yan-agent-lab
~~~

Runtime logs:

~~~text
Yanprosto/yan-runtime-logs
~~~

Development workflow:

- feature branch;
- draft PR;
- live test;
- only then merge;
- main should remain last known green;
- runtime logs should capture meaningful runs;
- successful capabilities should be documented and saved as skills.

Do not claim a branch is merged unless confirmed.

---

## 31. Run logging

Every meaningful live mission should produce durable logs.

Useful run information:

- command;
- goal/prompt;
- run id;
- actions;
- observations;
- chat decisions;
- failures;
- repairs;
- final verdict;
- saved skill.

The log should allow future analysis without screenshots.

The user should be able to say “смотри последний run” and the agent should inspect the
runtime repository directly.

---

## 32. Success is not “placed blocks”

A build is not successful just because the blocks exist.

Success requires proving the intended behavior.

Factory:
- material entered;
- machines processed;
- outputs reached destination;
- transit cleared;
- counts reconcile.

Power:
- source contains/provides energy;
- network transfers;
- consumers receive.

Rail:
- route is connected;
- traversal is possible.

Restored sector:
- required systems function;
- critical routes are usable;
- subsystem state is stable.

Verification should match the semantic goal.

---

## 33. Failure is useful data

A failed run should produce knowledge.

The system should ask:

- what assumption failed?
- was the model wrong?
- was placement wrong?
- was configuration wrong?
- was topology wrong?
- was routing wrong?
- was timing wrong?
- did the environment differ from prediction?

Then:

~~~text
failure
→ diagnosis
→ model update
→ candidate penalty / new rule
→ repair
~~~

Blind retries are low-value.

---

## 34. Observability before brute force

When a subsystem fails, prefer adding or using observation rather than randomly changing
configuration.

Bad:

~~~text
power failed
→ toggle random sides
→ retry
~~~

Good:

~~~text
power failed
→ inspect source
→ inspect cable state
→ inspect network
→ inspect consumer
→ isolate failing edge
→ repair edge
~~~

This principle should apply everywhere.

---

## 35. Visual references and design discussion

When visual understanding matters, use relevant images/references more often.

Good uses:

- compare worldgen styles;
- compare industrial architecture;
- compare district layouts;
- compare brutalist forms;
- compare megastructure references;
- inspect downloadable Minecraft maps;
- choose visual motifs.

Do not use images merely as decoration. Visual references should help make design
decisions.

---

## 36. Minecraft reference curation

For YAN REFS, prioritize references that are actually downloadable.

Preferred:
- Planet Minecraft world downloads;
- CurseForge maps;
- verified schematics;
- verified litematics;
- direct archives.

Video-only inspiration can be secondary, but should not dominate the main reference list
unless a real download is verified.

Reference organization should be multi-scale.

Large:
- megastructure maps;
- arcologies;
- city-scale sectors.

Medium:
- industrial halls;
- stations;
- depots;
- workshops;
- residential modules.

Small:
- doors;
- machine rooms;
- kiosks;
- service nodes;
- utility details;
- props;
- architectural motifs.

---

## 37. Soft constraints over artificial gating

Gameplay progression should prefer soft constraints.

Examples:

- inaccessible because power is off;
- unsafe because route is exposed;
- inefficient until logistics are restored;
- expensive until production exists;
- difficult until transport is connected.

Prefer this over arbitrary level gating.

The world itself should explain progression.

---

## 38. What should not happen

Avoid drifting into:

### Endless toy tests
Small tests are for unknown primitives only.

### Static blueprint spam
The final agent must adapt to world state.

### Empty-air-only construction
Eventually it must work in existing structures.

### Factory-only scope
Factories are foundation, not endpoint.

### Full rebuild after every failure
Local repair is preferred.

### One hard-coded script per goal
Move toward declarative process/capability planning.

### Blind mod assumptions
Inspect APIs and verify live.

### Purely decorative megastructures
Infrastructure should have systemic meaning.

---

## 39. North-star example mission

Representative final-scale goal:

~~~text
Restore this abandoned industrial sector and integrate it into our settlement.
~~~

Possible decomposition:

1. scan sector;
2. identify existing power backbone;
3. identify blocked routes;
4. identify useful rooms;
5. generate several restoration plans;
6. restore power;
7. reopen one safe traversal route;
8. establish temporary storage;
9. reconnect freight transport;
10. build or restore processing;
11. establish lighting and access control;
12. create settlement support areas;
13. secure dangerous branches;
14. connect sector to external network;
15. verify all critical systems;
16. preserve and document the restored sector as a reusable pattern.

This is the type of mission the whole project should eventually support.

---

## 40. Current north-star progression

The intended trajectory is:

~~~text
verified primitive
→ reusable skill
→ composed subsystem
→ branching planner
→ workshop
→ district
→ restored sector
→ living megastructure
~~~

The important measure of progress is not how many blocks the agent can place.

It is how much intent one user command can express while the agent reliably handles the
decisions underneath.

The project succeeds when a command like:

~~~text
restore this sector
~~~

can eventually replace hundreds or thousands of manual low-level instructions.

---

## 41. Short version

YAN Agent Lab is building an autonomous Minecraft engineer that can:

- understand high-level goals;
- inspect real environments;
- generate several candidate solutions;
- search among them;
- build incrementally;
- verify function in the real game;
- repair locally;
- reuse existing infrastructure;
- learn verified skills;
- scale from machines to districts and megastructures;
- physically transform abandoned sectors into functioning civilization.

The industrial Mekanism experiments are the first laboratory for this larger goal.

They are not the destination.
