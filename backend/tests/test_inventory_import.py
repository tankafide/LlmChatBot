from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import write_config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from autoassist.app import create_app
from autoassist.config import Settings, load_runtime_config
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import (
    SessionFactory,
    create_database_engine,
    initialize_schema,
    make_session_factory,
)
from autoassist.db.models import Dealership, Vehicle
from autoassist.inventory.import_cli import main as import_main
from autoassist.inventory.import_repository import InventoryImportRepository
from autoassist.inventory.importer import (
    InventoryImportService,
    InventoryValidationError,
    parse_inventory_csv,
)
from autoassist.inventory.records import ImportVehicle


def find_real_inventory() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "context" / "inventory" / "data.csv"
        if candidate.is_file():
            return candidate
    raise RuntimeError("the committed assignment inventory fixture is unavailable")


REAL_INVENTORY = find_real_inventory()


def configured_storage(tmp_path: Path) -> tuple[Settings, SessionFactory]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'inventory.db'}",
        config_file=write_config(tmp_path / "dealerships.json"),
    )
    engine = create_database_engine(settings.database_url)
    initialize_schema(engine)
    session_factory = make_session_factory(engine)
    bootstrap_dealerships(session_factory, load_runtime_config(settings.config_file))
    return settings, session_factory


def vehicle_rows(session_factory: SessionFactory, slug: str) -> list[Vehicle]:
    with session_factory() as session:
        return list(
            session.scalars(
                select(Vehicle)
                .join(Dealership, Vehicle.dealership_id == Dealership.id)
                .where(Dealership.slug == slug)
                .order_by(Vehicle.source_id)
            )
        )


def test_real_csv_mapping_and_expected_values() -> None:
    records = parse_inventory_csv(REAL_INVENTORY)

    assert len(records) == 127
    assert records[0] == ImportVehicle(
        source_id="AA-1001",
        year=2022,
        make="Toyota",
        model="RAV4",
        trim="LE",
        body_type="SUV",
        condition="Used",
        price_cents=2_633_500,
        mileage=15_819,
        exterior_color="Silver Sky Metallic",
        drivetrain="FWD",
        transmission="Automatic",
        fuel="Gasoline",
    )
    assert records[-1].source_id == "AA-1127"
    assert records[-1].model == "Carnival"
    assert records[-1].price_cents == 4_016_700


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "empty"),
        (",".join((*["wrong"] * 12, "columns")) + "\n", "columns"),
        (
            ",".join(
                (
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
            )
            + "\nAA-1,2022,Toyota,Camry,LE,Sedan,Used,19999.95,10,Blue,FWD,Auto,Gas\n",
            "whole US-dollar",
        ),
        (
            ",".join(
                (
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
            )
            + "\nAA-1,2022,,Camry,LE,Sedan,Used,19999,10,Blue,FWD,Auto,Gas\n",
            "value is required",
        ),
    ],
)
def test_corrupt_csv_is_rejected_without_raw_row_values(
    tmp_path: Path, contents: str, message: str
) -> None:
    path = tmp_path / "corrupt.csv"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(InventoryValidationError, match=message) as captured:
        parse_inventory_csv(path)

    assert "19999.95" not in str(captured.value)


def test_duplicate_source_ids_and_file_bounds_are_rejected(tmp_path: Path) -> None:
    lines = REAL_INVENTORY.read_text(encoding="utf-8").splitlines()
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("\n".join((lines[0], lines[1], lines[1])), encoding="utf-8")

    with pytest.raises(InventoryValidationError, match="duplicates an earlier row"):
        parse_inventory_csv(duplicate)
    with pytest.raises(InventoryValidationError, match="byte limit"):
        parse_inventory_csv(REAL_INVENTORY, max_file_bytes=1)
    with pytest.raises(InventoryValidationError, match="record limit"):
        parse_inventory_csv(REAL_INVENTORY, max_records=1)


def test_import_is_idempotent_updates_changed_rows_retains_absent_rows_and_isolates_dealers(
    tmp_path: Path,
) -> None:
    _, session_factory = configured_storage(tmp_path)
    records = parse_inventory_csv(REAL_INVENTORY)
    service = InventoryImportService(session_factory)

    first = service.import_records("mia-motors", records)
    initial_rows = vehicle_rows(session_factory, "mia-motors")
    initial_ids = {row.source_id: row.id for row in initial_rows}
    assert (first.inserted, first.updated, first.unchanged) == (127, 0, 0)

    repeat = service.import_records("mia-motors", records)
    assert (repeat.inserted, repeat.updated, repeat.unchanged) == (0, 0, 127)
    assert {
        row.source_id: row.id for row in vehicle_rows(session_factory, "mia-motors")
    } == initial_ids

    changed = replace(records[0], price_cents=records[0].price_cents + 100)
    update = service.import_records("mia-motors", (changed,))
    assert (update.inserted, update.updated, update.unchanged) == (0, 1, 0)
    mia_rows = vehicle_rows(session_factory, "mia-motors")
    assert len(mia_rows) == 127
    assert mia_rows[0].id == initial_ids["AA-1001"]
    assert mia_rows[0].price_cents == 2_633_600

    other = service.import_records("lakeview-auto", (records[0],))
    assert other.inserted == 1
    lakeview_row = vehicle_rows(session_factory, "lakeview-auto")[0]
    assert lakeview_row.id != initial_ids["AA-1001"]
    assert lakeview_row.price_cents == 2_633_500


