from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoassist.app import create_app
from autoassist.config import Settings


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
