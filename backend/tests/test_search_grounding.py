"""Synthetic inventory; real SQL/tools and a scripted model returning stale search evidence."""

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from autoassist.chat.contracts import ChatRunRequest
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.db.database import create_database_engine, initialize_schema, make_session_factory
from autoassist.db.models import Dealership, Vehicle
from autoassist.inventory.repository import InventoryRepository
from autoassist.inventory.service import InventoryService


@pytest.mark.parametrize("origin", ["previous_turn", "earlier_search"])
@pytest.mark.parametrize("has_match", [False, True])
async def test_list_repairs_evidence_outside_latest_search(
    tmp_path: Path, origin: str, has_match: bool
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'search.db'}")
    initialize_schema(engine)
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        session.add(Dealership(id="dealer", slug="test", name="Test", default_connection="test"))
        for identifier, make, model, body in (
            ("old", "Toyota", "Camry", "Sedan"),
            ("current", "Ford", "Escape", "SUV"),
        ):
            if identifier == "current" and not has_match:
                continue
            session.add(
                Vehicle(
                    id=identifier,
                    dealership_id="dealer",
                    source_id=identifier,
                    make=make,
                    make_key=make.casefold(),
                    model=model,
                    model_key=model.casefold(),
                    year=2024,
                    body_type=body,
                    body_type_key=body.casefold(),
                )
            )
    searches = ["Toyota", "Ford"] if origin == "earlier_search" else ["Ford"]
    calls = 0

    async def scripted(_messages: list[object], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls <= len(searches):
            return ModelResponse([ToolCallPart("search_inventory", {"make": searches[calls - 1]})])
        if calls == len(searches) + 1:
            answer = {"intent": "list", "vehicles": [{"vehicle_id": "old"}]}
        elif has_match:
            answer = {"intent": "list", "vehicles": [{"vehicle_id": "current"}]}
        else:
            answer = {"intent": "no_match"}
        return ModelResponse([ToolCallPart(info.output_tools[0].name, answer)])

    runner = PydanticChatRunner(
        FunctionModel(scripted), InventoryService(sessions, InventoryRepository())
    )
    try:
        result = await runner.run(
            ChatRunRequest(
                "dealer",
                "conversation",
                "request",
                "Show Ford SUVs",
                None,
                ("old",) if origin == "previous_turn" else (),
                (),
            )
        )
        assert calls == len(searches) + 2  # Stale output was rejected and repaired.
        assert "Toyota" not in result.reply
        assert result.presented_vehicle_ids == (("current",) if has_match else ())
        assert result.selection_action == "clear"
        if has_match:
            assert "Ford Escape" in result.reply
        else:
            assert "couldn't find" in result.reply
    finally:
        await runner.close()
        engine.dispose()
