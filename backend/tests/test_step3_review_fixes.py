"""Synthetic inventory with real safety tool/service boundaries."""

from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from pydantic_ai.models.function import FunctionModel
from test_nhtsa_client import discovery, vehicle
from test_safety_matching import presentation

from autoassist.chat.answers import GroundedAnswer, selection_for
from autoassist.chat.context import ChatDependencies
from autoassist.chat.contracts import ChatRunRequest
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.chat.tools import lookup_crash_ratings
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.safety.records import Candidate
from autoassist.safety.service import SafetyService


@pytest.mark.parametrize(
    "text,expected_stock",
    [
        ("crash ratings for stock AA-1002", "AA-1002"),
        ("crash ratings for AA-1002", "AA-1002"),
        ("crash ratings for the first vehicle", "AA-1002"),
        ("crash ratings for stock UNKNOWN", None),
        ("not the first one", "AA-1001"),
        ("number 1", "AA-1001"),
        ("first", "AA-1001"),
    ],
)
async def test_pending_choices_never_override_stock_or_use_inventory_ordinal(
    text, expected_stock
) -> None:
    first = vehicle()
    second = replace(first, id="other-id", source_id="AA-1002", model="Camry")
    records = {item.id: item for item in (first, second)}
    reads = []
    calls = []

    def get(dealer, identifier):
        assert dealer == "dealer"
        reads.append(identifier)
        return records[identifier]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert "VehicleId" not in request.url.path
        model = "Camry" if "Camry" in request.url.path else "RAV4"
        return httpx.Response(200, json=discovery([f"2022 Toyota {model} SUV FWD new variant"]))

    inventory = SimpleNamespace(get=get)
    request = ChatRunRequest(
        "dealer", "conversation", "request", text, first.id, (second.id, first.id), ()
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        deps = ChatDependencies(
            inventory=inventory,
            request=request,
            evidence=records,
            safety=SafetyService(NhtsaClient(client)),
            safety_presentation=presentation(
                (Candidate(vehicle_id=100, description="2022 Toyota RAV4 SUV FWD old variant"),)
            ),
        )
        ctx = SimpleNamespace(deps=deps)
        result = await lookup_crash_ratings(ctx)
        if expected_stock is None:
            assert "clarification" in result and not reads and not calls
        else:
            assert result["result"]["stock_id"] == expected_stock
            assert result["result"]["status"] == "ambiguous"
            assert len(calls) == 1
            selected = first.id if expected_stock == first.source_id else second.id
            runner = PydanticChatRunner(FunctionModel(lambda *_: None), inventory)
            answer = runner._validate_answer(
                ctx,
                GroundedAnswer(
                    intent="safety",
                    safety_evidence_ids=["crash"],
                ),
            )
            assert selection_for(answer, deps) == ("set", selected)
