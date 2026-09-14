"""Completion invariants and public outcome assembly, independent of SQL/session mechanics."""

from __future__ import annotations

import json
from dataclasses import asdict, replace

from autoassist.chat.contracts import ChatProviderError
from autoassist.conversations.outcomes import ConversationOutcome
from autoassist.conversations.records import MessageRecord
from autoassist.safety.records import PresentationUpdate


def completion_presentation(replay_json: str) -> PresentationUpdate | None:
    """Read the safety-context update from a completed model replay envelope.

    Called inside completion validation. Return PresentationUpdate, or None if the metadata
    key is absent. Invalid JSON, unexpected shapes, or invalid update fields propagate as
    decoding/validation errors before persistence.
    """
    metadata = json.loads(replay_json)
    if "safety_presentation_update" not in metadata:
        return None
    return PresentationUpdate.model_validate_json(
        json.dumps(metadata["safety_presentation_update"])
    )


def validate_completion_selection(
    previous: str | None,
    selected: str | None,
    update: PresentationUpdate | None,
    vehicle_identity: tuple[int, str, str] | None,
) -> None:
    """Ensure proposed safety choices agree with the selection being committed.

    Called by ConversationStore.complete under its transaction. Return None for a consistent
    update or absent metadata. Raise ChatProviderError if a presentation names another
    vehicle/identity or keep would preserve choices after selection changed.
    """
    if update is None:
        return
    if update.presentation is not None and update.presentation.inventory_vehicle_id != selected:
        raise ChatProviderError("safety presentation selection mismatch")
    if selected != previous and update.action == "keep":
        raise ChatProviderError("selection change must invalidate safety choices")
    if update.presentation is not None:
        identity = update.presentation.lookup_identity
        if vehicle_identity != (identity.year, identity.make, identity.model):
            raise ChatProviderError("safety presentation identity mismatch")


def completed_outcome(
    conversation_id: str,
    selected: str | None,
    user: MessageRecord,
    assistant: MessageRecord,
) -> ConversationOutcome:
    """Build the replayable public response for a successful turn.

    Called before atomic completion persistence. Return a 200 ConversationOutcome with both
    messages and selection, marking the copied user message completed. Do not mutate the input
    records or commit database work.
    """
    return ConversationOutcome(
        200,
        {
            "conversation_id": conversation_id,
            "request_id": user.request_id,
            "status": "completed",
            "user_message": asdict(replace(user, request_status="completed", error_code=None)),
            "assistant_message": asdict(assistant),
            "selected_vehicle_id": selected,
        },
    )
