# Semantic catalog v1

This stage joins:

runtime_registry_*.json
+ minecraft_lab_oracle.json
= semantic_block_catalog.json

The result is factual project memory, not yet a building palette.

Each block descriptor contains runtime registry facts, tags, default state, state-property domains, physical properties, item counterpart, BlockEntity information, mechanically derived facts, and retrieval hints into the static recon oracle.

No architecture / functional / prestige / forbidden policy is applied here.

Run:

    cd D:\YAN_AGENT_LAB
    git fetch origin
    git switch yan-semantic-catalog-v1
    git pull
    powershell -ExecutionPolicy Bypass -File .\tools\publish_semantic_catalog.ps1

The command finds the newest runtime registry dump automatically, builds the catalog, commits it, and pushes the branch.
