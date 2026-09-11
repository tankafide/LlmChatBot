from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DealershipRecord:
    id: str
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class VehicleRecord:
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
    items: tuple[VehicleRecord, ...]
    next_after: str | None


def normalize_text(value: str) -> str:
    return value.strip().casefold()


@dataclass(frozen=True, slots=True)
class ImportVehicle:
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
    inserted: int
    updated: int
    unchanged: int
