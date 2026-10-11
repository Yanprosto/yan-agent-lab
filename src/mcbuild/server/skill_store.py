"""Persistent verified-skill memory for YAN Agent.

Skills are intentionally plain JSON so they survive chats, branches and model changes.
Only verified live-world results should be admitted here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _skills_dir() -> Path:
    path = _project_root() / "yan_knowledge" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_skill(
    skill_id: str,
    *,
    description: str,
    implementation: dict[str, Any],
    verification: dict[str, Any],
    source_experiment: str,
) -> Path:
    payload = {
        "skill_id": skill_id,
        "status": "VERIFIED",
        "description": description,
        "implementation": implementation,
        "verification": verification,
        "source_experiment": source_experiment,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = _skills_dir() / f"{skill_id}.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def load_skill(skill_id: str) -> dict[str, Any] | None:
    path = _skills_dir() / f"{skill_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_skills() -> list[str]:
    return sorted(path.stem for path in _skills_dir().glob("*.json"))
