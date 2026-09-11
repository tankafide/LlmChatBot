from __future__ import annotations

import asyncio

import httpx
from pydantic_ai.models.function import FunctionModel
from safety_scripted_model import ScriptedSafety

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunRequest, ChatRunResult
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.inventory.records import InventoryFilters, VehicleRecord
from autoassist.inventory.service import InventoryService
from autoassist.safety.service import SafetyService


class DeterministicAcceptanceRunner:
    """Test-only runner used by the disposable container acceptance harness."""

    def __init__(self, inventory: InventoryService) -> None:
        self._inventory = inventory
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(self._nhtsa))
        self._safety_runner = PydanticChatRunner(
            FunctionModel(ScriptedSafety()),
            inventory,
            safety=SafetyService(NhtsaClient(self._client)),
        )

    @staticmethod
    def _nhtsa(request: httpx.Request) -> httpx.Response:
        descriptions = [
            "2022 Toyota RAV4 SUV FWD variant alpha",
            "2022 Toyota RAV4 SUV FWD variant beta",
        ]
        if "recalls" in request.url.path:
            return httpx.Response(200, json={"Count": 0, "results": []})
        if "VehicleId" in request.url.path:
            assert request.url.path.endswith("/202")
            return httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Results": [
                        {
                            "VehicleId": 202,
                            "VehicleDescription": descriptions[1],
                            "ModelYear": 2022,
                            "Make": "Toyota",
                            "Model": "RAV4",
                            "OverallRating": "5",
                            "OverallFrontCrashRating": "4",
                            "OverallSideCrashRating": "5",
                            "RolloverRating": "Not Rated",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "Count": 2,
                "Results": [
                    {"VehicleId": 201 + i, "VehicleDescription": desc}
                    for i, desc in enumerate(descriptions)
                ],
            },
        )

    async def run(self, request: ChatRunRequest) -> ChatRunResult:
        if request.text in {"both", "202", "recalls"}:
            return await self._safety_runner.run(request)
        if request.selected_vehicle_id is not None:
            vehicle = await asyncio.to_thread(
                self._inventory.get, request.dealership_id, request.selected_vehicle_id
            )
            return ChatRunResult(
                reply=self._details(vehicle),
                replay_json='{"messages_json":"[]"}',
            )
        if "AA-1001" in request.text:
            vehicle = await asyncio.to_thread(
                self._inventory.get_by_source_id, request.dealership_id, "AA-1001"
            )
            return ChatRunResult(
                reply=f"Selected {self._identity(vehicle)}.",
                replay_json='{"messages_json":"[]"}',
                selection_action="set",
                selected_vehicle_id=vehicle.id,
            )
        if request.presented_vehicle_ids:
            vehicle_id = request.presented_vehicle_ids[0]
            vehicle = await asyncio.to_thread(
                self._inventory.get, request.dealership_id, vehicle_id
            )
            return ChatRunResult(
                reply=f"Selected {self._identity(vehicle)}.",
                replay_json='{"messages_json":"[]"}',
                selection_action="set",
                selected_vehicle_id=vehicle.id,
            )
        page = await asyncio.to_thread(
            self._inventory.search,
            request.dealership_id,
            InventoryFilters(make="Toyota", model="RAV4", year_min=2022, year_max=2022, limit=2),
        )
        lines = [f"{index}. {self._identity(item)}" for index, item in enumerate(page.items, 1)]
        return ChatRunResult(
            reply="\n".join(lines),
            replay_json='{"messages_json":"[]"}',
            presented_vehicle_ids=tuple(item.id for item in page.items),
            selection_action="clear",
        )

    async def close(self) -> None:
        await self._safety_runner.close()
        await self._client.aclose()

    @staticmethod
    def _identity(vehicle: VehicleRecord) -> str:
        return f"{vehicle.year} {vehicle.make} {vehicle.model} (stock {vehicle.source_id})"

    @classmethod
    def _details(cls, vehicle: VehicleRecord) -> str:
        price = (
            "unknown"
            if vehicle.price_cents is None
            else f"${vehicle.price_cents // 100:,}.{vehicle.price_cents % 100:02d}"
        )
        mileage = "unknown" if vehicle.mileage is None else f"{vehicle.mileage:,} miles"
        drivetrain = vehicle.drivetrain or "unknown"
        return (
            f"{cls._identity(vehicle)} — price: {price}; "
            f"mileage: {mileage}; drivetrain: {drivetrain}"
        )


def runner_factory(
    _model_name: str, _api_key: str, inventory: InventoryService
) -> DeterministicAcceptanceRunner:
    return DeterministicAcceptanceRunner(inventory)


app = create_app(runner_factory=runner_factory)
