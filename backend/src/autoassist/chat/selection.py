"""Conservative reference resolution; model evidence alone cannot authorize selection."""

import re

from autoassist.chat.contracts import ChatRunRequest
from autoassist.inventory.records import VehicleRecord

ORDINALS = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
)
LIST_REFERENCE = re.compile(
    r"\b(" + "|".join(ORDINALS) + r")\b|\b(\d+)(?:st|nd|rd|th)\b|"
    r"(?:\b(?:number|option|vehicle|car)\s*|#)(\d+)\b",
    re.IGNORECASE,
)
STOCK_REFERENCE = re.compile(r"\bstock(?:\s+(?:number|no\.?))?\s*[:#]?\s*([\w-]+)", re.IGNORECASE)


def resolve_reference(
    request: ChatRunRequest,
    evidence: dict[str, VehicleRecord],
    *,
    allow_selected: bool = True,
    allow_list_references: bool = True,
) -> str | None:
    """Return the single referenced inventory UUID, optionally falling back to selection. Return
    None for unresolved/conflicting explicit references or unavailable fallback; no state is
    mutated.

    Called by answer validation, selection derivation, and safety reference resolution.
    """
    text = request.text
    # Repeated references to one vehicle agree; references to different vehicles
    # are ambiguous and must not silently update the selected vehicle.
    candidates: set[str] = set()
    explicit = False
    stocks = {record.source_id.casefold(): record.id for record in evidence.values()}
    for match in STOCK_REFERENCE.finditer(text):
        explicit = True
        vehicle_id = stocks.get(match[1].casefold())
        # An explicit unknown stock blocks fallback to the previous selection so a typo
        # cannot produce facts about an unrelated previously selected car.
        if vehicle_id is None:
            return None
        candidates.add(vehicle_id)
    # Exact stock tokens also support natural requests such as "Tell me about STK-123".
    for stock, vehicle_id in stocks.items():
        if re.search(r"(?<![\w-])" + re.escape(stock) + r"(?![\w-])", text, re.IGNORECASE):
            explicit = True
            candidates.add(vehicle_id)
    # A stock number introduced with '#' or 'number' is not a list ordinal.
    ordinal_text = STOCK_REFERENCE.sub("", text)
    for match in LIST_REFERENCE.finditer(ordinal_text if allow_list_references else ""):
        explicit = True
        index = ORDINALS.index(match[1].lower()) + 1 if match[1] else int(match[2] or match[3])
        # Ordinals use the persisted rendered list, not evidence dictionary order or
        # a fresh search. Out-of-range references require clarification.
        if not 1 <= index <= len(request.presented_vehicle_ids):
            return None
        candidates.add(request.presented_vehicle_ids[index - 1])
    # Fall back to selected context only when there is no explicit reference.
    # This is conservative pattern matching, not general language understanding.
    if explicit:
        return next(iter(candidates)) if len(candidates) == 1 else None
    return request.selected_vehicle_id if allow_selected else None


def resolve_safety_reference(
    request: ChatRunRequest, evidence: dict[str, VehicleRecord], has_pending_choices: bool
) -> str | None:
    """Return the resolved inventory UUID or None, reserving bare ordinals for pending NHTSA
    choices unless the user explicitly refers to a vehicle/car.

    Called by safety tools and answer validation so both agree on the inventory subject.
    """
    # Pending NHTSA choices own ordinals, including rejected/negated choices.
    # Explicit stock references still take precedence and retain scope validation.
    # Inventory lists and NHTSA menus both use numbers. During a pending variant
    # choice, explicit vehicle/car wording re-enables inventory list references.
    inventory_list_reference = re.search(r"\b(?:vehicle|car)\b", request.text, re.IGNORECASE)
    return resolve_reference(
        request,
        evidence,
        allow_list_references=(not has_pending_choices or inventory_list_reference is not None),
    )
