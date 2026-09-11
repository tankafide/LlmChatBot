"""Owned async work and bounded process capacity for conversation turns."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress


async def finish_task[T](task: asyncio.Task[T]) -> T:
    """Drain owned work even if cancellation is repeated during cleanup."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def database_write[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with suppress(Exception):
            await finish_task(task)
        raise


class ActiveTurnLimiter:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._active = 0
        self._lock = asyncio.Lock()
        self._idle = asyncio.Event()
        self._idle.set()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._active >= self._limit:
                return False
            self._active += 1
            self._idle.clear()
            return True

    async def release(self) -> None:
        async with self._lock:
            self._active -= 1
            if self._active == 0:
                self._idle.set()

    async def wait_idle(self, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            await self._idle.wait()
