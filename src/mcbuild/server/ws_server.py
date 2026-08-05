"""WebSocket server entry point for single builds and multi-component projects."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json

from dotenv import load_dotenv
from websockets.asyncio.server import ServerConnection, serve

from mcbuild.config import Config
from mcbuild.server import protocol
from mcbuild.server.project_session import run_project_session
from mcbuild.server.session import run_build_session

# Only one task runs at a time in this version; a second connection while a task is in
# flight is rejected outright rather than queued.
_task_in_progress = False


async def _handler(connection: ServerConnection, config: Config) -> None:
    global _task_in_progress

    raw = await connection.recv()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        await connection.send(protocol.error("Malformed request: expected JSON."))
        return

    command = request.get("cmd")
    prompt = request.get("prompt")
    if command not in {"build", "project"} or not isinstance(prompt, str) or not prompt.strip():
        await connection.send(protocol.error('Expected {"cmd": "build|project", "prompt": "..."}.'))
        return

    if _task_in_progress:
        await connection.send(protocol.error("A build is already in progress; try again shortly."))
        return

    _task_in_progress = True
    try:
        if command == "build":
            await run_build_session(prompt, connection.send, config=config)
        else:
            await run_project_session(prompt, connection.send, config=config)
    finally:
        _task_in_progress = False


async def _serve(host: str, port: int, config: Config) -> None:
    handler = functools.partial(_handler, config=config)
    async with serve(handler, host, port) as server:
        print(f"mcbuild server listening on ws://{host}:{port} (model={config.model})")
        await server.serve_forever()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="mcbuild live-build WebSocket server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=Config.model, help="Vision-capable OpenRouter model id.")
    parser.add_argument("--max-iters", type=int, default=Config.max_iters)
    parser.add_argument("--reasoning", default=Config.reasoning, help="off|low|medium|high")
    parser.add_argument(
        "--cost-ceiling",
        type=float,
        default=None,
        help="Abort a build (keeping its best build so far) once usage cost reaches this many USD.",
    )
    args = parser.parse_args()

    config = Config(
        model=args.model,
        max_iters=args.max_iters,
        reasoning=args.reasoning,
        cost_ceiling=args.cost_ceiling,
    )
    asyncio.run(_serve(args.host, args.port, config))


if __name__ == "__main__":
    main()
