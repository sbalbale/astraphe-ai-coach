"""Fire-and-forget tasks that aren't garbage-collected mid-flight and don't fail silently."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

logger = logging.getLogger(__name__)

# The event loop only keeps weak references to tasks; without a strong reference a
# running task can be collected before it finishes.
_tasks: set[asyncio.Task] = set()


def _done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("background task %s failed", task.get_name(), exc_info=exc)


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro) if name is None else asyncio.create_task(coro, name=name)
    if isinstance(task, asyncio.Task):  # tests patch create_task with a mock
        _tasks.add(task)
        task.add_done_callback(_done)
    return task
