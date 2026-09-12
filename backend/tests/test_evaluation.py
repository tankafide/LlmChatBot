from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from autoassist.chat.grounded import PydanticChatRunner
from autoassist.evaluation.runner import evaluate, load_labels, repair_feedback
from autoassist.evaluation.scoring import TurnLabel, score_turn

ROOT = Path(__file__).resolve().parents[2]


def test_suite_has_varied_labeled_conversations() -> None:
    labels = load_labels(ROOT / "evaluations/conversations.json")
    assert len(labels) == 20
    assert {case.category for case in labels} == {
        "filters",
        "follow_up",
        "clarification",
        "unsupported",
        "safety",
    }
    assert sum(len(case.turns) > 1 for case in labels) >= 2
    assert all(turn.rubric for case in labels for turn in case.turns)


def test_scorer_rejects_extra_filters_wrong_tool_and_unsupported_claim() -> None:
    label = TurnLabel(
        text="SUVs under 30k",
        intent="list",
        tools=["search_inventory"],
        filters={"body_type": "SUV", "price_max_cents": 3000000},
        forbids=["guaranteed"],
        rubric="Use only requested filters.",
    )
    calls = [
        {
            "name": "search_inventory",
            "args": {"body_type": "suv", "price_max_cents": 3000000, "make": "Toyota"},
        }
    ]
    checks = score_turn(label, calls, {"intent": "list"}, "Guaranteed financing", {}, {})
    assert not checks["inventory_filters"] and not checks["forbidden_claims"]
    assert not score_turn(label, [], {"intent": "list"}, "", {}, {})["tool_choice"]


def test_scorer_distinguishes_unavailable_from_empty_and_wrong_selection() -> None:
    label = TurnLabel(
        text="recalls",
        intent="safety",
        stock="AA-1001",
        safety={"recalls": "unavailable"},
        rubric="No safety assurance.",
    )
    checks = score_turn(
        label,
        [],
        {"intent": "safety", "vehicles": [{"vehicle_id": "wrong"}]},
        "",
        {"wrong": "AA-1002"},
        {"recalls": "empty"},
    )
    assert not checks["safety_uncertainty"] and not checks["follow_up_resolution"]


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_search", [False, True])
async def test_evaluation_runs_production_agent_with_isolated_import_and_reports(
    monkeypatch,
    extra_search,
) -> None:
    calls = 0

    def respond(_messages, _info):
        nonlocal calls
        calls += 1
        if extra_search and calls == 1:
            return ModelResponse(parts=[ToolCallPart("search_inventory", {})])
        return ModelResponse(parts=[ToolCallPart("final_result", {"intent": "clarify"})])

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setattr(
        "autoassist.evaluation.runner.create_openai_runner",
        lambda _model, _key, inventory: PydanticChatRunner(FunctionModel(respond), inventory),
    )
    report = await evaluate(
        ROOT / "config/dealerships.json",
        ROOT / "docs/context/inventory/data.csv",
        ROOT / "evaluations/conversations.json",
        "primary-openai",
        1,
        "ambiguous-pronoun",
    )
    assert report["summary"]["passed"] == (0 if extra_search else 1)
    assert report["summary"]["functional_passed"] == 1
    assert report["turns"][0]["model_calls"] == (2 if extra_search else 1)
    assert report["turns"][0]["tool_calls"] == (1 if extra_search else 0)
    assert report["turns"][0]["latency_ms"] > 0
    assert report["turns"][0]["human_review"]["clarification_quality"] is None


def test_evaluation_feedback_keeps_actionable_errors_without_input_payloads():
    feedback = repair_feedback(
        [
            ModelRequest(
                parts=[
                    RetryPromptPart(content="Return clarify after a missing stock lookup."),
                    RetryPromptPart(
                        content=[
                            {
                                "type": "extra_forbidden",
                                "loc": ("selection",),
                                "msg": "Extra inputs are not permitted",
                                "input": "private-value",
                            }
                        ]
                    ),
                ]
            )
        ]
    )
    assert "Return clarify" in feedback[0]["reason"]
    assert feedback[1]["reason"][0]["location"] == ("selection",)
    assert "private-value" not in str(feedback)


@pytest.mark.asyncio
async def test_evaluation_retains_failed_model_output_and_repair_reason(monkeypatch):
    def respond(_messages, _info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"intent": "details", "vehicles": [{"vehicle_id": "invented-id"}]},
                )
            ]
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setattr(
        "autoassist.evaluation.runner.create_openai_runner",
        lambda _model, _key, inventory: PydanticChatRunner(FunctionModel(respond), inventory),
    )
    report = await evaluate(
        ROOT / "config/dealerships.json",
        ROOT / "docs/context/inventory/data.csv",
        ROOT / "evaluations/conversations.json",
        "primary-openai",
        1,
        "ambiguous-pronoun",
    )
    assert report["summary"]["passed"] == report["summary"]["functional_passed"] == 0
    turn = report["turns"][0]
    assert turn["error_category"] == "ChatProviderError"
    assert turn["repair_feedback"]
    assert "authoritative evidence" in turn["repair_feedback"][0]["reason"]
