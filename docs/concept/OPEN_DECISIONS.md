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

## D3. Priority between the two lines (industrial vs environment)

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

## D10. What the teleport is

The player's day is split between far expeditions and settling "near the teleport".
Is it a fixed home point, a network between restored nodes, the spawn? What limits it?
What happens to a player far from it on day 7? (GAMEPLAY §9)

## D12. Details of what is lost

Decided: world, infrastructure and settlement persist; unextracted inventory is lost.
Open: what counts as "extracted", death mid-cycle, whether the settlement near the
teleport is safe from day-7 events. (GAMEPLAY §1a)

## D13. Cycle length, sleep, offline time

7 Minecraft days ≈ 2h20m real time; sleep shortens it; does the clock run while the
player is away? (GAMEPLAY §1b)

## D11. Biome resources in a world without an overworld

Wood, food, ores when the whole world is megastructure; which BMC5 parts remain.
(WORLD §6)

---

## Closed decisions

- **2026-11-06 — Product model.** The agent is part of the world generator: it
  designs working factories, which are then broken for the player to restore or
  scavenge. A runtime helper (e.g. maids) is a secondary, later mode. (vision §0)
- **2026-11-06 — The City is the whole world**, not a dimension or a region. (WORLD §1)
- **2026-11-06 — Tone.** BLAME! is the base (emptiness, scale, indifferent machines);
  giga-khrushchevka = aesthetics of past life (archaeology, not population); liminal
  spaces as a light accent. The generator creates no populated districts. (WORLD §2–3)
- **2026-11-06 — NPC engine.** Touhou Little Maid, reskinned and trimmed, is the engine
  for companions, hostile NPCs and rare loners. Closes former D9. (WORLD §3)
- **2026-11-06 — MCA Reborn** only for the player's own settlement. (WORLD §3)
- **2026-11-06 — Restoration goal.** The player decides; the seven-day cycle limits
  time, so the daily choice is far expedition vs settling near the teleport. Supersedes
  the October "build a civilization in every sector" reading. (GAMEPLAY §1)
- **2026-11-06 — Roguelite hub.** A hub location where the player picks perks and
  equipment before each seven-day cycle; a cycle is a run. (GAMEPLAY §1a)
- **2026-11-06 — Persistence (option a).** World, restored infrastructure, supply
  networks and settlement persist; inventory not extracted to the hub is lost.
  (GAMEPLAY §1a)
- **2026-11-06 — Settlement location.** The player's MCA settlement is in the world,
  near the teleport. (GAMEPLAY §1a)
- **2026-11-06 — Anomaly zones.** World rebuilding happens only in dedicated anomaly
  zones of hundreds of chunks; the rest of the world is stable, so supply routes are
  never cut. Invariant I18. (GAMEPLAY §1b)

