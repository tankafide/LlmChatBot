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
    """Construct URLs from a fixed NHTSA origin and encoded inventory identity. Model tools do not
    accept arbitrary remote URLs. Return an encoded NHTSA recall URL for year/make/model; no
    network request occurs.

    Called by SafetyService.recalls.
    """
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
    """Return an encoded crash-variant discovery URL for inventory identity; no lookup is
    performed.

    Called before crash variant discovery.
    """
    return (
        f"{BASE}/SafetyRatings/modelyear/{identity.year}/make/{quote(identity.make, safe='')}"
        f"/model/{quote(identity.model, safe='')}?format=json"
    )


def detail_url(vehicle_id: int) -> str:
    """Return the crash-detail URL for a numeric NHTSA variant ID, which is distinct from the
    inventory UUID.

    Called after selecting a valid crash variant.
    """
    return f"{BASE}/SafetyRatings/VehicleId/{vehicle_id}?format=json"


def create_client() -> httpx.AsyncClient:
    """Share a bounded connection pool. Disable automatic retries and redirects so hidden extra
    requests do not bypass the explicit per-turn lookup budget. Return a configured AsyncClient
    with bounded connections/timeouts and no redirects or transport retries. Its owner must
    await aclose when finished.

    Called by app lifespan to construct its shared NHTSA client.
    """
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=2, read=5, write=2, pool=1),
        limits=limits,
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=0, limits=limits),
    )


class NhtsaError(Exception):
    """Carry a typed lookup failure reason without exposing raw upstream content.

    SafetyService converts expected transport, budget, or payload failures into unavailable
    evidence.
    """

    def __init__(self, reason: Reason) -> None:
        """Create a typed safety lookup failure without raising it.

        Called at transport/budget failure sites before raising NhtsaError. Store the reason
        for SafetyService to convert into unavailable evidence. Return None.
        """
        self.reason = reason
        super().__init__(reason)


@dataclass(slots=True)
class LookupBudget:
    """Track the shared NHTSA call/time allowance for one turn.

    deadline is monotonic, calls and elapsed charge attempted requests, and correlation IDs
    support metadata-only events.
    """

    deadline: float
    conversation_id: str = ""
    request_id: str = ""
    calls: int = 0
    elapsed: float = 0


class NhtsaClient:
    """Fetch bounded NHTSA JSON using an externally owned async HTTP client.

    Enforce shared call/time/response-size limits and classify failures; safety parsing
    separately validates record identity and meaning.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Wrap the shared HTTP client used by the safety service.

        Called during application startup. Store the externally owned AsyncClient and return
        None; the application lifespan, not this wrapper, is responsible for closing it.
        """
        self.client = client

    async def get(self, url: str, operation: str, budget: LookupBudget) -> object:
        """Fetch and decode one budgeted response, returning arbitrary JSON for later semantic
        validation. Charge attempts/time; raise NhtsaError for exhausted budgets, transport,
        HTTP, or JSON failures.

        Called for recall, discovery, and detail requests within the shared turn budget.
        """
        # Share three calls and twenty elapsed seconds across safety branches, while
        # reserving ten seconds before the turn deadline for model/answer completion.
        remaining = min(20 - budget.elapsed, budget.deadline - time.monotonic() - 10)
        if budget.calls >= 3 or remaining <= 0:
            raise NhtsaError("budget_exhausted")
        # Charge before I/O: unsuccessful attempts still consume the call budget.
        budget.calls += 1
        started = time.monotonic()
        outcome = "received"
        try:
            # The outer timeout bounds the entire response, including body reading. HTTPX
            # also applies separate connect/read/write/pool timeouts.
            async with asyncio.timeout(min(7, remaining)):
                async with self.client.stream("GET", url, follow_redirects=False) as response:
                    if response.status_code != 200:
                        raise NhtsaError("http_error")
                    body = bytearray()
                    # Read incrementally and reject oversized decoded bodies before JSON parsing,
                    # even if Content-Length is absent or inaccurate.
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise NhtsaError("response_limit")
                    try:
                        # Transport-valid JSON is not yet safety evidence. safety/parsing.py checks
                        # the external payload shape and meaning before the service uses it.
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
            # Charge elapsed time on both success and failure. Emit outcome metadata
            # without logging the external response body.
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
