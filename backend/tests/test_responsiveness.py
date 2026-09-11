from __future__ import annotations

import asyncio
import threading

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from autoassist.app import create_app
from autoassist.config import Settings
from autoassist.inventory.records import InventoryFilters, InventoryPage


class BlockingInventoryService:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._started = started
        self._release = release

    def search(self, dealership_id: str, filters: InventoryFilters) -> InventoryPage:
        self._started.set()
        if not self._release.wait(timeout=2):
            raise TimeoutError("test did not release blocking database unit")
        return InventoryPage(items=(), next_after=None)


async def test_sync_inventory_unit_does_not_block_event_loop(
    application_settings: Settings,
) -> None:
    app = create_app(application_settings)
    started = threading.Event()
    release = threading.Event()
    async with LifespanManager(app):
        app.state.inventory_service = BlockingInventoryService(started, release)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            dealership_id = "00000000-0000-0000-0000-000000000001"
            request_task = asyncio.create_task(client.get(f"/dealerships/{dealership_id}/vehicles"))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                progressed = False

                async def unrelated_work() -> None:
                    nonlocal progressed
                    await asyncio.sleep(0)
                    progressed = True

                await unrelated_work()
                assert progressed
            finally:
                release.set()
            response = await request_task
            assert response.status_code == 200
