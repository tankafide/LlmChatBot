from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from conftest import write_config
from fastapi.testclient import TestClient
from turn_client import post_and_wait

from autoassist.app import create_app
from autoassist.chat.contracts import ChatProviderError, ChatRunRequest, ChatRunResult
from autoassist.config import Settings
from autoassist.db.models import Vehicle
from autoassist.inventory.records import normalize_text
from autoassist.inventory.service import InventoryService


class FakeRunner:
    def __init__(self, result: ChatRunResult | None = None, error: Exception | None = None) -> None:
        self.result = result or ChatRunResult(reply="Inventory reply", replay_json="{}")
        self.error = error
        self.requests: list[ChatRunRequest] = []
        self.closed = False

    async def run(self, request: ChatRunRequest) -> ChatRunResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result

    async def close(self) -> None:
        self.closed = True


def factory_for(runner: FakeRunner) -> Callable[[str, str, InventoryService], FakeRunner]:
    def factory(_model: str, _api_key: str, _inventory: InventoryService) -> FakeRunner:
        return runner

    return factory


def mia_dealership_id(client: TestClient) -> str:
    items = client.get("/dealerships").json()["items"]
    return next(item["id"] for item in items if item["slug"] == "mia-motors")


def add_vehicle(app: Any, dealership_id: str, source_id: str = "MIA-001") -> str:
    vehicle_id = str(uuid4())
    with app.state.session_factory.begin() as session:
        session.add(
            Vehicle(
                id=vehicle_id,
                dealership_id=dealership_id,
                source_id=source_id,
                make="Toyota",
                make_key=normalize_text("Toyota"),
                model="Camry",
                model_key=normalize_text("Camry"),
                year=2023,
                price_cents=2_750_000,
                body_type="Sedan",
                body_type_key=normalize_text("Sedan"),
                trim="SE",
            )
        )
    return vehicle_id


def test_turn_persists_and_terminal_retry_replays_after_restart(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'conversation.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    first_runner = FakeRunner()
    app = create_app(settings, runner_factory=factory_for(first_runner))
    request_id = str(uuid4())
    submitted_text = "  Find me a Camry  "
    with TestClient(app) as client:
        dealership_id = mia_dealership_id(client)
        vehicle_id = add_vehicle(app, dealership_id)
        first_runner.result = ChatRunResult(
            reply="1. 2023 Toyota Camry (stock MIA-001) — price: $27,500.00",
            replay_json='{"messages_json":"[]"}',
            presented_vehicle_ids=(vehicle_id,),
            selection_action="set",
            selected_vehicle_id=vehicle_id,
        )
        created = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations",
            json={"creation_id": str(uuid4())},
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        response = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
            json={"request_id": request_id, "text": submitted_text},
        )
        assert response.status_code == 200
        assert response.json()["user_message"]["text"] == submitted_text
        assert response.json()["selected_vehicle_id"] == vehicle_id
        original_body = response.json()

        history = client.get(
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages?limit=1"
        ).json()
        assert [item["role"] for item in history["items"]] == ["user"]
        assert history["next_after_sequence"] == 1
        second_page = client.get(
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
            "?after_sequence=1"
        ).json()
        assert [item["role"] for item in second_page["items"]] == ["assistant"]
        assert len(first_runner.requests) == 1

    second_runner = FakeRunner()
    with TestClient(create_app(settings, runner_factory=factory_for(second_runner))) as client:
        replay = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
            json={"request_id": request_id, "text": submitted_text},
        )
        assert replay.status_code == 200
        assert replay.json() == original_body
        status = client.get(
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/requests/{request_id}"
        )
        assert status.status_code == 200
        assert status.json()["status"] == "completed"
        assert status.json()["outcome"] == original_body
        assert second_runner.requests == []

        follow_up_id = str(uuid4())
        second_runner.result = ChatRunResult(
            reply="2023 Toyota Camry (stock MIA-001) — trim: SE",
            replay_json='{"messages_json":"[]"}',
        )
        follow_up = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
            json={"request_id": follow_up_id, "text": "What trim is the selected one?"},
        )
        assert follow_up.status_code == 200
        assert second_runner.requests[0].selected_vehicle_id == vehicle_id
        assert second_runner.requests[0].presented_vehicle_ids == (vehicle_id,)
        assert len(second_runner.requests[0].replay_units) == 1


