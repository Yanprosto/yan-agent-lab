"""Skill memory: local skills, committed seeds and latest-version lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcbuild.server import skill_store


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    local = tmp_path / "skills"
    seed = tmp_path / "seed"
    local.mkdir()
    seed.mkdir()
    monkeypatch.setattr(skill_store, "_skills_dir", lambda: local)
    monkeypatch.setattr(skill_store, "_seed_dir", lambda: seed)
    return local, seed


def _write(directory: Path, skill_id: str, marker: str) -> None:
    (directory / f"{skill_id}.json").write_text(json.dumps({"skill_id": skill_id, "marker": marker}))


def test_load_skill_falls_back_to_seed(stores):
    _local, seed = stores
    _write(seed, "family_v3", "seed")
    assert skill_store.load_skill("family_v3") == {"skill_id": "family_v3", "marker": "seed"}


def test_local_skill_wins_over_seed(stores):
    local, seed = stores
    _write(seed, "family_v3", "seed")
    _write(local, "family_v3", "local")
    skill = skill_store.load_skill("family_v3")
    assert skill is not None
    assert skill["marker"] == "local"


def test_load_latest_skill_picks_highest_version_across_stores(stores):
    local, seed = stores
    _write(local, "family_v2", "local")
    _write(seed, "family_v3", "seed")
    _write(local, "other_v9", "unrelated")
    skill, version = skill_store.load_latest_skill("family")
    assert version == 3
    assert skill is not None
    assert skill["marker"] == "seed"


def test_load_latest_skill_respects_min_version(stores):
    local, _seed = stores
    _write(local, "family_v2", "local")
    assert skill_store.load_latest_skill("family", min_version=3) == (None, 0)
    assert skill_store.load_latest_skill("family", min_version=2)[1] == 2


def test_repository_seed_has_evidence():
    seed = Path(skill_store.__file__).resolve().parents[3] / "yan_knowledge" / "seed"
    skills = sorted(seed.glob("*.json"))
    assert skills, "expected committed seed skills"
    for path in skills:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "VERIFIED"
        assert payload["evidence"]["level"] == "runtime_observed"
        assert payload["evidence"]["run_id"]
