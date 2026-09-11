"""Opt-in live safety check. Owns only a temporary SQLite database; never prints credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from autoassist.app import create_app
from autoassist.config import Settings, load_runtime_config
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import (
    create_database_engine,
    initialize_schema,
    make_session_factory,
)
from autoassist.db.models import Dealership
from autoassist.integrations.nhtsa import LookupBudget, NhtsaClient, create_client
from autoassist.inventory.importer import InventoryImportService, parse_inventory_csv
from autoassist.inventory.repository import InventoryRepository
from autoassist.inventory.service import InventoryService
from autoassist.safety.service import SafetyRun, SafetyService


async def nhtsa(inventory: InventoryService, dealer: str) -> None:
    vehicle = inventory.get_by_source_id(dealer, "AA-1001")
    async with create_client() as client:
        service = SafetyService(NhtsaClient(client))
        run = SafetyRun(LookupBudget(time.monotonic() + 60))
        for result in (
            await service.recalls(vehicle, run),
            await service.crash(vehicle, run),
        ):
            print(result.model_dump_json())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", action="store_true")
    args = parser.parse_args()
    base = Settings()
    config = load_runtime_config(base.config_file)
    print(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "pydantic_ai": version("pydantic-ai-slim"),
                "xai_sdk": version("xai-sdk"),
                "httpx": version("httpx"),
                "models": [item.model for item in config.connections.values()],
            }
        )
    )
    with tempfile.TemporaryDirectory(prefix="autoassist-live-") as directory:
        settings = Settings(
            database_url=f"sqlite:///{Path(directory).as_posix()}/live.db",
            config_file=base.config_file,
        )
        engine = create_database_engine(settings.database_url)
        sessions = make_session_factory(engine)
        try:
            initialize_schema(engine)
            bootstrap_dealerships(sessions, config)
            InventoryImportService(sessions).import_records(
                "mia-motors",
                parse_inventory_csv(Path("docs/context/inventory/data.csv")),
            )
            with sessions() as session:
                dealer = session.scalar(
                    select(Dealership.id).where(Dealership.slug == "mia-motors")
                )
            assert dealer is not None
            asyncio.run(
                nhtsa(InventoryService(sessions, InventoryRepository()), dealer)
            )
        finally:
            engine.dispose()
        if args.chat:
            with TestClient(create_app(settings)) as client:
                response = client.post(f"/dealerships/{dealer}/conversations", json={})
                if response.status_code != 201:
                    print(
                        json.dumps(
                            {
                                "live_chat": "unavailable",
                                "http_status": response.status_code,
                            }
                        )
                    )
                    raise SystemExit(1)
                conversation = response.json()["id"]
                endpoint = (
                    f"/dealerships/{dealer}/conversations/{conversation}/messages"
                )
                for text in (
                    "Show Toyota RAV4 vehicles from 2022",
                    "Select stock AA-1001",
                    "What are its recalls and crash ratings?",
                    "What is its price?",
                ):
                    response = client.post(
                        endpoint, json={"request_id": str(uuid4()), "text": text}
                    )
                    body = response.json()
                    print(
                        json.dumps(
                            {
                                "step": text,
                                "status": response.status_code,
                                "reply": body.get("assistant_message", {}).get("text"),
                                "error": body.get("error", {}).get("code"),
                            }
                        )
                    )
                    if response.status_code != 200:
                        raise SystemExit(1)


if __name__ == "__main__":
    main()
