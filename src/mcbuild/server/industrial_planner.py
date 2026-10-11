"""Branching industrial design search for YAN Iron Works v4.0.

This is deliberately small and interpretable: generate several architecture candidates,
score them, keep a beam, and execute the best verified design. Future versions can
expand this into learned/MCTS search without changing the execution contract.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class IronWorksCandidate:
    id: str
    enrichment_cells: int
    smelting_cells: int
    direct_smelting: bool
    raw_input: int
    final_output: int
    estimated_blocks: int
    energy_islands: int
    verified_primitives_only: bool
    throughput_score: float
    efficiency_score: float
    robustness_score: float
    compactness_score: float
    reuse_score: float
    risk_penalty: float

    @property
    def machine_count(self) -> int:
        # Each verified production cell contains two processing machines.
        return 2 * (self.enrichment_cells + self.smelting_cells)

    @property
    def score(self) -> float:
        return round(
            self.throughput_score * 0.30
            + self.efficiency_score * 0.25
            + self.robustness_score * 0.20
            + self.compactness_score * 0.10
            + self.reuse_score * 0.15
            - self.risk_penalty,
            2,
        )

    def as_dict(self) -> dict:
        return {**asdict(self), "machine_count": self.machine_count, "score": self.score}


def generate_iron_works_candidates() -> list[IronWorksCandidate]:
    """Generate distinct high-level architectures, not block-by-block permutations."""

    return [
        IronWorksCandidate(
            id="compact_single_lane",
            enrichment_cells=1,
            smelting_cells=1,
            direct_smelting=False,
            raw_input=18,
            final_output=24,
            estimated_blocks=49,
            energy_islands=2,
            verified_primitives_only=True,
            throughput_score=45,
            efficiency_score=100,
            robustness_score=55,
            compactness_score=92,
            reuse_score=80,
            risk_penalty=0,
        ),
        IronWorksCandidate(
            id="balanced_parallel_works",
            enrichment_cells=2,
            smelting_cells=2,
            direct_smelting=False,
            raw_input=36,
            final_output=48,
            estimated_blocks=97,
            energy_islands=4,
            verified_primitives_only=True,
            throughput_score=92,
            efficiency_score=100,
            robustness_score=88,
            compactness_score=62,
            reuse_score=90,
            risk_penalty=0,
        ),
        IronWorksCandidate(
            id="direct_smelting_yard",
            enrichment_cells=0,
            smelting_cells=3,
            direct_smelting=True,
            raw_input=48,
            final_output=48,
            estimated_blocks=73,
            energy_islands=3,
            verified_primitives_only=True,
            throughput_score=95,
            efficiency_score=55,
            robustness_score=82,
            compactness_score=74,
            reuse_score=85,
            risk_penalty=2,
        ),
        IronWorksCandidate(
            id="dense_factory_future",
            enrichment_cells=1,
            smelting_cells=1,
            direct_smelting=False,
            raw_input=36,
            final_output=48,
            estimated_blocks=42,
            energy_islands=1,
            verified_primitives_only=False,
            throughput_score=100,
            efficiency_score=100,
            robustness_score=78,
            compactness_score=100,
            reuse_score=25,
            risk_penalty=30,
        ),
    ]


def rank_iron_works_candidates(beam_width: int = 3) -> list[IronWorksCandidate]:
    candidates = generate_iron_works_candidates()
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    verified = [c for c in ranked if c.verified_primitives_only]
    return verified[: max(1, beam_width)]
