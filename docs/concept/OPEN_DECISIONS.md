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

**Decided 2026-11-07: singleplayer** (the owner plays alone). Multiplayer is out of scope until
the owner says otherwise; the headless lab stays a dedicated-server stand-in for the integrated server.

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

## D12. Teleport zone details

Size of the immutable teleport zone; whether the warehouse is the bank between cycles
or items move further into the hub; how warehouse contents relate to hub loadout.
(GAMEPLAY §1a)

## D13. Cycle length, sleep, offline time

7 Minecraft days ≈ 2h20m real time; sleep shortens it; does the clock run while the
player is away? (GAMEPLAY §1b)

## D11. Biome resources in a world without an overworld

Wood, food, ores when the whole world is megastructure; which BMC5 parts remain.
(WORLD §6)

## D14. Where the ground is (height is decided)

Height decided 2026-11-07: **4096 blocks, Y −128 … 3967** (width is practically unlimited, so
vertical range is a direction, not a record). Open: at which Y the player starts and what "ground"
means: with the floor fixed at −128, "deeper" has little room, so the start level sits in the
middle and depth is the tiers below it. (WORLD §3c)

## D17. How narrative locality is applied

Reading (a): everything important right now lies within ~100 blocks of the teleport and the circle
grows as sectors are restored. Reading (b): the world is a scattering of ~100-block scenes with
void or road between them. Either way, how does it fit "far runs into the wastes" (GAMEPLAY §1)?
(WORLD §3d)

## D15. Client-side check of tall worlds

Server side is verified (docs/recon/TALL_WORLD_SPIKE.md). Needed on the owner's machine: create a
singleplayer world with the height, run with Distant Horizons and the real pack, look at rendering
and lighting at 2000+ blocks; then vertical traversal mods (elevators, grapples).

## D16. Dynamic Height license

Jar says CC-BY-NC-ND-4.0, Modrinth page says GPL-3.0-only. Irrelevant for a private pack; resolve
before the pack is published.

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
- **2026-11-07 — Extraction.** "Extracted" means stored in the warehouse at the
  teleport, reached by carrying or via the Cargo Relay network. Everything not sent
  there is lost, including on death mid-cycle. (GAMEPLAY §1a)
- **2026-11-07 — Immutable teleport zone.** Settlement and warehouse sit in an
  immutable zone around the teleport, untouched by events and rebuilds. Invariant I19.
- **2026-11-07 — Moddability first.** Minecraft was chosen because it can be built into the best
  personal pack; vanilla limits are bypassed with mods and datapacks, not designed around. Each mod
  is checked for version, license and compatibility before adoption (owner's statement).
- **2026-11-07 — Singleplayer, no Lithium** in the current pack (owner). Closes D6.
- **2026-11-07 — World height 4096** (Y −128 … 3967); 32k not needed because width is unlimited.
- **2026-11-07 — Narrative locality** (reference: Peripeteia): despite the vast scale, the story
  unfolds within about a hundred blocks. The scale is a backdrop to be seen, not a distance to be
  crossed. (WORLD §3d; reading of the rule is D17)
- **2026-11-07 — Two generation modes, three scales.** Mode A (world first: fit a
  factory into a given volume; later human workshops) and mode B (factory first:
  process and trunk lines, architecture generated around them; old machine plants,
  tens of chunks). Scales: cell, shop module with ports, district. In mode B the
  environment line wraps the agent's process skeleton in architecture.
  (ARCHITECTURE §11, WORLD §3b, ROADMAP M3)

