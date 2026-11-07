import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcbuild.server import iron_works_session as session
from mcbuild.server.industrial_build_plan import compile_industrial_plan
from mcbuild.server.industrial_planner import generate_iron_works_candidates, rank_iron_works_candidates


@pytest.mark.parametrize("candidate", generate_iron_works_candidates(), ids=lambda c: c.id)
def test_real_session_consumes_selected_plan(candidate, monkeypatch):
    plan = compile_industrial_plan(candidate)
    built = []

    async def build(connection, layout, stage, **kwargs):
        built.append((layout, stage))

    monkeypatch.setattr(session, "rank_iron_works_candidates", lambda **kw: [candidate])
    monkeypatch.setattr(session, "select_build_plan", AsyncMock(return_value=plan))
    monkeypatch.setattr(session, "_build_stage_cell", build)
    for name in ("_verify_power", "_seed_material", "_configure_transporter_pull", "_wait_stage_output"):
        monkeypatch.setattr(session, name, AsyncMock(return_value={}))

    async def count(connection, label, pos, item):
        return (candidate.final_output // candidate.smelting_cells if label.endswith("-final") else 0), {}

    monkeypatch.setattr(session, "_item_count", count)
    monkeypatch.setattr(session, "_read_transit", AsyncMock(return_value={"total_items": 0}))
    monkeypatch.setattr(session, "save_skill", lambda *a, **kw: Path("skill.json"))
    connection = AsyncMock()
    asyncio.run(session.run_iron_works_session("iron works", connection))
    assert len(built) * 2 == candidate.machine_count
    assert sum(s.machine_block.endswith("enrichment_chamber") for _, s in built) == candidate.enrichment_cells
    assert {layout.smelter_a for layout, _ in built} == {c.layout.smelter_a for c in plan.cells}
    assert json.loads(connection.send.call_args.args[0])["type"] == "finish"


def test_compiler_rejects_bad_balance_and_overlap():
    candidate = generate_iron_works_candidates()[1]
    with pytest.raises(ValueError):
        compile_industrial_plan(replace(candidate, final_output=47))
    with pytest.raises(ValueError):
        compile_industrial_plan(candidate, spacing=4)


def test_handoffs_and_distinct_geometry():
    plans = [compile_industrial_plan(c) for c in generate_iron_works_candidates()]
    assert len({frozenset(p.footprint) for p in plans}) == 6
    for plan in plans:
        by_id = {c.id: c for c in plan.cells}
        for c in plan.cells:
            if c.upstream:
                assert c.layout.source == by_id[c.upstream].layout.sink


def test_goal_changes_selection():
    assert rank_iron_works_candidates(goal="железный завод компактный")[0].smelting_cells == 1
    assert all(c.direct_smelting for c in rank_iron_works_candidates(goal="железный завод прямая плавка"))


def test_site_fallback_and_incomplete_observation(monkeypatch):
    candidate = generate_iron_works_candidates()[0]
    calls = []

    async def action(connection, label, action, args):
        calls.append(args)
        if len(calls) == 1:
            return {"blocks": []}
        return {"blocks": [{**p, "is_air": True} for p in args["positions"]]}

    monkeypatch.setattr(session, "_action", action)
    plan = asyncio.run(session.select_build_plan(AsyncMock(), [candidate]))
    assert len(calls) == 2
    assert plan.cells[0].layout.shift_z == 30


def test_no_rollback_before_placement(monkeypatch):
    monkeypatch.setattr(session, "select_build_plan", AsyncMock(side_effect=RuntimeError("occupied")))
    action = AsyncMock()
    monkeypatch.setattr(session, "_action", action)
    asyncio.run(session.run_iron_works_session("iron works", AsyncMock()))
    action.assert_not_called()


def test_production_starts_all_roots_before_waiting(monkeypatch):
    candidate = next(c for c in generate_iron_works_candidates() if c.id == "enriched_3_lanes")
    plan = compile_industrial_plan(candidate)
    events = []
    monkeypatch.setattr(session, "select_build_plan", AsyncMock(return_value=plan))
    monkeypatch.setattr(session, "_build_stage_cell", AsyncMock())
    monkeypatch.setattr(session, "_verify_power", AsyncMock(return_value={}))

    async def seed(connection, pos, item, count, label):
        events.append(("seed", label.removesuffix("-seed")))

    async def pull(connection, label, pos, side):
        events.append(("open", label.split("-handoff")[0]))

    async def wait(connection, layout, stage, **kwargs):
        assert kwargs["check_before_wait"]
        events.append(("verified", stage.id))
        return {}

    monkeypatch.setattr(session, "_seed_material", seed)
    monkeypatch.setattr(session, "_configure_transporter_pull", pull)
    monkeypatch.setattr(session, "_wait_stage_output", wait)

    async def count(connection, label, pos, item):
        return (24 if label.endswith("-final") else 0), {}

    monkeypatch.setattr(session, "_item_count", count)
    monkeypatch.setattr(session, "_read_transit", AsyncMock(return_value={"total_items": 0}))
    monkeypatch.setattr(session, "save_skill", lambda *a, **kw: Path("skill.json"))
    asyncio.run(session.run_iron_works_session("iron works", AsyncMock()))
    assert [kind for kind, _ in events[:3]] == ["seed"] * 3
    first_open = next(i for i, (kind, _) in enumerate(events) if kind == "open")
    assert sum(kind == "verified" for kind, _ in events[:first_open]) == 3
    first_smelt_verify = next(i for i, (kind, name) in enumerate(events) if kind == "verified" and "smelt" in name)
    assert sum(kind == "open" for kind, _ in events[:first_smelt_verify]) == 6
