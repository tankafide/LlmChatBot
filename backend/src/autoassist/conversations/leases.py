"""Bounded background recovery and renewal; database units own their sessions."""

import asyncio
from contextlib import suppress

from autoassist.conversations.execution import database_write
from autoassist.conversations.store import ConversationStore
from autoassist.observability import event

RENEW_INTERVAL_SECONDS = 20.0
SWEEP_INTERVAL_SECONDS = 30.0


async def renew_owner(store: ConversationStore, internal_id: str) -> None:
    """The executing turn runs this heartbeat alongside provider work. Ownership lives in a
    database-clock lease, not in this task or a local timestamp. Periodically renew one active
    request lease. Return None when renewal says ownership is lost; storage errors are logged
    and retried, cancellation propagates.

    Launched alongside an owned turn when leases are enabled.
    """
    while True:
        await asyncio.sleep(RENEW_INTERVAL_SECONDS)
        try:
            renewed = await database_write(store.renew_lease, internal_id)
        except Exception:
            event("lease_renewal", outcome="storage_error")
            # Do not extend ownership locally. The database lease remains authoritative.
            continue
        # A failed conditional renewal means the request expired or became terminal.
        # Stop renewing; this helper does not cancel the model task. Terminal row locking
        # in the store prevents late completion from overwriting a recovered outcome.
        if not renewed:
            event("lease_renewal", outcome="ownership_lost")
            return
        event("lease_renewal", outcome="renewed")


async def sweep_stale(store: ConversationStore) -> None:
    """Each worker periodically recovers a bounded batch of expired requests. The repository uses
    skip-locked rows so sweepers can coexist across workers. Keep sweeping bounded expired
    batches until cancelled. There is no normal return; storage errors are logged and the next
    interval retries.

    Launched at startup once per worker when leases are enabled.
    """
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await database_write(store.recover_interrupted)
        # A temporary storage failure does not kill the sweep loop; a later interval
        # can try again without pretending the current recovery succeeded.
        except Exception:
            event("stale_recovery", outcome="storage_error")


async def stop_task(task: asyncio.Task[None] | None) -> None:
    """Cancel and await background cleanup before disposing the resources it uses. Cancel and await
    a background task, swallowing its cancellation. Return None (also for no task); other task
    exceptions propagate.

    Called to stop the execution heartbeat or the lifespan sweeper.
    """
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
