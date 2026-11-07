# Seed skills

Baseline verified skills committed to the repository, so a fresh checkout does not
start without memory. `skill_store.load_skill` reads `yan_knowledge/skills/` (this
machine's runs, git-ignored) first, then this folder.

Each seed must be a skill verified in a live run and carry an `evidence` block
(level, run id, environment, note). Do not hand-write seeds.

| Skill | Used by | Evidence |
| --- | --- | --- |
| `mekanism_two_branch_distribution_v3` | spatial search v0.9 (v2+), environment builder v1.x (v3+) | headless lab run `20261107T102435Z_splitter_1b27c520` |
