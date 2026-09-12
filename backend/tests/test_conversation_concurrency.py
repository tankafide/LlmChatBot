from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from conftest import write_config
from httpx import ASGITransport, AsyncClient

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunRequest, ChatRunResult
from autoassist.config import Settings
from autoassist.inventory.service import InventoryService


class GatedRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.started = asyncio.Event()
        self.four_started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, _request: ChatRunRequest) -> ChatRunResult:
        self.calls += 1
        self.active += 1
        self.started.set()
        if self.active == 4:
            self.four_started.set()
        try:
            await self.release.wait()
            return ChatRunResult(reply="Done", replay_json='{"messages_json":"[]"}')
        finally:
            self.active -= 1

    async def close(self) -> None:
        self.release.set()


async def test_four_turn_limit_has_no_queue_and_identity_wins_under_saturation(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'capacity.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    runner = GatedRunner()

    def factory(_model: str, _key: str, _inventory: InventoryService) -> GatedRunner:
        return runner

    app = create_app(settings, runner_factory=factory)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        dealership_id = next(
            item["id"]
            for item in (await client.get("/dealerships")).json()["items"]
            if item["slug"] == "mia-motors"
        )
        conversations = [
            (
                await client.post(
                    f"/dealerships/{dealership_id}/conversations",
                    json={"creation_id": str(uuid4())},
                )
            ).json()["id"]
            for _ in range(5)
        ]
        request_ids = [str(uuid4()) for _ in range(5)]

        async def submit(index: int):
            return await client.post(
                f"/dealerships/{dealership_id}/conversations/{conversations[index]}/messages",
                json={"request_id": request_ids[index], "text": f"request {index}"},
            )

        tasks = [asyncio.create_task(submit(index)) for index in range(4)]
        try:
            await asyncio.wait_for(runner.four_started.wait(), timeout=2)
            fifth = await submit(4)
            assert fifth.status_code == 503
            assert fifth.json()["error"]["code"] == "server_busy"

            replay_active = await client.post(
                f"/dealerships/{dealership_id}/conversations/{conversations[0]}/messages",
                json={"request_id": request_ids[0], "text": "request 0"},
            )
            assert replay_active.status_code == 202
            assert replay_active.json()["status"] == "in_progress"
            assert runner.calls == 4
        finally:
            runner.release.set()
        completed = await asyncio.gather(*tasks)
        assert all(response.status_code == 202 for response in completed)

        await app.state.conversation_service._limiter.wait_idle(5)
        retried_fifth = await submit(4)
        assert retried_fifth.status_code == 202
        await app.state.conversation_service._limiter.wait_idle(5)
        assert runner.calls == 5


async def test_cancellation_settles_interruption_and_releases_capacity(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'cancel.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    runner = GatedRunner()

    def factory(_model: str, _key: str, _inventory: InventoryService) -> GatedRunner:
        return runner

    app = create_app(settings, runner_factory=factory)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        dealership_id = next(
            item["id"]
            for item in (await client.get("/dealerships")).json()["items"]
            if item["slug"] == "mia-motors"
        )
        conversation_id = (
            await client.post(
                f"/dealerships/{dealership_id}/conversations", json={"creation_id": str(uuid4())}
            )
        ).json()["id"]
        request_id = str(uuid4())
        url = f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
        task = asyncio.create_task(
            client.post(url, json={"request_id": request_id, "text": "Cancel this turn"})
        )
        await asyncio.wait_for(runner.started.wait(), timeout=2)
        assert (await task).status_code == 202
        task = next(iter(app.state.conversation_service._tasks.values()))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        replay = await client.post(url, json={"request_id": request_id, "text": "Cancel this turn"})
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "request_interrupted"
        runner.release.set()
        next_request = await client.post(
            url,
            json={"request_id": str(uuid4()), "text": "A deliberate retry"},
        )
        assert next_request.status_code == 202
