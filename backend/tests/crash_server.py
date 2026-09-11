from __future__ import annotations

import asyncio
import os
from pathlib import Path

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunRequest, ChatRunResult
from autoassist.inventory.service import InventoryService


class CrashGateRunner:
    async def run(self, _request: ChatRunRequest) -> ChatRunResult:
        Path(os.environ["AUTOASSIST_CRASH_MARKER"]).write_text("admitted", encoding="utf-8")
        await asyncio.Event().wait()
        raise AssertionError("crash gate was unexpectedly released")

    async def close(self) -> None:
        return None


def runner_factory(
    _model_name: str, _api_key: str, _inventory: InventoryService
) -> CrashGateRunner:
    return CrashGateRunner()


app = create_app(runner_factory=runner_factory)
