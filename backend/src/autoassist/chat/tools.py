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

# Annotations constrain model arguments; tool docstrings also supply model-facing
# descriptions, so their usage instructions and Args sections are part of the prompt.
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
    """Validate requested filters, fetch inventory, and update run evidence. Return items plus
    has_more; invalid ranges or output budgets raise ModelRetry, storage failures propagate.

    Invoked by the agent when the customer asks to find/list vehicles or supplies new search
    criteria.

    Find/list vehicles using only the customer's requested filters.

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
    # Individual field checks do not catch contradictory ranges. ModelRetry feeds
    # this problem back for a bounded correction attempt.
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ModelRetry("year_min must not exceed year_max")
    if (
        price_min_cents is not None
        and price_max_cents is not None
        and price_min_cents > price_max_cents
    ):
        raise ModelRetry("price_min_cents must not exceed price_max_cents")
    # The model supplies structured filters, never SQL. Offload the whole service
    # call so session creation, queries, and cleanup stay in the worker thread.
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
    # Keep authoritative records separately from model-facing JSON. Validation later
    # checks answer IDs against this evidence and the latest search subset.
    for item in page.items:
        ctx.deps.evidence[item.id] = item
    ctx.deps.search_executed = True
    ctx.deps.last_search_ids = tuple(item.id for item in page.items)
    value: dict[str, object] = {
        "items": [vehicle_evidence(item) for item in page.items],
        "has_more": page.next_after is not None,
    }
    # Account for serialized tool output before returning it; repeated or large
    # results consume budget even when the final answer is short.
    ctx.deps.register_tool_result(value)
    return value


async def get_vehicle_by_stock(
    ctx: RunContext[ChatDependencies], stock_number: str
) -> dict[str, object]:
    """Fetch one scoped stock and register its evidence. Return found=True with the vehicle, or
    found=False with clarification; output budget/storage failures can propagate.

    Invoked by the agent when an explicit stock is absent from current evidence.

    Retrieve one vehicle by stock when absent from current_vehicle_evidence.

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
    """Resolve and refresh the subject, then invoke the requested safety branch. Return
    clarification without an evidence ID, or evidence_id plus typed result JSON; invalid
    scope/budgets may raise.

    Called by the two safety tool wrappers; branch is selected by application code.
    """
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
    # Application code resolves the subject from the customer reference. Safety
    # tools cannot silently choose an arbitrary vehicle ID supplied by the model.
    vehicle_id = resolve_safety_reference(
        deps.request, deps.evidence, deps.safety_presentation is not None
    )
    # Clarification has no evidence_id and cannot authorize a factual safety answer.
    # Actual empty/unavailable lookup results are evidence with an explicit status.
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
    # Expose a stable branch ID for answer validation to match against the typed
    # run result, including ambiguous and unavailable outcomes.
    value = {"evidence_id": branch, "result": result.model_dump(mode="json")}
    deps.register_tool_result(value)
    return value


async def lookup_recalls(ctx: RunContext[ChatDependencies]) -> dict[str, object]:
    """Return recall evidence or subject clarification through the shared safety adapter.
    Empty/unavailable results remain evidence; adapter errors propagate.

    Invoked by the agent for a customer recall question.

    Get recalls for the vehicle identified by stock, list reference or selected context.

    Use only for a customer recall request, never for price/specification clarification.
    Resolve an explicit stock with get_vehicle_by_stock first if absent from current evidence.
    A clarification result means return clarify and stop, not another lookup. An evidence_id
    means return safety with that ID, even for empty/unavailable results. Do not repeat this
    branch. Call crash ratings as well only if requested. Selection is application-owned.
    """
    return await _lookup_safety(ctx, "recalls")


async def lookup_crash_ratings(ctx: RunContext[ChatDependencies]) -> dict[str, object]:
    """Return crash evidence or clarification, using a pending variant menu when valid.
    Ambiguous/unavailable results remain evidence; adapter errors propagate.

    Invoked by the agent for crash ratings or a pending variant choice.

    Get crash ratings for the identified vehicle or resolve a pending NHTSA variant choice.

    Use only for crash ratings or pending variant choices, never for inventory clarification.
    Resolve an explicit stock with get_vehicle_by_stock first if absent from current evidence.
    A clarification result means return clarify and stop. An evidence_id means return safety
    with that ID, even for ambiguous/unavailable results. Do not repeat this branch. Call
    recalls as well only if requested. The application resolves choices and manages selection.
    """
    return await _lookup_safety(ctx, "crash")


def vehicle_evidence(record: VehicleRecord) -> dict[str, object]:
    """Return the plain JSON-compatible projection used in prompts/tools, retaining null inventory
    values as unknown facts; no database read occurs.

    Called by inventory tools and the runner refreshed-context projection; it does not register
    budget usage itself.

    The same factual inventory projection for tool results and refreshed prompt context.
    """
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
