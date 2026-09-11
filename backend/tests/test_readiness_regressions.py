from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import write_config
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import event, update
from sqlalchemy.exc import OperationalError
from test_conversation_api import FakeRunner, factory_for, mia_dealership_id

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunResult
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.config import Settings
from autoassist.db.models import ChatRequest
from autoassist.inventory.service import InventoryService


@pytest.mark.parametrize("defect", ["column", "index"])
def test_existing_incompatible_schema_fails_startup_without_changing_data(
    tmp_path: Path, defect: str
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'old.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        dealer = mia_dealership_id(client)
        with app.state.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE vehicles DROP COLUMN trim"
                if defect == "column"
                else "DROP INDEX uq_chat_request_active_conversation"
            )
    with sqlite3.connect(tmp_path / "old.db") as connection:
        before = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    with (
        pytest.raises(RuntimeError, match="incompatible.*recreate"),
        TestClient(create_app(settings)),
    ):
        pytest.fail("An incompatible database must never become ready")
    with sqlite3.connect(tmp_path / "old.db") as connection:
        assert (
            connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
            == before
        )
        assert connection.execute(
            'SELECT id FROM dealerships WHERE slug="mia-motors"'
        ).fetchone() == (dealer,)


def test_health_detects_missing_required_column_after_startup(
    application_settings: Settings,
) -> None:
    app = create_app(application_settings)
    with TestClient(app) as client:
        with app.state.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE vehicles DROP COLUMN trim")
        with pytest.raises(OperationalError, match="no such column"):
            client.get("/health")


@pytest.mark.parametrize(
    "failure,expected_status,expected_code",
    [
        ("schema", 500, "internal_error"),
        ("locked", 503, "storage_unavailable"),
        ("bug", 500, "internal_error"),
        ("provider", 502, "provider_error"),
    ],
)
def test_real_agent_tool_errors_are_classified_settled_and_replayed(
    application_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_status: int,
    expected_code: str,
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    calls = 0

    async def model(messages: object, info: object) -> ModelResponse:
        nonlocal calls
        calls += 1
        if failure == "provider":
            raise RuntimeError("test provider transport broke: secret")
        return ModelResponse([ToolCallPart("search_inventory", {"limit": 1})])

    def factory(_model: str, _key: str, inventory: InventoryService) -> PydanticChatRunner:
        return PydanticChatRunner(FunctionModel(model), inventory)

    app = create_app(application_settings, runner_factory=factory)
    with TestClient(app) as client:
        dealer = mia_dealership_id(client)
        conversation = client.post(f"/dealerships/{dealer}/conversations", json={}).json()["id"]
        endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"

        def fault(*args: object) -> None:
            # Inject at SQL execution inside the real inventory tool, after admission.
            statement = str(args[2])
            if "vehicles.source_id" not in statement:
                return
            if failure == "schema":
                original = sqlite3.OperationalError("no such column: vehicles.trim")
                original.sqlite_errorcode = sqlite3.SQLITE_ERROR
                raise OperationalError(statement, {}, original)
            if failure == "locked":
                original = sqlite3.OperationalError("database is locked")
                original.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise OperationalError(statement, {}, original)
            if failure == "bug":
                raise ValueError("test application bug: secret")

        event.listen(app.state.engine, "before_cursor_execute", fault)
        try:
            body = {"request_id": str(uuid4()), "text": "can you give me an example?"}
            response = client.post(endpoint, json=body)
            assert response.status_code == expected_status, response.text
            assert response.json()["error"]["code"] == expected_code
            assert "secret" not in response.text
            history = client.get(endpoint).json()["items"]
            assert len(history) == 1
            assert history[0]["role"] == "user"
            assert history[0]["request_status"] == "failed"
            assert history[0]["error_code"] == expected_code
            assert client.post(endpoint, json=body).json() == response.json()
            assert calls == 1
            # The claim was released; a deliberate new attempt is admitted.
            second = client.post(endpoint, json={**body, "request_id": str(uuid4())})
            assert second.status_code == expected_status
            assert calls == 2
        finally:
            event.remove(app.state.engine, "before_cursor_execute", fault)
    with TestClient(create_app(application_settings, runner_factory=factory)) as restarted:
        replay = restarted.post(endpoint, json=body)
        assert replay.status_code == expected_status
        assert replay.json() == response.json()
        assert calls == 2


def test_partial_startup_closes_previously_created_runners(
    application_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    monkeypatch.setenv("TEST_SECONDARY_XAI_API_KEY", "test-only")
    first = FakeRunner()
    calls = 0

    def factory(_model: str, _key: str, _inventory: InventoryService) -> FakeRunner:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("invalid second provider configuration")
        return first

    with (
        pytest.raises(ValueError, match="invalid second"),
        TestClient(create_app(application_settings, runner_factory=factory)),
    ):
        pass
    assert first.closed


def test_corrupt_persisted_model_history_is_internal_error_without_calling_provider(
    application_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    first = FakeRunner(ChatRunResult(reply="Saved answer", replay_json='{"messages_json":"[]"}'))
    app = create_app(application_settings, runner_factory=factory_for(first))
    with TestClient(app) as client:
        dealer = mia_dealership_id(client)
        conversation = client.post(f"/dealerships/{dealer}/conversations", json={}).json()["id"]
        endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"
        assert (
            client.post(endpoint, json={"request_id": str(uuid4()), "text": "first"}).status_code
            == 200
        )
        with app.state.session_factory.begin() as session:
            session.execute(update(ChatRequest).values(replay_json='{"messages_json":"corrupt"}'))

    calls = 0

    async def model(messages: object, info: object) -> ModelResponse:
        nonlocal calls
        calls += 1
        raise AssertionError("Provider must not receive corrupt history")

    def factory(_model: str, _key: str, inventory: InventoryService) -> PydanticChatRunner:
        return PydanticChatRunner(FunctionModel(model), inventory)

    with TestClient(create_app(application_settings, runner_factory=factory)) as client:
        body = {"request_id": str(uuid4()), "text": "next"}
        response = client.post(endpoint, json=body)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert calls == 0
        assert client.get(endpoint).json()["items"][-1]["request_status"] == "failed"
        assert client.post(endpoint, json=body).json() == response.json()
