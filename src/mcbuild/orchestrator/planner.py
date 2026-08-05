"""Bounded, tool-driven planner loop for large Minecraft projects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mcbuild.llm.client import Usage, image_to_data_url
from mcbuild.orchestrator.models import ModelValidationError, ProjectConfig, ProjectPlan
from mcbuild.orchestrator.plan_render import render_plan
from mcbuild.orchestrator.prompts import (
    build_planner_review_prompt,
    build_planner_system_prompt,
    build_planner_user_prompt,
)
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.orchestrator.validator import PlanValidationReport, validate_project_plan

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
        "site": {"type": "object"},
        "style_bible": {"type": "object"},
        "work_packages": {"type": "array", "items": {"type": "object"}},
        "interfaces": {"type": "array", "items": {"type": "object"}},
    },
}


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
        if isinstance(value, dict):
            return {str(key): sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return _to_plain(value)

    return sanitize(messages)


def run_planner(
    prompt: str,
    llm: Any,
    config: ProjectConfig,
    rundir: ProjectRunDir,
    on_event: Any | None = None,
) -> PlannerResult:
    """Generate, validate, visually review, and explicitly approve one project plan.

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
