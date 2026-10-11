# YAN Industrial Plan Compiler v4.1

The selected architecture now determines the actual machines, positions, batch contracts
and physical handoff buffers. v4.0 ranked candidates but always executed the same
four-cell layout; that mismatch is removed.

## Run

Java did not change; use the installed v4 JAR. Update Python:

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-plan-compiler-v4.1
git pull --ff-only
```

With `mcbuild-server-dev` running:

```text
/yanindustry железный завод
/yanindustry железный завод компактный
/yanindustry железный завод прямая плавка
/yanindustry железный завод enriched_2_lanes
```

The planner expands process choice (enrichment + smelting / direct smelting) and
capacity (1–3 lanes) into six alternatives. Heuristic scores derive from quantities;
these are estimates, not measured throughput. An explicit candidate ID selects only
that candidate. Compact and direct goals constrain the candidate set.

The compiler produces typed cells, machine specifications, batch contracts, positions
and upstream edges; validates material balance, stage handoff and voxel collisions;
then the executor consumes those cells. Candidates and full build plan appear in run
chat logs. Before placement, each candidate is checked at four offsets. Occupied or
incompletely observed sites are rejected without writes. Lower-ranked architectures
can be selected if higher-ranked ones fit nowhere.

Execution builds and checks power, seeds root stages, verifies exact upstream output,
opens downstream intake, verifies final production and zero remaining source/transit.
Stage verification also checks machine input/output buffers. Only live success saves
`compiled_iron_works_v1` knowledge.

## Validation and limits

11 new offline tests cover all six architectures through the real session entry point,
recipe balance, distinct geometry, handoff, goal selection, site fallback and no rollback
before placement. These tests mock the Minecraft bridge: live verification is pending.

Still bounded to verified two-machine cell geometry and iron recipes. Power remains
per-cell; parallel lanes retain separate storage. No general recipe discovery, common
power spine, arbitrary port routing, continuous-load commissioning, runtime replanning
or local repair is added here. Execution failure rolls back session-owned edits; it does
not automatically rebuild another candidate after mutation. This milestone establishes
a genuine plan-to-execution contract for those future changes.

## Production scheduling correction

The live direct-smelting run on 2026-10-11 took 399.6 seconds. About 399.2 seconds
were explicit tick waits: the executor seeded and completed each independent lane
serially. Construction/power checks finished in roughly nine seconds.

Independent cells now start in dependency waves before any output wait. Completed
upstream contracts still gate downstream intake. Each production check reads current
state before waiting, so already-complete lanes incur no extra 200-tick delay. The
WebSocket observation stream remains serial. Twelve offline tests pass, including
ordering assertions for three roots and all downstream gates.

Expected direct-three-lane commissioning is about one lane's processing time plus
setup (~2 minutes 20 seconds for the same batch at 20 TPS), rather than three lane
times. This estimate needs a new live run; machines are not artificially accelerated.
