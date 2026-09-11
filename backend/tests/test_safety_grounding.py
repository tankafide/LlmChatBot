from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry
from pydantic_ai.models.function import FunctionModel
from test_nhtsa_client import vehicle

from autoassist.chat.answers import GroundedAnswer
from autoassist.chat.context import ChatDependencies
from autoassist.chat.contracts import ChatRunRequest
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.safety.matching import identity_for
from autoassist.safety.records import RecallResult


@pytest.mark.parametrize("extra", ["stars", "campaign", "source_url", "prose"])
def test_model_cannot_supply_safety_facts(extra) -> None:
    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate(
            {"intent": "safety", "safety_evidence_ids": ["recalls"], extra: "invented"}
        )


def test_validator_rejects_old_evidence_and_omitted_branch() -> None:
    # Output validator needs only run-local dependencies here; no model/network/SQL call occurs.
    request = ChatRunRequest(
        "dealer", "conversation", "request", "recalls and crash ratings", vehicle().id, (), ()
    )
    dependencies = ChatDependencies(inventory=SimpleNamespace(), request=request)
    dependencies.safety_run.vehicle_id = vehicle().id
    dependencies.safety_run.results["recalls"] = RecallResult(
        inventory_vehicle_id=vehicle().id,
        stock_id=vehicle().source_id,
        lookup_identity=identity_for(vehicle()),
        source_url="https://api.nhtsa.gov/recalls/recallsByVehicle",
        attempted_at=datetime.now(UTC),
        status="unavailable",
        reason="timeout",
    )
    runner = PydanticChatRunner(FunctionModel(lambda *_: None), SimpleNamespace())
    context = SimpleNamespace(deps=dependencies)
    for ids in (["recalls"], ["previous-turn"], []):
        with pytest.raises(ModelRetry):
            runner._validate_answer(
                context, GroundedAnswer(intent="safety", safety_evidence_ids=ids)
            )
    with pytest.raises(ModelRetry):
        runner._validate_answer(context, GroundedAnswer(intent="clarify"))