def test_provider_failure_is_visible_and_replayed_without_assistant_message(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'failure.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    runner = FakeRunner(error=ChatProviderError("private provider detail"))
    with TestClient(create_app(settings, runner_factory=factory_for(runner))) as client:
        dealership_id = mia_dealership_id(client)
        conversation_id = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations",
            json={"creation_id": str(uuid4())},
        ).json()["id"]
        request_id = str(uuid4())
        url = f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
        first = post_and_wait(client, url, json={"request_id": request_id, "text": "Find a truck"})
        second = post_and_wait(client, url, json={"request_id": request_id, "text": "Find a truck"})

        assert first.status_code == second.status_code == 502
        assert (
            first.json()
            == second.json()
            == {
                "error": {
                    "code": "provider_error",
                    "message": "The chat provider could not complete the request.",
                }
            }
        )
        assert len(runner.requests) == 1
        history = client.get(url).json()
        assert [(item["role"], item["request_status"]) for item in history["items"]] == [
            ("user", "failed")
        ]
        assert history["items"][0]["error_code"] == "provider_error"


def test_invalid_unknown_and_cross_dealership_requests_append_nothing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'scope.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    runner = FakeRunner()
    with TestClient(create_app(settings, runner_factory=factory_for(runner))) as client:
        dealerships = client.get("/dealerships").json()["items"]
        mia_id = next(item["id"] for item in dealerships if item["slug"] == "mia-motors")
        lakeview_id = next(item["id"] for item in dealerships if item["slug"] == "lakeview-auto")
        conversation_id = post_and_wait(
            client, f"/dealerships/{mia_id}/conversations", json={"creation_id": str(uuid4())}
        ).json()["id"]
        request_id = str(uuid4())
        assert (
            post_and_wait(
                client,
                f"/dealerships/{mia_id}/conversations/{conversation_id}/messages",
                json={"request_id": request_id, "text": "   "},
            ).status_code
            == 422
        )
        assert (
            post_and_wait(
                client,
                f"/dealerships/{lakeview_id}/conversations/{conversation_id}/messages",
                json={"request_id": request_id, "text": "Find a car"},
            ).status_code
            == 404
        )
        history = client.get(
            f"/dealerships/{mia_id}/conversations/{conversation_id}/messages"
        ).json()
        assert history["items"] == []
        assert runner.requests == []


def test_missing_connection_blocks_new_chat_but_not_inventory(
    application_settings: Settings,
) -> None:
    with TestClient(create_app(application_settings)) as client:
        dealership_id = mia_dealership_id(client)
        response = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations",
            json={"creation_id": str(uuid4())},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "connection_unavailable"
        assert client.get("/dealerships").status_code == 200


def test_cross_dealership_selection_is_rejected_without_publishing_reply(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'selection-scope.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    runner = FakeRunner()
    app = create_app(settings, runner_factory=factory_for(runner))
    with TestClient(app) as client:
        dealerships = client.get("/dealerships").json()["items"]
        mia_id = next(item["id"] for item in dealerships if item["slug"] == "mia-motors")
        lakeview_id = next(item["id"] for item in dealerships if item["slug"] == "lakeview-auto")
        foreign_vehicle_id = add_vehicle(app, lakeview_id, "LAKE-001")
        runner.result = ChatRunResult(
            reply="Attempted cross-scope reply",
            replay_json='{"messages_json":"[]"}',
            selection_action="set",
            selected_vehicle_id=foreign_vehicle_id,
        )
        conversation_id = post_and_wait(
            client, f"/dealerships/{mia_id}/conversations", json={"creation_id": str(uuid4())}
        ).json()["id"]
        url = f"/dealerships/{mia_id}/conversations/{conversation_id}/messages"
        response = post_and_wait(
            client, url, json={"request_id": str(uuid4()), "text": "Select that vehicle"}
        )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "provider_error"
        history = client.get(url).json()
        assert [item["role"] for item in history["items"]] == ["user"]
        assert history["selected_vehicle_id"] is None


def test_old_conversation_does_not_reroute_after_connection_identity_changes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    config_path = write_config(tmp_path / "config.json")
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'pinned.db'}", config_file=config_path)
    first_runner = FakeRunner()
    request_id = str(uuid4())
    with TestClient(create_app(settings, runner_factory=factory_for(first_runner))) as client:
        dealership_id = mia_dealership_id(client)
        conversation_id = post_and_wait(
            client,
            f"/dealerships/{dealership_id}/conversations",
            json={"creation_id": str(uuid4())},
        ).json()["id"]
        url = f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
        completed = post_and_wait(
            client, url, json={"request_id": request_id, "text": "Find a sedan"}
        )
        assert completed.status_code == 200

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["connections"]["primary-grok"]["model"] = "changed-model"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    second_runner = FakeRunner()
    with TestClient(create_app(settings, runner_factory=factory_for(second_runner))) as client:
        replay = post_and_wait(client, url, json={"request_id": request_id, "text": "Find a sedan"})
        assert replay.status_code == 200
        unavailable = post_and_wait(
            client, url, json={"request_id": str(uuid4()), "text": "Now find a truck"}
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "connection_unavailable"
        assert second_runner.requests == []
