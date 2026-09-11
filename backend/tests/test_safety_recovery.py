from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel
from safety_scripted_model import ScriptedSafety
from test_conversation_api import add_vehicle, mia_dealership_id
from test_conversation_recovery import NoCallRunner

from autoassist.app import create_app
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.config import Settings
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.inventory.service import InventoryService
from autoassist.safety.history import restore_presentation
from autoassist.safety.service import SafetyService


def test_abrupt_nhtsa_wait_preserves_previous_safety_and_choices(
    application_settings: Settings, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "synthetic")

    def factory(_model: str, _key: str, inventory: InventoryService) -> PydanticChatRunner:
        return PydanticChatRunner(FunctionModel(ScriptedSafety()), inventory)

    app = create_app(application_settings, runner_factory=factory)
    with TestClient(app) as client:
        dealer = mia_dealership_id(client)
        selected_id = add_vehicle(app, dealer)
        conversation = client.post(f"/dealerships/{dealer}/conversations", json={}).json()["id"]
        endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"
        assert (
            client.post(
                endpoint, json={"request_id": str(uuid4()), "text": "stock MIA-001"}
            ).status_code
            == 200
        )
        mock = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "Count": 1,
                        "Results": [
                            {
                                "VehicleId": 777,
                                "VehicleDescription": "2023 Toyota Camry Sedan special",
                            }
                        ],
                    },
                )
            )
        )
        try:
            for runner in app.state.conversation_service._runners.values():
                runner.set_safety_service(SafetyService(NhtsaClient(mock)))
            prior_id = str(uuid4())
            prior = client.post(endpoint, json={"request_id": prior_id, "text": "ratings"})
            assert prior.status_code == 200, prior.text
            previous_body = prior.json()
        finally:
            client.portal.call(mock.aclose)
    marker = tmp_path / "nhtsa.marker"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        {
            "AUTOASSIST_DATABASE_URL": application_settings.database_url,
            "AUTOASSIST_CONFIG_FILE": str(application_settings.config_file),
            "AUTOASSIST_CRASH_MARKER": str(marker),
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "safety_crash_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).parent,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pending_id = str(uuid4())
    thread = None
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as remote:
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    if remote.get("/health").status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                assert time.monotonic() < deadline, "subprocess startup failed"
                threading.Event().wait(0.02)

            def submit() -> None:
                with suppress(httpx.RequestError):
                    remote.post(
                        endpoint, json={"request_id": pending_id, "text": "recalls"}, timeout=20
                    )

            thread = threading.Thread(target=submit)
            thread.start()
            while not marker.exists():
                assert time.monotonic() < deadline, "NHTSA gate not reached"
                threading.Event().wait(0.01)
            # A network wait holds no SQLite transaction: another durable write succeeds.
            assert remote.post(f"/dealerships/{dealer}/conversations", json={}).status_code == 201
            assert remote.get("/health").status_code == 200
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            if thread:
                thread.join(timeout=10)
                assert not thread.is_alive()
    no_calls = NoCallRunner()
    for _ in range(2):
        restarted_app = create_app(application_settings, runner_factory=lambda *_: no_calls)
        with TestClient(restarted_app) as restarted:
            replay = restarted.post(endpoint, json={"request_id": prior_id, "text": "ratings"})
            assert replay.json() == previous_body
            interrupted = restarted.post(
                endpoint, json={"request_id": pending_id, "text": "recalls"}
            )
            assert interrupted.status_code == 409
            assert interrupted.json()["error"]["code"] == "request_interrupted"
            context = restarted_app.state.conversation_service._store.load_context(
                dealer, conversation
            )
            assert context is not None
            pending = restore_presentation(context.replay_units, selected_id)
            assert pending is not None and pending.candidates[0].vehicle_id == 777
    assert no_calls.calls == 0
