"""Regressions from the real-browser session on 2026-09-11."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from test_conversation_api import mia_dealership_id
from turn_client import post_and_wait

from autoassist.app import create_app
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.inventory.importer import InventoryImportService, parse_inventory_csv
from autoassist.safety.service import SafetyService


def test_numbered_details_retain_selection_for_restored_safety_followup(
    application_settings, monkeypatch
):
    monkeypatch.setenv("TEST_XAI_API_KEY", "synthetic")
    ids = []
    seen_selected = []
    nhtsa_calls = []

    async def model(messages, info):
        current = []
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart):
                        context = json.loads(part.content.split(": ", 1)[1])
                        current = []
                    elif isinstance(part, ToolReturnPart):
                        current.append(part)
        text = context["user_text"]
        if text.startswith("Show"):
            if not current:
                return ModelResponse(
                    [
                        ToolCallPart(
                            "search_inventory",
                            {"make": "Toyota", "body_type": "SUV", "price_max_cents": 3500000},
                        )
                    ]
                )
            found = current[-1].content["items"]
            # Preserve the presentation order from the observed manual session.
            found.sort(
                key=lambda v: [
                    "AA-1049",
                    "AA-1004",
                    "AA-1001",
                    "AA-1002",
                    "AA-1035",
                    "AA-1041",
                ].index(v["stock_number"])
            )
            ids[:] = [v["vehicle_id"] for v in found]
            answer = {"intent": "list", "vehicles": [{"vehicle_id": v} for v in ids]}
        elif text.startswith("Tell"):
            answer = {
                "intent": "details",
                "vehicles": [{"vehicle_id": ids[2], "fields": ["mileage", "drivetrain", "price"]}],
            }
        else:
            seen_selected.append(context["selected_vehicle_id"])
            done = {p.tool_name for p in current}
            for tool in ("lookup_recalls", "lookup_crash_ratings"):
                if tool not in done:
                    return ModelResponse([ToolCallPart(tool, {})])
            evidence = [p.content["evidence_id"] for p in current if "evidence_id" in p.content]
            answer = {
                "intent": "safety" if evidence else "clarify",
                "safety_evidence_ids": evidence,
            }
        return ModelResponse([ToolCallPart(info.output_tools[0].name, answer)])

    def factory(_model, _key, inventory):
        return PydanticChatRunner(FunctionModel(model), inventory)

    def nhtsa(request):
        nhtsa_calls.append(str(request.url))
        if "recalls" in request.url.path:
            return httpx.Response(200, json={"Count": 0, "results": []})
        return httpx.Response(200, json={"Count": 0, "Results": []})

    first = create_app(application_settings, runner_factory=factory)
    with TestClient(first) as client:
        dealer = mia_dealership_id(client)
        InventoryImportService(first.state.session_factory).import_records(
            "mia-motors", parse_inventory_csv(Path("docs/context/inventory/data.csv"))
        )
        conversation = post_and_wait(
            client, f"/dealerships/{dealer}/conversations", json={"creation_id": str(uuid4())}
        ).json()["id"]
        endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"
        assert (
            post_and_wait(
                client,
                endpoint,
                json={"request_id": str(uuid4()), "text": "Show me Toyota SUVs under $35,000."},
            ).status_code
            == 200
        )
        response = post_and_wait(
            client,
            endpoint,
            json={
                "request_id": str(uuid4()),
                "text": (
                    "Tell me more about the third one. What is its mileage, drivetrain, and price?"
                ),
            },
        )
        assert response.status_code == 200, response.text
        assert "$26,335.00" in response.json()["assistant_message"]["text"]
        assert response.json()["selected_vehicle_id"] == ids[2]

    restored = create_app(application_settings, runner_factory=factory)
    with TestClient(restored) as client:
        transport = httpx.AsyncClient(transport=httpx.MockTransport(nhtsa))
        for runner in restored.state.conversation_service._runners.values():
            runner.set_safety_service(SafetyService(NhtsaClient(transport)))
        try:
            history = client.get(endpoint).json()
            assert history["selected_vehicle_id"] == ids[2]
            assert len(history["items"]) == 4
            body = {
                "request_id": str(uuid4()),
                "text": "What recalls and crash-test ratings does it have?",
            }
            response = post_and_wait(client, endpoint, json=body)
            assert response.status_code == 200, response.text
            reply = response.json()["assistant_message"]["text"]
            assert "No campaigns returned" in reply
            assert len(nhtsa_calls) == 2
            assert all(value == ids[2] for value in seen_selected)
            assert post_and_wait(client, endpoint, json=body).json() == response.json()
            assert len(nhtsa_calls) == 2
        finally:
            client.portal.call(transport.aclose)
