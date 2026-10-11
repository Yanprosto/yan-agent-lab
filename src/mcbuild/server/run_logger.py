"""Structured runtime logging + Git publisher for YAN Agent.

Every live websocket session can emit machine-readable artifacts locally and publish them
into a separate Git repository. Publishing failures never change the experiment verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from typing import Any


DEFAULT_REMOTE = "https://github.com/Yanprosto/yan-runtime-logs.git"
DEFAULT_BRANCH = "main"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:48] or "run"


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def _run_git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


@dataclass
class RunRecorder:
    command: str
    prompt: str = ""
    run_id: str = field(init=False)
    started_at_utc: str = field(default_factory=_utc_now)
    events: list[dict[str, Any]] = field(default_factory=list)
    verdict: dict[str, Any] = field(default_factory=dict)
    finished_at_utc: str | None = None

    def __post_init__(self) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}_{_safe_slug(self.command)}_{uuid.uuid4().hex[:8]}"
        self.record("RUN_START", command=self.command, prompt=self.prompt)

    def record(self, event: str, **payload: Any) -> None:
        row = {"ts_utc": _utc_now(), "event": event}
        row.update(payload)
        self.events.append(row)

    def observe_wire(self, direction: str, raw: Any) -> None:
        if not isinstance(raw, str):
            self.record("WIRE", direction=direction, raw_type=type(raw).__name__)
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            self.record("WIRE_TEXT", direction=direction, text=raw)
            return

        msg_type = str(msg.get("type") or "unknown")
        if msg_type == "action":
            self.record(
                "ACTION",
                direction=direction,
                id=msg.get("id"),
                action=msg.get("action"),
                args=msg.get("args") or {},
            )
        elif msg_type == "observation":
            self.record(
                "OBSERVATION",
                direction=direction,
                id=msg.get("id"),
                ok=bool(msg.get("ok", False)),
                result=msg.get("result"),
                error=msg.get("error"),
            )
        elif msg_type == "chat":
            self.record("CHAT", direction=direction, text=msg.get("text"))
        elif msg_type == "finish":
            summary = str(msg.get("summary") or "")
            self.verdict = {
                "pass": True,
                "status": "PASS",
                "summary": summary,
            }
            self.record("FINISH", direction=direction, summary=summary)
        elif msg_type == "error":
            reason = str(msg.get("reason") or "")
            self.verdict = {
                "pass": False,
                "status": "FAIL",
                "reason": reason,
            }
            self.record("ERROR", direction=direction, reason=reason)
        elif msg_type == "blocks":
            changes = msg.get("changes") or []
            self.record(
                "BLOCKS",
                direction=direction,
                iteration=msg.get("iteration"),
                change_count=len(changes),
            )
        else:
            self.record("WIRE_JSON", direction=direction, message=msg)

    def fail_from_exception(self, exc: BaseException) -> None:
        if not self.verdict:
            self.verdict = {
                "pass": False,
                "status": "EXCEPTION",
                "reason": f"{exc.__class__.__name__}: {exc}",
            }
        self.record("EXCEPTION", error=f"{exc.__class__.__name__}: {exc}")

    def finalize_local(self) -> Path:
        if self.finished_at_utc is None:
            self.finished_at_utc = _utc_now()
        if not self.verdict:
            self.verdict = {
                "pass": None,
                "status": "UNKNOWN",
                "reason": "session ended without finish/error message",
            }
        self.record("RUN_END", verdict=self.verdict)

        root = _project_root() / ".yan_runtime_runs"
        run_dir = root / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        run_payload = {
            "run_id": self.run_id,
            "command": self.command,
            "prompt": self.prompt,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "event_count": len(self.events),
        }
        _json_dump(run_dir / "run.json", run_payload)
        _json_dump(run_dir / "verdict.json", self.verdict)
        (run_dir / "events.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in self.events),
            encoding="utf-8",
        )
        return run_dir

    def finalize_and_publish(self) -> dict[str, Any]:
        run_dir = self.finalize_local()
        if os.getenv("YAN_RUNTIME_LOGS_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
            return {"published": False, "reason": "disabled", "run_dir": str(run_dir)}

        try:
            published = _publish_to_git(run_dir, self.run_id)
            published["run_dir"] = str(run_dir)
            return published
        except Exception as exc:  # publishing must never break an experiment
            return {
                "published": False,
                "reason": f"{exc.__class__.__name__}: {exc}",
                "run_dir": str(run_dir),
            }


class LoggedConnection:
    """Small proxy around websockets ServerConnection that records JSON wire traffic."""

    def __init__(self, inner: Any, recorder: RunRecorder):
        self._inner = inner
        self._recorder = recorder

    async def send(self, data: Any) -> Any:
        self._recorder.observe_wire("server_to_minecraft", data)
        return await self._inner.send(data)

    async def recv(self, *args: Any, **kwargs: Any) -> Any:
        data = await self._inner.recv(*args, **kwargs)
        self._recorder.observe_wire("minecraft_to_server", data)
        return data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _prepare_logs_checkout() -> tuple[Path, str]:
    root = _project_root()
    checkout = Path(os.getenv("YAN_RUNTIME_LOGS_DIR", str(root / ".yan_runtime_logs_repo")))
    remote = os.getenv("YAN_RUNTIME_LOGS_REPO", DEFAULT_REMOTE)
    branch = os.getenv("YAN_RUNTIME_LOGS_BRANCH", DEFAULT_BRANCH)

    if not (checkout / ".git").exists():
        if checkout.exists():
            shutil.rmtree(checkout)
        checkout.parent.mkdir(parents=True, exist_ok=True)
        clone = subprocess.run(
            ["git", "clone", remote, str(checkout)],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed: {clone.stderr.strip() or clone.stdout.strip()}")

    # Ensure this checkout points to the configured runtime-log repository.
    current_remote = _run_git(["remote", "get-url", "origin"], cwd=checkout).stdout.strip()
    if current_remote != remote:
        _run_git(["remote", "set-url", "origin", remote], cwd=checkout)

    _run_git(["fetch", "origin", branch], cwd=checkout)
    local_branch = _run_git(["branch", "--show-current"], cwd=checkout).stdout.strip()
    if local_branch != branch:
        checkout_result = _run_git(["checkout", branch], cwd=checkout, check=False)
        if checkout_result.returncode != 0:
            _run_git(["checkout", "-B", branch, f"origin/{branch}"], cwd=checkout)

    _run_git(["reset", "--hard", f"origin/{branch}"], cwd=checkout)
    return checkout, branch


def _publish_to_git(run_dir: Path, run_id: str) -> dict[str, Any]:
    checkout, branch = _prepare_logs_checkout()

    dest = checkout / "runs" / run_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(run_dir, dest)

    latest = checkout / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(run_dir, latest)

    _run_git(["config", "user.name", "YAN Agent Runtime"], cwd=checkout)
    _run_git(["config", "user.email", "yan-agent-runtime@local"], cwd=checkout)
    _run_git(["add", "runs", "latest"], cwd=checkout)

    status = _run_git(["status", "--porcelain"], cwd=checkout).stdout.strip()
    if not status:
        return {"published": True, "branch": branch, "commit": None, "reason": "no changes"}

    _run_git(["commit", "-m", f"runtime: {run_id}"], cwd=checkout)
    push = _run_git(["push", "origin", branch], cwd=checkout, check=False)
    if push.returncode != 0:
        # One retry after rebasing in case another writer pushed between fetch and push.
        _run_git(["pull", "--rebase", "origin", branch], cwd=checkout)
        push = _run_git(["push", "origin", branch], cwd=checkout, check=False)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip() or push.stdout.strip()}")

    commit = _run_git(["rev-parse", "HEAD"], cwd=checkout).stdout.strip()
    return {"published": True, "branch": branch, "commit": commit}
