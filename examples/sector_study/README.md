# Freight-node spatial study

Three authored block-model alternatives for choosing an environment direction before Minecraft placement. Each occupies a 96 × 96 plot, reaches 60–61 blocks high and connects the entrance to three principal galleries at elevations 14, 30 and 46. These are spatial prototypes, not a completed general-purpose generator or functioning mod machinery.

![Comparison](output/comparison.jpg)

| Alternative | Spatial idea | Tradeoff |
| --- | --- | --- |
| Well | Square central void, galleries, overhead gantry and suspended platform | Strong enclosure; repeated decks obscure the interior in exterior views |
| Canyon | Opposing structural masses, staggered bridges, service bays | Clearest long freight axis; less enclosed |
| Shaft | Circular galleries, central core and side machine hall | Strongest distinct silhouette; hall interrupts the ring |

## Reproduce

From the repository root, in its installed Python environment:

```sh
PYTHONPATH=src python examples/sector_study/build.py
python examples/sector_study/present.py
PYTHONPATH=src:examples/sector_study python -m unittest discover -s examples/sector_study -p 'test_*.py'
```

`--no-render` runs geometry, validation, route checks and schematic export only. `--only well|canyon|shaft` selects one design. The presentation script uses DejaVu Sans at the standard Linux font location; change `FONT` on another platform.

Every variant includes executable DSL (`blueprint.py`), a ProjectPlan, merge/connectivity report, Sponge v3 schematic, overview and Z ≥ 46 cutaway. The cutaway removes the front half only for rendering; the schematic contains the whole model. Schematics contain air in their bounding volume and must be placed only in a selected disposable/cleared location after review.

## Reuse and provenance

- Actual existing mcbuild DSL sandbox compiles every design; vanilla block registry checks the palette.
- Actual ProjectPlan validator and transactional merge validate four **authored elevation partitions** and preserve the compiled geometry exactly. These partitions are not semantic LLM worker outputs and do not prove autonomous orchestration.
- Existing textured software camera renderer produces both views directly from the resulting voxels. No generated concept imagery.
- Existing schematic exporter produces the build artifact.
- Custom code is limited to composition, a small geometric reachability check and contact-sheet presentation. No new renderer, exporter, Minecraft bridge or general planner.
- No model API key was available. Composition was authored by the assistant in this session; no external planner/worker LLM call, game placement or live test occurred.

`docs/REUSE_CATALOG.md` remains the source for deferred integrations. Minecraft-agentic repair/critic is a later candidate when a live placement/repair loop is required; Voyager/Mindcraft memory and roles are not needed for this static study. FAWE is not assumed compatible with the NeoForge bridge. No external code was copied.

## Validation and limits

The route check starts at foot coordinate (6, 3, 4), requires solid support and two air blocks, traverses cardinal neighbors and permits one-block ascent/descent with overhead clearance. All used geometry is full cubes. The access stair therefore requires jumping; this is **not a stair-state model, Minecraft pathfinder, accessibility claim or agent traversal test**. Targets are on the main front galleries, beyond the stair exits. The test suite also fills destination cells with stone and requires the checker to reject them.

Checks cover all three targets, palette warnings, plot/height bounds, plan validity and exact merge preservation. They do not establish accessibility of every ledge/service room, structural physics, safe railings, terrain adaptation or working freight machinery. Tracks, crane and machinery are architectural representations. There is no production simulation in this study.

Reported `compile_validate_seconds` covers DSL compilation, plan/merge validation and route checking, not rendering/export/model inference. It is a local measurement, not a performance promise. The two rendered views take materially longer than geometry generation.

## Next decision

Select the spatial direction, then evolve that model: proper stair blocks and railings, more convincing damage/weathering, functional room assignments and fit to an actual site. Preserve the other alternatives as references. Inspect the chosen schematic in a disposable Minecraft location and verify traversal before merging any live-placement behavior. No change to runtime behavior is included here.
