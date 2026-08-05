import json

from typer.testing import CliRunner

from mcbuild.config import Config
from mcbuild.orchestrator.cli import app
from mcbuild.orchestrator.fake import (
    FakeProjectPlannerLLM,
    fake_worker_llm_factory,
    fake_worker_runner,
)
from mcbuild.orchestrator.loop import run_project
from mcbuild.orchestrator.models import ProjectConfig
from mcbuild.orchestrator.run_dir import ProjectRunDir


def test_offline_project_runs_the_complete_pipeline(tmp_path):
    run_dir = ProjectRunDir.create("a small fortified settlement", base=tmp_path)
    config = ProjectConfig(
        worker_config=Config(max_iters=2, display="off", out_dir=str(tmp_path)),
        planner_model="offline-planner",
        planner_max_iters=2,
        max_components=4,
    )
    events: list[tuple[str, dict]] = []

    result = run_project(
        "a small fortified settlement",
        FakeProjectPlannerLLM(),
        fake_worker_llm_factory,
        config,
        run_dir,
        on_event=lambda event_type, data: events.append((event_type, data)),
        worker_runner=fake_worker_runner,
    )

    assert result.finished is True
    assert result.completed_packages == ["gatehouse", "tower_family"]
    assert result.failed_package is None
    assert result.grid is not None and len(result.grid) > 0
    assert (run_dir.root / "project" / "approved_plan.png").exists()
    assert (run_dir.root / "project" / "approved_plan.json").exists()
    assert (run_dir.root / "final.schem").exists()
    assert (run_dir.root / "project_result.json").exists()
    assert (run_dir.root / "components" / "01_gatehouse" / "worker_prompt.txt").exists()
    tower_prompt = (run_dir.root / "components" / "02_tower_family" / "worker_prompt.txt").read_text()
    assert all(anchor in tower_prompt for anchor in ("-10", "10", "12"))
    assert "shared blueprint helper" in tower_prompt

    event_types = [event_type for event_type, _ in events]
    assert event_types.count("component_merged") == 2
    assert event_types[-1] == "project_finish"
    merged_ids = [data["package_id"] for event_type, data in events if event_type == "component_merged"]
    assert merged_ids == ["gatehouse", "tower_family"]

    saved = json.loads((run_dir.root / "project_result.json").read_text())
    assert saved["finished"] is True
    assert saved["grid"]["block_count"] == len(result.grid)
    event_log = (run_dir.root / "project_events.jsonl").read_text()
    assert "VoxelGrid" not in event_log


def test_project_cli_fake_llm_is_offline_and_exports(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "a small fortified settlement",
            "--fake-llm",
            "--display",
            "off",
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "final.schem").exists()
    assert (run_dirs[0] / "project" / "approved_plan.png").exists()
    assert "Exported:" in result.output
