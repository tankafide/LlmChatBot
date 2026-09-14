"""Dealership-scoped import queries and upserts; the import service owns the transaction."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from autoassist.db.models import Dealership, Vehicle
from autoassist.inventory.records import ImportResult, ImportVehicle, normalize_text


class InventoryImportRepository:
    _lookup_batch_size = 500

    def dealership_id(self, session: Session, slug: str) -> str | None:
        """Resolve the import target slug to its persisted UUID.

        Called inside the import service transaction. Return the ID or None if absent; no
        dealership is created here.
        """
        return session.scalar(select(Dealership.id).where(Dealership.slug == slug))

    def upsert(
        self, session: Session, dealership_id: str, records: Sequence[ImportVehicle]
    ) -> ImportResult:
        """Stage inserts or updates by dealership-local stock ID.

        Called with validated records inside the import transaction. Batch-load matching rows,
        preserve existing UUIDs, and update normalized search keys with display fields. Return
        inserted/updated/unchanged counts before commit. Missing-file stocks are retained;
        database errors propagate and the caller owns atomic commit.
        """
        existing: dict[str, Vehicle] = {}
        source_ids = [record.source_id for record in records]
        for offset in range(0, len(source_ids), self._lookup_batch_size):
            batch = source_ids[offset : offset + self._lookup_batch_size]
            vehicles = session.scalars(
                select(Vehicle).where(
                    Vehicle.dealership_id == dealership_id,
                    Vehicle.source_id.in_(batch),
                )
            )
            existing.update((vehicle.source_id, vehicle) for vehicle in vehicles)

        inserted = updated = unchanged = 0
        for record in records:
            vehicle = existing.get(record.source_id)
            values: dict[str, object] = {
                "make": record.make,
                "make_key": normalize_text(record.make),
                "model": record.model,
                "model_key": normalize_text(record.model),
                "year": record.year,
                "price_cents": record.price_cents,
                "body_type": record.body_type,
                "body_type_key": (
                    None if record.body_type is None else normalize_text(record.body_type)
                ),
                "trim": record.trim,
                "condition": record.condition,
                "mileage": record.mileage,
                "exterior_color": record.exterior_color,
                "drivetrain": record.drivetrain,
                "transmission": record.transmission,
                "fuel": record.fuel,
            }
            if vehicle is None:
                session.add(
                    Vehicle(
                        dealership_id=dealership_id,
                        source_id=record.source_id,
                        **values,
                    )
                )
                inserted += 1
            elif any(getattr(vehicle, name) != value for name, value in values.items()):
                for name, value in values.items():
                    setattr(vehicle, name, value)
                updated += 1
            else:
                unchanged += 1
        return ImportResult(inserted=inserted, updated=updated, unchanged=unchanged)
