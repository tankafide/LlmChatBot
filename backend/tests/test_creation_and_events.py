import json
from uuid import uuid4

from fastapi.testclient import TestClient
from test_conversation_api import FakeRunner, factory_for, mia_dealership_id
from turn_client import post_and_wait

from autoassist.app import create_app
from autoassist.observability import current_turn, logger


def test_creation_replays_after_restart_without_a_configured_provider(
    application_settings, monkeypatch
):
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    body = {"creation_id": str(uuid4())}
    with TestClient(
        create_app(application_settings, runner_factory=factory_for(FakeRunner()))
    ) as client:
        dealer = mia_dealership_id(client)
        path = f"/dealerships/{dealer}/conversations"
        assert post_and_wait(client, path, json={}).status_code == 422
        first = post_and_wait(client, path, json=body)
        assert first.status_code == 201
    monkeypatch.delenv("TEST_XAI_API_KEY")
    with TestClient(create_app(application_settings)) as client:
        retry = post_and_wait(client, path, json=body)
        assert retry.status_code == 201 and retry.json() == first.json()


def test_turn_events_exclude_customer_text_and_replay_has_no_calls(
    application_settings, monkeypatch, caplog
):
    monkeypatch.setenv("TEST_XAI_API_KEY", "secret-key")
    with TestClient(
        create_app(application_settings, runner_factory=factory_for(FakeRunner()))
    ) as client:
        # Capture this dedicated JSON logger without changing its production handler.
        logger.addHandler(caplog.handler)
        try:
            dealer = mia_dealership_id(client)
            conversation = post_and_wait(
                client, f"/dealerships/{dealer}/conversations", json={"creation_id": str(uuid4())}
            ).json()["id"]
            endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"
            body = {"request_id": str(uuid4()), "text": "private-customer-prompt"}
            assert post_and_wait(client, endpoint, json=body).status_code == 200
            assert post_and_wait(client, endpoint, json=body).status_code == 200
            events = [
                json.loads(record.message)
                for record in caplog.records
                if record.name == logger.name
            ]
            assert sum(item["event"] == "request_admitted" for item in events) == 1
            terminal = [item for item in events if item["event"] == "turn_finished"]
            assert len(terminal) == 1
            assert "private-customer-prompt" not in caplog.text and "secret-key" not in caplog.text
            assert current_turn.get() is None
        finally:
            logger.removeHandler(caplog.handler)
