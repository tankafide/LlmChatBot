from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from test_nhtsa_client import detail, discovery, recall, run, vehicle

from autoassist.integrations.nhtsa import LookupBudget, NhtsaClient, NhtsaError
from autoassist.safety.rendering import render_safety
from autoassist.safety.service import SafetyService


@pytest.mark.parametrize(
    "stars,expected",
    [
        (["5", "4", "5", "4"], "available"),
        (["5", "Not Rated", None, "nonsense"], "partial"),
        (["Not Rated"] * 4, "unrated"),
        ([None, "Not Rated", True, ""], "no_ratings"),
    ],
)
async def test_crash_category_statuses_and_warning_coverage(stars, expected) -> None:
    payload = detail()
    row = payload["Results"][0]
    for key, value in zip(
        ("OverallRating", "OverallFrontCrashRating", "OverallSideCrashRating", "RolloverRating"),
        stars,
        strict=True,
    ):
        row[key] = value
    row.update(
        {
            "RolloverConcern": "Synthetic concern",
            "NHTSAForwardCollisionWarning": "Standard",
            "OtherWarning": {"invalid": True},
            "dynamicTipResult": "No Tip",
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=payload if "VehicleId" in request.url.path else discovery()
            )
        )
    ) as client:
        result = await SafetyService(NhtsaClient(client)).crash(vehicle(), run())
    assert result.status == expected
    assert result.notes == {"RolloverConcern": "Synthetic concern"}
    assert result.concern_notes_omitted == 1
    reply = render_safety([result])
    assert (
        "Synthetic concern" in reply
        and "incomplete" in reply
        and "dynamicTipResult: No Tip" in reply
    )


@pytest.mark.parametrize(
    "mutation", ["wrong-id", "wrong-year", "wrong-description", "multiple", "wrong-case"]
)
async def test_bad_detail_never_produces_stars(mutation) -> None:
    payload = detail()
    row = payload["Results"][0]
    if mutation == "wrong-id":
        row["VehicleId"] = 999
    elif mutation == "wrong-year":
        row["ModelYear"] = 2021
    elif mutation == "wrong-description":
        row["VehicleDescription"] = "2022 Toyota RAV4 SUV AWD"
    elif mutation == "multiple":
        payload["Results"].append(dict(row))
        payload["Count"] = 2
    else:
        payload["results"] = payload.pop("Results")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=payload if "VehicleId" in request.url.path else discovery()
            )
        )
    ) as client:
        result = await SafetyService(NhtsaClient(client)).crash(vehicle(), run())
    assert result.reason == "invalid_response" and not result.categories


async def test_stream_is_closed_on_timeout_and_response_limit() -> None:
    class GatedStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"{"
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = GatedStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(NhtsaError, match="timeout"):
            await NhtsaClient(client).get(
                "https://api.nhtsa.gov/test",
                "synthetic",
                LookupBudget(time.monotonic() + 60, elapsed=19.99),
            )
    assert stream.closed


async def test_three_get_limit_and_four_gated_lookups() -> None:
    entered = 0
    ready, release = asyncio.Event(), asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal entered
        entered += 1
        if entered == 4:
            ready.set()
        await release.wait()
        return httpx.Response(200, json={"Count": 0, "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = NhtsaClient(client)
        tasks = [
            asyncio.create_task(SafetyService(adapter).recalls(vehicle(), run())) for _ in range(4)
        ]
        try:
            await asyncio.wait_for(ready.wait(), 2)
            assert entered == 4 and not any(task.done() for task in tasks)
        finally:
            release.set()
            results = await asyncio.gather(*tasks)
        assert all(result.status == "empty" for result in results)
        budget = LookupBudget(time.monotonic() + 60)
        for _ in range(3):
            await adapter.get("https://api.nhtsa.gov/test", "synthetic", budget)
        with pytest.raises(NhtsaError, match="budget_exhausted"):
            await adapter.get("https://api.nhtsa.gov/test", "synthetic", budget)
        assert budget.calls == 3 and entered == 7


def test_boundary_size_json_parse_measurement(capsys) -> None:
    # Measurement only; no noisy latency correctness threshold.
    payload = {"Count": 200, "results": [recall(str(i)) for i in range(200)], "padding": ""}
    encoded = json.dumps(payload).encode()
    payload["padding"] = "x" * (512 * 1024 - len(encoded))
    encoded = json.dumps(payload).encode()
    assert len(encoded) == 512 * 1024
    started = time.perf_counter()
    parsed = json.loads(encoded)
    elapsed = time.perf_counter() - started
    assert len(parsed["results"]) == 200
    print(f"512 KiB JSON parse: {elapsed * 1000:.3f} ms")
    assert "512 KiB" in capsys.readouterr().out


async def test_excessively_nested_json_preserves_the_other_safety_branch() -> None:
    calls = []
    responses = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        response = (
            httpx.Response(200, json={"Count": 0, "results": []})
            if "recalls" in request.url.path
            else httpx.Response(200, content=b"[" * 2000 + b"]" * 2000)
        )
        responses.append(response)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SafetyService(NhtsaClient(client))
        state = run()
        recalls = await service.recalls(vehicle(), state)
        crash = await service.crash(vehicle(), state)
    assert recalls.status == "empty"
    assert crash.status == "unavailable" and crash.reason == "invalid_response"
    reply = render_safety([recalls, crash])
    assert "No campaigns returned" in reply and "Crash ratings: unavailable" in reply
    assert len(calls) == 2 and all(response.is_closed for response in responses)
