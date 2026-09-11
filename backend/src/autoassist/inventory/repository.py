from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from autoassist.db.models import Dealership, Vehicle
from autoassist.inventory.records import (
    DealershipRecord,
    InventoryFilters,
    VehicleRecord,
    normalize_text,
)

VehicleProjection = tuple[
    str,
    str,
    str,
    str,
    int,
    int | None,
    str | None,
    str | None,
    str | None,
    int | None,
    str | None,
    str | None,
    str | None,
    str | None,
]


class InventoryRepository:
    def dealership_exists(self, session: Session, dealership_id: str) -> bool:
        return (
            session.scalar(select(Dealership.id).where(Dealership.id == dealership_id)) is not None
        )

    def list_dealerships(self, session: Session) -> tuple[DealershipRecord, ...]:
        rows = session.execute(
            select(Dealership.id, Dealership.slug, Dealership.name).order_by(Dealership.slug)
        )
        return tuple(DealershipRecord(id=row.id, slug=row.slug, name=row.name) for row in rows)

    def search(
        self, session: Session, dealership_id: str, filters: InventoryFilters
    ) -> tuple[VehicleRecord, ...]:
        statement = self._vehicle_query(dealership_id)
        statement = self._apply_filters(statement, filters)
        rows = session.execute(statement.order_by(Vehicle.id).limit(filters.limit + 1))
        return tuple(self._record(row) for row in rows)

    def get(self, session: Session, dealership_id: str, vehicle_id: str) -> VehicleRecord | None:
        row = session.execute(
            self._vehicle_query(dealership_id).where(Vehicle.id == vehicle_id)
        ).one_or_none()
        return None if row is None else self._record(row)

    def get_by_source_id(
        self, session: Session, dealership_id: str, source_id: str
    ) -> VehicleRecord | None:
        row = session.execute(
            self._vehicle_query(dealership_id).where(Vehicle.source_id == source_id)
        ).one_or_none()
        return None if row is None else self._record(row)

    @staticmethod
    def _vehicle_query(dealership_id: str) -> Select[VehicleProjection]:
        return select(
            Vehicle.id,
            Vehicle.source_id,
            Vehicle.make,
            Vehicle.model,
            Vehicle.year,
            Vehicle.price_cents,
            Vehicle.body_type,
            Vehicle.trim,
            Vehicle.condition,
            Vehicle.mileage,
            Vehicle.exterior_color,
            Vehicle.drivetrain,
            Vehicle.transmission,
            Vehicle.fuel,
        ).where(Vehicle.dealership_id == dealership_id)

    def _apply_filters(
        self, statement: Select[VehicleProjection], filters: InventoryFilters
    ) -> Select[VehicleProjection]:
        if filters.make is not None:
            statement = statement.where(Vehicle.make_key == normalize_text(filters.make))
        if filters.model is not None:
            statement = statement.where(Vehicle.model_key == normalize_text(filters.model))
        if filters.body_type is not None:
            statement = statement.where(Vehicle.body_type_key == normalize_text(filters.body_type))
        if filters.year_min is not None:
            statement = statement.where(Vehicle.year >= filters.year_min)
        if filters.year_max is not None:
            statement = statement.where(Vehicle.year <= filters.year_max)
        if filters.price_min_cents is not None:
            statement = statement.where(Vehicle.price_cents >= filters.price_min_cents)
        if filters.price_max_cents is not None:
            statement = statement.where(Vehicle.price_cents <= filters.price_max_cents)
        if filters.after is not None:
            statement = statement.where(Vehicle.id > filters.after)
        return statement

    @staticmethod
    def _record(row: Row[VehicleProjection]) -> VehicleRecord:
        (
            vehicle_id,
            source_id,
            make,
            model,
            year,
            price_cents,
            body_type,
            trim,
            condition,
            mileage,
            exterior_color,
            drivetrain,
            transmission,
            fuel,
        ) = row._tuple()
        return VehicleRecord(
            id=vehicle_id,
            source_id=source_id,
            make=make,
            model=model,
            year=year,
            price_cents=price_cents,
            body_type=body_type,
            trim=trim,
            condition=condition,
            mileage=mileage,
            exterior_color=exterior_color,
            drivetrain=drivetrain,
            transmission=transmission,
            fuel=fuel,
        )
