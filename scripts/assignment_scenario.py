"""Portable HTTP acceptance scenario for the AutoAssist assignment.

This module intentionally uses only Python's standard library and plain JSON values.
The caller owns application/container startup, restart, external fakes, and cleanup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

Json = dict[str, Any]
Request = Callable[[str, str, Json | None], tuple[int, Json]]


def _expect_status(actual: int, expected: int, body: Json, action: str) -> None:
    if actual != expected:
        raise AssertionError(
            f"{action}: expected HTTP {expected}, got {actual}: {body!r}"
        )


def _message(request: Request, url: str, text: str) -> tuple[str, Json]:
    request_id = str(uuid4())
    status, body = request("POST", url, {"request_id": request_id, "text": text})
    _expect_status(status, 200, body, f"submit {text!r}")
    if body.get("request_id") != request_id or body.get("status") != "completed":
        raise AssertionError(
            f"submission did not return its completed request identity: {body!r}"
        )
    return request_id, body


def _history(request: Request, url: str) -> Json:
    items: list[Json] = []
    after = 0
    selected_vehicle_id: str | None = None
    while True:
        status, page = request("GET", f"{url}?after_sequence={after}&limit=3", None)
        _expect_status(status, 200, page, "page conversation history")
        page_items = page.get("items")
        if not isinstance(page_items, list):
            raise AssertionError(f"history items are not a list: {page!r}")
        items.extend(page_items)
        selected_vehicle_id = page.get("selected_vehicle_id")
        next_after = page.get("next_after_sequence")
        if next_after is None:
            break
        if not isinstance(next_after, int) or next_after <= after:
            raise AssertionError(f"history cursor did not advance: {page!r}")
        after = next_after
    return {"selected_vehicle_id": selected_vehicle_id, "items": items}


def before_restart(request: Request, expected_vehicle: Json) -> Json:
    """Exercise the full assignment flow and return restart-safe evidence."""

    status, health = request("GET", "/health", None)
    _expect_status(status, 200, health, "health")
    if health != {"status": "ok"}:
        raise AssertionError(f"unexpected health response: {health!r}")

    status, dealerships = request("GET", "/dealerships", None)
    _expect_status(status, 200, dealerships, "list dealerships")
    dealership = next(
        (
            item
            for item in dealerships.get("items", [])
            if item.get("slug") == "mia-motors"
        ),
        None,
    )
    if dealership is None:
        raise AssertionError("mia-motors was not returned by the API")
    dealership_id = dealership["id"]

    query = urlencode(
        {
            "make": expected_vehicle["make"],
            "model": expected_vehicle["model"],
            "body_type": expected_vehicle["body_type"],
            "year_min": expected_vehicle["year"],
            "year_max": expected_vehicle["year"],
            "price_min": expected_vehicle["price"],
            "price_max": expected_vehicle["price"],
        }
    )
    inventory_url = f"/dealerships/{dealership_id}/vehicles"
    status, search = request("GET", f"{inventory_url}?{query}", None)
    _expect_status(status, 200, search, "combined inventory search")
    matches = search.get("items", [])
    if len(matches) != 1:
        raise AssertionError(
            f"combined search did not return one exact match: {search!r}"
        )
    vehicle = matches[0]
    for field in ("source_id", "make", "model", "year", "price", "body_type"):
        if vehicle.get(field) != expected_vehicle[field]:
            raise AssertionError(f"combined search mismatch for {field}: {vehicle!r}")

    contradictory = urlencode(
        {"make": "Toyota", "model": "RAV4", "year_min": 1900, "year_max": 1900}
    )
    status, empty = request("GET", f"{inventory_url}?{contradictory}", None)
    _expect_status(status, 200, empty, "contradictory inventory search")
    if empty.get("items") != []:
        raise AssertionError(f"contradictory search was not empty: {empty!r}")

    status, conversation = request(
        "POST", f"/dealerships/{dealership_id}/conversations", {}
    )
    _expect_status(status, 201, conversation, "create conversation")
    conversation_id = conversation["id"]
    messages_url = (
        f"/dealerships/{dealership_id}/conversations/{conversation_id}/messages"
    )

    search_id, search_reply = _message(
        request, messages_url, "Show me Toyota RAV4 SUVs from 2022 at $26,335"
    )
    if expected_vehicle["source_id"] not in search_reply["assistant_message"]["text"]:
        raise AssertionError("chat search was not grounded in the imported vehicle")

    select_id, selection = _message(request, messages_url, "Select stock AA-1001")
    if selection.get("selected_vehicle_id") != vehicle["id"]:
        raise AssertionError("explicit selection did not persist the displayed vehicle")

    _, details = _message(request, messages_url, "What are its mileage and drivetrain?")
    detail_text = details["assistant_message"]["text"]
    if "15,819" not in detail_text or "FWD" not in detail_text:
        raise AssertionError(
            f"follow-up omitted imported detail facts: {detail_text!r}"
        )

    _, recalls = _message(request, messages_url, "recalls")
    if "recall" not in recalls["assistant_message"]["text"].lower():
        raise AssertionError("recall response was not rendered")

    _, combined = _message(request, messages_url, "both")
    if "NHTSA ID 202" not in combined["assistant_message"]["text"]:
        raise AssertionError("combined safety response did not present crash variants")
    _, rating = _message(request, messages_url, "202")
    if "Overall: 5/5" not in rating["assistant_message"]["text"]:
        raise AssertionError("crash-rating choice did not return the scripted rating")

    history = _history(request, messages_url)
    if history["selected_vehicle_id"] != vehicle["id"]:
        raise AssertionError("history did not expose the committed vehicle selection")

    return {
        "dealership_id": dealership_id,
        "conversation_id": conversation_id,
        "vehicle_id": vehicle["id"],
        "messages_url": messages_url,
        "search_request_id": search_id,
        "search_text": "Show me Toyota RAV4 SUVs from 2022 at $26,335",
        "search_response": search_reply,
        "select_request_id": select_id,
        "select_text": "Select stock AA-1001",
        "selection_response": selection,
        "history": history,
    }


def after_restart(request: Request, state: Json) -> Json:
    """Prove durable history/replay, then complete a fresh contextual follow-up."""

    messages_url = state["messages_url"]
    history = _history(request, messages_url)
    if history != state["history"]:
        raise AssertionError("conversation history changed across restart")

    status, replay = request(
        "POST",
        messages_url,
        {"request_id": state["select_request_id"], "text": state["select_text"]},
    )
    _expect_status(status, 200, replay, "replay completed request")
    if replay != state["selection_response"]:
        raise AssertionError("terminal replay was not byte-for-byte JSON equivalent")

    _, follow_up = _message(request, messages_url, "What is its price?")
    if follow_up.get("selected_vehicle_id") != state["vehicle_id"]:
        raise AssertionError(
            "fresh follow-up lost selected vehicle context after restart"
        )
    if "price:" not in follow_up["assistant_message"]["text"]:
        raise AssertionError("fresh follow-up did not return grounded vehicle details")
    return {"history_before_follow_up": history, "follow_up": follow_up}