class FailingAfterFlushRepository(InventoryImportRepository):
    def upsert(
        self, session: Session, dealership_id: str, records: tuple[ImportVehicle, ...]
    ) -> object:
        super().upsert(session, dealership_id, records)
        session.flush()
        raise RuntimeError("injected mid-batch failure")


def test_mid_batch_and_commit_failures_roll_back_the_whole_import(tmp_path: Path) -> None:
    _, session_factory = configured_storage(tmp_path)
    records = parse_inventory_csv(REAL_INVENTORY)[:2]

    failing_service = InventoryImportService(session_factory, FailingAfterFlushRepository())
    with pytest.raises(RuntimeError, match="injected"):
        failing_service.import_records("mia-motors", records)
    assert vehicle_rows(session_factory, "mia-motors") == []

    engine = session_factory.kw["bind"]

    def fail_commit(*_args: object) -> None:
        raise RuntimeError("injected commit failure")

    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit"):
            InventoryImportService(session_factory).import_records("mia-motors", records)
    finally:
        event.remove(engine, "commit", fail_commit)
    assert vehicle_rows(session_factory, "mia-motors") == []


def test_competing_writer_fails_within_busy_timeout_and_preserves_committed_data(
    tmp_path: Path,
) -> None:
    _, session_factory = configured_storage(tmp_path)
    records = parse_inventory_csv(REAL_INVENTORY)
    service = InventoryImportService(session_factory)
    service.import_records("mia-motors", (records[0],))

    with session_factory() as lock_session:
        dealership = lock_session.scalar(select(Dealership).where(Dealership.slug == "mia-motors"))
        assert dealership is not None
        dealership.name = "Uncommitted lock holder"
        lock_session.flush()

        started = time.monotonic()
        with pytest.raises(OperationalError):
            service.import_records("mia-motors", (records[1],))
        assert time.monotonic() - started < 6.5
        lock_session.rollback()

    rows = vehicle_rows(session_factory, "mia-motors")
    assert [row.source_id for row in rows] == ["AA-1001"]


def test_cli_imports_before_api_startup_and_detail_fields_survive_recreation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'cli.db'}",
        config_file=write_config(tmp_path / "dealerships.json"),
    )
    monkeypatch.setenv("AUTOASSIST_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("AUTOASSIST_CONFIG_FILE", str(settings.config_file))

    result = import_main(
        [
            "--file",
            str(REAL_INVENTORY),
            "--dealership",
            "mia-motors",
            "--server-stopped",
        ]
    )
    assert result == 0
    assert "inserted=127 updated=0 unchanged=0" in capsys.readouterr().out

    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            dealership_id = next(
                item["id"]
                for item in client.get("/dealerships").json()["items"]
                if item["slug"] == "mia-motors"
            )
            search = client.get(
                f"/dealerships/{dealership_id}/vehicles",
                params={
                    "make": "Toyota",
                    "model": "RAV4",
                    "year_min": 2022,
                    "year_max": 2022,
                    "price_min": "26335.00",
                    "price_max": "26335.00",
                },
            )
            assert search.status_code == 200
            vehicle_id = search.json()["items"][0]["id"]
            detail = client.get(f"/dealerships/{dealership_id}/vehicles/{vehicle_id}").json()
            assert detail["source_id"] == "AA-1001"
            assert detail["trim"] == "LE"
            assert detail["mileage"] == 15_819
            assert detail["exterior_color"] == "Silver Sky Metallic"


def test_abrupt_process_stop_before_commit_leaves_no_partial_inventory(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'crash.db'}",
        config_file=write_config(tmp_path / "dealerships.json"),
    )
    marker = tmp_path / "after-flush.marker"
    script = r"""
import sys
import time
from pathlib import Path
from sqlalchemy import event
from autoassist.config import load_runtime_config
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import create_database_engine, initialize_schema, make_session_factory
from autoassist.inventory.importer import InventoryImportService, parse_inventory_csv

database_url, config_path, csv_path, marker_path = sys.argv[1:]
engine = create_database_engine(database_url)
initialize_schema(engine)
factory = make_session_factory(engine)
bootstrap_dealerships(factory, load_runtime_config(Path(config_path)))

@event.listens_for(factory.class_, "after_flush_postexec")
def pause_after_writes(*_args):
    Path(marker_path).write_text("ready", encoding="utf-8")
    while True:
        time.sleep(1)

InventoryImportService(factory).import_records("mia-motors", parse_inventory_csv(Path(csv_path)))
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            settings.database_url,
            str(settings.config_file),
            str(REAL_INVENTORY),
            str(marker),
        ]
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "importer did not reach the post-write, pre-commit gate"
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    engine = create_database_engine(settings.database_url)
    try:
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Vehicle)) == 0
        records = parse_inventory_csv(REAL_INVENTORY)
        result = InventoryImportService(session_factory).import_records("mia-motors", records)
        assert result.inserted == 127
    finally:
        engine.dispose()
