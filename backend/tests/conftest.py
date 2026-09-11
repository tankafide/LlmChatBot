from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from autoassist.app import create_app
from autoassist.config import Settings
from autoassist.db.database import create_database_engine, database_startup_lock, initialize_schema
from autoassist.db.models import Base


@pytest.fixture
def postgres_engine() -> Iterator[Engine]:
    value = os.environ.get("AUTOASSIST_TEST_POSTGRES_URL")
    if value is None:
        pytest.skip("isolated PostgreSQL verification URL is not configured")
    if make_url(value).database != "autoassist_verify":
        raise RuntimeError("PostgreSQL tests require the autoassist_verify database")
    engine = create_database_engine(value)
    try:
        with database_startup_lock(engine):
            Base.metadata.drop_all(engine)
            initialize_schema(engine)
        yield engine
    finally:
        with database_startup_lock(engine):
            Base.metadata.drop_all(engine)
        engine.dispose()


def write_config(path: Path, *, first_name: str = "Mia Motors") -> Path:
    path.write_text(
        json.dumps(
            {
                "connections": {
                    "primary-grok": {
                        "provider": "xai",
                        "model": "test-model-one",
                        "api_key_env": "TEST_XAI_API_KEY",
                    },
                    "secondary-grok": {
                        "provider": "xai",
                        "model": "test-model-two",
                        "api_key_env": "TEST_SECONDARY_XAI_API_KEY",
                    },
                },
                "dealerships": [
                    {
                        "slug": "mia-motors",
                        "name": first_name,
                        "default_connection": "primary-grok",
                    },
                    {
                        "slug": "lakeview-auto",
                        "name": "Lakeview Auto",
                        "default_connection": "secondary-grok",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def application_settings(tmp_path: Path) -> Settings:
    config_path = write_config(tmp_path / "dealerships.json")
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'autoassist.db'}",
        config_file=config_path,
    )


@pytest.fixture
def client(application_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(application_settings)) as test_client:
        yield test_client
