# YAN Agent Lab: durable project context

Before changing factory planning, simulation, mod reconnaissance or generator scope:

1. Read `docs/YAN_PROJECT_CONCEPT.md` for the intended goal and design principles.
2. Read `docs/recon/MEKANISM_AUDIT.md` and `docs/recon/mekanism/oracle_defaults.json`.
3. Consult archived source evidence for the specific mechanism before requesting another scan.

Mekanism reconnaissance already exists. Reuse it; investigate concrete missing facts
rather than repeating the broad audit. Separate JAR defaults, effective world settings,
derived estimates and runtime observations. The recovered audit used javap; it does not
prove universal-modder was executed or all mod semantics automatically exported.

The generator must design functional systems for goals and available 3D space.
Duplicating fixed flat cell layouts is not the intended end result. Known production
should be evaluated with fast event simulation; repeated full real-time batch waits are
not required for every design. Preserve working infrastructure and account for resources.

Runtime work: feature branch, draft PR, live verification before merging behavior changes.
Documentation-only evidence preservation does not require a Minecraft run.

## Reuse before new subsystems

Read `docs/REUSE_CATALOG.md` before introducing a new planning, rendering, building,
repair, memory or reconnaissance subsystem. Check existing mcbuild components first.
Record the considered existing tool/module and the reason for reuse, adaptation or
custom implementation in the PR. Keep deferred candidates with a reason and return
condition; do not silently discard them between conversations. Catalog entries are
candidates unless explicitly marked integrated. Verify target-version compatibility
and the license of any code actually copied; preserve upstream notices and commit IDs.
