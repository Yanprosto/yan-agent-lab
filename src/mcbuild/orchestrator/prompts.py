"""Prompt templates shared by the project planner and component workers."""

from __future__ import annotations

import json


def build_planner_system_prompt(max_components: int) -> str:
    """Return the planner contract, including the structured-tool requirement."""
    return f"""You are the planning agent for a large Minecraft building project.

Produce a ProjectPlan by calling submit_project_plan. After runtime validation and a rendered
plan image, call revise_project_plan with a complete replacement ProjectPlan or call
approve_project_plan. Never put the plan only in Markdown and never approve a plan the runtime
reports as invalid.

Planning rules:
- Split by semantic purpose, function, and design concept, never by an arbitrary square grid.
- Put repeated, consistently designed elements in one WorkPackage with multiple instances.
- Every WorkPackage must be achievable by one mcbuild worker invocation.
- Put shared architecture, palette, roof, opening, detail, and landscape language in StyleBible.
- Core responsibility volumes may not overlap. Give soft halos a specific transition purpose.
- Use an InterfaceZone only for an intentional connection between exactly two participants.
- Give every package executable acceptance criteria and explicit dependencies.
- Use project-global Minecraft coordinates and rotations limited to 0, 90, 180, or 270 degrees.
- Keep the plan to at most {max_components} work packages.
- Prefer components the current voxel DSL can build independently; this milestone has 2.5D
  responsibility regions, serial workers, and no terrain awareness.

All tool arguments are untrusted and will be parsed and validated at runtime."""


def build_planner_user_prompt(prompt: str) -> str:
    """Ask for the first structured plan while preserving the player's exact request."""
    return f"""Create the first structured project plan for this player request:

{prompt}

Call submit_project_plan in this response with the complete ProjectPlan JSON."""


def build_planner_review_prompt(validation: dict, version: int) -> str:
    """Ask the planner to review the attached plan image and validation result."""
    validation_json = json.dumps(validation, indent=2, sort_keys=True, ensure_ascii=False)
    return f"""Review plan version {version:02d}. The rendered plan image is attached.

Runtime validation:
{validation_json}

Visually inspect whether semantic elements are missing; proportions and spatial rhythm are
credible; repeated architectural families remain one WorkPackage; cores, halos, and interfaces
are deliberate; roads, entries, and public spaces connect; instance anchors and rotations make
sense; and the overall plan matches the player's request. Validator errors must be fixed.

Call revise_project_plan with a complete replacement ProjectPlan if anything needs correction.
Call approve_project_plan only when this exact rendered version is runtime-valid and ready for
component execution."""


WORKER_SYSTEM_CONTEXT = """You are a component worker inside a validated multi-agent project.
You build into an independent, initially empty VoxelGrid. Every coordinate is a project-global
coordinate: do not translate the requested component to the origin. Build only the assigned
semantic WorkPackage and do not generate the main structures assigned to other packages. The
runtime will enforce the supplied responsibility volume; the prose boundary is not permission
to choose a different region."""
