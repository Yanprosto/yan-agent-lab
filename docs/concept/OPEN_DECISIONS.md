# Open conceptual decisions

Questions the vision text leaves open. Each must be decided by the owner or explicitly
deferred with a return condition. Closed decisions move to the bottom with a date.

## D1. Role of the LLM

ARCHITECTURE §7 proposes "LLM proposes, deterministic code disposes".
Alternative: the LLM is the planner itself and search is a tool it calls.
*Affects:* how much search/scoring is code vs prompts; cost per run; debuggability.

## D2. Mod scope for the next two milestones

Stay Mekanism-only until M3 is done, or add a second tech mod (e.g. Create) earlier to
force the capability layer to be truly mod-agnostic?

## D3. Two lines of work

Industrial (planning/verification) and environment/visual (palettes, sectors,
catalogs) are developing in parallel. Is the environment line in scope for M1–M3,
or paused until the planner exists?

## D4. Simulation depth (T1)

How faithful must the event simulator be: connectivity + recipe counts only, or rates,
buffer sizes and tick timing? Deeper simulation saves live runs but costs effort and
needs more recon facts.

## D5. Permission policy for non-owned blocks

I5 currently forbids touching anything not placed by the agent. World restoration
(vision §2, §21.6) requires modifying existing structures. When and how is that
allowed: per-mission region grant, per-block-class rules, explicit user confirmation?

## D6. Target environment

Singleplayer test instance only, or must the design hold for a multiplayer server
(other players' blocks, concurrent sessions, tick budgets shared with others)?

## D7. Language of durable docs

The vision and invariants are in English, `REUSE_CATALOG.md` is in Russian. Pick one
for docs agents treat as source of truth, or keep both with one marked canonical.

---

## Closed decisions

*(none yet)*
