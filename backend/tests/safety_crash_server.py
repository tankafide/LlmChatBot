"""Subprocess-only NHTSA wait gate; all transport is synthetic."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import httpx

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunRequest, ChatRunResult
from autoassist.integrations.nhtsa import LookupBudget, NhtsaClient
from autoassist.inventory.service import InventoryService
from autoassist.safety.service import SafetyRun, SafetyService


class SafetyCrashRunner:
    def __init__(self, inventory: InventoryService) -> None:
        self.inventory = inventory
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.wait))

    async def wait(self, _: httpx.Request) -> httpx.Response:
        Path(os.environ["AUTOASSIST_CRASH_MARKER"]).write_text("nhtsa-await")
        await asyncio.Event().wait()
        raise AssertionError("gate unexpectedly released")

    async def run(self, request: ChatRunRequest) -> ChatRunResult:
        assert request.selected_vehicle_id is not None
        vehicle = await asyncio.to_thread(
            self.inventory.get, request.dealership_id, request.selected_vehicle_id
        )
        await SafetyService(NhtsaClient(self.client)).recalls(
            vehicle, SafetyRun(LookupBudget(time.monotonic() + 60))
        )
        raise AssertionError("process should terminate during await")

    async def close(self) -> None:
        await self.client.aclose()


def factory(_model: str, _key: str, inventory: InventoryService) -> SafetyCrashRunner:
    return SafetyCrashRunner(inventory)


app = create_app(runner_factory=factory)
