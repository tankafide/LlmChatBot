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


# Vehicle queries share a dealership-scoped projection and materialize plain records.
# The service owns the session; attached ORM rows do not escape this repository.
class InventoryRepository:
    def dealership_exists(self, session: Session, dealership_id: str) -> bool:
        """Return True if the dealership ID exists, otherwise False; no ORM object leaves this
        query.

        Called by InventoryService before scoped inventory operations.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
        return (
            session.scalar(select(Dealership.id).where(Dealership.id == dealership_id)) is not None
        )

    def list_dealerships(self, session: Session) -> tuple[DealershipRecord, ...]:
        """Return plain dealership records ordered by slug, or an empty tuple if none exist.

        Called by the service for the dealership listing endpoint.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
        rows = session.execute(
            select(Dealership.id, Dealership.slug, Dealership.name).order_by(Dealership.slug)
        )
        return tuple(DealershipRecord(id=row.id, slug=row.slug, name=row.name) for row in rows)

    def search(
        self, session: Session, dealership_id: str, filters: InventoryFilters
    ) -> tuple[VehicleRecord, ...]:
        """Return materialized scoped/filter-matching vehicles ordered by UUID, up to limit+1 to
        detect another page. The service trims the extra row; zero matches return an empty
        tuple.

        Called by InventoryService.search for HTTP and model-tool searches.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
        statement = self._vehicle_query(dealership_id)
        statement = self._apply_filters(statement, filters)
        # Stable UUID ordering and one extra row support cursor pagination. The service
        # trims that extra row and reports whether more results exist.
        rows = session.execute(statement.order_by(Vehicle.id).limit(filters.limit + 1))
        return tuple(self._record(row) for row in rows)

    def get(self, session: Session, dealership_id: str, vehicle_id: str) -> VehicleRecord | None:
        """Return the plain vehicle record for a dealership/UUID pair, or None if absent/out of
        scope.

        Called by InventoryService.get for details and refreshed evidence.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
        row = session.execute(
            self._vehicle_query(dealership_id).where(Vehicle.id == vehicle_id)
        ).one_or_none()
        return None if row is None else self._record(row)

    def get_by_source_id(
        self, session: Session, dealership_id: str, source_id: str
    ) -> VehicleRecord | None:
        """Return the plain vehicle record for an exact dealership-local stock ID, or None if no
        scoped match exists.

        Called by the service for exact stock lookup.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
        row = session.execute(
            self._vehicle_query(dealership_id).where(Vehicle.source_id == source_id)
        ).one_or_none()
        return None if row is None else self._record(row)

    @staticmethod
    def _vehicle_query(dealership_id: str) -> Select[VehicleProjection]:
        """Build and return an unexecuted SQL SELECT of supported inventory columns, restricted to
        the dealership. Centralize dealership scope for search and direct lookup. Query scoping
        keeps results within a dealership; it does not authenticate the caller.

        Used by search, UUID lookup, and stock lookup.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
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
        """Return a SELECT extended with supplied filter/cursor predicates. It builds SQL
        expressions without executing a query or mutating inventory.

        Called by search before query execution.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
        # Combine supplied predicates with AND and bound values. Normalized equality
        # provides structured matching rather than fuzzy or semantic search.
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
        # Bounds include their endpoints. NULL prices fail a price comparison rather
        # than being treated as zero; they remain eligible when no price filter is supplied.
        if filters.price_min_cents is not None:
            statement = statement.where(Vehicle.price_cents >= filters.price_min_cents)
        if filters.price_max_cents is not None:
            statement = statement.where(Vehicle.price_cents <= filters.price_max_cents)
        # Keyset pagination continues after a UUID instead of scanning OFFSET rows.
        # Separate page requests do not form a frozen snapshot of inventory.
        if filters.after is not None:
            statement = statement.where(Vehicle.id > filters.after)
        return statement

    @staticmethod
    def _record(row: Row[VehicleProjection]) -> VehicleRecord:
        """Convert a projected SQL row into a plain VehicleRecord, preserving null fields; no
        further database access occurs.

        Called by read methods while their service-owned session remains open.

        Called within InventoryService read units for HTTP inventory and model tools. The
        service owns the session; database errors propagate.
        """
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
