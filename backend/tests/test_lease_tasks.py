import asyncio
from threading import Event

import pytest

from autoassist.conversations.leases import renew_owner, stop_task, sweep_stale


@pytest.mark.asyncio
async def test_renewal_repeats_and_stops_when_ownership_is_lost(monkeypatch):
    monkeypatch.setattr("autoassist.conversations.leases.RENEW_INTERVAL_SECONDS", 0)

    class Store:
        calls = 0

        def renew_lease(self, internal_id):
            assert internal_id == "owned-request"
            self.calls += 1
            return self.calls < 3

    store = Store()
    await asyncio.wait_for(renew_owner(store, "owned-request"), timeout=3)
    assert store.calls == 3


@pytest.mark.asyncio
async def test_sweeper_recovers_without_submission_and_drains_cancelled_write(monkeypatch):
    monkeypatch.setattr("autoassist.conversations.leases.SWEEP_INTERVAL_SECONDS", 0)
    entered, release, exited = Event(), Event(), Event()

    class Store:
        def recover_interrupted(self):
            entered.set()
            assert release.wait(3)
            exited.set()
            return 1

    task = asyncio.create_task(sweep_stale(Store()))
    stopper = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        stopper = asyncio.create_task(stop_task(task))
        await asyncio.sleep(0)
        assert not stopper.done()
    finally:
        release.set()
        if stopper is not None:
            await asyncio.wait_for(stopper, 3)
        else:
            await stop_task(task)
    assert exited.is_set()
