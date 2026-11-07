"""Persistent verified-skill memory for YAN Agent.

Skills are intentionally plain JSON so they survive chats, branches and model changes.
Only verified live-world results should be admitted here.

Two locations are searched:

- ``yan_knowledge/skills/``: skills this machine verified (git-ignored, written by runs);
- ``yan_knowledge/seed/``: committed baseline skills, each verified live and carrying its
  evidence, so a fresh checkout does not start without memory.

A local skill with the same id wins over the seed.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _skills_dir() -> Path:
    path = _project_root() / "yan_knowledge" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _seed_dir() -> Path:
    return _project_root() / "yan_knowledge" / "seed"


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
        "verified_at_utc": datetime.now(UTC).isoformat(),
    }
    path = _skills_dir() / f"{skill_id}.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def load_skill(skill_id: str) -> dict[str, Any] | None:
    for directory in (_skills_dir(), _seed_dir()):
        path = directory / f"{skill_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def list_skills() -> list[str]:
    ids = {path.stem for path in _skills_dir().glob("*.json")}
    if _seed_dir().is_dir():
        ids.update(path.stem for path in _seed_dir().glob("*.json"))
    return sorted(ids)


def load_latest_skill(family: str, *, min_version: int = 1) -> tuple[dict[str, Any] | None, int]:
    """Load the highest available ``<family>_v<N>`` skill with N >= min_version.

    Returns ``(skill, version)``, or ``(None, 0)`` when no matching version exists.
    """
    pattern = re.compile(rf"^{re.escape(family)}_v(\d+)$")
    versions = sorted(
        (int(match.group(1)) for skill_id in list_skills() if (match := pattern.match(skill_id))),
        reverse=True,
    )
    for version in versions:
        if version < min_version:
            break
        skill = load_skill(f"{family}_v{version}")
        if skill is not None:
            return skill, version
    return None, 0
