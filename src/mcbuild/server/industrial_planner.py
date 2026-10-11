"""Branching industrial design search for YAN Iron Works v4.0.

This is deliberately small and interpretable: generate several architecture candidates,
score them, keep a beam, and execute the best verified design. Future versions can
expand this into learned/MCTS search without changing the execution contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


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

    candidates = []
    # Expand process choice × capacity. Scores derive from design quantities.
    for direct in (False, True):
        for lanes in range(1, 4):
            cells = lanes if direct else 2 * lanes
            raw = lanes * (24 if direct else 18)
            final = lanes * 24
            blocks = cells * 25 - (0 if direct else lanes)
            candidate_id = f"{'direct' if direct else 'enriched'}_{lanes}_lanes"
            candidates.append(
                IronWorksCandidate(
                    id=candidate_id,
                    enrichment_cells=0 if direct else lanes,
                    smelting_cells=lanes,
                    direct_smelting=direct,
                    raw_input=raw,
                    final_output=final,
                    estimated_blocks=blocks,
                    energy_islands=cells,
                    verified_primitives_only=True,
                    throughput_score=min(100, lanes * 33),
                    efficiency_score=100 * final / raw / (4 / 3),
                    robustness_score=50 + 15 * (lanes - 1),
                    compactness_score=100 * 49 / max(49, blocks),
                    reuse_score=100,
                    risk_penalty=0,
                )
            )
    return candidates


def rank_iron_works_candidates(beam_width: int = 6, goal: str = "") -> list[IronWorksCandidate]:
    candidates = generate_iron_works_candidates()
    normalized = goal.lower()
    for candidate in candidates:
        if candidate.id in normalized:
            return [candidate]
    if "компакт" in normalized or "compact" in normalized:
        candidates = [c for c in candidates if c.smelting_cells == 1]
    if "прямая" in normalized or "direct" in normalized:
        candidates = [c for c in candidates if c.direct_smelting]
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    verified = [c for c in ranked if c.verified_primitives_only]
    return verified[: max(1, beam_width)]
