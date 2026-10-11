# Fact-grounded palette compiler v1

This compiler consumes:

- semantic_block_catalog.json
- visual_block_catalog.json

It deliberately does not reuse the old token-based safety classifier.

Safety is derived from runtime facts first:
- air / replaceable / fluid / known impossible blocks -> forbidden;
- runtime ore tags -> resource, never architecture;
- BlockEntity providers -> functional, planner-only by default;
- runtime storage-block tags -> prestige/budgeted until recipe-cost analysis exists;
- blocks without item counterparts -> restricted;
- remaining ordinary registered blocks -> architecture candidates;
- bulk use requires occlusion + non-empty collision and no light-emission detail role.

Visual scoring uses the actual texture features already extracted for 99.8% of the lab registry.
Mekanism-family visuals form the default industrial anchor profile, while vanilla and Mekanism architectural candidates compete in the same slots.

Run:

    cd D:\YAN_AGENT_LAB
    git fetch origin
    git switch yan-palette-compiler-v1
    git pull
    powershell -ExecutionPolicy Bypass -File .\tools\publish_fact_grounded_palette.ps1

Review the generated markdown before wiring it into the sector builder.
