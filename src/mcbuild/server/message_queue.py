"""Shared async message-pump helpers for build and project WebSocket sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

Send = Callable[[str], Awaitable[None]]


async def drain_messages(queue: asyncio.Queue[str], send: Send) -> None:
    """Send queued frames until cancelled, always balancing ``queue.get``."""

    while True:
        message = await queue.get()
        try:
            await send(message)
        finally:
            queue.task_done()


async def finish_message_drain(queue: asyncio.Queue[str], drain_task: asyncio.Task[None]) -> None:
    """Flush all frames or propagate a failed sender without deadlocking ``join``."""

    join_task = asyncio.create_task(queue.join())
    done, _pending = await asyncio.wait({join_task, drain_task}, return_when=asyncio.FIRST_COMPLETED)
    if drain_task in done:
        join_task.cancel()
        with suppress(asyncio.CancelledError):
            await join_task
        while not queue.empty():
            queue.get_nowait()
            queue.task_done()
        error = drain_task.exception()
        if error is not None:
            raise error
        raise ConnectionError("WebSocket message sender stopped before the queue was flushed")

    await join_task
    drain_task.cancel()
    with suppress(asyncio.CancelledError):
        await drain_task
