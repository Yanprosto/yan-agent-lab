"""Bounded, tool-driven planner loop for large Minecraft projects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mcbuild.llm.client import PlanJSONMode, Usage, image_to_data_url
from mcbuild.orchestrator.models import ModelValidationError, ProjectConfig, ProjectPlan
from mcbuild.orchestrator.plan_render import render_plan
from mcbuild.orchestrator.prompts import (
    build_planner_review_prompt,
    build_planner_system_prompt,
    build_planner_user_prompt,
    build_planner_visual_review_prompt,
    build_planner_visual_review_system_prompt,
    build_structured_planner_revision_prompt,
    build_structured_planner_system_prompt,
    build_structured_planner_user_prompt,
)
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.orchestrator.validator import PlanValidationReport, validate_project_plan

_NONEMPTY_STRING_SCHEMA: dict[str, Any] = {"type": "string", "minLength": 1}
_IDENTIFIER_SCHEMA: dict[str, Any] = {
    "type": "string",
    "pattern": "^[a-z][a-z0-9_]*$",
}
_STYLE_VALUE_SCHEMA: dict[str, Any] = {
    "oneOf": [
        _NONEMPTY_STRING_SCHEMA,
        {
            "type": "array",
            "minItems": 1,
            "items": _NONEMPTY_STRING_SCHEMA,
        },
    ]
}

_PLAN_SCHEMA_DEFS: dict[str, Any] = {
    "site": {
        "type": "object",
        "additionalProperties": False,
        "required": ["min_x", "max_x", "min_z", "max_z", "base_y"],
        "properties": {
            "min_x": {"type": "integer"},
            "max_x": {"type": "integer"},
            "min_z": {"type": "integer"},
            "max_z": {"type": "integer"},
            "base_y": {"type": "integer"},
        },
    },
    "style_bible": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "architectural_style",
            "scale_and_massing",
            "primary_palette",
            "secondary_palette",
            "accent_palette",
            "roof_language",
            "opening_language",
            "detail_language",
            "landscape_language",
            "global_constraints",
        ],
        "properties": {
            name: _STYLE_VALUE_SCHEMA
            for name in (
                "architectural_style",
                "scale_and_massing",
                "primary_palette",
                "secondary_palette",
                "accent_palette",
                "roof_language",
                "opening_language",
                "detail_language",
                "landscape_language",
                "global_constraints",
            )
        },
    },
    "region_shape": {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "min_x", "max_x", "min_z", "max_z"],
                "properties": {
                    "kind": {"const": "axis_aligned_rectangle"},
                    "min_x": {"type": "number"},
                    "max_x": {"type": "number"},
                    "min_z": {"type": "number"},
                    "max_z": {"type": "number"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "center", "width", "depth", "rotation"],
                "properties": {
                    "kind": {"const": "rotated_rectangle"},
                    "center": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "number"},
                    },
                    "width": {"type": "number", "exclusiveMinimum": 0},
                    "depth": {"type": "number", "exclusiveMinimum": 0},
                    "rotation": {"type": "number"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "center", "radius"],
                "properties": {
                    "kind": {"const": "circle"},
                    "center": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "number"},
                    },
                    "radius": {"type": "number", "exclusiveMinimum": 0},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "center", "radius_x", "radius_z"],
                "properties": {
                    "kind": {"const": "ellipse"},
                    "center": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "number"},
                    },
                    "radius_x": {"type": "number", "exclusiveMinimum": 0},
                    "radius_z": {"type": "number", "exclusiveMinimum": 0},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "points"],
                "properties": {
                    "kind": {"const": "polygon"},
                    "points": {
                        "type": "array",
                        "minItems": 3,
                        "items": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": {"type": "number"},
                        },
                    },
                },
            },
        ]
    },
    "region_expr": {
        "description": (
            "A RegionExpr. Discriminator key is always 'op' (never 'type'). "
            "Nested children, base, and subtract entries use this same RegionExpr contract."
        ),
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "shape"],
                "properties": {
                    "op": {"const": "shape"},
                    "shape": {"$ref": "#/$defs/region_shape"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "children"],
                "properties": {
                    "op": {"enum": ["union", "intersection"]},
                    "children": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/region_expr"},
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "base", "subtract"],
                "properties": {
                    "op": {"const": "difference"},
                    "base": {"$ref": "#/$defs/region_expr"},
                    "subtract": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/region_expr"},
                    },
                },
            },
        ],
    },
    "instance": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "anchor", "rotation"],
        "properties": {
            "id": _IDENTIFIER_SCHEMA,
            "anchor": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "integer"},
            },
            "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
        },
    },
    "responsibility": {
        "type": "object",
        "additionalProperties": False,
        "required": ["boundary_kind", "core", "min_y", "max_y"],
        "properties": {
            "boundary_kind": {"type": "string", "enum": ["hard", "soft"]},
            "core": {"$ref": "#/$defs/region_expr"},
            "halo": {
                "oneOf": [
                    {"$ref": "#/$defs/region_expr"},
                    {"type": "null"},
                ]
            },
            "min_y": {"type": "integer"},
            "max_y": {"type": "integer"},
            "write_policy": {
                "type": "string",
                "enum": ["preserve_existing", "additive", "overwrite", "carve"],
            },
        },
    },
    "requested_view": {
        "description": (
            "Use exactly one branch. The mode literal is 'iso', never 'isometric'. Cutaway is "
            "the string 'x' or 'z', never a boolean, and is never combined with a slice."
        ),
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode"],
                "properties": {"mode": {"const": "top-down"}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "yaw"],
                "properties": {
                    "mode": {"const": "iso"},
                    "yaw": {"type": "integer", "minimum": 0, "maximum": 3},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "yaw", "cutaway"],
                "properties": {
                    "mode": {"const": "iso"},
                    "yaw": {"type": "integer", "minimum": 0, "maximum": 3},
                    "cutaway": {"type": "string", "enum": ["x", "z"]},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "yaw", "slice_axis", "slice_at"],
                "properties": {
                    "mode": {"const": "iso"},
                    "yaw": {"type": "integer", "minimum": 0, "maximum": 3},
                    "slice_axis": {"type": "string", "enum": ["x", "y", "z"]},
                    "slice_at": {"type": "integer"},
                },
            },
        ],
    },
    "work_package": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "name",
            "semantic_type",
            "objective",
            "instances",
            "responsibility",
            "depends_on",
            "neighbor_context",
            "worker_brief",
            "acceptance_criteria",
            "requested_views",
        ],
        "properties": {
            "id": _IDENTIFIER_SCHEMA,
            "name": _NONEMPTY_STRING_SCHEMA,
            "semantic_type": _NONEMPTY_STRING_SCHEMA,
            "objective": _NONEMPTY_STRING_SCHEMA,
            "instances": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/instance"},
            },
            "responsibility": {"$ref": "#/$defs/responsibility"},
            "depends_on": {"type": "array", "items": _IDENTIFIER_SCHEMA},
            "neighbor_context": {"type": "array", "items": _NONEMPTY_STRING_SCHEMA},
            "worker_brief": _NONEMPTY_STRING_SCHEMA,
            "acceptance_criteria": {
                "type": "array",
                "minItems": 1,
                "items": _NONEMPTY_STRING_SCHEMA,
            },
            "requested_views": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {"$ref": "#/$defs/requested_view"},
            },
        },
    },
    "interface_zone": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "participants", "region", "description", "merge_policy"],
        "properties": {
            "id": _IDENTIFIER_SCHEMA,
            "participants": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": _IDENTIFIER_SCHEMA,
            },
            "region": {"$ref": "#/$defs/region_expr"},
            "description": _NONEMPTY_STRING_SCHEMA,
            "merge_policy": {"type": "string", "const": "preserve_existing"},
        },
    },
}

_PLAN_TOP_LEVEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "title",
        "project_summary",
        "site",
        "style_bible",
        "work_packages",
        "interfaces",
    ],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "title": {"type": "string"},
        "project_summary": {"type": "string"},
        "site": {"$ref": "#/$defs/site"},
        "style_bible": {"$ref": "#/$defs/style_bible"},
        "work_packages": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/work_package"},
        },
        "interfaces": {"type": "array", "items": {"$ref": "#/$defs/interface_zone"}},
    },
}


def _strict_schema_copy(value: Any) -> Any:
    """Copy the Planner schema into the strict subset used by provider-native JSON."""
    if isinstance(value, list):
        return [_strict_schema_copy(item) for item in value]
    if not isinstance(value, dict):
        return value

    copied: dict[str, Any] = {}
    for key, item in value.items():
        if key == "oneOf":
            copied["anyOf"] = _strict_schema_copy(item)
        elif key == "const":
            copied["enum"] = [_strict_schema_copy(item)]
        else:
            copied[key] = _strict_schema_copy(item)
    if copied.get("type") == "object":
        properties = copied.get("properties", {})
        copied["additionalProperties"] = False
        copied["required"] = list(properties)
    return copied


# Self-contained: every #/$defs reference resolves inside this root object. The legacy
# function-tool schema below is intentionally left unchanged for compatible-provider fallback.
PROJECT_PLAN_JSON_SCHEMA: dict[str, Any] = _strict_schema_copy({**_PLAN_TOP_LEVEL_SCHEMA, "$defs": _PLAN_SCHEMA_DEFS})


def _plan_tool(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["plan"],
                "properties": {"plan": _PLAN_TOP_LEVEL_SCHEMA},
                "$defs": _PLAN_SCHEMA_DEFS,
            },
        },
    }


PLANNER_TOOLS: list[dict[str, Any]] = [
    _plan_tool(
        "submit_project_plan",
        "Submit the first complete ProjectPlan. Runtime schema and semantic validation are authoritative.",
    ),
    _plan_tool(
        "revise_project_plan",
        "Replace the current draft with a complete revised ProjectPlan after reviewing its plan image and validation.",
    ),
    {
        "type": "function",
        "function": {
            "name": "approve_project_plan",
            "description": "Approve the currently rendered plan after visual review; invalid plans cannot be approved.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "review_notes"],
                "properties": {
                    "summary": {"type": "string"},
                    "review_notes": {"type": "string"},
                },
            },
        },
    },
]


PLANNER_REVIEW_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "approve_project_plan",
            "description": "Approve the rendered plan after visual review; invalid plans cannot be approved.",
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "review_notes"],
                "properties": {
                    "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "review_notes": {"type": "string", "maxLength": 4000},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_project_plan_revision",
            "description": "Request a complete new plan generation using concise visual corrections.",
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["review_notes", "revision_instructions"],
                "properties": {
                    "review_notes": {"type": "string", "maxLength": 4000},
                    "revision_instructions": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 4000,
                    },
                },
            },
        },
    },
]


@dataclass(frozen=True)
class PlannerResult:
    """Outcome of planning; workers may run only when ``approved`` is true."""

    approved: bool
    plan: ProjectPlan | None
    summary: str
    review_notes: str
    versions: int
    usage: Usage
    error: str | None = None


def _field(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    for method_name in ("model_dump", "dict", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _to_plain(method())
            except Exception:
                continue
    return str(value)


def _message_to_dict(message: object) -> dict[str, Any]:
    result: dict[str, Any] = {"role": "assistant", "content": _field(message, "content", None) or ""}
    tool_calls = _field(message, "tool_calls", None) or []
    if tool_calls:
        result["tool_calls"] = [
            {
                "id": _field(call, "id", ""),
                "type": "function",
                "function": {
                    "name": _field(_field(call, "function", {}), "name", ""),
                    "arguments": _field(_field(call, "function", {}), "arguments", ""),
                },
            }
            for call in tool_calls
        ]
    reasoning_details = _field(message, "reasoning_details", None)
    if reasoning_details:
        result["reasoning_details"] = _to_plain(reasoning_details)
    return result


def _tool_result(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def _parse_tool_arguments(arguments: object) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(arguments, str):
        return None, "Tool arguments must be a JSON object string."
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as error:
        return None, f"Invalid tool JSON at line {error.lineno}, column {error.colno}: {error.msg}"
    if not isinstance(parsed, dict):
        return None, "Tool arguments must decode to an object."
    return parsed, None


def _schema_failure(error: Exception) -> dict[str, Any]:
    path = getattr(error, "path", "plan")
    message = getattr(error, "message", str(error))
    return {
        "valid": False,
        "errors": [{"code": "schema_error", "path": str(path), "message": str(message)}],
        "warnings": [],
    }


def _report_dict(report: PlanValidationReport | dict[str, Any]) -> dict[str, Any]:
    if isinstance(report, PlanValidationReport):
        return report.to_dict()
    return report


def _report_valid(report: PlanValidationReport | dict[str, Any]) -> bool:
    if isinstance(report, dict):
        return bool(report.get("valid", False))
    return report.valid


def _sanitized_messages(messages: list[dict[str, Any]], image_paths: dict[str, str]) -> list[dict[str, Any]]:
    """Return JSON-safe history with embedded plan images replaced by artifact paths."""

    def sanitize(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("data:image/"):
            return image_paths.get(value, "project/<embedded-plan-image>")
        if isinstance(value, str) and "data:image/" in value:
            return "project/<embedded-plan-image>"
        if isinstance(value, dict):
            return {str(key): sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return _to_plain(value)

    return sanitize(messages)


def _safe_review_text(value: str, max_length: int = 4000) -> str:
    """Bound untrusted reviewer prose and ensure it cannot persist embedded image data."""
    if "data:image/" in value:
        value = value.split("data:image/", 1)[0] + "[embedded image omitted]"
    return value[:max_length]


def _run_tool_planner(
    prompt: str,
    llm: Any,
    config: ProjectConfig,
    rundir: ProjectRunDir,
    on_event: Any | None = None,
) -> PlannerResult:
    """Legacy function-tool Planner used by chat-only or generic compatible clients.

    ``planner_max_iters`` limits submitted plan versions.  A separate derived LLM-turn
    limit prevents text-only, malformed-tool, or repeated-invalid-approval loops.  Every
    submitted version is preserved, even when its JSON cannot instantiate ``ProjectPlan``.
    """

    def emit(event_type: str, **data: Any) -> None:
        if on_event is not None:
            on_event(event_type, data)

    usage = Usage()
    versions = 0
    current_plan: ProjectPlan | None = None
    current_report: PlanValidationReport | dict[str, Any] | None = None
    current_image = None
    current_image_path: str | None = None
    image_paths: dict[str, str] = {}
    review_has_been_sent = False

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_planner_system_prompt(config.max_components)},
        {"role": "user", "content": build_planner_user_prompt(prompt)},
    ]

    def save_session() -> None:
        rundir.write_project_json("planner_session.json", _sanitized_messages(messages, image_paths))

    def finish_failure(error: str) -> PlannerResult:
        save_session()
        return PlannerResult(False, current_plan, "", "", versions, usage, error)

    max_turns = max(4, config.planner_max_iters * 3 + 2)
    worker_config = config.worker_config

    try:
        for turn in range(1, max_turns + 1):
            approval_ready_this_turn = review_has_been_sent

            def on_delta(kind: str, text: str) -> None:
                emit(f"planner_{kind}_delta", text=text)

            chat_result = llm.chat(
                model=config.planner_model,
                messages=messages,
                tools=PLANNER_TOOLS,
                reasoning=worker_config.reasoning,
                stream=worker_config.stream,
                on_delta=on_delta,
            )
            usage.add(chat_result.usage)
            message = chat_result.message
            assistant_message = _message_to_dict(message)
            messages.append(assistant_message)
            emit(
                "planner_turn_usage",
                turn=turn,
                prompt_tokens=chat_result.usage.prompt_tokens,
                completion_tokens=chat_result.usage.completion_tokens,
                reasoning_tokens=chat_result.usage.reasoning_tokens,
                cached_tokens=chat_result.usage.cached_tokens,
                cost_usd=chat_result.usage.cost_usd,
                cumulative_cost_usd=usage.cost_usd,
            )

            if config.cost_ceiling is not None and usage.cost_usd >= config.cost_ceiling:
                return finish_failure(
                    f"Planner cost ceiling reached: ${usage.cost_usd:.6f} >= ${config.cost_ceiling:.6f}"
                )

            calls = _field(message, "tool_calls", None) or []
            if not calls:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Use exactly one planner tool now. Submit the first complete plan, revise the current "
                            "plan, or approve the valid rendered plan."
                        ),
                    }
                )
                save_session()
                continue

            if len(calls) != 1:
                for call in calls:
                    messages.append(
                        _tool_result(
                            str(_field(call, "id", "")),
                            {"ok": False, "error": "Call exactly one planner tool per turn."},
                        )
                    )
                save_session()
                continue

            call = calls[0]
            call_id = str(_field(call, "id", ""))
            function = _field(call, "function", {})
            name = str(_field(function, "name", ""))
            arguments_raw = _field(function, "arguments", "")
            arguments, argument_error = _parse_tool_arguments(arguments_raw)
            if argument_error is not None:
                messages.append(_tool_result(call_id, {"ok": False, "error": argument_error}))
                save_session()
                continue
            assert arguments is not None

            if name == "approve_project_plan":
                summary = arguments.get("summary")
                review_notes = arguments.get("review_notes")
                if not isinstance(summary, str) or not summary.strip():
                    messages.append(
                        _tool_result(call_id, {"ok": False, "error": "summary must be a non-empty string."})
                    )
                    save_session()
                    continue
                if not isinstance(review_notes, str):
                    messages.append(_tool_result(call_id, {"ok": False, "error": "review_notes must be a string."}))
                    save_session()
                    continue
                if current_plan is None or current_report is None or current_image is None:
                    messages.append(
                        _tool_result(call_id, {"ok": False, "error": "No rendered plan is available to approve."})
                    )
                    save_session()
                    continue
                if not _report_valid(current_report):
                    messages.append(
                        _tool_result(
                            call_id,
                            {"ok": False, "error": "The current plan is invalid. Revise it before approval."},
                        )
                    )
                    save_session()
                    continue
                if not approval_ready_this_turn:
                    messages.append(
                        _tool_result(
                            call_id,
                            {
                                "ok": False,
                                "error": "Review the rendered plan image in a subsequent turn before approval.",
                            },
                        )
                    )
                    save_session()
                    continue

                messages.append(_tool_result(call_id, {"ok": True, "approved_version": versions}))
                rundir.write_project_json("approved_plan.json", current_plan.to_dict())
                approved_image = rundir.save_project_image("approved_plan.png", current_image)
                emit(
                    "plan_approved",
                    version=versions,
                    path=str(rundir.project_path("approved_plan.json")),
                    image_path=str(approved_image),
                    summary=summary.strip(),
                    review_notes=review_notes,
                )
                save_session()
                return PlannerResult(
                    True,
                    current_plan,
                    summary.strip(),
                    review_notes,
                    versions,
                    usage,
                    None,
                )

            if name not in {"submit_project_plan", "revise_project_plan"}:
                messages.append(_tool_result(call_id, {"ok": False, "error": f"Unknown planner tool: {name!r}"}))
                save_session()
                continue
            if name == "submit_project_plan" and versions != 0:
                messages.append(
                    _tool_result(call_id, {"ok": False, "error": "A plan already exists; use revise_project_plan."})
                )
                save_session()
                continue
            if name == "revise_project_plan" and versions == 0:
                messages.append(
                    _tool_result(call_id, {"ok": False, "error": "Submit the first plan with submit_project_plan."})
                )
                save_session()
                continue
            if versions >= config.planner_max_iters:
                messages.append(
                    _tool_result(call_id, {"ok": False, "error": "The plan-version limit has been reached."})
                )
                save_session()
                if current_report is None or not _report_valid(current_report):
                    return finish_failure(f"No valid plan after {config.planner_max_iters} versions.")
                continue

            versions += 1
            version_label = f"plan_v{versions:02d}"
            review_has_been_sent = False
            current_plan = None
            current_report = None
            current_image = None
            current_image_path = None

            plan_payload = arguments.get("plan")
            if not isinstance(plan_payload, dict):
                schema_report = _schema_failure(ValueError("plan must be an object"))
                rundir.write_project_json(
                    f"{version_label}.json",
                    {"raw_tool_arguments": arguments_raw, "parse_error": "plan must be an object"},
                )
                rundir.write_project_json(f"{version_label}_validation.json", schema_report)
                current_report = schema_report
            else:
                try:
                    current_plan = ProjectPlan.from_dict(plan_payload)
                    current_report = validate_project_plan(current_plan, max_components=config.max_components)
                    rundir.write_project_json(f"{version_label}.json", current_plan.to_dict())
                    rundir.write_project_json(f"{version_label}_validation.json", _report_dict(current_report))
                    current_image = render_plan(current_plan, current_report)
                    image_file = rundir.save_project_image(f"{version_label}.png", current_image)
                    current_image_path = f"project/{image_file.name}"
                except (ModelValidationError, ValueError, TypeError) as error:
                    current_plan = None
                    current_report = _schema_failure(error)
                    rundir.write_project_json(f"{version_label}.json", plan_payload)
                    rundir.write_project_json(f"{version_label}_validation.json", current_report)

            report_payload = _report_dict(current_report)
            event_type = "plan_submitted" if name == "submit_project_plan" else "plan_revised"
            emit(event_type, version=versions, path=str(rundir.project_path(f"{version_label}.json")))
            emit("plan_validation", version=versions, report=report_payload)
            if current_image_path is not None:
                emit(
                    "plan_render",
                    version=versions,
                    image_path=str(rundir.project_path(f"{version_label}.png")),
                )
            messages.append(
                _tool_result(
                    call_id,
                    {
                        "ok": True,
                        "version": versions,
                        "valid": _report_valid(current_report),
                        "validation": report_payload,
                        "image_path": current_image_path,
                    },
                )
            )

            review_text = build_planner_review_prompt(report_payload, versions)
            review_content: list[dict[str, Any]] = [{"type": "text", "text": review_text}]
            if current_image is not None and current_image_path is not None:
                data_url = image_to_data_url(current_image)
                image_paths[data_url] = current_image_path
                review_content.append({"type": "image_url", "image_url": {"url": data_url}})
            messages.append({"role": "user", "content": review_content})
            review_has_been_sent = True
            save_session()

            if versions >= config.planner_max_iters and not _report_valid(current_report):
                return finish_failure(f"No valid plan after {config.planner_max_iters} versions.")

        return finish_failure(f"Planner stopped after the {max_turns}-turn safety limit without approval.")
    except Exception as error:
        save_session()
        return PlannerResult(
            False,
            current_plan,
            "",
            "",
            versions,
            usage,
            f"Planner failed: {type(error).__name__}: {error}",
        )


def _run_structured_planner(
    prompt: str,
    llm: Any,
    config: ProjectConfig,
    rundir: ProjectRunDir,
    on_event: Any | None = None,
) -> PlannerResult:
    """Run strict plan generation and stateless visual review as separate phases."""

    def emit(event_type: str, **data: Any) -> None:
        if on_event is not None:
            on_event(event_type, data)

    usage = Usage()
    versions = 0
    llm_turn = 0
    current_plan: ProjectPlan | None = None
    current_payload: dict[str, Any] | None = None
    current_report: PlanValidationReport | dict[str, Any] | None = None
    current_image = None
    session: list[dict[str, Any]] = []
    revision_notes = ""
    worker_config = config.worker_config
    system_prompt = build_structured_planner_system_prompt(config.max_components)

    def save_session() -> None:
        rundir.write_project_json("planner_session.json", _sanitized_messages(session, {}))

    def finish_failure(error: str) -> PlannerResult:
        session.append({"stage": "failure", "error": error})
        save_session()
        return PlannerResult(False, current_plan, "", "", versions, usage, error)

    def add_usage(stage: str, turn_usage: Usage) -> str | None:
        nonlocal llm_turn
        llm_turn += 1
        usage.add(turn_usage)
        emit(
            "planner_turn_usage",
            turn=llm_turn,
            stage=stage,
            prompt_tokens=turn_usage.prompt_tokens,
            completion_tokens=turn_usage.completion_tokens,
            reasoning_tokens=turn_usage.reasoning_tokens,
            cached_tokens=turn_usage.cached_tokens,
            cost_usd=turn_usage.cost_usd,
            cumulative_cost_usd=usage.cost_usd,
        )
        if config.cost_ceiling is not None and usage.cost_usd >= config.cost_ceiling:
            return f"Planner cost ceiling reached: ${usage.cost_usd:.6f} >= ${config.cost_ceiling:.6f}"
        return None

    try:
        while versions < config.planner_max_iters:
            next_version = versions + 1
            if next_version == 1:
                user_prompt = build_structured_planner_user_prompt(prompt)
            else:
                assert current_payload is not None
                assert current_report is not None
                user_prompt = build_structured_planner_revision_prompt(
                    prompt,
                    current_payload,
                    _report_dict(current_report),
                    revision_notes,
                    next_version,
                )

            def on_generation_delta(kind: str, text: str) -> None:
                emit(f"planner_{kind}_delta", text=text)

            try:
                generation = llm.generate_plan_json(
                    model=config.planner_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=PROJECT_PLAN_JSON_SCHEMA,
                    schema_name="project_plan",
                    reasoning=worker_config.reasoning,
                    stream=worker_config.stream,
                    on_delta=on_generation_delta,
                )
            except Exception as error:
                error_usage = getattr(error, "usage", None)
                if isinstance(error_usage, Usage):
                    cost_error = add_usage("plan_generation", error_usage)
                    if cost_error is not None:
                        return finish_failure(cost_error)
                raise
            generation_usage = _field(generation, "usage")
            if not isinstance(generation_usage, Usage):
                raise TypeError("generate_plan_json must return a Usage object.")
            cost_error = add_usage("plan_generation", generation_usage)
            if cost_error is not None:
                return finish_failure(cost_error)

            versions = next_version
            version_label = f"plan_v{versions:02d}"
            payload = _field(generation, "data")
            current_payload = payload if isinstance(payload, dict) else {"invalid_payload": _to_plain(payload)}
            current_plan = None
            current_report = None
            current_image = None
            current_image_path: str | None = None

            if not isinstance(payload, dict):
                current_report = _schema_failure(ValueError("structured plan must be an object"))
                rundir.write_project_json(f"{version_label}.json", current_payload)
                rundir.write_project_json(f"{version_label}_validation.json", current_report)
            else:
                try:
                    current_plan = ProjectPlan.from_dict(payload)
                    current_report = validate_project_plan(current_plan, max_components=config.max_components)
                    current_payload = current_plan.to_dict()
                    rundir.write_project_json(f"{version_label}.json", current_payload)
                    rundir.write_project_json(f"{version_label}_validation.json", _report_dict(current_report))
                except (ModelValidationError, ValueError, TypeError) as error:
                    current_plan = None
                    current_report = _schema_failure(error)
                    rundir.write_project_json(f"{version_label}.json", payload)
                    rundir.write_project_json(f"{version_label}_validation.json", current_report)
                if current_plan is not None and current_report is not None:
                    try:
                        current_image = render_plan(current_plan, current_report)
                        image_file = rundir.save_project_image(f"{version_label}.png", current_image)
                        current_image_path = f"project/{image_file.name}"
                    except Exception as error:
                        raise RuntimeError(
                            f"Plan rendering failed for version {versions:02d}: {type(error).__name__}: {error}"
                        ) from error

            assert current_report is not None
            report_payload = _report_dict(current_report)
            event_type = "plan_submitted" if versions == 1 else "plan_revised"
            emit(event_type, version=versions, path=str(rundir.project_path(f"{version_label}.json")))
            emit("plan_validation", version=versions, report=report_payload)
            if current_image_path is not None:
                emit(
                    "plan_render",
                    version=versions,
                    image_path=str(rundir.project_path(f"{version_label}.png")),
                )
            session.append(
                {
                    "stage": "plan_generation",
                    "version": versions,
                    "mode": str(_field(llm, "plan_json_mode", "structured")),
                    "plan_path": f"project/{version_label}.json",
                    "validation_path": f"project/{version_label}_validation.json",
                    "image_path": current_image_path,
                    "valid": _report_valid(current_report),
                    "revision_instructions": revision_notes if versions > 1 else "",
                }
            )
            save_session()

            if current_plan is None or current_image is None or current_image_path is None:
                if versions >= config.planner_max_iters:
                    return finish_failure(f"No schema-valid plan after {config.planner_max_iters} versions.")
                revision_notes = (
                    "Correct every authoritative local schema error below. No image could be rendered.\n"
                    + json.dumps(report_payload, indent=2, sort_keys=True, ensure_ascii=False)
                )
                continue

            base_review_prompt = build_planner_visual_review_prompt(prompt, report_payload, versions)
            data_url = image_to_data_url(current_image)
            review_error = ""
            decision_name = ""
            decision_arguments: dict[str, Any] | None = None
            for review_attempt in range(1, 3):
                review_prompt = base_review_prompt
                if review_error:
                    review_prompt += (
                        "\n\nThe previous review response was invalid: "
                        + review_error
                        + " Call exactly one review tool now."
                    )
                review_messages = [
                    {"role": "system", "content": build_planner_visual_review_system_prompt()},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": review_prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ]

                def on_review_delta(kind: str, text: str) -> None:
                    emit(f"planner_{kind}_delta", text=text)

                review = llm.chat(
                    model=config.planner_model,
                    messages=review_messages,
                    tools=PLANNER_REVIEW_TOOLS,
                    reasoning=worker_config.reasoning,
                    stream=worker_config.stream,
                    on_delta=on_review_delta,
                )
                review_usage = _field(review, "usage")
                if not isinstance(review_usage, Usage):
                    raise TypeError("chat must return a Usage object.")
                cost_error = add_usage("visual_review", review_usage)
                if cost_error is not None:
                    return finish_failure(cost_error)

                def record_review_failure(message: str, version: int, attempt: int) -> None:
                    nonlocal review_error
                    review_error = message
                    session.append(
                        {
                            "stage": "visual_review_attempt",
                            "version": version,
                            "attempt": attempt,
                            "valid": False,
                            "error": message,
                        }
                    )
                    save_session()

                calls = _field(_field(review, "message"), "tool_calls", None) or []
                if len(calls) != 1:
                    record_review_failure("Visual review must call exactly one review tool.", versions, review_attempt)
                    continue
                function = _field(calls[0], "function", {})
                name = str(_field(function, "name", ""))
                arguments, argument_error = _parse_tool_arguments(_field(function, "arguments", ""))
                if argument_error is not None:
                    record_review_failure(argument_error, versions, review_attempt)
                    continue
                assert arguments is not None
                if name == "approve_project_plan":
                    summary = arguments.get("summary")
                    notes = arguments.get("review_notes")
                    if not isinstance(summary, str) or not summary.strip():
                        record_review_failure("summary must be a non-empty string.", versions, review_attempt)
                        continue
                    if not isinstance(notes, str):
                        record_review_failure("review_notes must be a string.", versions, review_attempt)
                        continue
                elif name == "request_project_plan_revision":
                    notes = arguments.get("review_notes")
                    instructions = arguments.get("revision_instructions")
                    if not isinstance(notes, str):
                        record_review_failure("review_notes must be a string.", versions, review_attempt)
                        continue
                    if not isinstance(instructions, str) or not instructions.strip():
                        record_review_failure(
                            "revision_instructions must be a non-empty string.", versions, review_attempt
                        )
                        continue
                else:
                    record_review_failure(f"Unknown visual review tool: {name!r}.", versions, review_attempt)
                    continue
                decision_name = name
                decision_arguments = dict(arguments)
                if "summary" in decision_arguments:
                    decision_arguments["summary"] = _safe_review_text(
                        str(decision_arguments["summary"]), max_length=1000
                    )
                if "review_notes" in decision_arguments:
                    decision_arguments["review_notes"] = _safe_review_text(str(decision_arguments["review_notes"]))
                if "revision_instructions" in decision_arguments:
                    decision_arguments["revision_instructions"] = _safe_review_text(
                        str(decision_arguments["revision_instructions"])
                    )
                session.append(
                    {
                        "stage": "visual_review",
                        "version": versions,
                        "attempt": review_attempt,
                        "decision": name,
                        "review_notes": decision_arguments.get("review_notes", ""),
                        "summary": decision_arguments.get("summary", ""),
                        "revision_instructions": decision_arguments.get("revision_instructions", ""),
                    }
                )
                save_session()
                break

            if decision_arguments is None:
                return finish_failure(f"Visual review failed after 2 attempts: {review_error}")

            if decision_name == "approve_project_plan" and _report_valid(current_report):
                summary = str(decision_arguments["summary"]).strip()
                review_notes = str(decision_arguments["review_notes"])
                rundir.write_project_json("approved_plan.json", current_plan.to_dict())
                approved_image = rundir.save_project_image("approved_plan.png", current_image)
                emit(
                    "plan_approved",
                    version=versions,
                    path=str(rundir.project_path("approved_plan.json")),
                    image_path=str(approved_image),
                    summary=summary,
                    review_notes=review_notes,
                )
                save_session()
                return PlannerResult(True, current_plan, summary, review_notes, versions, usage, None)

            if decision_name == "approve_project_plan":
                revision_notes = (
                    "The visual reviewer requested approval, but local validation is authoritative and invalid. "
                    "Fix every validation error before approval.\n"
                    + json.dumps(report_payload, indent=2, sort_keys=True, ensure_ascii=False)
                )
                session.append(
                    {
                        "stage": "approval_overridden",
                        "version": versions,
                        "reason": "local_validation_invalid",
                    }
                )
            else:
                revision_notes = str(decision_arguments["revision_instructions"]).strip()

            save_session()
            if versions >= config.planner_max_iters:
                return finish_failure(f"No approved plan after {config.planner_max_iters} versions.")

        return finish_failure(f"No approved plan after {config.planner_max_iters} versions.")
    except Exception as error:
        return finish_failure(f"Planner failed: {type(error).__name__}: {error}")


def run_planner(
    prompt: str,
    llm: Any,
    config: ProjectConfig,
    rundir: ProjectRunDir,
    on_event: Any | None = None,
) -> PlannerResult:
    """Route Planner generation by explicit client capability, never by model name."""
    generate_plan_json = getattr(llm, "generate_plan_json", None)
    mode = getattr(llm, "plan_json_mode", None)
    supports_structured = getattr(llm, "supports_structured_plan_json", None)
    if (
        callable(generate_plan_json)
        and mode not in {PlanJSONMode.TOOL_CALL, PlanJSONMode.TOOL_CALL.value}
        and supports_structured is not False
    ):
        return _run_structured_planner(prompt, llm, config, rundir, on_event)
    return _run_tool_planner(prompt, llm, config, rundir, on_event)
