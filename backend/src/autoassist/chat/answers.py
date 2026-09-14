"""Grounded answer schema, evidence validation and deterministic inventory rendering."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoassist.chat.context import ChatDependencies
from autoassist.chat.selection import resolve_reference, resolve_safety_reference
from autoassist.inventory.records import VehicleRecord

# The model requests field names, never factual values. The renderer obtains
# prices and specifications from current inventory evidence.
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
    """An evidenced vehicle and the inventory fields the customer requested."""

    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(description="Copy the UUID from current inventory evidence.")
    fields: list[AllowedField] = Field(
        default_factory=list,
        max_length=9,
        description="Requested field names only; the application supplies their factual values.",
    )


class GroundedAnswer(BaseModel):
    """Choose a grounded response. The application renders facts and owns vehicle selection."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["list", "details", "clarify", "no_match", "safety", "unsupported"] = Field(
        description=(
            "list: nonempty latest search; details: one identified inventory vehicle; "
            "clarify: missing/ambiguous vehicle, stock not found, or safety tool clarification; "
            "no_match: latest filtered inventory search was empty (not a missing stock lookup); "
            "safety: current safety evidence was returned; unsupported: outside supported scope "
            "or a request to fabricate facts."
        )
    )
    safety_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=2,
        description=(
            "For safety only, copy every current safety tool evidence_id, including unavailable "
            "or empty results. A clarification has no evidence_id. Otherwise leave empty."
        ),
    )
    vehicles: list[AnswerVehicle] = Field(
        default_factory=list,
        max_length=10,
        description="For list/details only. All other intents require an empty list.",
    )


class InvalidAnswerError(ValueError):
    """A proposed answer is inconsistent with the current retrieved evidence."""


def validate_answer(deps: ChatDependencies, answer: GroundedAnswer) -> GroundedAnswer:
    """Pydantic checks shape; these checks enforce meaning against evidence from this run. Validate
    before rendering or deriving persistent selection changes. Return the proposed answer
    unchanged when its intent, evidence IDs, and subject agree with this run. Raise
    InvalidAnswerError on a semantic mismatch; do not persist selection.

    Called by the runner output validator before rendering or selection changes.
    """
    if answer.intent == "safety":
        if not deps.safety_run.results:
            raise InvalidAnswerError(
                "Safety needs evidence_id results. If the lookup returned clarification, "
                "return clarify; otherwise call the requested safety tool."
            )
        text = deps.request.text.casefold()
        required = set()
        if re.search(r"\brecalls?\b", text) or text.strip() == "both":
            required.add("recalls")
        if re.search(r"\b(?:crash|ratings?|stars?)\b", text) or text.strip() == "both":
            required.add("crash")
        if not required.issubset(deps.safety_run.results):
            raise InvalidAnswerError("Call every requested safety branch before answering.")
        # Require every branch, including failures, so successful recall evidence
        # cannot hide unavailable crash evidence or vice versa.
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
        resolved = resolve_safety_reference(
            deps.request, deps.evidence, deps.safety_presentation is not None
        )
        if (
            resolved is None
            or resolved not in deps.evidence
            or resolved != deps.safety_run.vehicle_id
        ):
            raise InvalidAnswerError("Safety evidence must match the requested inventory vehicle.")
    elif answer.safety_evidence_ids or deps.safety_run.results:
        raise InvalidAnswerError("Current safety evidence requires a safety answer.")
    vehicle_ids = [entry.vehicle_id for entry in answer.vehicles]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise InvalidAnswerError("Vehicle IDs must not repeat.")
    if any(vehicle_id not in deps.evidence for vehicle_id in vehicle_ids):
        raise InvalidAnswerError("Every vehicle ID must come from current authoritative evidence.")
    # Being in context does not make a vehicle a search result. Lists and no_match
    # must describe the latest actual filtered search in this turn.
    if answer.intent == "list":
        if not deps.search_executed or not answer.vehicles:
            raise InvalidAnswerError("A list requires a non-empty inventory search.")
        if not set(vehicle_ids).issubset(deps.last_search_ids):
            raise InvalidAnswerError(
                "List vehicles must come from the latest inventory search results."
            )
    elif answer.intent == "no_match":
        if not deps.search_executed or deps.last_search_ids:
            raise InvalidAnswerError(
                "no_match requires an empty filtered search. A stock lookup with found=false "
                "requires clarify, without a broad replacement search."
            )
        if answer.vehicles:
            raise InvalidAnswerError("A no-match answer cannot contain vehicles.")
    elif answer.intent == "details" and len(answer.vehicles) != 1:
        raise InvalidAnswerError("Vehicle details require exactly one vehicle.")
    elif answer.intent in {"clarify", "unsupported"} and answer.vehicles:
        raise InvalidAnswerError("This intent cannot contain vehicle facts.")
    # A real evidenced vehicle can still be the wrong subject. Independently resolve
    # the customer reference and require the answer to identify that same vehicle.
    if answer.intent == "details":
        resolved = resolve_reference(deps.request, deps.evidence)
        if resolved != vehicle_ids[0]:
            raise InvalidAnswerError(
                "Details must match the stock/list reference or selected vehicle."
            )
    return answer


def selection_for(
    answer: GroundedAnswer, deps: ChatDependencies
) -> tuple[Literal["keep", "set", "clear"], str | None]:
    """Derive and return (keep/set/clear, vehicle ID or None) from a validated answer. None
    accompanies keep/clear; the caller applies the action after successful completion.

    Called by the runner only after answer validation succeeds.

    Derive the state update only after answer/evidence validation has succeeded.
    """
    if answer.intent == "details":
        return "set", answer.vehicles[0].vehicle_id
    if answer.intent == "safety":
        return "set", deps.safety_run.vehicle_id
    if answer.intent == "list":
        explicit = resolve_reference(deps.request, deps.evidence, allow_selected=False)
        if explicit is not None and explicit in {item.vehicle_id for item in answer.vehicles}:
            return "set", explicit
        # A fresh list without an explicit choice clears the old selection so later
        # pronouns do not silently refer to a car from the previous search.
        return "clear", None
    if answer.intent == "no_match":
        return "clear", None
    return "keep", None


def presentation_for(answer: GroundedAnswer) -> tuple[str, ...] | None:
    """None keeps the previous list; an empty tuple clears it. Preserve rendered order because a
    follow-up such as "the second one" uses these IDs. Return ordered vehicle IDs for a list, an
    empty tuple for no_match, or None to keep the previous list. This describes a state update
    without applying it.

    Called by the runner to describe the list-context update saved with completion.
    """
    if answer.intent == "list":
        return tuple(item.vehicle_id for item in answer.vehicles)
    if answer.intent == "no_match":
        return ()
    return None


def render_answer(answer: GroundedAnswer, evidence: dict[str, VehicleRecord]) -> str:
    """Deterministic templates form the final grounding boundary: the model chooses what to show,
    while inventory records supply all vehicle facts. Return deterministic
    inventory/clarification text from a validated answer and current records. Safety rendering
    is handled separately; missing evidence IDs raise KeyError.

    Called by the runner for validated non-safety answers.
    """
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
    """Return one labeled inventory value as text, formatting cents/mileage and using unknown for
    null data. Supported field names come from AllowedField.

    Called for each requested inventory field during answer rendering.
    """
    # Integer cents avoid floating-point currency errors. Missing fields remain
    # explicitly unknown instead of being guessed.
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
