from __future__ import annotations

from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel
from safety_scripted_model import ScriptedSafety
from test_conversation_api import add_vehicle, mia_dealership_id
from turn_client import post_and_wait

from autoassist.app import create_app
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.config import Settings
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.inventory.service import InventoryService
from autoassist.safety.service import SafetyService


def test_http_combined_ambiguity_restart_choice_and_replay(
    application_settings: Settings, monkeypatch
) -> None:
    monkeypatch.setenv("TEST_XAI_API_KEY", "synthetic")
    calls: list[str] = []
    descriptions = ["2023 Toyota Camry Sedan variant alpha", "2023 Toyota Camry Sedan variant beta"]

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "recalls" in request.url.path:
            return httpx.Response(200, json={"Count": 0, "results": []})
        if "VehicleId" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Results": [
                        {
                            "ModelYear": 2023,
                            "Make": "Toyota",
                            "Model": "Camry",
                            "VehicleId": 202,
                            "VehicleDescription": descriptions[1],
                            "OverallRating": "5",
                            "OverallFrontCrashRating": "Not Rated",
                            "OverallSideCrashRating": "4",
                            "RolloverRating": None,
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "Count": 2,
                "Results": [
                    {"VehicleId": 201 + i, "VehicleDescription": desc}
                    for i, desc in enumerate(descriptions)
                ],
            },
        )

    def factory(_model: str, _key: str, inventory: InventoryService) -> PydanticChatRunner:
        return PydanticChatRunner(FunctionModel(ScriptedSafety()), inventory)

    original = None
    request_id = str(uuid4())
    for iteration in range(3):
        app = create_app(application_settings, runner_factory=factory)
        with TestClient(app) as client:
            # Test transport replaces only NHTSA HTTP; application tools and persistence are real.
            mock = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
            service = SafetyService(NhtsaClient(mock))
            for runner in app.state.conversation_service._runners.values():
                runner.set_safety_service(service)
            try:
                if iteration == 0:
                    dealer = mia_dealership_id(client)
                    add_vehicle(app, dealer)
                    conversation = post_and_wait(
                        client,
                        f"/dealerships/{dealer}/conversations",
                        json={"creation_id": str(uuid4())},
                    ).json()["id"]
                    endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"
                    selected = post_and_wait(
                        client, endpoint, json={"request_id": str(uuid4()), "text": "stock MIA-001"}
                    )
                    assert selected.status_code == 200, selected.text
                    response = post_and_wait(
                        client, endpoint, json={"request_id": request_id, "text": "both"}
                    )
                    assert response.status_code == 200, response.text
                    original = response.json()
                    assert "No campaigns returned" in original["assistant_message"]["text"]
                    assert "NHTSA ID 202" in original["assistant_message"]["text"]
                    assert len(calls) == 2
                elif iteration == 1:
                    replay = post_and_wait(
                        client, endpoint, json={"request_id": request_id, "text": "both"}
                    )
                    assert replay.json() == original and len(calls) == 2
                    choice = post_and_wait(
                        client, endpoint, json={"request_id": str(uuid4()), "text": "202"}
                    )
                    assert choice.status_code == 200, choice.text
                    reply = choice.json()["assistant_message"]["text"]
                    assert "Overall: 5/5" in reply and "Frontal: not rated" in reply
                    assert calls[-1].endswith("/202") and len(calls) == 4
                    fresh = post_and_wait(
                        client, endpoint, json={"request_id": str(uuid4()), "text": "ratings"}
                    )
                    assert fresh.status_code == 200 and len(calls) == 5
                    add_vehicle(app, dealer, "MIA-002")
                    for stock in ("MIA-002", "MIA-001"):
                        selected = post_and_wait(
                            client,
                            endpoint,
                            json={"request_id": str(uuid4()), "text": f"stock {stock}"},
                        )
                        assert selected.status_code == 200
                else:
                    stale = post_and_wait(
                        client, endpoint, json={"request_id": str(uuid4()), "text": "202"}
                    )
                    assert stale.status_code == 200 and len(calls) == 5
                    assert "5/5" not in stale.json()["assistant_message"]["text"]
            finally:
                client.portal.call(mock.aclose)
