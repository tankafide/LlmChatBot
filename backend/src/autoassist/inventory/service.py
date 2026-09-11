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
        self._session_factory = session_factory
        self._repository = repository

    def list_dealerships(self) -> tuple[DealershipRecord, ...]:
        try:
            with self._session_factory() as session:
                return self._repository.list_dealerships(session)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise StorageUnavailableError from exc

    def search(self, dealership_id: str, filters: InventoryFilters) -> InventoryPage:
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
