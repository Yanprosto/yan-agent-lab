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

## D3. Priority between the two lines

Both lines are one product (vision §0): industrial = functional content, environment =
how it looks when aged and broken. Open: what order and share of effort until M4.

## D4. Simulation depth (T1)

How faithful must the event simulator be: connectivity + recipe counts only, or rates,
buffer sizes and tick timing? Deeper simulation saves live runs but costs effort and
needs more recon facts.

## D5. Permission policy in helper mode

In generation the engine owns its whole lab world. In the runtime helper mode it acts
on the player's world: what may a helper change (region grant, block classes, explicit
confirmation)? Only needed before helper mode.

## D6. Target environment

Singleplayer test instance only, or must the design hold for a multiplayer server
(other players' blocks, concurrent sessions, tick budgets shared with others)?

## D7. Language of durable docs

The vision and invariants are in English, `REUSE_CATALOG.md` is in Russian. Pick one
for docs agents treat as source of truth, or keep both with one marked canonical.

## D8. How generated content enters the world

Options: (a) pre-generated map / sector saves; (b) library of verified modules that a
worldgen mod assembles at chunk generation (jigsaw-like); (c) hybrid: pregenerated
large sectors + module-based fill. The LLM agent cannot run during chunk generation.

## D9. Helper mode carrier

Which NPC system carries the runtime helper (maid mod, custom NPC, other), and when.

---

## Closed decisions

- **2026-11-06 — Product model.** The agent is part of the world generator: it
  designs working factories, which are then broken for the player to restore or
  scavenge. A runtime helper (e.g. maids) is a secondary, later mode. (vision §0)

