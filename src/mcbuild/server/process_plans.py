"""Goal -> process-graph registry for YAN industrial missions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessStage:
    id: str
    machine_block: str
    input_item: str
    output_item: str
    input_count: int
    output_count: int
    machines: int = 2


@dataclass(frozen=True)
class ProcessPlan:
    id: str
    title: str
    aliases: tuple[str, ...]
    source_item: str
    source_count: int
    final_item: str
    final_count: int
    stages: tuple[ProcessStage, ...]


IRON_PROCESSING = ProcessPlan(
    id="iron_processing",
    title="iron processing district",
    aliases=(
        "iron",
        "iron processing",
        "process iron",
        "переработка железа",
        "железо",
        "железный цех",
        "железный участок",
    ),
    source_item="minecraft:raw_iron",
    source_count=18,
    final_item="minecraft:iron_ingot",
    final_count=24,
    stages=(
        ProcessStage(
            id="enriching",
            machine_block="mekanism:enrichment_chamber",
            input_item="minecraft:raw_iron",
            output_item="mekanism:dust_iron",
            input_count=18,
            output_count=24,
            machines=2,
        ),
        ProcessStage(
            id="smelting",
            machine_block="mekanism:energized_smelter",
            input_item="mekanism:dust_iron",
            output_item="minecraft:iron_ingot",
            input_count=24,
            output_count=24,
            machines=2,
        ),
    ),
)


PLANS = (IRON_PROCESSING,)


def resolve_process_plan(goal: str) -> ProcessPlan:
    normalized = " ".join(goal.lower().strip().split())
    if not normalized:
        return IRON_PROCESSING
    for plan in PLANS:
        if normalized == plan.id or any(alias in normalized for alias in plan.aliases):
            return plan
    supported = ", ".join(p.id for p in PLANS)
    raise ValueError(f"unsupported industrial goal {goal!r}; supported plans: {supported}")
