"""Typed Pydantic AI adapters over inventory and safety application services."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from autoassist.chat.context import ChatDependencies
from autoassist.chat.selection import resolve_safety_reference
from autoassist.inventory.records import InventoryFilters, VehicleRecord
from autoassist.inventory.service import InventoryNotFoundError
from autoassist.safety.matching import identity_for
from autoassist.safety.records import CrashResult, RecallResult

Limit = Annotated[int, Field(ge=1, le=10)]
Year = Annotated[int, Field(ge=1886, le=2100)]
PriceCents = Annotated[int, Field(ge=0)]


async def search_inventory(
    ctx: RunContext[ChatDependencies],
    make: str | None = None,
    model: str | None = None,
    body_type: str | None = None,
    year_min: Year | None = None,
    year_max: Year | None = None,
    price_min_cents: PriceCents | None = None,
    price_max_cents: PriceCents | None = None,
    limit: Limit = 10,
) -> dict[str, object]:
    """Find/list vehicles using only the customer's requested filters.

    Do not search to answer a selected-vehicle follow-up, resolve an ambiguous pronoun,
    replace a missing stock lookup, or answer an unsupported request. Reuse the prompt's
    refreshed current_vehicle_evidence for follow-ups. Empty items means no_match;
    otherwise return list using these latest results.

    Args:
        make: Requested manufacturer, or null when unspecified.
        model: Requested model, or null when unspecified.
        body_type: Requested body type, such as SUV, Sedan or Truck.
        year_min: Inclusive earliest year; for an exact year set both year bounds.
        year_max: Inclusive latest year, or null for no upper bound.
        price_min_cents: Inclusive minimum price in cents, not dollars.
        price_max_cents: Inclusive maximum price in cents, not dollars.
        limit: Maximum number of results, from 1 to 10.
    """
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ModelRetry("year_min must not exceed year_max")
    if (
        price_min_cents is not None
        and price_max_cents is not None
        and price_min_cents > price_max_cents
    ):
        raise ModelRetry("price_min_cents must not exceed price_max_cents")
    page = await asyncio.to_thread(
        ctx.deps.inventory.search,
        ctx.deps.request.dealership_id,
        InventoryFilters(
            make=make,
            model=model,
            body_type=body_type,
            year_min=year_min,
            year_max=year_max,
            price_min_cents=price_min_cents,
            price_max_cents=price_max_cents,
            limit=limit,
        ),
    )
    for item in page.items:
        ctx.deps.evidence[item.id] = item
    ctx.deps.search_executed = True
    ctx.deps.last_search_ids = tuple(item.id for item in page.items)
    value: dict[str, object] = {
        "items": [vehicle_evidence(item) for item in page.items],
        "has_more": page.next_after is not None,
    }
    ctx.deps.register_tool_result(value)
    return value


async def get_vehicle_by_stock(
    ctx: RunContext[ChatDependencies], stock_number: str
) -> dict[str, object]:
    """Retrieve one vehicle by stock when absent from current_vehicle_evidence.

    Reuse existing current evidence for selected-vehicle follow-ups instead of fetching
    it again. found=false means return clarify and ask for a valid stock; do not run a
    broad search or use no_match. found=true supplies evidence for details or safety tools.

    Args:
        stock_number: The customer's exact stock number, never an invented identifier.
    """
    try:
        item = await asyncio.to_thread(
            ctx.deps.inventory.get_by_source_id,
            ctx.deps.request.dealership_id,
            stock_number,
        )
    except InventoryNotFoundError:
        value: dict[str, object] = {
            "found": False,
            "clarification": "Stock not found. Return clarify and ask for a valid stock number.",
        }
    else:
        ctx.deps.evidence[item.id] = item
        value = {"found": True, "vehicle": vehicle_evidence(item)}
    ctx.deps.register_tool_result(value)
    return value


async def _lookup_safety(ctx: RunContext[ChatDependencies], branch: str) -> dict[str, object]:
    deps = ctx.deps
    if (
        branch == "crash"
        and deps.safety_presentation is None
        and re.fullmatch(
            r"(?:nhtsa(?: id)?\s+|id\s+)?\d+|(?:the )?(?:first|second|third|fourth|fifth)(?: one)?",
            deps.request.text.strip(),
            re.IGNORECASE,
        )
    ):
        value: dict[str, object] = {
            "clarification": "No current NHTSA choices exist; request crash ratings again."
        }
        deps.register_tool_result(value)
        return value
    vehicle_id = resolve_safety_reference(
        deps.request, deps.evidence, deps.safety_presentation is not None
    )
    if vehicle_id is None or deps.safety is None:
        value = {"clarification": "Specify a stock number or choose an inventory vehicle."}
        deps.register_tool_result(value)
        return value
    if deps.safety_run.vehicle_id not in {None, vehicle_id}:
        raise ModelRetry("Only one inventory vehicle may be used for safety in a turn.")
    try:
        vehicle = await asyncio.to_thread(
            deps.inventory.get, deps.request.dealership_id, vehicle_id
        )
    except InventoryNotFoundError:
        raise ModelRetry("The scoped vehicle is unavailable.") from None
    deps.safety_run.vehicle_id = vehicle_id
    deps.evidence[vehicle_id] = vehicle
    if branch == "recalls":
        result: RecallResult | CrashResult = await deps.safety.recalls(vehicle, deps.safety_run)
    else:
        presentation = deps.safety_presentation
        if presentation is not None and (
            presentation.inventory_vehicle_id != vehicle_id
            or presentation.lookup_identity != identity_for(vehicle)
        ):
            presentation = None
        result = await deps.safety.crash(
            vehicle,
            deps.safety_run,
            presentation,
            deps.request.text if presentation is not None else None,
        )
    value = {"evidence_id": branch, "result": result.model_dump(mode="json")}
    deps.register_tool_result(value)
    return value


async def lookup_recalls(ctx: RunContext[ChatDependencies]) -> dict[str, object]:
    """Get recalls for the vehicle identified by stock, list reference or selected context.

    Use only for a customer recall request, never for price/specification clarification.
    Resolve an explicit stock with get_vehicle_by_stock first if absent from current evidence.
    A clarification result means return clarify and stop, not another lookup. An evidence_id
    means return safety with that ID, even for empty/unavailable results. Do not repeat this
    branch. Call crash ratings as well only if requested. Selection is application-owned.
    """
    return await _lookup_safety(ctx, "recalls")


async def lookup_crash_ratings(ctx: RunContext[ChatDependencies]) -> dict[str, object]:
    """Get crash ratings for the identified vehicle or resolve a pending NHTSA variant choice.

    Use only for crash ratings or pending variant choices, never for inventory clarification.
    Resolve an explicit stock with get_vehicle_by_stock first if absent from current evidence.
    A clarification result means return clarify and stop. An evidence_id means return safety
    with that ID, even for ambiguous/unavailable results. Do not repeat this branch. Call
    recalls as well only if requested. The application resolves choices and manages selection.
    """
    return await _lookup_safety(ctx, "crash")


def vehicle_evidence(record: VehicleRecord) -> dict[str, object]:
    """The same factual inventory projection for tool results and refreshed prompt context."""
    return {
        "vehicle_id": record.id,
        "stock_number": record.source_id,
        "make": record.make,
        "model": record.model,
        "year": record.year,
        "price_cents": record.price_cents,
        "body_type": record.body_type,
        "trim": record.trim,
        "condition": record.condition,
        "mileage": record.mileage,
        "exterior_color": record.exterior_color,
        "drivetrain": record.drivetrain,
        "transmission": record.transmission,
        "fuel": record.fuel,
    }
