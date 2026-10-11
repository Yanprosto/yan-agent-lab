"""Generate topology candidates by mutating verified YAN skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcbuild.server.skill_store import load_skill


@dataclass(frozen=True)
class TopologyCandidate:
    candidate_id: str
    family: str
    source: str
    arm_blocks: int
    description: str

    @property
    def estimated_blocks(self) -> int:
        if self.family == "shared_t":
            return 7
        # source + 2 pull transporters + 2 sinks + two symmetric arm runs
        return 5 + 2 * self.arm_blocks

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "source": self.source,
            "arm_blocks": self.arm_blocks,
            "estimated_blocks": self.estimated_blocks,
            "description": self.description,
        }


def generate_two_branch_candidates() -> tuple[list[TopologyCandidate], dict[str, Any] | None]:
    """Generate a compact search set from verified two-branch knowledge.

    The previous verified skill provides the topology family. We then generate smaller,
    exact, and larger mutations around it. A shared-network control remains in the set
    to ensure the evaluator still detects branch starvation rather than blindly trusting
    every candidate.
    """

    skill = load_skill("mekanism_two_branch_distribution_v1")
    skill_topology = ((skill or {}).get("implementation") or {}).get("topology")

    candidates: list[TopologyCandidate] = [
        TopologyCandidate(
            candidate_id="control-shared-t",
            family="shared_t",
            source="control",
            arm_blocks=1,
            description="Single PULL extractor feeding a shared T-network.",
        )
    ]

    if skill_topology == "dual_independent_pull":
        candidates.extend(
            [
                TopologyCandidate(
                    candidate_id="skill-compact",
                    family="dual_independent_pull",
                    source="mutation_from_verified_skill",
                    arm_blocks=0,
                    description="Compress verified dual-PULL skill by removing both intermediate arm transporters.",
                ),
                TopologyCandidate(
                    candidate_id="skill-exact",
                    family="dual_independent_pull",
                    source="verified_skill",
                    arm_blocks=1,
                    description="Reproduce the verified v0.6 dual independent PULL topology.",
                ),
                TopologyCandidate(
                    candidate_id="skill-expanded",
                    family="dual_independent_pull",
                    source="mutation_from_verified_skill",
                    arm_blocks=2,
                    description="Expand the verified skill by one transporter on each branch.",
                ),
            ]
        )
    else:
        # If durable memory is absent or incompatible, exploration still remains possible,
        # but candidates are explicitly marked as fallback rather than pretending memory loaded.
        candidates.extend(
            [
                TopologyCandidate(
                    candidate_id="fallback-compact",
                    family="dual_independent_pull",
                    source="fallback",
                    arm_blocks=0,
                    description="Fallback compact dual-PULL topology.",
                ),
                TopologyCandidate(
                    candidate_id="fallback-standard",
                    family="dual_independent_pull",
                    source="fallback",
                    arm_blocks=1,
                    description="Fallback standard dual-PULL topology.",
                ),
            ]
        )

    return candidates, skill
