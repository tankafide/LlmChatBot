"""Owned async work and bounded process capacity for conversation turns."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress


async def finish_task[T](task: asyncio.Task[T]) -> T:
    """Await owned work despite repeated caller cancellation, then return its result. If the owned
    task itself failed or was cancelled, task.result propagates that outcome.

    Used in cancellation cleanup when owned work must finish before its outcome is known.

    Drain owned work even if cancellation is repeated during cleanup.
    """
    # shield prevents cancellation of this await from cancelling owned work. Repeat
    # until it finishes even if shutdown delivers cancellation more than once.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def database_write[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a synchronous unit in a worker thread and return its result. On caller cancellation,
    drain the write before re-raising; ordinary unit errors propagate.

    Used by conversation and lease code to offload a complete synchronous write unit.
    """
    # Offload the whole synchronous transaction, including session creation/close.
    # Keep a task handle: cancelling an await cannot stop a database worker thread.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    # Wait for the write to settle before propagating cancellation. Otherwise
    # cleanup could race a commit whose outcome the caller has not yet observed.
    except asyncio.CancelledError:
        with suppress(Exception):
            await finish_task(task)
        raise


class ActiveTurnLimiter:
    """Bound concurrent owned turns in one server process.

    Admission acquires capacity and exactly one owner releases it; an idle event supports
    graceful shutdown. Database constraints separately coordinate each conversation across
    workers.
    """

    def __init__(self, limit: int) -> None:
        """Initialize a process-local slot counter, lock, and idle event. Return None; initially
        all capacity is available.

        Constructed by ConversationService once per process.
        """
        self._limit = limit
        self._active = 0
        self._lock = asyncio.Lock()
        self._idle = asyncio.Event()
        self._idle.set()

    async def try_acquire(self) -> bool:
        """Return True after reserving a slot or False when full. The check and increment are
        atomic under the async lock; this does not wait for free capacity.

        Called before new request admission.
        """
        # Check and increment under one async lock so concurrent admissions cannot
        # all observe the same available slot.
        async with self._lock:
            if self._active >= self._limit:
                return False
            self._active += 1
            self._idle.clear()
            return True

    async def release(self) -> None:
        """Return one acquired slot and signal idle when the count reaches zero. Return None;
        callers must release exactly once per successful acquisition.

        Called by admission cleanup or execution cleanup, according to which owns the slot.
        """
        async with self._lock:
            self._active -= 1
            # The idle event supports a bounded graceful shutdown wait without polling.
            if self._active == 0:
                self._idle.set()

    async def wait_idle(self, timeout: float) -> None:
        """Wait for all acquired slots to be released. Return None when idle, or raise TimeoutError
        after the supplied duration.

        Called during graceful shutdown before forced cancellation.
        """
        async with asyncio.timeout(timeout):
            await self._idle.wait()
