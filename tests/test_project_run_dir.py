import json
from pathlib import Path

import pytest
from PIL import Image

from mcbuild.orchestrator.run_dir import ProjectRunDir


def test_project_run_dir_creates_expected_isolated_layout(tmp_path):
    rundir = ProjectRunDir.create("A fortified town", base=tmp_path)

    assert rundir.root.parent == tmp_path
    assert (rundir.root / "prompt.txt").read_text(encoding="utf-8") == "A fortified town"

    first = rundir.component_rundir(1, "gatehouse")
    second = rundir.component_rundir(2, "tower_family")
    first.write_json("session.json", {"worker": 1})
    second.write_json("session.json", {"worker": 2})

    assert first.root != second.root
    assert json.loads((first.root / "session.json").read_text(encoding="utf-8")) == {"worker": 1}
    assert json.loads((second.root / "session.json").read_text(encoding="utf-8")) == {"worker": 2}
    assert rundir.merge_report_path(1).name == "component_01.json"
    assert rundir.project_path("plan_v01.json").parent.name == "project"


@pytest.mark.parametrize(
    "operation",
    [
        lambda rundir: rundir.path("../escape.json"),
        lambda rundir: rundir.project_path("../../escape.json"),
        lambda rundir: rundir.component_dir(1, "../escape"),
        lambda rundir: rundir.component_dir(1, "UPPERCASE"),
        lambda rundir: rundir.component_dir(0, "valid_id"),
        lambda rundir: rundir.merge_report_path(0),
    ],
)
def test_project_run_dir_rejects_unsafe_paths_and_ids(tmp_path, operation):
    rundir = ProjectRunDir(tmp_path / "run")
    with pytest.raises(ValueError):
        operation(rundir)


def test_project_run_dir_json_is_strict_and_image_is_png(tmp_path):
    rundir = ProjectRunDir(tmp_path / "run")
    with pytest.raises(TypeError):
        rundir.write_json("bad.json", {"path": Path("not-json")})

    image = Image.new("RGB", (4, 3), (20, 30, 40))
    path = rundir.save_project_image("plan.png", image)
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_project_run_dir_create_avoids_same_second_collisions(tmp_path, monkeypatch):
    monkeypatch.setattr("mcbuild.orchestrator.run_dir.time.strftime", lambda _format: "20260101-010101")
    first = ProjectRunDir.create("same prompt", base=tmp_path)
    second = ProjectRunDir.create("same prompt", base=tmp_path)
    assert first.root.name == "20260101-010101-same-prompt"
    assert second.root.name == "20260101-010101-same-prompt-02"
