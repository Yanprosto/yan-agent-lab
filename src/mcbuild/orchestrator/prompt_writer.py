"""Translate a validated ProjectPlan package into one complete worker prompt."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mcbuild.orchestrator.models import BoundaryKind, ProjectPlan, WorkPackage
from mcbuild.orchestrator.prompts import WORKER_SYSTEM_CONTEXT


@dataclass(frozen=True)
class WorkerPrompt:
    """The two prompt layers supplied to the existing mcbuild worker loop."""

    system_context: str
    user_prompt: str

    def to_dict(self) -> dict[str, str]:
        return {"system_context": self.system_context, "user_prompt": self.user_prompt}


def _json(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _region_summary(name: str, region: Any | None) -> str:
    if region is None:
        return f"{name}: none"
    bounds = region.bounds()
    if bounds is None:
        bounds_text = "empty"
    else:
        min_x, max_x, min_z, max_z = bounds
        bounds_text = f"x={min_x}..{max_x}, z={min_z}..{max_z}"
    return f"{name} readable bounds: {bounds_text}\n{name} RegionExpr JSON:\n{_json(region)}"


def build_worker_prompt(project_prompt: str, plan: ProjectPlan, package: WorkPackage) -> WorkerPrompt:
    """Build exactly one prompt for a semantic WorkPackage, including all instances."""
    responsibility = package.responsibility
    relevant_interfaces = [interface for interface in plan.interfaces if package.id in interface.participants]
    other_packages = [
        {
            "id": candidate.id,
            "name": candidate.name,
            "semantic_type": candidate.semantic_type,
        }
        for candidate in plan.work_packages
        if candidate.id != package.id
    ]
    instance_data = [instance.to_dict() for instance in package.instances]
    instance_lines = "\n".join(
        f"- {instance.id}: anchor={json.dumps(list(instance.anchor))}, rotation={instance.rotation}"
        for instance in package.instances
    )
    interface_data = [interface.to_dict() for interface in relevant_interfaces]
    boundary_value = responsibility.boundary_kind.value
    write_policy_value = responsibility.write_policy.value
    allowed_text = "core only" if responsibility.boundary_kind is BoundaryKind.HARD else "core union halo"

    system_context = f"""{WORKER_SYSTEM_CONTEXT}

Assigned package: {package.id} ({package.semantic_type}).
Runtime permission: {boundary_value} boundary; allowed volume is {allowed_text},
y={responsibility.min_y}..{responsibility.max_y}.
Core write policy: {write_policy_value}. Halo and interface writes always preserve existing blocks.
An explicit air voxel is a write intent. It may clear a destination only under carve policy in the core."""

    family_instruction = (
        "This package has multiple repeated instances. Define shared blueprint helper/construction logic once, then "
        "invoke it at every listed anchor and rotation. All instances must share dimensions, materials, roof language, "
        "openings, and detail grammar. Do not turn the instances into separate worker tasks."
        if len(package.instances) > 1
        else "Build the listed instance at its exact project-global anchor and rotation."
    )

    user_prompt = f"""# Large-project component assignment

## Original player request
{project_prompt}

## Approved project
Title: {plan.title}
Summary: {plan.project_summary}
Site: {_json(plan.site)}

## Shared StyleBible (mandatory; do not invent a conflicting local style)
{_json(plan.style_bible)}

## Your semantic WorkPackage
ID: {package.id}
Name: {package.name}
Semantic type: {package.semantic_type}
Objective: {package.objective}
Worker brief: {package.worker_brief}

Instances (use every entry exactly):
{instance_lines}

Instances JSON:
{_json(instance_data)}

{family_instruction}

## Responsibility and write permission
All coordinates below and all coordinates you emit are project-global. Your VoxelGrid starts empty; do not move this
component to the origin. Runtime masks, not this prose, make the final permission decision.

Boundary: {boundary_value}
Vertical range (inclusive): y={responsibility.min_y}..{responsibility.max_y}
Allowed volume: {allowed_text}
Core write policy: {write_policy_value}
{_region_summary("Core", responsibility.core)}

{_region_summary("Halo", responsibility.halo)}

Hard means one stored voxel intent outside core rejects the complete patch. Soft means intents outside core union halo
are clipped. In halo and interface cells, preserve existing non-air blocks. Explicit air clears only with carve in core.

## Interface contracts involving this package
{_json(interface_data)}

Interfaces are intentional connection bands with the named participant only. They use preserve_existing: fill empty/air
destinations, never overwrite existing non-air structure, and never treat an interface as general shared space.

## Dependencies and neighbor context
Depends on: {_json(package.depends_on)}
Known neighbor context: {_json(package.neighbor_context)}

## Structures outside this assignment (do not generate their main bodies)
{_json(other_packages)}

Only construct {package.id}. You may create the minimum joining detail required by a declared interface, but do not
modify or reproduce another package's primary structure and do not choose a new responsibility region.

## Acceptance criteria
{_json(package.acceptance_criteria)}

## Required review views
{_json(package.requested_views)}

Request these views in your build tool calls so you can verify the assigned component. Complete every acceptance
criterion, inspect the result, and call finish only when the entire semantic package (including every instance) is
done."""
    return WorkerPrompt(system_context=system_context, user_prompt=user_prompt)
