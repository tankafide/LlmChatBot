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
    """Search the current dealership inventory using combined filters."""
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
        "items": [_tool_vehicle(item) for item in page.items],
        "has_more": page.next_after is not None,
    }
    ctx.deps.register_tool_result(value)
    return value


async def get_vehicle_by_stock(
    ctx: RunContext[ChatDependencies], stock_number: str
) -> dict[str, object]:
    """Retrieve one current-dealership vehicle by its exact stock number."""
    try:
        item = await asyncio.to_thread(
            ctx.deps.inventory.get_by_source_id,
            ctx.deps.request.dealership_id,
            stock_number,
        )
    except InventoryNotFoundError:
        value: dict[str, object] = {"found": False}
    else:
        ctx.deps.evidence[item.id] = item
        value = {"found": True, "vehicle": _tool_vehicle(item)}
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
    """Look up NHTSA campaigns for the resolved scoped inventory vehicle."""
    return await _lookup_safety(ctx, "recalls")


async def lookup_crash_ratings(ctx: RunContext[ChatDependencies]) -> dict[str, object]:
    """Look up NHTSA crash ratings or resolve the current message's pending variant choice."""
    return await _lookup_safety(ctx, "crash")


def _tool_vehicle(record: VehicleRecord) -> dict[str, object]:
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
