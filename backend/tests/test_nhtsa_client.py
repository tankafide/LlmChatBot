"""Synthetic upstream fixtures; never assert live NHTSA campaign counts."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import httpx
import pytest

from autoassist.integrations.nhtsa import LookupBudget, NhtsaClient
from autoassist.inventory.records import VehicleRecord
from autoassist.safety.parsing import category
from autoassist.safety.rendering import render_safety
from autoassist.safety.service import SafetyRun, SafetyService


def vehicle() -> VehicleRecord:
    return VehicleRecord(
        "inventory-id",
        "AA-1001",
        "Toyota",
        "RAV4",
        2022,
        2633500,
        "SUV",
        "LE",
        "Used",
        15819,
        "Silver",
        "FWD",
        "Automatic",
        "Gasoline",
    )


def recall(number: str = "SYNTHETIC-1") -> dict[str, object]:
    return {
        "ModelYear": "2022",
        "Make": "TOYOTA",
        "Model": "RAV4",
        "NHTSACampaignNumber": number,
        "Component": "Synthetic component",
        "Summary": "Synthetic summary",
        "Consequence": "Synthetic consequence",
        "Remedy": "Contact manufacturer",
        "ReportReceivedDate": "01/02/2024",
    }


def discovery(descriptions: list[str] | None = None) -> dict[str, object]:
    descriptions = descriptions or ["2022 Toyota RAV4 SUV FWD"]
    return {
        "Count": len(descriptions),
        "Results": [
            {"VehicleId": 100 + i, "VehicleDescription": text}
            for i, text in enumerate(descriptions)
        ],
    }


def detail(
    description: str = "2022 Toyota RAV4 SUV FWD", identifier: int = 100
) -> dict[str, object]:
    return {
        "Count": 1,
        "Results": [
            {
                "VehicleId": identifier,
                "VehicleDescription": description,
                "ModelYear": 2022,
                "Make": "Toyota",
                "Model": "RAV4",
                "OverallRating": "5",
                "OverallFrontCrashRating": "4",
                "OverallSideCrashRating": "5",
                "RolloverRating": "4",
            }
        ],
    }


def run() -> SafetyRun:
    return SafetyRun(LookupBudget(time.monotonic() + 60))


@pytest.mark.parametrize(
    "value,status,stars",
    [
        (1, "rated", 1),
        (" 5 ", "rated", 5),
        ("Not Rated", "not_rated", None),
        (None, "missing", None),
        ("", "missing", None),
        (0, "invalid", None),
        (6, "invalid", None),
        (True, "invalid", None),
        (1.5, "invalid", None),
        ("garbage", "invalid", None),
        (float("nan"), "invalid", None),
    ],
)
def test_category(value: object, status: str, stars: int | None) -> None:
    result = category(value)
    assert (result.status, result.stars) == (status, stars)


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"Count": 0, "results": []}, "empty"),
        ({"Count": 1, "results": [recall()]}, "available"),
        ({"Count": 0, "Results": []}, "unavailable"),
        ({"Count": False, "results": []}, "unavailable"),
        ({"Count": 1, "results": []}, "unavailable"),
        ({"Count": 2, "results": [recall(), recall()]}, "unavailable"),
        ({"Count": 1, "results": [{**recall(), "Model": "RAV4 Hybrid"}]}, "unavailable"),
        ({"Count": 1, "results": [{**recall(), "ReportReceivedDate": "invalid"}]}, "unavailable"),
        ({"Count": 1, "results": [{**recall(), "parkIt": "false"}]}, "unavailable"),
    ],
)
async def test_recall_envelope_and_identity(payload: object, status: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SafetyService(NhtsaClient(client))
        state = run()
        result = await service.recalls(vehicle(), state)
        assert result.status == status
        assert await service.recalls(vehicle(), state) is result
        assert len(calls) == 1
        assert dict(calls[0].url.params) == {"make": "Toyota", "model": "RAV4", "modelYear": "2022"}
        if status == "unavailable":
            assert result.total_count is None and "unavailable" in render_safety([result])


async def test_urgent_aggregate_and_utf8_excerpts() -> None:
    rows = [{**recall(str(i)), "Summary": "車" * 1000, "parkIt": i >= 5} for i in range(8)]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"Count": 8, "results": rows})
        )
    ) as client:
        result = await SafetyService(NhtsaClient(client)).recalls(vehicle(), run())
    assert result.status == "available" and result.urgent_count == 3
    assert result.campaigns[0].park_it
    assert result.omitted_count >= 3
    assert "summary" in result.campaigns[0].clipped_fields
    assert len(result.model_dump_json().encode()) <= 12 * 1024
    assert "park it" in render_safety([result])


@pytest.mark.parametrize(
    "descriptions,expected,gets",
    [
        (["2022 Toyota RAV4 SUV AWD", "2022 Toyota RAV4 SUV FWD"], "available", 2),
        (["2022 Toyota RAV4 SUV AWD"], "no_record", 1),
        (["2022 Toyota RAV4 Hybrid SUV FWD"], "no_record", 1),
        (["2022 Toyota RAV4 SUV FWD special"], "ambiguous", 1),
    ],
)
async def test_conservative_matching(descriptions: list[str], expected: str, gets: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "VehicleId" in request.url.path:
            identifier = int(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, json=detail(descriptions[identifier - 100], identifier))
        return httpx.Response(200, json=discovery(descriptions))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SafetyService(NhtsaClient(client)).crash(vehicle(), run())
    assert result.status == expected
    assert len(calls) == gets


@pytest.mark.parametrize("status_code", [301, 404, 429, 500])
async def test_status_no_retries(status_code: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status_code, headers={"Location": "https://example.org"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SafetyService(NhtsaClient(client)).recalls(vehicle(), run())
    assert result.reason == "http_error" and len(calls) == 1


async def test_budget_and_response_limit() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (512 * 1024 + 1))
        )
    ) as client:
        service = SafetyService(NhtsaClient(client))
        assert (await service.recalls(vehicle(), run())).reason == "response_limit"
        for budget in (
            LookupBudget(time.monotonic() + 5),
            LookupBudget(time.monotonic() + 60, calls=3),
        ):
            assert (
                await service.recalls(vehicle(), SafetyRun(budget))
            ).reason == "budget_exhausted"


async def test_cancel_propagates_and_other_work_progresses() -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"Count": 0, "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(SafetyService(NhtsaClient(client)).recalls(vehicle(), run()))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()


async def test_independent_branch_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "recalls" in request.url.path:
            return httpx.Response(200, json={"Count": 0, "results": []})
        raise httpx.ReadTimeout("synthetic")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SafetyService(NhtsaClient(client))
        state = run()
        recalls = await service.recalls(vehicle(), state)
        crash = await service.crash(vehicle(), state)
    assert recalls.status == "empty" and crash.reason == "timeout"
    assert state.budget.calls == 2
    assert "No campaigns returned" in render_safety([recalls, crash])


async def test_missing_attribute_needs_confirmation() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=discovery()))
    ) as client:
        result = await SafetyService(NhtsaClient(client)).crash(
            replace(vehicle(), drivetrain=None), run()
        )
    assert result.status == "ambiguous"
