from __future__ import annotations

import re

from autoassist.inventory.records import VehicleRecord
from autoassist.safety.records import Candidate, Identity, Presentation


def tokens(text: str) -> tuple[str, ...]:
    """Normalize safety identity/description text into comparable tokens.

    Used by matching and upstream validation. Return case-folded whitespace tokens with
    hyphens/en dashes treated as separators; an empty input yields an empty tuple.
    """
    return tuple(re.sub(r"[-–]", " ", text.casefold()).split())


def identity_for(vehicle: VehicleRecord) -> Identity:
    """Project an inventory vehicle into its NHTSA year/make/model identity.

    Called before safety lookups and presentation checks. Return Identity without inferring
    VIN, trim, or repair applicability.
    """
    return Identity(year=vehicle.year, make=vehicle.make, model=vehicle.model)


def compatibility(vehicle: VehicleRecord, candidate: Candidate) -> str:
    """Compare a discovered variant conservatively against inventory identity.

    Called by SafetyService.crash before presenting or selecting candidates. Return
    compatible when the identity prefix and known suffix attributes agree, conflicting
    for an identity/attribute contradiction, or unresolved when suffix information cannot
    be established. Unknown suffixes never authorize an automatic match; no model alias
    or vehicle selection is inferred here.
    """
    prefix = tokens(f"{vehicle.year} {vehicle.make} {vehicle.model}")
    description = tokens(candidate.description)
    if description[: len(prefix)] != prefix:
        return "conflicting"
    suffix = description[len(prefix) :]
    unresolved = False
    groups = (
        ({"fwd", "awd", "4wd", "rwd"}, vehicle.drivetrain),
        ({"suv", "sedan", "hatchback", "coupe", "wagon", "van", "pickup"}, vehicle.body_type),
        ({"hybrid", "electric", "diesel", "gasoline"}, vehicle.fuel),
    )
    for token in suffix:
        if token in {"hybrid", "prime"} and token not in prefix:
            return "conflicting"
        for vocabulary, actual in groups:
            if token in vocabulary:
                if actual is None:
                    unresolved = True
                elif token not in tokens(actual):
                    return "conflicting"
                break
        else:
            # Semantic model suffixes are never user-confirmable base-model substitutes.
            if token in {"hybrid", "prime"} and token not in prefix:
                return "conflicting"
            unresolved = True
    return "unresolved" if unresolved else "compatible"


def resolve_choice(text: str, presentation: Presentation) -> tuple[int | None, tuple[str, ...]]:
    """Interpret a whole reply against the NHTSA menu the customer actually saw.

    Called by SafetyService.crash when a presentation is pending. Resolve an exact
    unique description, displayed ID, or unambiguous ordinal before considering descriptors.

    Returns:
        (candidate_id, ()) for a resolved displayed choice; (None, descriptor_tokens)
        for a permitted descriptive reply that still needs fresh candidate matching;
        or (None, ()) for invalid, negated, combined, ambiguous, or out-of-range choices.
        A descriptor never invents an upstream ID. This function does not fetch or select
        a fresh NHTSA record itself.
    """
    normalized = " ".join(text.casefold().split())
    exact = [
        candidate
        for candidate in presentation.candidates
        if normalized == " ".join(candidate.description.casefold().split())
    ]
    if exact:
        return (exact[0].vehicle_id, ()) if len(exact) == 1 else (None, ())
    match = re.fullmatch(r"(?:nhtsa(?: id)?\s+|id\s+)?([0-9]+)", normalized)
    if match:
        number = int(match[1])
        ids = {candidate.vehicle_id for candidate in presentation.candidates}
        if (
            number in ids
            and 1 <= number <= len(presentation.candidates)
            and normalized == str(number)
        ):
            return None, ()
        if number in ids:
            return number, ()
        if 1 <= number <= len(presentation.candidates) and normalized == str(number):
            return presentation.candidates[number - 1].vehicle_id, ()
        return None, ()
    ordinals = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
    ordinal = normalized.removeprefix("the ").removesuffix(" one")
    if ordinal in ordinals:
        index = ordinals[ordinal]
        return (
            (presentation.candidates[index].vehicle_id, ())
            if index < len(presentation.candidates)
            else (None, ())
        )
    descriptor = normalized.removeprefix("the ").removesuffix(" one")
    words = tokens(descriptor)
    forbidden = {"not", "no", "don't", "except", "or", "and", "but", "instead", "neither", "either"}
    if (
        not words
        or len(descriptor) > 200
        or forbidden.intersection(words)
        or not re.fullmatch(r"[a-z0-9 -]+", descriptor)
        or len(set(words).intersection({"awd", "fwd", "4wd", "rwd"})) > 1
    ):
        return None, ()
    return None, words
