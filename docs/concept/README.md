# YAN concept: document map

The concept is split by how it is used, not by topic.

| Document | Purpose | Changes how often |
| --- | --- | --- |
| [`../YAN_PROJECT_CONCEPT.md`](../YAN_PROJECT_CONCEPT.md) | Vision: world fantasy, aesthetics, long-term scope, north-star mission | Rarely |
| [`WORLD.md`](WORLD.md) | Canon of the world: The City, tone, who lives there, generation scales, world ideas | When the owner decides |
| [`GAMEPLAY.md`](GAMEPLAY.md) | Canon of the game loop: 7-day cycle, restoration payoffs, Cargo Relay, NPC, sector state | When the owner decides |
| [`INVARIANTS.md`](INVARIANTS.md) | Hard rules every change and every live run must obey | Rarely, by explicit decision |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Layers, intermediate representation, evaluation tiers, skill format, role of the LLM | When a layer is designed or redesigned |
| [`ROADMAP.md`](ROADMAP.md) | Verified current state, the single active milestone, its done criteria | Every milestone |
| [`OPEN_DECISIONS.md`](OPEN_DECISIONS.md) | Open questions and the dated log of closed decisions | Until each one is closed |

History and detail (October 2026 recovery, PR #24): `../MINECRAFT_PROJECT_INDEX.md`,
`../WORLD_DESIGN.md`, `../GAMEPLAY_SYSTEMS.md`, `../CIVILIZATION_PROGRESSION.md`,
`../MODPACK_SPEC.md`. They keep the record of earlier decisions; where they conflict
with `WORLD.md` / `GAMEPLAY.md`, the canon files win (their decisions are newer).

## Precedence on conflict

~~~text
INVARIANTS  >  WORLD / GAMEPLAY  >  ARCHITECTURE  >  ROADMAP  >  vision and history docs
~~~

The vision says *where* the project goes. The invariants say *what may never be
violated on the way*. If an implementation idea conflicts with an invariant, the idea
loses unless the invariant is changed deliberately and the change is recorded in
`OPEN_DECISIONS.md` → closed decisions.

## Reading order for an agent starting work

1. `INVARIANTS.md` (always).
2. `ROADMAP.md` (what is actually done, what is being worked on now).
3. `ARCHITECTURE.md` (the layer you are about to touch).
4. `WORLD.md` / `GAMEPLAY.md` when the task touches world generation, tone or gameplay.
5. Vision and history docs for background.
