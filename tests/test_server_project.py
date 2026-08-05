import asyncio
import json
from typing import cast

import pytest
from websockets.asyncio.server import ServerConnection

from mcbuild.config import Config
from mcbuild.llm.client import Usage
from mcbuild.orchestrator.fake import fake_project_plan
from mcbuild.orchestrator.models import ProjectResult
from mcbuild.palette import get_block
from mcbuild.server import project_session, ws_server
from mcbuild.voxel import VoxelGrid


class _Connection:
    def __init__(self, request: dict):
        self.request = json.dumps(request)
        self.sent: list[str] = []

    async def recv(self):
        return self.request

    async def send(self, message: str):
        self.sent.append(message)


def test_ws_handler_preserves_build_and_dispatches_project(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_build(prompt, send, config):
        del send, config
        calls.append(("build", prompt))

    async def fake_project(prompt, send, config):
        del send, config
        calls.append(("project", prompt))

    monkeypatch.setattr(ws_server, "run_build_session", fake_build)
    monkeypatch.setattr(ws_server, "run_project_session", fake_project)
    ws_server._task_in_progress = False

    build_connection = _Connection({"cmd": "build", "prompt": "a tower"})
    asyncio.run(ws_server._handler(cast(ServerConnection, build_connection), Config()))
    project_connection = _Connection({"cmd": "project", "prompt": "a town"})
    asyncio.run(ws_server._handler(cast(ServerConnection, project_connection), Config()))

    assert calls == [("build", "a tower"), ("project", "a town")]
    assert build_connection.sent == []
    assert project_connection.sent == []


def test_ws_handler_shared_lock_covers_both_commands():
    ws_server._task_in_progress = True
    connection = _Connection({"cmd": "project", "prompt": "a town"})
    try:
        asyncio.run(ws_server._handler(cast(ServerConnection, connection), Config()))
    finally:
        ws_server._task_in_progress = False

    response = json.loads(connection.sent[0])
    assert response["type"] == "error"
    assert "already in progress" in response["reason"]


def test_ws_handler_releases_shared_lock_when_session_fails(monkeypatch):
    async def failing_project(prompt, send, config):
        del prompt, send, config
        raise ConnectionError("client disconnected")

    monkeypatch.setattr(ws_server, "run_project_session", failing_project)
    ws_server._task_in_progress = False
    connection = _Connection({"cmd": "project", "prompt": "a town"})

    with pytest.raises(ConnectionError, match="client disconnected"):
        asyncio.run(ws_server._handler(cast(ServerConnection, connection), Config()))

    assert ws_server._task_in_progress is False


def test_project_session_streams_component_deltas_without_reasoning(monkeypatch, tmp_path):
    plan = fake_project_plan()
    first = VoxelGrid()
    first.set(0, 0, 0, get_block("stone").index)
    second = first.clone()
    second.set(1, 0, 0, get_block("dirt").index)

    class FakeClient:
        pass

    monkeypatch.setattr(project_session, "OpenRouterClient", FakeClient)

    def fake_run_project(prompt, planner_llm, worker_factory, config, rundir, on_event):
        del prompt, planner_llm, worker_factory, config, rundir
        on_event("plan_submitted", {"version": 1})
        on_event("component_start", {"index": 1, "total": 2, "package_id": "gatehouse"})
        on_event(
            "component_worker_event",
            {"worker_event": "reasoning", "data": {"text": "SECRET REASONING"}},
        )
        on_event(
            "component_merged",
            {"index": 1, "total": 2, "package_id": "gatehouse", "block_count": 1, "grid": first},
        )
        on_event("component_start", {"index": 2, "total": 2, "package_id": "tower_family"})
        on_event(
            "component_merged",
            {"index": 2, "total": 2, "package_id": "tower_family", "block_count": 2, "grid": second},
        )
        return ProjectResult(True, "done", plan, second, ["gatehouse", "tower_family"], None, [], Usage())

    monkeypatch.setattr(project_session, "run_project", fake_run_project)
    sent: list[str] = []

    async def send(message: str):
        sent.append(message)

    asyncio.run(
        project_session.run_project_session(
            "a town",
            send,
            config=Config(out_dir=str(tmp_path)),
        )
    )

    messages = [json.loads(message) for message in sent]
    assert [message["iteration"] for message in messages if message["type"] == "blocks"] == [1, 2]
    assert messages[-1]["type"] == "finish"
    assert "SECRET REASONING" not in "\n".join(sent)


def test_project_session_sends_error_when_client_initialization_fails(monkeypatch, tmp_path):
    class MissingKeyClient:
        def __init__(self):
            raise RuntimeError("missing test API key")

    monkeypatch.setattr(project_session, "OpenRouterClient", MissingKeyClient)
    sent: list[str] = []

    async def send(message: str):
        sent.append(message)

    asyncio.run(project_session.run_project_session("a town", send, config=Config(out_dir=str(tmp_path))))

    messages = [json.loads(message) for message in sent]
    assert [message["type"] for message in messages] == ["hello", "error"]
    assert messages[-1]["reason"] == "missing test API key"


def test_project_session_sender_failure_does_not_deadlock(monkeypatch, tmp_path):
    class MissingKeyClient:
        def __init__(self):
            raise RuntimeError("missing test API key")

    monkeypatch.setattr(project_session, "OpenRouterClient", MissingKeyClient)

    async def send(message: str):
        del message
        raise ConnectionError("client disconnected")

    async def run():
        with pytest.raises(ConnectionError, match="client disconnected"):
            await asyncio.wait_for(
                project_session.run_project_session(
                    "a town",
                    send,
                    config=Config(out_dir=str(tmp_path)),
                ),
                timeout=1,
            )

    asyncio.run(run())
