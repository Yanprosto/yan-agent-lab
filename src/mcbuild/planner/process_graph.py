"""Goal -> candidate process chains, enumerated from catalog recipes.

A chain is a sequence of stages from one available source item to the target item.
Each stage is a catalog recipe on a plannable machine (its side config was observed
live). Chains never revisit an item, so loops such as ingot -> dust -> ingot are
excluded. Candidates are scored and ranked; the planner builds the best and keeps the
rest as fallbacks (beam search over the ProcessGraph level).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from mcbuild.catalog import Catalog, Recipe


@dataclass(frozen=True)
class Stage:
    recipe: Recipe
    machine: str
    input_item: str
    output_item: str
    input_count: int
    output_count: int

    @property
    def ratio(self) -> Fraction:
        return Fraction(self.output_count, self.input_count)


@dataclass(frozen=True)
class ProcessChain:
    source_item: str
    target_item: str
    stages: tuple[Stage, ...]

    @property
    def id(self) -> str:
        return " -> ".join([self.source_item, *(f"{s.machine.split(':')[1]}:{s.output_item}" for s in self.stages)])

    @property
    def yield_per_source(self) -> Fraction:
        result = Fraction(1)
        for stage in self.stages:
            result *= stage.ratio
        return result

    def exact_seed_unit(self) -> int:
        """Smallest source amount for which every stage consumes its whole input."""
        source = 1
        while True:
            amount = Fraction(source)
            ok = True
            for stage in self.stages:
                if amount.denominator != 1 or int(amount) % stage.input_count:
                    ok = False
                    break
                amount *= stage.ratio
            if ok and amount.denominator == 1:
                return source
            source += 1

    def plan_counts(self, target_count: int) -> tuple[int, list[int]]:
        """Source amount (multiple of the exact unit) reaching at least target_count, and
        the item count entering each stage plus the final output."""
        unit = self.exact_seed_unit()
        per_unit = self.yield_per_source * unit
        units = max(1, -(-target_count // int(per_unit)))
        source = unit * units
        counts = [source]
        amount = Fraction(source)
        for stage in self.stages:
            amount *= stage.ratio
            counts.append(int(amount))
        return source, counts


@dataclass(frozen=True)
class ScoredChain:
    chain: ProcessChain
    score: float
    source_needed: int
    output: int
    machines: int
    energy_j: int
    ticks: int


def _concrete_item(catalog: Catalog, ingredient: dict) -> list[str]:
    if "item" in ingredient:
        return [ingredient["item"]]
    return sorted(catalog.tags.get(ingredient.get("tag", ""), ()))


def enumerate_chains(
    catalog: Catalog, target_item: str, sources: set[str], *, max_stages: int = 3
) -> list[ProcessChain]:
    """All acyclic chains from any item in ``sources`` to ``target_item``."""
    chains: list[ProcessChain] = []

    def walk(item: str, suffix: tuple[Stage, ...], seen: frozenset[str]) -> None:
        if len(suffix) >= max_stages:
            return
        for recipe in catalog.recipes_producing(item):
            if len(recipe.item_inputs) != 1 or len(recipe.inputs) != 1:
                continue  # single-input recipes only for now (no chemical side inputs)
            machines = [m for m in catalog.machines_for(recipe.type) if catalog.plannable(m)]
            if not machines:
                continue
            for input_item in _concrete_item(catalog, recipe.item_inputs[0]):
                if input_item in seen:
                    continue
                stage = Stage(
                    recipe=recipe,
                    machine=machines[0],
                    input_item=input_item,
                    output_item=item,
                    input_count=int(recipe.item_inputs[0].get("count", 1)),
                    output_count=int(recipe.main_output.get("count", 1)),
                )
                chain_stages = (stage, *suffix)
                if input_item in sources:
                    chains.append(ProcessChain(input_item, target_item, chain_stages))
                walk(input_item, chain_stages, seen | {input_item})

    walk(target_item, (), frozenset({target_item}))
    unique = {c.id: c for c in chains}
    return list(unique.values())


def score_chain(catalog: Catalog, chain: ProcessChain, target_count: int) -> ScoredChain:
    """Higher is better: output per source item first, then fewer machines and less energy."""
    source, counts = chain.plan_counts(target_count)
    energy = 0
    ticks = 0
    for stage, entering in zip(chain.stages, counts, strict=False):
        operations = entering // stage.input_count
        per_op_ticks = int(catalog.fact(stage.machine, "ticks_per_operation") or 200)
        per_tick_j = int(catalog.fact(stage.machine, "energy_per_tick_j") or 0)
        energy += operations * per_op_ticks * per_tick_j
        ticks += operations * per_op_ticks
    output = counts[-1]
    score = float(chain.yield_per_source) * 100 - len(chain.stages) * 5 - energy / 10000
    return ScoredChain(chain, round(score, 2), source, output, len(chain.stages), energy, ticks)


def rank_chains(
    catalog: Catalog, target_item: str, target_count: int, sources: set[str], *, beam: int = 5
) -> list[ScoredChain]:
    scored = [score_chain(catalog, c, target_count) for c in enumerate_chains(catalog, target_item, sources)]
    scored.sort(key=lambda s: (-s.score, s.machines, s.chain.id))
    return scored[:beam]
