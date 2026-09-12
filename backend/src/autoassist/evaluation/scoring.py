"""Labeled behavioral checks. Semantic quality is explicitly left for human review."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TurnLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    intent: str
    tools: list[str] = Field(default_factory=list)
    filters: dict[str, str | int] | None = None
    stock: str | None = None
    fields: list[str] = Field(default_factory=list)
    safety: dict[str, str] = Field(default_factory=dict)
    contains: list[str] = Field(default_factory=list)
    forbids: list[str] = Field(default_factory=list)
    rubric: str


class ConversationLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    category: str
    safety_fixture: Literal["empty", "unavailable", "ambiguous"] = "empty"
    turns: list[TurnLabel] = Field(min_length=1, max_length=5)


def score_turn(
    label: TurnLabel,
    calls: list[dict[str, Any]],
    answer: dict[str, Any],
    reply: str,
    stocks: dict[str, str],
    safety: dict[str, str],
) -> dict[str, bool]:
    observed_tools = {call["name"] for call in calls}
    checks = {
        "tool_choice": observed_tools == set(label.tools),
        "intent": answer.get("intent") == label.intent,
    }
    if label.filters is not None:
        searches = [call["args"] for call in calls if call["name"] == "search_inventory"]

        def normalized(values: dict[str, Any]) -> dict[str, Any]:
            return {
                key: value.casefold() if isinstance(value, str) else value
                for key, value in values.items()
                if value is not None and key != "limit"
            }

        checks["inventory_filters"] = bool(searches) and all(
            normalized(search) == normalized(label.filters) for search in searches
        )
    if label.stock is not None:
        vehicles = answer.get("vehicles", [])
        checks["follow_up_resolution"] = (
            len(vehicles) == 1 and stocks.get(vehicles[0].get("vehicle_id")) == label.stock
        )
    if label.fields:
        checks["requested_fields"] = bool(answer.get("vehicles")) and all(
            set(label.fields).issubset(vehicle.get("fields", [])) for vehicle in answer["vehicles"]
        )
    if label.safety:
        checks["safety_uncertainty"] = safety == label.safety
    checks["required_language"] = all(
        value.casefold() in reply.casefold() for value in label.contains
    )
    checks["forbidden_claims"] = all(
        value.casefold() not in reply.casefold() for value in label.forbids
    )
    return checks
