from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from autoassist.observability import event
from autoassist.safety.records import Identity, Reason

BASE = "https://api.nhtsa.gov"
MAX_RESPONSE_BYTES = 512 * 1024


def recall_url(identity: Identity) -> str:
    return str(
        httpx.URL(
            BASE + "/recalls/recallsByVehicle",
            params={
                "make": identity.make,
                "model": identity.model,
                "modelYear": str(identity.year),
            },
        )
    )


def discovery_url(identity: Identity) -> str:
    return (
        f"{BASE}/SafetyRatings/modelyear/{identity.year}/make/{quote(identity.make, safe='')}"
        f"/model/{quote(identity.model, safe='')}?format=json"
    )


def detail_url(vehicle_id: int) -> str:
    return f"{BASE}/SafetyRatings/VehicleId/{vehicle_id}?format=json"


def create_client() -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=2, read=5, write=2, pool=1),
        limits=limits,
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=0, limits=limits),
    )


class NhtsaError(Exception):
    def __init__(self, reason: Reason) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(slots=True)
class LookupBudget:
    deadline: float
    conversation_id: str = ""
    request_id: str = ""
    calls: int = 0
    elapsed: float = 0


class NhtsaClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get(self, url: str, operation: str, budget: LookupBudget) -> object:
        remaining = min(20 - budget.elapsed, budget.deadline - time.monotonic() - 10)
        if budget.calls >= 3 or remaining <= 0:
            raise NhtsaError("budget_exhausted")
        budget.calls += 1
        started = time.monotonic()
        outcome = "received"
        try:
            async with asyncio.timeout(min(7, remaining)):
                async with self.client.stream("GET", url, follow_redirects=False) as response:
                    if response.status_code != 200:
                        raise NhtsaError("http_error")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise NhtsaError("response_limit")
                    try:
                        return json.loads(body)
                    except (ValueError, UnicodeError, RecursionError) as exc:
                        raise NhtsaError("invalid_response") from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            outcome = "timeout"
            raise NhtsaError("timeout") from exc
        except httpx.RequestError as exc:
            outcome = "transport_error"
            raise NhtsaError("transport_error") from exc
        except NhtsaError as exc:
            outcome = exc.reason
            raise
        finally:
            elapsed = time.monotonic() - started
            budget.elapsed += elapsed
            event(
                "nhtsa_request",
                operation=operation,
                conversation_id=budget.conversation_id,
                request_id=budget.request_id,
                call=budget.calls,
                duration_ms=round(elapsed * 1000, 2),
                outcome=outcome,
            )
