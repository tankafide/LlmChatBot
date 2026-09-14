from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DealershipRecord:
    """Carry immutable public dealership identity outside a database session.

    Used by inventory service listing and API serialization.
    """

    id: str
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    """Carry immutable authoritative inventory facts outside a database session.

    Tools and deterministic renderers use this snapshot; optional None values mean unknown
    facts and price is integer cents.
    """

    id: str
    source_id: str
    make: str
    model: str
    year: int
    price_cents: int | None
    body_type: str | None
    trim: str | None
    condition: str | None
    mileage: int | None
    exterior_color: str | None
    drivetrain: str | None
    transmission: str | None
    fuel: str | None


@dataclass(frozen=True, slots=True)
class InventoryFilters:
    """Carry already-validated structured search criteria from HTTP or model tools.

    None omits a filter, bounds are inclusive, and after/limit control pagination. This
    dataclass does not itself validate ranges.
    """

    make: str | None = None
    model: str | None = None
    body_type: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    after: str | None = None
    limit: int = 20


@dataclass(frozen=True, slots=True)
class InventoryPage:
    """Return a materialized inventory page with its next UUID cursor.

    next_after=None means no additional page was detected; an empty tuple is a valid no-match
    result.
    """

    items: tuple[VehicleRecord, ...]
    next_after: str | None


def normalize_text(value: str) -> str:
    """Produce the shared inventory search/import comparison key.

    Return whitespace-trimmed, case-folded text for consistent matching while retaining
    original display text elsewhere; no I/O or record mutation occurs.
    """
    return value.strip().casefold()


@dataclass(frozen=True, slots=True)
class ImportVehicle:
    """Carry a validated CSV row before it is assigned or matched to a database UUID.

    source_id is the dealership-local stock number, optional blanks are None, and prices have
    been converted to cents.
    """

    source_id: str
    year: int
    make: str
    model: str
    trim: str | None
    body_type: str | None
    condition: str | None
    price_cents: int | None
    mileage: int | None
    exterior_color: str | None
    drivetrain: str | None
    transmission: str | None
    fuel: str | None


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Report inserted, updated, and unchanged inventory counts.

    Repository results describe staged work; the service returns these counts only after a
    successful commit.
    """

    inserted: int
    updated: int
    unchanged: int
