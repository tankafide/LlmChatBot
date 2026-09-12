"""Model-visible contract and application-owned selection regressions; synthetic inventory."""

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from test_step2_review_fixes import vehicle

from autoassist.chat.answers import GroundedAnswer, selection_for, validate_answer
from autoassist.chat.context import ChatDependencies
from autoassist.chat.contracts import ChatRunRequest
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.inventory.service import InventoryNotFoundError
from autoassist.safety.service import SafetyService


def test_model_cannot_author_selection_state():
    with pytest.raises(ValidationError, match="Extra inputs"):
        GroundedAnswer.model_validate(
            {"intent": "clarify", "selection": {"action": "set", "vehicle_id": "A"}}
        )


@pytest.mark.parametrize(
    "intent,text,expected",
    [
        ("list", "Show cars", ("clear", None)),
        ("list", "Show stock STK-B", ("set", "B")),
        ("clarify", "Which one?", ("keep", None)),
        ("unsupported", "Guarantee financing", ("keep", None)),
        ("no_match", "Show flying cars", ("clear", None)),
    ],
)
def test_selection_policy_has_no_model_state_decision(intent, text, expected):
    deps = ChatDependencies(
        inventory=None,
        request=ChatRunRequest("dealer", "conversation", "request", text, "A", ("B",), ()),
        evidence={identifier: vehicle(identifier) for identifier in ("A", "B")},
        search_executed=intent in {"list", "no_match"},
        last_search_ids=("B",) if intent == "list" else (),
    )
    answer = GroundedAnswer.model_validate(
        {"intent": intent, "vehicles": [{"vehicle_id": "B"}] if intent == "list" else []}
    )
    assert selection_for(validate_answer(deps, answer), deps) == expected


async def test_followup_prompt_supplies_refreshed_evidence_without_stock_lookup():
    current_record = vehicle("A")
    reads = []
    seen_prices = []

    def get(dealer, identifier):
        assert dealer == "dealer" and identifier == "A"
        reads.append(identifier)
        return current_record

    def respond(messages, info):
        prompts = [
            json.loads(part.content.split(": ", 1)[1])
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        evidence = prompts[-1]["current_vehicle_evidence"]
        assert len(evidence) == 1 and evidence[0]["vehicle_id"] == "A"
        seen_prices.append(evidence[0]["price_cents"])
        assert "selection" not in info.output_tools[0].parameters_json_schema["properties"]
        return ModelResponse(
            [
                ToolCallPart(
                    "final_result",
                    {"intent": "details", "vehicles": [{"vehicle_id": "A", "fields": ["price"]}]},
                )
            ]
        )

    runner = PydanticChatRunner(FunctionModel(respond), SimpleNamespace(get=get))
    request = ChatRunRequest("dealer", "conversation", "request", "What is its price?", "A", (), ())
    try:
        first = await runner.run(request)
        current_record = replace(current_record, price_cents=2345678)
        second = await runner.run(replace(request, replay_units=(first.replay_json,)))
    finally:
        await runner.close()
    assert reads == ["A", "A"] and seen_prices == [10000, 2345678]
    assert "$23,456.78" in second.reply and "$100.00" not in second.reply
    assert second.selection_action == "set" and second.selected_vehicle_id == "A"


@pytest.mark.parametrize("unavailable", [False, True])
@pytest.mark.parametrize("prior_selection", [None, "B"])
async def test_safety_selects_explicit_stock_without_model_selection(unavailable, prior_selection):
    calls = 0
    urls = []
    records = {identifier: vehicle(identifier) for identifier in ("A", "B")}
    inventory = SimpleNamespace(
        get=lambda _dealer, identifier: records[identifier],
        get_by_source_id=lambda _dealer, stock: records[stock.removeprefix("STK-")],
    )

    def respond(_messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse([ToolCallPart("get_vehicle_by_stock", {"stock_number": "STK-A"})])
        if calls == 2:
            return ModelResponse([ToolCallPart("lookup_recalls", {})])
        if calls == 3:
            return ModelResponse([ToolCallPart("lookup_crash_ratings", {})])
        return ModelResponse(
            [
                ToolCallPart(
                    "final_result",
                    {"intent": "safety", "safety_evidence_ids": ["recalls", "crash"]},
                )
            ]
        )

    def upstream(request):
        urls.append(request.url.path)
        if unavailable:
            return httpx.Response(503)
        return httpx.Response(200, json={"Count": 0, "results": [], "Results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        runner = PydanticChatRunner(
            FunctionModel(respond), inventory, safety=SafetyService(NhtsaClient(client))
        )
        try:
            result = await runner.run(
                ChatRunRequest(
                    "dealer",
                    "conversation",
                    "request",
                    "recalls and crash ratings for stock STK-A",
                    prior_selection,
                    (),
                    (),
                )
            )
        finally:
            await runner.close()
    assert calls == 4 and len(urls) == 2
    assert result.selection_action == "set" and result.selected_vehicle_id == "A"
    assert ("unavailable" in result.reply.lower()) == unavailable
    if not unavailable:
        assert "No campaigns returned" in result.reply


@pytest.mark.parametrize("case", ["missing_stock", "ambiguous_safety"])
async def test_missing_subject_repairs_to_clarification_without_extra_lookup(case):
    calls = 0
    reads = []

    def missing(_dealer, stock):
        reads.append(stock)
        raise InventoryNotFoundError

    def respond(messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            name = "get_vehicle_by_stock" if case == "missing_stock" else "lookup_recalls"
            args = {"stock_number": "UNKNOWN"} if case == "missing_stock" else {}
            return ModelResponse([ToolCallPart(name, args)])
        if calls == 2:
            intent = "no_match" if case == "missing_stock" else "safety"
            return ModelResponse([ToolCallPart("final_result", {"intent": intent})])
        assert "clarify" in str(messages[-1].parts)
        return ModelResponse([ToolCallPart("final_result", {"intent": "clarify"})])

    runner = PydanticChatRunner(FunctionModel(respond), SimpleNamespace(get_by_source_id=missing))
    try:
        result = await runner.run(
            ChatRunRequest(
                "dealer",
                "conversation",
                "request",
                "stock UNKNOWN" if case == "missing_stock" else "Does it have recalls?",
                None,
                (),
                (),
            )
        )
    finally:
        await runner.close()
    assert calls == 3 and reads == (["UNKNOWN"] if case == "missing_stock" else [])
    assert "specify a stock" in result.reply
    assert result.selection_action == "keep" and result.selected_vehicle_id is None
