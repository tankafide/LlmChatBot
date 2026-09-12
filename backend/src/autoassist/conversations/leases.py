"""Bounded background recovery and renewal; database units own their sessions."""

import asyncio
from contextlib import suppress

from autoassist.conversations.execution import database_write
from autoassist.conversations.store import ConversationStore
from autoassist.observability import event

RENEW_INTERVAL_SECONDS = 20.0
SWEEP_INTERVAL_SECONDS = 30.0


async def renew_owner(store: ConversationStore, internal_id: str) -> None:
    while True:
        await asyncio.sleep(RENEW_INTERVAL_SECONDS)
        try:
            renewed = await database_write(store.renew_lease, internal_id)
        except Exception:
            event("lease_renewal", outcome="storage_error")
            # Do not extend ownership locally. The database lease remains authoritative.
            continue
        if not renewed:
            event("lease_renewal", outcome="ownership_lost")
            return
        event("lease_renewal", outcome="renewed")


async def sweep_stale(store: ConversationStore) -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await database_write(store.recover_interrupted)
        except Exception:
            event("stale_recovery", outcome="storage_error")


async def stop_task(task: asyncio.Task[None] | None) -> None:
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
