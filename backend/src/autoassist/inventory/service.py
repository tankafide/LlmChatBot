from __future__ import annotations

from sqlalchemy.exc import OperationalError

from autoassist.db.database import SessionFactory, is_storage_unavailable
from autoassist.inventory.records import (
    DealershipRecord,
    InventoryFilters,
    InventoryPage,
    VehicleRecord,
)
from autoassist.inventory.repository import InventoryRepository


class InventoryNotFoundError(LookupError):
    pass


class StorageUnavailableError(RuntimeError):
    pass


class InventoryService:
    def __init__(self, session_factory: SessionFactory, repository: InventoryRepository) -> None:
        """Wire the shared inventory read service.

        Constructed during startup/evaluation with a session factory and repository. Return
        None; individual operations own independent sessions.
        """
        self._session_factory = session_factory
        self._repository = repository

    def list_dealerships(self) -> tuple[DealershipRecord, ...]:
        """Load plain dealership records for the listing endpoint.

        Return an ordered tuple, possibly empty, after closing the session. Convert recognized
        outages into StorageUnavailableError; unexpected SQL defects propagate.
        """
        try:
            with self._session_factory() as session:
                return self._repository.list_dealerships(session)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise StorageUnavailableError from exc

    def search(self, dealership_id: str, filters: InventoryFilters) -> InventoryPage:
        """Search scoped inventory and build the public/tool cursor page.

        Called by HTTP routes and model tools. Return InventoryPage, possibly empty, with
        next_after=None when exhausted. Raise InventoryNotFoundError for missing dealership,
        StorageUnavailableError for recognized outages, or propagate other database errors.
        Close the session before returning.
        """
        try:
            with self._session_factory() as session:
                if not self._repository.dealership_exists(session, dealership_id):
                    raise InventoryNotFoundError
                records = self._repository.search(session, dealership_id, filters)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise StorageUnavailableError from exc

        has_more = len(records) > filters.limit
        items = records[: filters.limit]
        return InventoryPage(
            items=items,
            next_after=items[-1].id if has_more else None,
        )

    def get(self, dealership_id: str, vehicle_id: str) -> VehicleRecord:
        """Retrieve one scoped vehicle as detached evidence.

        Called by detail routes and context/safety refresh. Return VehicleRecord; raise
        InventoryNotFoundError for missing dealership/vehicle, StorageUnavailableError for
        recognized outages, or propagate unexpected SQL errors. No live ORM row leaves the
        session.
        """
        try:
            with self._session_factory() as session:
                if not self._repository.dealership_exists(session, dealership_id):
                    raise InventoryNotFoundError
                record = self._repository.get(session, dealership_id, vehicle_id)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise StorageUnavailableError from exc
        if record is None:
            raise InventoryNotFoundError
        return record

    def get_by_source_id(self, dealership_id: str, source_id: str) -> VehicleRecord:
        """Resolve an exact dealership-local stock number.

        Called by stock lookup tools. Return VehicleRecord after closing the session; raise
        InventoryNotFoundError for missing scope/stock or StorageUnavailableError for
        recognized outages. Other SQL errors propagate.
        """
        try:
            with self._session_factory() as session:
                if not self._repository.dealership_exists(session, dealership_id):
                    raise InventoryNotFoundError
                record = self._repository.get_by_source_id(session, dealership_id, source_id)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise StorageUnavailableError from exc
        if record is None:
            raise InventoryNotFoundError
        return record
