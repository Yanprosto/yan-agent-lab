# Mechanism catalog

What blocks can do, as data. Read through `mcbuild.catalog.load_catalog()`.
Planning code asks the catalog instead of hard-coding block ids, sides and ratios.

| Folder | Content | How it is made |
| --- | --- | --- |
| `blocks/` | roles, configurable sides, timing, energy, placement per block | hand-written; every fact carries an evidence level and a source or runs |
| `recipes/` | recipes of selected types from mod jars | `tools/recon/extract_mod_recipes.py <jar> --types ... --out ...` |
| `tags/` | flattened item tags (nested `#tags` resolved) | `tools/recon/extract_item_tags.py <jars...> --out ...` |

## Evidence levels

- `runtime_observed`: seen in a live run; `runs` names them. Only processors whose
  `side_config` is `runtime_observed` are plannable (`Catalog.plannable`).
- `source_default`: read from the jar (javap or shipped data). A world config or
  datapack can override it.
- `derived`: computed from other facts; `derivation` says how.
- `vanilla_fact`: documented vanilla behaviour, not yet observed in a YAN run.
- `unverified`: expected, not yet read or observed. Check in the headless lab first.

## Adding a block

1. Read the facts from the jar (timing, energy) and record them as `source_default`.
2. Add the block with `side_config` `unverified`.
3. Verify it in the headless lab (`tools/headless_lab/`), then switch `side_config`
   to `runtime_observed` with the run.

Recipes with `conditional: true` (usually `requires_mods`) are ignored unless asked for.
