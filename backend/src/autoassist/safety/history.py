from __future__ import annotations

import json

from autoassist.chat.history import retain_replay
from autoassist.safety.records import Presentation, PresentationUpdate


def restore_presentation(units: tuple[str, ...], selected: str | None) -> Presentation | None:
    """Replay retained safety-choice updates for the selected inventory vehicle.

    Called before a model turn. Apply keep/set/clear metadata in order, treating absent
    metadata as clear. Return the final Presentation only if it matches selected; otherwise
    None. Invalid stored JSON/update data raises rather than guessing choices.
    """
    presentation = None
    for unit in retain_replay(units):
        data = json.loads(unit)
        update = PresentationUpdate.model_validate_json(
            json.dumps(data.get("safety_presentation_update", {"action": "clear"}))
        )
        if update.action == "clear":
            presentation = None
        elif update.action == "set":
            presentation = update.presentation
    if presentation is not None and presentation.inventory_vehicle_id == selected:
        return presentation
    return None
