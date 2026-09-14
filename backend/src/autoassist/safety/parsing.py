"""Validate every upstream record before returning bounded application evidence."""

from __future__ import annotations

import re
from datetime import date, datetime

from autoassist.safety.matching import tokens
from autoassist.safety.records import Campaign, Candidate, Category, Identity

SUMMARY_KEYS = {
    "OverallRating": "overall",
    "OverallFrontCrashRating": "frontal",
    "OverallSideCrashRating": "side",
    "RolloverRating": "rollover",
}
EXTRA_KEYS = (
    "FrontCrashDriversideRating",
    "FrontCrashPassengersideRating",
    "SideCrashDriversideRating",
    "SideCrashPassengersideRating",
    "SidePoleCrashRating",
    "SideBarrierRating",
    "RolloverRating2",
    "SideBarrierRating-FrontSeat",
    "SideBarrierRating-RearSeat",
    "CombinedSideBarrierAndPoleRating-Front",
    "CombinedSideBarrierAndPoleRating-Rear",
)


class InvalidResponse(ValueError):
    pass


class ResponseLimit(InvalidResponse):
    pass


def envelope(payload: object, key: str, limit: int) -> list[dict[str, object]]:
    """Validate NHTSA row count, collection shape, and size before parsing records.

    Used by all response parsers. Return copied row dictionaries, possibly empty. Raise
    InvalidResponse for malformed/inconsistent envelopes or ResponseLimit when count exceeds
    the caller bound.
    """
    if not isinstance(payload, dict):
        raise InvalidResponse
    count, rows = payload.get("Count"), payload.get(key)
    if type(count) is not int or count < 0 or not isinstance(rows, list) or count != len(rows):
        raise InvalidResponse
    if count > limit:
        raise ResponseLimit
    if any(not isinstance(row, dict) for row in rows):
        raise InvalidResponse
    return [dict(row) for row in rows]


def text(value: object, *, required: bool = False) -> str | None:
    """Validate upstream text and collapse whitespace.

    Used by safety parsers. Return normalized text; return None for missing/blank optional
    values. Raise InvalidResponse for non-string values or missing/blank required text.
    """
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise InvalidResponse
    return " ".join(value.split()) or None


def check_identity(row: dict[str, object], identity: Identity) -> None:
    """Verify an upstream record names the requested year/make/model.

    Called for recall campaigns and crash detail. Accept a four-digit string year or matching
    integer and token-equivalent names. Return None on success; raise InvalidResponse for
    missing/mismatched identity.
    """
    year = row.get("ModelYear")
    if isinstance(year, str) and re.fullmatch(r"[0-9]{4}", year):
        year = int(year)
    if type(year) is not int or year != identity.year:
        raise InvalidResponse
    for key, expected in (("Make", identity.make), ("Model", identity.model)):
        actual = text(row.get(key), required=True)
        if actual is None or tokens(actual) != tokens(expected):
            raise InvalidResponse


def category(value: object) -> Category:
    """Classify a raw crash-rating value without converting uncertainty into stars.

    Called by crash parsing. Return rated with 1–5 stars, not_rated for explicit Not Rated,
    missing for null/blank, or invalid for every other value. Booleans are not accepted as
    integer ratings.
    """
    if value is None or isinstance(value, str) and not value.strip():
        return Category(status="missing")
    if isinstance(value, str):
        value = value.strip()
        if value == "Not Rated":
            return Category(status="not_rated")
        if value in {"1", "2", "3", "4", "5"}:
            return Category(status="rated", stars=int(value))
    if type(value) is int and 1 <= value <= 5:
        return Category(status="rated", stars=value)
    return Category(status="invalid")


