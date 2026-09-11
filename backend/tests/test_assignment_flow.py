from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from conftest import write_config
from container_acceptance_app import runner_factory
from fastapi.testclient import TestClient

from autoassist.app import create_app
from autoassist.config import Settings

for _parent in Path(__file__).resolve().parents:
    _scripts = _parent / "scripts"
    if (_scripts / "assignment_scenario.py").is_file():
        sys.path.insert(0, str(_scripts))
        break

from assignment_scenario import after_restart, before_restart  # noqa: E402


def _root_file(relative: str) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"required repository file is unavailable: {relative}")


def _expected_vehicle() -> dict[str, Any]:
    with _root_file("docs/context/inventory/data.csv").open(newline="", encoding="utf-8") as source:
        row = next(csv.DictReader(source))
    return {
        "source_id": row["stock_number"],
        "make": row["make"],
        "model": row["model"],
        "year": int(row["year"]),
        "price": f"{int(row['price'])}.00",
        "body_type": row["body_type"],
    }


def _adapter(client: TestClient):
    def request(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        response = client.request(method, path, json=body)
        decoded = response.json()
        assert isinstance(decoded, dict)
        return response.status_code, decoded

    return request


def test_complete_assignment_flow_survives_application_recreation(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'assignment.db'}",
        config_file=write_config(tmp_path / "dealerships.json"),
    )
    monkeypatch.setenv("AUTOASSIST_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("AUTOASSIST_CONFIG_FILE", str(settings.config_file))
    monkeypatch.setenv("TEST_XAI_API_KEY", "deterministic-test-key")

    environment = os.environ.copy()
    imported = subprocess.run(
        [
            sys.executable,
            "-m",
            "autoassist.inventory.import_cli",
            "--file",
            str(_root_file("docs/context/inventory/data.csv")),
            "--dealership",
            "mia-motors",
            "--server-stopped",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    assert imported.returncode == 0, imported.stderr
    assert "inserted=127" in imported.stdout

    with TestClient(create_app(settings, runner_factory=runner_factory)) as client:
        state = before_restart(_adapter(client), _expected_vehicle())

    with TestClient(create_app(settings, runner_factory=runner_factory)) as restarted:
        result = after_restart(_adapter(restarted), state)
    assert result["follow_up"]["selected_vehicle_id"] == state["vehicle_id"]
