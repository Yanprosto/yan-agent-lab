# YAN concept: document map

The concept is split by how it is used, not by topic.

| Document | Purpose | Changes how often |
| --- | --- | --- |
| [`../YAN_PROJECT_CONCEPT.md`](../YAN_PROJECT_CONCEPT.md) | Vision: world fantasy, aesthetics, long-term scope, north-star mission | Rarely |
| [`INVARIANTS.md`](INVARIANTS.md) | Hard rules every change and every live run must obey | Rarely, by explicit decision |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Layers, intermediate representation, evaluation tiers, skill format, role of the LLM | When a layer is designed or redesigned |
| [`ROADMAP.md`](ROADMAP.md) | Verified current state, the single active milestone, its done criteria | Every milestone |
| [`OPEN_DECISIONS.md`](OPEN_DECISIONS.md) | Conceptual questions not yet decided by the owner | Until each one is closed |

## Precedence on conflict

~~~text
INVARIANTS  >  ARCHITECTURE  >  ROADMAP  >  vision text
~~~

The vision says *where* the project goes. The invariants say *what may never be
violated on the way*. If an implementation idea conflicts with an invariant, the idea
loses unless the invariant is changed deliberately and the change is recorded in
`OPEN_DECISIONS.md` → closed decisions.

## Reading order for an agent starting work

1. `INVARIANTS.md` (always).
2. `ROADMAP.md` (what is actually done, what is being worked on now).
3. `ARCHITECTURE.md` (the layer you are about to touch).
4. Vision text only when the task involves scope, gameplay or aesthetics.
