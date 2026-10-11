# Mekanism lab profile — palette/builder branch

This branch is intentionally **not** the full ~200-mod production pack.

Current lab scope:
- vanilla Minecraft 1.21.1
- Mekanism 10.7.19.85
- Mekanism Generators 10.7.19.85
- Mekanism Tools 10.7.19.85
- Mekanism Additions 10.7.19.85

Keep all official Mekanism modules on the same release line as the core mod.

Purpose of this lab:
1. validate mod-aware palette extraction on a coherent technology family;
2. separate architecture / functional / prestige / forbidden blocks;
3. build a capability adapter around already-audited Mekanism behavior;
4. verify the procedural builder against a small controlled pack before moving to the full pack.

## Universal Modder is part of the workflow

Use `rehan-remade/universal-modder` as the reconnaissance/reverse-engineering helper for
unknown mod semantics instead of growing another ad-hoc recon subsystem.

Relevant upstream entry points:
- `skills/game-recon/`
- `skills/reverse-engineering/`
- `skills/mod-any-game/references/engines/minecraft.md`
- `um kb` field notes

The already-completed Mekanism audit remains the first source of truth. Do **not** rerun
a broad audit just because Universal Modder is now adopted. Use it for targeted gaps:
- runtime registry details;
- BlockEntity detection;
- capabilities and side configuration not already captured;
- recipe/tag resolution where static assets are insufficient;
- addon-specific behavior from Generators/Tools/Additions;
- future mods added to the lab.

Preferred loop:

```text
existing audit / oracle defaults
        ↓
known? ── yes → adapter/model
  │
  no
  ↓
Universal Modder targeted recon
        ↓
hypothesis
        ↓
small live verification only when needed
        ↓
field note / adapter fact
```

The local palette scanner and Universal Modder have different jobs:

```text
palette scanner
→ assets, textures, blockstates, tags, visual families

Universal Modder
→ code/behavior/API reconnaissance, capability semantics, runtime unknowns
```

They should feed one shared block/capability catalog rather than compete.
