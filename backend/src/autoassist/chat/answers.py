"""Grounded answer schema, evidence validation and deterministic inventory rendering."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoassist.chat.context import ChatDependencies
from autoassist.chat.selection import resolve_reference, resolve_safety_reference
from autoassist.inventory.records import VehicleRecord

AllowedField = Literal[
    "price",
    "body_type",
    "trim",
    "condition",
    "mileage",
    "exterior_color",
    "drivetrain",
    "transmission",
    "fuel",
]


class AnswerVehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    fields: list[AllowedField] = Field(default_factory=list, max_length=9)


class AnswerSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["keep", "set", "clear"] = "keep"
    vehicle_id: str | None = None


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["list", "details", "clarify", "no_match", "safety", "unsupported"]
    safety_evidence_ids: list[str] = Field(default_factory=list, max_length=2)
    vehicles: list[AnswerVehicle] = Field(default_factory=list, max_length=10)
    selection: AnswerSelection = Field(default_factory=AnswerSelection)


class InvalidAnswerError(ValueError):
    """A proposed answer is inconsistent with the current retrieved evidence."""


def validate_answer(deps: ChatDependencies, answer: GroundedAnswer) -> GroundedAnswer:
    if answer.intent == "safety":
        text = deps.request.text.casefold()
        required = set()
        if re.search(r"\brecalls?\b", text) or text.strip() == "both":
            required.add("recalls")
        if re.search(r"\b(?:crash|ratings?|stars?)\b", text) or text.strip() == "both":
            required.add("crash")
        if not required.issubset(deps.safety_run.results):
            raise InvalidAnswerError("Call every requested safety branch before answering.")
        if not answer.safety_evidence_ids or set(answer.safety_evidence_ids) != set(
            deps.safety_run.results
        ):
            raise InvalidAnswerError(
                "Reference every current safety tool result, including failures."
            )
        if (
            len(answer.safety_evidence_ids) != len(set(answer.safety_evidence_ids))
            or answer.vehicles
        ):
            raise InvalidAnswerError(
                "Safety references must be unique and contain no inventory fields."
            )
        if answer.selection.action == "clear":
            raise InvalidAnswerError("Safety answers must retain their vehicle selection.")
        final_selected = (
            answer.selection.vehicle_id
            if answer.selection.action == "set"
            else deps.request.selected_vehicle_id
        )
        if final_selected != deps.safety_run.vehicle_id:
            raise InvalidAnswerError("Select the resolved safety vehicle in this answer.")
    elif answer.safety_evidence_ids or deps.safety_run.results:
        raise InvalidAnswerError("Current safety evidence requires a safety answer.")
    vehicle_ids = [entry.vehicle_id for entry in answer.vehicles]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise InvalidAnswerError("Vehicle IDs must not repeat.")
    if any(vehicle_id not in deps.evidence for vehicle_id in vehicle_ids):
        raise InvalidAnswerError("Every vehicle ID must come from current authoritative evidence.")
    if answer.intent == "list":
        if not deps.search_executed or not answer.vehicles:
            raise InvalidAnswerError("A list requires a non-empty inventory search.")
        if not set(vehicle_ids).issubset(deps.last_search_ids):
            raise InvalidAnswerError(
                "List vehicles must come from the latest inventory search results."
            )
    elif answer.intent == "no_match":
        if not deps.search_executed or deps.last_search_ids:
            raise InvalidAnswerError("No-match is valid only after an empty search.")
        if answer.vehicles:
            raise InvalidAnswerError("A no-match answer cannot contain vehicles.")
    elif answer.intent == "details" and len(answer.vehicles) != 1:
        raise InvalidAnswerError("Vehicle details require exactly one vehicle.")
    elif answer.intent in {"clarify", "unsupported"} and answer.vehicles:
        raise InvalidAnswerError("This intent cannot contain vehicle facts.")
    if answer.selection.action == "set":
        if answer.selection.vehicle_id is None or answer.selection.vehicle_id not in deps.evidence:
            raise InvalidAnswerError("Selection must reference authoritative vehicle evidence.")
        resolved = (
            resolve_safety_reference(
                deps.request, deps.evidence, deps.safety_presentation is not None
            )
            if answer.intent == "safety"
            else resolve_reference(deps.request, deps.evidence)
        )
        if resolved != answer.selection.vehicle_id:
            raise InvalidAnswerError(
                "Selection must match a stock/list choice or selected context."
            )
        if answer.intent not in {"list", "details", "safety"}:
            raise InvalidAnswerError("This answer cannot change the selected vehicle.")
        if answer.intent == "list" and resolved == deps.request.selected_vehicle_id:
            # A previous selection alone does not authorize selecting from a new search.
            explicit = resolve_reference(deps.request, deps.evidence, allow_selected=False)
            if explicit != resolved:
                raise InvalidAnswerError(
                    "A new list clears selection unless the user explicitly chooses a vehicle."
                )
    elif answer.selection.vehicle_id is not None:
        raise InvalidAnswerError("Only a set selection may include a vehicle ID.")
    if answer.intent == "details":
        resolved = resolve_reference(deps.request, deps.evidence)
        if resolved != vehicle_ids[0]:
            raise InvalidAnswerError(
                "Details must match the stock/list reference or selected vehicle."
            )
        # Application reference resolution owns selection. A model's omitted,
        # keep, or clear action must not discard the subject of valid details.
        answer.selection = AnswerSelection(action="set", vehicle_id=resolved)
    return answer


def presentation_for(answer: GroundedAnswer) -> tuple[str, ...] | None:
    if answer.intent == "list":
        return tuple(item.vehicle_id for item in answer.vehicles)
    if answer.intent == "no_match":
        return ()
    return None


def render_answer(answer: GroundedAnswer, evidence: dict[str, VehicleRecord]) -> str:
    if answer.intent == "clarify":
        return "Please specify a stock number or a number from the latest vehicle list."
    if answer.intent == "no_match":
        return "I couldn't find a matching vehicle in this dealership's inventory."
    if answer.intent == "unsupported":
        return "I can help search this dealership's inventory and answer questions about a vehicle."
    lines: list[str] = []
    for index, item in enumerate(answer.vehicles, start=1):
        record = evidence[item.vehicle_id]
        identity = f"{record.year} {record.make} {record.model} (stock {record.source_id})"
        facts = [_render_field(record, field_name) for field_name in item.fields]
        detail = " — " + "; ".join(facts) if facts else ""
        line = f"{index}. {identity}{detail}" if answer.intent == "list" else identity + detail
        lines.append(line)
    return "\n".join(lines)


def _render_field(record: VehicleRecord, field_name: AllowedField) -> str:
    if field_name == "price":
        value = (
            "unknown"
            if record.price_cents is None
            else f"${record.price_cents // 100:,}.{record.price_cents % 100:02d}"
        )
    else:
        raw = getattr(record, field_name)
        if raw is None:
            value = "unknown"
        elif field_name == "mileage":
            value = f"{raw:,} miles"
        else:
            value = str(raw)
    return f"{field_name.replace('_', ' ')}: {value}"
