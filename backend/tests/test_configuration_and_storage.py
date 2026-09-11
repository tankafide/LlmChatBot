from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import write_config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from autoassist.app import create_app
from autoassist.config import ConfigurationError, Settings, load_runtime_config
from autoassist.db.database import (
    create_database_engine,
    initialize_schema,
    make_session_factory,
)
from autoassist.db.models import Dealership, Vehicle
from autoassist.inventory.records import normalize_text


def test_configuration_accepts_multiple_named_connections_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    valid_path = write_config(tmp_path / "valid.json")
    config = load_runtime_config(valid_path)
    assert set(config.connections) == {"primary-grok", "secondary-grok"}

    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(
        '{"connections": {"same": {"provider": "xai", "model": "one", '
        '"api_key_env": "KEY"}, "same": {"provider": "xai", "model": "two", '
        '"api_key_env": "KEY"}}, "dealerships": []}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_runtime_config(duplicate_path)


def test_repeat_startup_preserves_dealership_uuid_and_vehicle(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'persistent.db'}",
        config_file=write_config(tmp_path / "config.json"),
    )
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        dealership_id = client.get("/dealerships").json()["items"][0]["id"]
        with first_app.state.session_factory.begin() as session:
            session.add(
                Vehicle(
                    dealership_id=dealership_id,
                    source_id="stable-1",
                    make="Toyota",
                    make_key=normalize_text("Toyota"),
                    model="Camry",
                    model_key=normalize_text("Camry"),
                    year=2022,
                    price_cents=2500000,
                    body_type="Sedan",
                    body_type_key=normalize_text("Sedan"),
                )
            )

    second_app = create_app(settings)
    with TestClient(second_app) as client:
        assert client.get("/dealerships").json()["items"][0]["id"] == dealership_id
        response = client.get(f"/dealerships/{dealership_id}/vehicles")
        assert [item["source_id"] for item in response.json()["items"]] == ["stable-1"]


def test_invalid_reconfiguration_rolls_back_all_dealership_updates(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'rollback.db'}"
    initial_config = write_config(tmp_path / "initial.json")
    settings = Settings(database_url=database_url, config_file=initial_config)
    with TestClient(create_app(settings)):
        pass

    invalid_config = tmp_path / "invalid.json"
    invalid_config.write_text(
        json.dumps(
            {
                "connections": {
                    "primary-grok": {
                        "provider": "xai",
                        "model": "test-model",
                        "api_key_env": "TEST_KEY",
                    }
                },
                "dealerships": [
                    {
                        "slug": "mia-motors",
                        "name": "Should Roll Back",
                        "default_connection": "primary-grok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with (
        pytest.raises(ConfigurationError),
        TestClient(create_app(Settings(database_url=database_url, config_file=invalid_config))),
    ):
        pass

    engine = create_database_engine(database_url)
    try:
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            names = dict(session.execute(select(Dealership.slug, Dealership.name)).all())
        assert names == {"lakeview-auto": "Lakeview Auto", "mia-motors": "Mia Motors"}
    finally:
        engine.dispose()


def test_foreign_keys_are_enforced_on_every_connection(application_settings: Settings) -> None:
    engine = create_database_engine(application_settings.database_url)
    try:
        initialize_schema(engine)
        session_factory = make_session_factory(engine)
        with pytest.raises(IntegrityError), session_factory.begin() as session:
            session.add(
                Vehicle(
                    dealership_id="00000000-0000-0000-0000-000000000000",
                    source_id="orphan",
                    make="Test",
                    make_key="test",
                    model="Test",
                    model_key="test",
                    year=2020,
                )
            )
            session.flush()
    finally:
        engine.dispose()


def test_unusable_storage_fails_startup_and_openapi_needs_no_storage(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}",
        config_file=write_config(tmp_path / "config.json"),
    )
    app = create_app(settings)
    assert "/dealerships/{dealership_id}/vehicles" in app.openapi()["paths"]
    with pytest.raises(OperationalError), TestClient(app):
        pass
