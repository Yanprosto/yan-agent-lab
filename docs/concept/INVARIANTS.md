# YAN invariants

Hard rules. Each has a check, so a reviewer (human or agent) can tell whether it holds.
Source sections of the vision document are given in brackets.

## World and truth

**I1. The world is the source of truth.** [§5, §12]
A subsystem is "working" only after an in-world observation satisfies its contract.
Planner predictions, simulation results and skill memory are hypotheses.
*Check:* every "PASS"/"verified" claim references a run id with the observation.

**I2. Success is semantic, declared before execution.** [§32]
Every mission and every build stage has a verification contract written *before* it
runs (e.g. `source == 0, left > 0, right > 0, total == 6`). Placed blocks are never
the success criterion on their own.
*Check:* the contract is present in the run log before the first ACTION.

**I3. Countable resources are accounted for.** [§8]
Items, energy, fluids, chemicals: `source + buffers + transit + output = expected`.
Disappearance from the visible source is not success.
*Check:* the verdict lists every term of the balance, including transit and buffers.

**I4. Every fact carries its evidence level.** [§15, AGENTS.md]
`source/JAR default` · `effective world config` · `derived estimate` · `runtime observed`.
Only `runtime observed` facts may be called verified.
*Check:* catalog entries and skills store the level and, for observed facts, the run id.

## Safety and the world

**I5. Ownership is explicit.** [§26]
The agent may freely modify and roll back only blocks it placed in the current
mission. Anything else is *preserve* unless a permission policy grants more.
*Check:* the bridge refuses removal/overwrite of non-owned blocks without a grant.

**I6. Reuse before replacement.** [§4]
Inspect and evaluate existing infrastructure before planning new; flattening needs a
stated reason in the plan. The same rule applies to code: check existing modules and
`REUSE_CATALOG.md` before writing a new subsystem.
*Check:* the plan/PR names what was considered for reuse and why it was not used.

**I7. Bounded world mutation.** [§27]
Construction is queued with a per-tick budget. No large synchronous edits.
*Check:* the bridge enforces the budget; it is not left to the caller.

**I8. No manual test fixtures.** [§17]
The agent provisions its own test environment when safe. Asking the user to build
a fixture is an exception that must be justified in the run log.

## Execution and failure

**I9. Build in verifiable stages.** [§6]
Large builds are a sequence of stages, each with its own contract. A stage is not
started until the previous one passes.

**I10. Failure scope = repair scope.** [§7]
On failure, only the failing subsystem is isolated, rolled back and replaced. Healthy
subsystems stay untouched.
*Check:* rollback actions in the log are limited to the failing stage's owned blocks.

**I11. Diagnose before retry.** [§33, §34]
Every retry or alternative must cite a diagnosis (which assumption failed and what
observation showed it). Random reconfiguration is not allowed.
*Check:* each REPAIR / next-candidate event carries a `diagnosis` field.

**I12. Every live mission is logged.** [§31]
Command, goal, contract, actions, observations, decisions, failures, repairs, verdict,
saved skills. A run must be analysable without screenshots.

## Planning

**I13. Plan in capabilities, compile to blocks.** [§14]
Levels above layout reason about capabilities (`ITEM_TRANSPORT`, `PROCESSOR`, ...),
not mod block ids. Block ids appear only when compiling a layout to actions.

**I14. One engine, missions as data.** [§38 "one hard-coded script per goal"]
A new goal or experiment is described as data (goal, region, permissions, contract,
candidate generator) and run by the shared engine. Adding a new Python/Java function
per experiment is a temporary exception and must be listed as debt in `ROADMAP.md`.

## Project hygiene

**I15. `main` is last known green; claims follow `main`.** [§30]
A capability counts as "proven" in `ROADMAP.md` only when its code is on `main` and a
run log on that code passed. Work in branches is "demonstrated in branch X", not proven.
