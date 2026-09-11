from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from autoassist.db.database import SessionFactory
from autoassist.inventory.import_repository import InventoryImportRepository
from autoassist.inventory.records import ImportResult, ImportVehicle

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_RECORDS = 50_000
MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
EXPECTED_COLUMNS = (
    "stock_number",
    "year",
    "make",
    "model",
    "trim",
    "body_type",
    "condition",
    "price",
    "mileage",
    "exterior_color",
    "drivetrain",
    "transmission",
    "fuel",
)


class InventoryImportError(RuntimeError):
    """Base class for safe, actionable import failures."""


class InventoryValidationError(InventoryImportError):
    pass


class DealershipNotFoundError(InventoryImportError):
    pass


def _validation_error(row: int | None, field: str, message: str) -> InventoryValidationError:
    location = "header" if row is None else f"row {row}"
    return InventoryValidationError(f"{location}, field {field}: {message}")


def _required_text(value: str, *, row: int, field: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise _validation_error(row, field, "value is required")
    if len(cleaned) > maximum:
        raise _validation_error(row, field, f"must contain at most {maximum} characters")
    return cleaned


def _optional_text(value: str, *, row: int, field: str, maximum: int = 100) -> str | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > maximum:
        raise _validation_error(row, field, f"must contain at most {maximum} characters")
    return cleaned


def _integer(
    value: str,
    *,
    row: int,
    field: str,
    minimum: int,
    maximum: int,
    required: bool,
) -> int | None:
    cleaned = value.strip()
    if not cleaned and not required:
        return None
    if not cleaned or not cleaned.isascii() or not cleaned.isdigit():
        raise _validation_error(row, field, "must be a whole nonnegative integer")
    parsed = int(cleaned)
    if parsed < minimum or parsed > maximum:
        raise _validation_error(row, field, f"must be between {minimum} and {maximum}")
    return parsed


def _price_cents(value: str, *, row: int) -> int | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if not cleaned.isascii() or not cleaned.isdigit():
        raise _validation_error(row, "price", "must be a whole US-dollar amount")
    cents = int(cleaned) * 100
    if cents > MAX_SQLITE_INTEGER:
        raise _validation_error(row, "price", "is too large to store")
    return cents


def parse_inventory_csv(
    path: Path,
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_records: int = MAX_RECORDS,
) -> tuple[ImportVehicle, ...]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise InventoryValidationError("inventory file could not be read") from exc
    if size > max_file_bytes:
        raise InventoryValidationError(f"inventory file exceeds the {max_file_bytes}-byte limit")

    records: list[ImportVehicle] = []
    source_ids: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if header is None:
                raise InventoryValidationError("inventory file is empty")
            if tuple(header) != EXPECTED_COLUMNS:
                raise _validation_error(None, "columns", "must exactly match the documented CSV")

            for row_number, values in enumerate(reader, start=2):
                if len(records) >= max_records:
                    raise InventoryValidationError(
                        f"inventory file exceeds the {max_records}-record limit"
                    )
                if len(values) != len(EXPECTED_COLUMNS):
                    raise _validation_error(
                        row_number,
                        "columns",
                        f"expected {len(EXPECTED_COLUMNS)} values",
                    )
                fields = dict(zip(EXPECTED_COLUMNS, values, strict=True))
                source_id = _required_text(
                    fields["stock_number"], row=row_number, field="stock_number", maximum=200
                )
                if source_id in source_ids:
                    raise _validation_error(row_number, "stock_number", "duplicates an earlier row")
                source_ids.add(source_id)
                year = _integer(
                    fields["year"],
                    row=row_number,
                    field="year",
                    minimum=1886,
                    maximum=2100,
                    required=True,
                )
                assert year is not None
                records.append(
                    ImportVehicle(
                        source_id=source_id,
                        year=year,
                        make=_required_text(
                            fields["make"], row=row_number, field="make", maximum=100
                        ),
                        model=_required_text(
                            fields["model"], row=row_number, field="model", maximum=100
                        ),
                        trim=_optional_text(fields["trim"], row=row_number, field="trim"),
                        body_type=_optional_text(
                            fields["body_type"], row=row_number, field="body_type"
                        ),
                        condition=_optional_text(
                            fields["condition"], row=row_number, field="condition"
                        ),
                        price_cents=_price_cents(fields["price"], row=row_number),
                        mileage=_integer(
                            fields["mileage"],
                            row=row_number,
                            field="mileage",
                            minimum=0,
                            maximum=MAX_SQLITE_INTEGER,
                            required=False,
                        ),
                        exterior_color=_optional_text(
                            fields["exterior_color"], row=row_number, field="exterior_color"
                        ),
                        drivetrain=_optional_text(
                            fields["drivetrain"], row=row_number, field="drivetrain"
                        ),
                        transmission=_optional_text(
                            fields["transmission"], row=row_number, field="transmission"
                        ),
                        fuel=_optional_text(fields["fuel"], row=row_number, field="fuel"),
                    )
                )
    except OSError as exc:
        raise InventoryValidationError("inventory file could not be read") from exc
    except (UnicodeError, csv.Error) as exc:
        raise InventoryValidationError("inventory file must be valid UTF-8 CSV") from exc

    if not records:
        raise InventoryValidationError("inventory file contains no data records")
    return tuple(records)


class InventoryImportService:
    def __init__(
        self,
        session_factory: SessionFactory,
        repository: InventoryImportRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or InventoryImportRepository()

    def import_records(
        self, dealership_slug: str, records: Sequence[ImportVehicle]
    ) -> ImportResult:
        with self._session_factory.begin() as session:
            dealership_id = self._repository.dealership_id(session, dealership_slug)
            if dealership_id is None:
                raise DealershipNotFoundError(
                    f"configured dealership is not present in storage: {dealership_slug}"
                )
            result = self._repository.upsert(session, dealership_id, records)
        return result
