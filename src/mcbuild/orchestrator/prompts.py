"""Prompt templates shared by the project planner and component workers."""

from __future__ import annotations

import json

_PLANNER_RULES = """Planning rules:
- Split by semantic purpose, function, and design concept, never by an arbitrary square grid.
- Put repeated, consistently designed elements in one WorkPackage with multiple instances.
- Every WorkPackage must be achievable by one mcbuild worker invocation.
- Put shared architecture, palette, roof, opening, detail, and landscape language in StyleBible.
- Core responsibility volumes may not overlap. Give soft halos a specific transition purpose.
- Use an InterfaceZone only for an intentional connection between exactly two participants.
- Give every package executable acceptance criteria and explicit dependencies.
- Use project-global Minecraft coordinates and rotations limited to 0, 90, 180, or 270 degrees.
- Prefer components the current voxel DSL can build independently; this milestone has 2.5D
  responsibility regions, serial workers, and no terrain awareness.

Exact JSON contract (unknown keys are rejected):
- ProjectPlan keys: schema_version, title, project_summary, site, style_bible, work_packages,
  interfaces.
- Site keys: min_x, max_x, min_z, max_z, base_y.
- StyleBible keys: architectural_style, scale_and_massing, primary_palette,
  secondary_palette, accent_palette, roof_language, opening_language, detail_language,
  landscape_language, global_constraints.
- WorkPackage keys: id, name, semantic_type, objective, instances, responsibility,
  depends_on, neighbor_context, worker_brief, acceptance_criteria, requested_views.
- Instance keys: id, anchor, rotation. Responsibility keys: boundary_kind, core, halo,
  min_y, max_y, write_policy. Always include halo, using null when no halo is needed.
- neighbor_context, depends_on, acceptance_criteria, RegionExpr children/subtract, and all
  other schema arrays must remain JSON arrays even when they contain only one item.
- RegionExpr always uses discriminator key `op`, never `type`: shape uses `op` + `shape`;
  union/intersection use `op` + `children`; difference uses `op` + `base` + `subtract`.
  The difference `subtract` value is always an array. A rectangle shape kind is exactly
  `axis_aligned_rectangle`, never `rect` or `rectangle`.
- A requested view may use only mode, yaw, cutaway, slice_axis, slice_at. Safe exact forms are
  {"mode":"top-down"}, {"mode":"iso","yaw":0},
  {"mode":"iso","yaw":2,"cutaway":"x"}, or
  {"mode":"iso","yaw":2,"slice_axis":"z","slice_at":20}. The mode is `iso`, never
  `isometric`; cutaway is string `x`/`z`, never a boolean, and cannot coexist with slice fields.
  For an x cut/slice use yaw 2 or 3; for z use yaw 1 or 2. InterfaceZone keys are id,
  participants, region, description, merge_policy."""


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

Exact JSON contract (unknown keys are rejected):
- ProjectPlan keys: schema_version, title, project_summary, site, style_bible, work_packages,
  interfaces.
- Site keys: min_x, max_x, min_z, max_z, base_y.
- StyleBible keys: architectural_style, scale_and_massing, primary_palette,
  secondary_palette, accent_palette, roof_language, opening_language, detail_language,
  landscape_language, global_constraints.
- WorkPackage keys: id, name, semantic_type, objective, instances, responsibility,
  depends_on, neighbor_context, worker_brief, acceptance_criteria, requested_views.
- Instance keys: id, anchor, rotation. Responsibility keys: boundary_kind, core, halo,
  min_y, max_y, write_policy.
- neighbor_context, depends_on, acceptance_criteria, RegionExpr children/subtract, and all
  other schema arrays must remain JSON arrays even when they contain only one item.
- RegionExpr always uses discriminator key `op`, never `type`: shape uses `op` + `shape`;
  union/intersection use `op` + `children`; difference uses `op` + `base` + `subtract`.
  The difference `subtract` value is always an array. A rectangle shape kind is exactly
  `axis_aligned_rectangle`, never `rect` or `rectangle`.
- A requested view may use only mode, yaw, cutaway, slice_axis, slice_at. Safe exact forms are
  {{"mode":"top-down"}}, {{"mode":"iso","yaw":0}},
  {{"mode":"iso","yaw":2,"cutaway":"x"}}, or
  {{"mode":"iso","yaw":2,"slice_axis":"z","slice_at":20}}. The mode is `iso`, never
  `isometric`; cutaway is string `x`/`z`, never a boolean, and cannot coexist with slice fields.
  For an x cut/slice use yaw 2 or 3; for z use yaw 1 or 2. InterfaceZone keys are id,
  participants, region, description, merge_policy.

All tool arguments are untrusted and will be parsed and validated at runtime."""


def build_structured_planner_system_prompt(max_components: int) -> str:
    """Return the plan-only contract for provider-native strict JSON generation."""
    return f"""You are the planning agent for a large Minecraft building project.

Return exactly one complete ProjectPlan matching the supplied strict JSON Schema. Do not add
Markdown, commentary, review decisions, or tool state. Runtime parsing and semantic validation
remain authoritative.

{_PLANNER_RULES}
- Keep the plan to at most {max_components} work packages."""


def build_structured_planner_user_prompt(prompt: str) -> str:
    """Ask for the first plan as schema-constrained JSON, without tool instructions."""
    return f"""Create the first complete ProjectPlan for this player request:

{prompt}

Return only the schema-constrained ProjectPlan object."""


def build_structured_planner_revision_prompt(
    prompt: str,
    previous_plan: dict,
    validation: dict,
    review_notes: str,
    next_version: int,
) -> str:
    """Build a clean strict-generation request for a complete replacement plan."""
    previous_json = json.dumps(previous_plan, indent=2, sort_keys=True, ensure_ascii=False)
    validation_json = json.dumps(validation, indent=2, sort_keys=True, ensure_ascii=False)
    return f"""Create complete replacement ProjectPlan version {next_version:02d} for the original request:

{prompt}

Previous ProjectPlan JSON:
{previous_json}

Authoritative local validation:
{validation_json}

Revision instructions:
{review_notes}

Fix every validator error and address the review instructions. Return only a full replacement
ProjectPlan object matching the strict schema; do not return a patch or a review decision."""


def build_planner_visual_review_system_prompt() -> str:
    """Return the small, plan-free visual review tool contract."""
    return """You are the visual reviewer for a Minecraft project plan. Inspect only the rendered
plan image and the supplied local validation report. Call exactly one review tool. Approve only
when the rendered layout is coherent and the local report is valid. Otherwise request a revision
with concise, executable instructions. Never reproduce or submit the ProjectPlan JSON."""


def build_planner_visual_review_prompt(prompt: str, validation: dict, version: int) -> str:
    """Ask for a simple approve/revise decision about one already-rendered plan."""
    validation_json = json.dumps(validation, indent=2, sort_keys=True, ensure_ascii=False)
    return f"""Review rendered plan version {version:02d} against this player request:

{prompt}

Authoritative local validation:
{validation_json}

Check missing semantic elements, proportions, spatial rhythm, connections, entries, public
spaces, responsibility boundaries, anchors, rotations, and overall request fidelity. Use
approve_project_plan only if both the image and validation are ready; otherwise use
request_project_plan_revision. Do not include the plan itself in tool arguments."""


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
