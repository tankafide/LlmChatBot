from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from conftest import write_config
from fastapi.testclient import TestClient
from httpx import Client, RequestError
from sqlalchemy import update

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunRequest, ChatRunResult
from autoassist.config import Settings
from autoassist.conversations.repository import ConversationRepository
from autoassist.conversations.store import ConversationStore
from autoassist.db.database import create_database_engine, make_session_factory
from autoassist.db.models import ChatRequest, Conversation, Message
from autoassist.inventory.service import InventoryService


class NoCallRunner:
    calls = 0

    async def run(self, _request: ChatRunRequest) -> ChatRunResult:
        self.calls += 1
        return ChatRunResult(reply="unexpected", replay_json="{}")

    async def close(self) -> None:
        return None


def test_startup_recovers_active_request_and_replays_interruption(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'recovery.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    runner = NoCallRunner()

    def factory(_model: str, _key: str, _inventory: InventoryService) -> NoCallRunner:
        return runner

    app = create_app(settings, runner_factory=factory)
    request_id = str(uuid4())
    with TestClient(app) as client:
        dealership_id = next(
            item["id"]
            for item in client.get("/dealerships").json()["items"]
            if item["slug"] == "mia-motors"
        )
        conversation_id = client.post(
            f"/dealerships/{dealership_id}/conversations", json={}
        ).json()["id"]
        internal_id = str(uuid4())
        message_id = str(uuid4())
        with app.state.session_factory.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            assert conversation is not None
            session.add(
                ChatRequest(
                    id=internal_id,
                    conversation_id=conversation_id,
                    client_request_id=request_id,
                    payload="Continue",
                    status="in_progress",
                    created_at="2026-09-10T00:00:00+00:00",
                    updated_at="2026-09-10T00:00:00+00:00",
                )
            )
            session.add(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    request_id=internal_id,
                    sequence=conversation.next_message_sequence,
                    role="user",
                    text="Continue",
                    created_at="2026-09-10T00:00:00+00:00",
                )
            )
            conversation.next_message_sequence += 1

    with TestClient(create_app(settings, runner_factory=factory)) as client:
        url = f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
        replay = client.post(url, json={"request_id": request_id, "text": "Continue"})
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "request_interrupted"
        history = client.get(url).json()
        assert history["items"][0]["request_status"] == "interrupted"
        assert history["items"][0]["error_code"] == "request_interrupted"
        assert runner.calls == 0


@pytest.fixture(params=["sqlite", "postgresql"])
def crash_database_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    if request.param == "postgresql":
        engine = request.getfixturevalue("postgres_engine")
        return engine.url.render_as_string(hide_password=False)
    return f"sqlite:///{(tmp_path / 'abrupt.db').as_posix()}"


def test_abrupt_process_stop_after_admission_recovers_without_provider_rerun(
    tmp_path: Path, monkeypatch: Any, crash_database_url: str
) -> None:
    config_path = write_config(tmp_path / "config.json")
    marker_path = tmp_path / "admitted.marker"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    environment = os.environ.copy()
    environment.update(
        {
            "AUTOASSIST_DATABASE_URL": crash_database_url,
            "AUTOASSIST_CONFIG_FILE": str(config_path),
            "AUTOASSIST_CRASH_MARKER": str(marker_path),
            "TEST_XAI_API_KEY": "test-only-key",
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "crash_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
        ],
        cwd=Path(__file__).parent,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = Client(base_url=f"http://127.0.0.1:{port}", timeout=2.0)
    request_thread: threading.Thread | None = None
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                if client.get("/health").status_code == 200:
                    break
            except RequestError:
                pass
            if time.monotonic() >= deadline:
                raise AssertionError("crash test server did not become ready")
            time.sleep(0.05)

        dealership_id = next(
            item["id"]
            for item in client.get("/dealerships").json()["items"]
            if item["slug"] == "mia-motors"
        )
        conversation_id = client.post(
            f"/dealerships/{dealership_id}/conversations", json={}
        ).json()["id"]
        request_id = str(uuid4())
        prior_id = str(uuid4())
        engine = create_database_engine(crash_database_url)
        try:
            store = ConversationStore(make_session_factory(engine), ConversationRepository())
            prior, _ = store.admit(dealership_id, conversation_id, prior_id, "Earlier turn")
            store.complete(
                dealership_id, prior.id, ChatRunResult(reply="Earlier reply", replay_json="{}")
            )
        finally:
            engine.dispose()
        prior_response = client.post(
            f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
            json={"request_id": prior_id, "text": "Earlier turn"},
        )
        assert prior_response.status_code == 200

        def submit_blocked_request() -> None:
            try:
                client.post(
                    f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
                    json={"request_id": request_id, "text": "Wait for the crash"},
                    timeout=30,
                )
            except Exception:
                return

        request_thread = threading.Thread(target=submit_blocked_request)
        request_thread.start()
        deadline = time.monotonic() + 10
        while not marker_path.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("provider crash gate was not reached")
            time.sleep(0.02)
        process.kill()
        process.wait(timeout=10)
        request_thread.join(timeout=10)
        assert not request_thread.is_alive()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        client.close()
        if request_thread is not None:
            request_thread.join(timeout=10)

    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only-key")
    settings = Settings(database_url=crash_database_url, config_file=config_path)
    runner = NoCallRunner()

    def factory(_model: str, _key: str, _inventory: InventoryService) -> NoCallRunner:
        return runner

    restarted_app = create_app(settings, runner_factory=factory)
    with TestClient(restarted_app) as restarted:
        url = f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
        if crash_database_url.startswith("postgresql"):
            protected = restarted.post(
                url, json={"request_id": request_id, "text": "Wait for the crash"}
            )
            assert protected.status_code == 409
            assert protected.json()["error"]["code"] == "request_in_progress"
            # Advance only the persisted request age; do not wait two minutes or
            # shorten the production recovery threshold in the application.
            with restarted_app.state.session_factory.begin() as session:
                session.execute(
                    update(ChatRequest)
                    .where(ChatRequest.client_request_id == request_id)
                    .values(updated_at="2000-01-01T00:00:00+00:00")
                )
        replay = restarted.post(url, json={"request_id": request_id, "text": "Wait for the crash"})
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "request_interrupted"
        history = restarted.get(url).json()
        assert [(item["role"], item["request_status"]) for item in history["items"]] == [
            ("user", "completed"),
            ("assistant", "completed"),
            ("user", "interrupted"),
        ]
        assert runner.calls == 0
        assert (
            restarted.post(url, json={"request_id": prior_id, "text": "Earlier turn"}).json()
            == prior_response.json()
        )

    with TestClient(create_app(settings, runner_factory=factory)) as restarted:
        repeated = restarted.post(
            url, json={"request_id": request_id, "text": "Wait for the crash"}
        )
        assert repeated.status_code == replay.status_code
        assert repeated.json() == replay.json()
        assert runner.calls == 0