def variants(payload: object) -> tuple[Candidate, ...]:
    """Validate and deterministically sort crash-variant discovery results.

    Called before candidate matching. Return a tuple ordered by description/ID, possibly
    empty. Raise InvalidResponse for invalid/duplicate IDs or descriptions, and ResponseLimit
    for oversized envelopes.
    """
    result: list[Candidate] = []
    for row in envelope(payload, "Results", 100):
        vehicle_id = row.get("VehicleId")
        description = text(row.get("VehicleDescription"), required=True)
        if (
            type(vehicle_id) is not int
            or vehicle_id <= 0
            or description is None
            or len(description) > 300
        ):
            raise InvalidResponse
        result.append(Candidate(vehicle_id=vehicle_id, description=description))
    if len({item.vehicle_id for item in result}) != len(result):
        raise InvalidResponse
    return tuple(sorted(result, key=lambda item: (item.description, item.vehicle_id)))


def campaigns(payload: object, identity: Identity) -> tuple[Campaign, ...]:
    """Validate every recall campaign before producing bounded evidence fields.

    Called by SafetyService.recalls. Return campaigns sorted by urgent flags, newest date,
    then number; clip long text with excerpt markers. Empty valid results return an empty
    tuple. Invalid identity, required fields, dates, flags, or duplicate numbers raise
    InvalidResponse; excessive count raises ResponseLimit.
    """
    result: list[Campaign] = []
    for row in envelope(payload, "results", 200):
        check_identity(row, identity)
        number = text(row.get("NHTSACampaignNumber"), required=True)
        if number is None or len(number) > 40:
            raise InvalidResponse
        fields: dict[str, str | None] = {}
        clipped: list[str] = []
        for upstream, local, limit in (
            ("Component", "component", 150),
            ("Summary", "summary", 300),
            ("Consequence", "consequence", 300),
            ("Remedy", "remedy", 300),
            ("Notes", "notes", 150),
        ):
            if upstream != "Notes" and upstream not in row:
                raise InvalidResponse
            value = text(row.get(upstream))
            if value is not None and len(value) > limit:
                clipped.append(local)
                value = value[:limit] + " [excerpt]"
            fields[local] = value
        report_date: date | None = None
        raw_date = text(row.get("ReportReceivedDate"))
        if raw_date:
            try:
                report_date = (
                    datetime.strptime(raw_date, "%d/%m/%Y").date()
                    if "/" in raw_date
                    else date.fromisoformat(raw_date)
                )
            except ValueError as exc:
                raise InvalidResponse from exc
        flags: list[bool | None] = []
        for key in ("parkIt", "parkOutSide"):
            flag = row.get(key)
            if flag is not None and type(flag) is not bool:
                raise InvalidResponse
            flags.append(flag)
        result.append(
            Campaign(
                campaign_number=number,
                component=fields["component"],
                summary=fields["summary"],
                consequence=fields["consequence"],
                remedy=fields["remedy"],
                notes=fields["notes"],
                report_date=report_date,
                park_it=flags[0],
                park_outside=flags[1],
                clipped_fields=tuple(clipped),
            )
        )
    if len({item.campaign_number for item in result}) != len(result):
        raise InvalidResponse
    return tuple(
        sorted(
            result,
            key=lambda item: (
                not (item.park_it or item.park_outside),
                -(item.report_date or date.min).toordinal(),
                item.campaign_number,
            ),
        )
    )


def detail(payload: object, identity: Identity, chosen: Candidate) -> dict[str, object] | None:
    """Validate one crash-detail response against its requested identity and variant.

    Called after choosing a discovery candidate. Return the single validated row or None for a
    valid empty result. Raise InvalidResponse for multiple/mismatched rows and ResponseLimit
    for an oversized envelope.
    """
    rows = envelope(payload, "Results", 100)
    if len(rows) > 1:
        raise InvalidResponse
    if not rows:
        return None
    row = rows[0]
    check_identity(row, identity)
    if type(row.get("VehicleId")) is not int or row["VehicleId"] != chosen.vehicle_id:
        raise InvalidResponse
    description = text(row.get("VehicleDescription"), required=True)
    if description is None or tokens(description) != tokens(chosen.description):
        raise InvalidResponse
    return row
