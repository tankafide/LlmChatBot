from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from autoassist.app import create_app
from autoassist.config import ConfigurationError, Settings, load_runtime_config


def test_normalized_connection_collisions_reject_startup_without_updates(
    application_settings: Settings,
) -> None:
    with TestClient(create_app(application_settings)) as client:
        original_dealerships = client.get("/dealerships").json()

    path = application_settings.config_file
    original_config = path.read_text(encoding="utf-8")
    config = json.loads(original_config)
    config["connections"][" primary-grok "] = config["connections"]["secondary-grok"]
    config["dealerships"][0]["name"] = "Must not be persisted"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConfigurationError), TestClient(create_app(application_settings)):
        pass

    database_path = make_url(application_settings.database_url).database
    with closing(sqlite3.connect(database_path)) as connection:
        persisted = connection.execute(
            "SELECT id, slug, name FROM dealerships ORDER BY slug"
        ).fetchall()
    assert persisted == [
        (item["id"], item["slug"], item["name"]) for item in original_dealerships["items"]
    ]

    path.write_text(original_config, encoding="utf-8")
    with TestClient(create_app(application_settings)) as client:
        assert client.get("/dealerships").json() == original_dealerships


def test_unique_connection_names_can_still_be_trimmed(application_settings: Settings) -> None:
    path = application_settings.config_file
    config = json.loads(path.read_text(encoding="utf-8"))
    connection = config["connections"].pop("primary-grok")
    config["connections"][" primary-grok "] = connection
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_runtime_config(path).connections["primary-grok"].model == connection["model"]


@pytest.mark.parametrize("endpoint", ["health", "dealerships", "search", "detail"])
def test_locked_storage_returns_sanitized_503_and_recovers(
    client: TestClient, endpoint: str
) -> None:
    app = client.app
    dealership_id = client.get("/dealerships").json()["items"][0]["id"]
    search_path = f"/dealerships/{dealership_id}/vehicles"
    paths = {
        "health": "/health",
        "dealerships": "/dealerships",
        "search": search_path,
        "detail": f"{search_path}/00000000-0000-0000-0000-000000000001",
    }
    # Lock only the fixture's temporary SQLite file, with a separate connection.
    lock = sqlite3.connect(app.state.engine.url.database, autocommit=True)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        response = client.get(paths[endpoint])
        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "storage_unavailable",
                "message": "Inventory storage is unavailable.",
            }
        }
    finally:
        lock.execute("ROLLBACK")
        lock.close()

    assert client.get("/health").status_code == 200
    assert client.get(search_path).status_code == 200


@pytest.mark.parametrize("endpoint", ["health", "dealerships", "search", "detail"])
def test_schema_defects_propagate_instead_of_becoming_storage_503(
    client: TestClient, endpoint: str
) -> None:
    app = client.app
    dealership_id = client.get("/dealerships").json()["items"][0]["id"]
    search_path = f"/dealerships/{dealership_id}/vehicles"
    paths = {
        "health": "/health",
        "dealerships": "/dealerships",
        "search": search_path,
        "detail": f"{search_path}/00000000-0000-0000-0000-000000000001",
    }
    with app.state.engine.begin() as connection:
        if endpoint == "dealerships":
            connection.exec_driver_sql("ALTER TABLE dealerships DROP COLUMN name")
        elif endpoint == "health":
            connection.exec_driver_sql("DROP TABLE vehicles")
        else:
            connection.exec_driver_sql("ALTER TABLE vehicles DROP COLUMN trim")

    # TestClient surfaces the original server exception; Uvicorn logs it and sends 500.
    with pytest.raises(OperationalError, match="no such (column|table)"):
        client.get(paths[endpoint])
