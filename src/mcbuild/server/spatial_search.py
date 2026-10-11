"""Spatial candidate generation for YAN v0.9.

Builds a small but genuinely geometric search space from the verified v2 two-branch skill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcbuild.server.skill_store import load_skill


@dataclass(frozen=True)
class SpatialCandidate:
    candidate_id: str
    family: str
    source: str
    axis: str
    left_arm: int
    right_arm: int
    sink_drop: int
    extractor_count: int
    description: str

    @property
    def estimated_blocks(self) -> int:
        if self.family == "shared_t":
            return 7
        return 5 + self.left_arm + self.right_arm

    @property
    def horizontal_span(self) -> int:
        return 3 + self.left_arm + self.right_arm

    @property
    def vertical_span(self) -> int:
        return 1 + self.sink_drop

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "source": self.source,
            "axis": self.axis,
            "left_arm": self.left_arm,
            "right_arm": self.right_arm,
            "sink_drop": self.sink_drop,
            "extractor_count": self.extractor_count,
            "estimated_blocks": self.estimated_blocks,
            "horizontal_span": self.horizontal_span,
            "vertical_span": self.vertical_span,
            "description": self.description,
        }


def generate_spatial_candidates() -> tuple[list[SpatialCandidate], dict[str, Any] | None]:
    """Generate rotations, asymmetry and vertical variants from the verified v2 skill."""

    skill = load_skill("mekanism_two_branch_distribution_v2")
    impl = (skill or {}).get("implementation") or {}
    family = impl.get("family")
    arm_blocks = int(impl.get("arm_blocks", 0) or 0)

    candidates: list[SpatialCandidate] = [
        SpatialCandidate(
            candidate_id="control-shared-x",
            family="shared_t",
            source="control",
            axis="x",
            left_arm=1,
            right_arm=1,
            sink_drop=0,
            extractor_count=1,
            description="Known one-extractor shared T control; expected to expose branch starvation.",
        )
    ]

    if family == "dual_independent_pull":
        candidates.extend(
            [
                SpatialCandidate(
                    candidate_id="v2-x-flat",
                    family="dual_independent_pull",
                    source="verified_v2",
                    axis="x",
                    left_arm=arm_blocks,
                    right_arm=arm_blocks,
                    sink_drop=0,
                    extractor_count=2,
                    description="Exact v2 geometry in the original X orientation.",
                ),
                SpatialCandidate(
                    candidate_id="rotate-z-flat",
                    family="dual_independent_pull",
                    source="rotation_from_v2",
                    axis="z",
                    left_arm=arm_blocks,
                    right_arm=arm_blocks,
                    sink_drop=0,
                    extractor_count=2,
                    description="Rotate the verified v2 topology by 90 degrees onto the Z axis.",
                ),
                SpatialCandidate(
                    candidate_id="x-asym-right",
                    family="dual_independent_pull",
                    source="length_mutation_from_v2",
                    axis="x",
                    left_arm=0,
                    right_arm=1,
                    sink_drop=0,
                    extractor_count=2,
                    description="Asymmetric X layout: compact left branch, one extra transporter on right.",
                ),
                SpatialCandidate(
                    candidate_id="z-asym-left",
                    family="dual_independent_pull",
                    source="length_mutation_from_v2",
                    axis="z",
                    left_arm=1,
                    right_arm=0,
                    sink_drop=0,
                    extractor_count=2,
                    description="Asymmetric Z layout: one extra transporter on left, compact right.",
                ),
                SpatialCandidate(
                    candidate_id="x-drop",
                    family="dual_independent_pull",
                    source="vertical_mutation_from_v2",
                    axis="x",
                    left_arm=0,
                    right_arm=0,
                    sink_drop=1,
                    extractor_count=2,
                    description="Compact X topology with both sinks one block below the pull transporters.",
                ),
                SpatialCandidate(
                    candidate_id="z-drop",
                    family="dual_independent_pull",
                    source="rotation_vertical_mutation_from_v2",
                    axis="z",
                    left_arm=0,
                    right_arm=0,
                    sink_drop=1,
                    extractor_count=2,
                    description="Rotate to Z and place both sinks one block below the pull transporters.",
                ),
                SpatialCandidate(
                    candidate_id="x-wide-drop",
                    family="dual_independent_pull",
                    source="compound_mutation_from_v2",
                    axis="x",
                    left_arm=1,
                    right_arm=1,
                    sink_drop=1,
                    extractor_count=2,
                    description="Wider X topology with one-arm branches and lowered sinks.",
                ),
            ]
        )
    else:
        candidates.extend(
            [
                SpatialCandidate(
                    candidate_id="fallback-x",
                    family="dual_independent_pull",
                    source="fallback",
                    axis="x",
                    left_arm=0,
                    right_arm=0,
                    sink_drop=0,
                    extractor_count=2,
                    description="Fallback compact dual-PULL X topology.",
                ),
                SpatialCandidate(
                    candidate_id="fallback-z",
                    family="dual_independent_pull",
                    source="fallback",
                    axis="z",
                    left_arm=0,
                    right_arm=0,
                    sink_drop=0,
                    extractor_count=2,
                    description="Fallback compact dual-PULL Z topology.",
                ),
            ]
        )

    return candidates, skill
