from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from autoassist.api.schemas import (
    AcceptedRequestResponse,
    ConversationHistoryResponse,
    ConversationMessageResponse,
    ConversationResponse,
    CreateConversationRequest,
    DealershipListResponse,
    DealershipResponse,
    ErrorEnvelope,
    HealthResponse,
    InventoryPageResponse,
    InventoryQuery,
    RequestStatusResponse,
    SubmitMessageRequest,
    SubmitMessageResponse,
    VehicleDetailResponse,
    VehicleResponse,
    decimal_to_cents,
)
from autoassist.conversations.outcomes import ConversationApplicationError
from autoassist.conversations.service import ConversationService
from autoassist.db.database import check_storage, is_storage_unavailable
from autoassist.inventory.records import InventoryFilters, VehicleRecord
from autoassist.inventory.service import (
    InventoryNotFoundError,
    InventoryService,
    StorageUnavailableError,
)

# HTTP boundary: schemas validate inputs, services own behavior, and these routes
# translate application records/errors into the public contract. Dealership IDs
# provide query scope; these routes do not implement authentication.
router = APIRouter()
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "Dealership or vehicle not found"},
    503: {"model": ErrorEnvelope, "description": "Inventory storage unavailable"},
}
CHAT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "Conversation or dealership not found"},
    409: {"model": ErrorEnvelope, "description": "Request conflict or interruption"},
    500: {"model": ErrorEnvelope, "description": "Sanitized internal failure"},
    502: {"model": ErrorEnvelope, "description": "Chat provider failure"},
    503: {"model": ErrorEnvelope, "description": "Connection, capacity, or storage unavailable"},
    504: {"model": ErrorEnvelope, "description": "Chat provider timeout"},
}


def _service(request: Request) -> InventoryService:
    """Return the inventory service installed on this app during startup; no database work occurs
    here.

    Used by inventory HTTP handlers to retrieve the startup-created service.
    """
    return cast(InventoryService, request.app.state.inventory_service)


def _conversation_service(request: Request) -> ConversationService:
    """Return the conversation service installed on this app during startup.

    Used by conversation HTTP handlers to retrieve the startup-created service.
    """
    return cast(ConversationService, request.app.state.conversation_service)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """Build and return a JSONResponse with the supplied HTTP status and public error envelope;
    this helper does not raise the error.

    Used by inventory/health handlers when translating an expected failure into HTTP.
    """
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def _vehicle_response(record: VehicleRecord) -> VehicleResponse:
    """Convert an inventory record into the public summary schema. Return decimal price text, or a
    null price when inventory has no value.

    Used by inventory search responses and the detail-response helper.
    """
    price = (
        None
        if record.price_cents is None
        else f"{record.price_cents // 100}.{record.price_cents % 100:02d}"
    )
    return VehicleResponse(
        id=UUID(record.id),
        source_id=record.source_id,
        make=record.make,
        model=record.model,
        year=record.year,
        price=price,
        body_type=record.body_type,
    )


def _vehicle_detail_response(record: VehicleRecord) -> VehicleDetailResponse:
    """Return the public vehicle detail schema by combining the summary with supported
    specifications; unknown fields remain null.

    Used by the single-vehicle HTTP handler.
    """
    summary = _vehicle_response(record)
    return VehicleDetailResponse(
        **summary.model_dump(),
        trim=record.trim,
        condition=record.condition,
        mileage=record.mileage,
        exterior_color=record.exterior_color,
        drivetrain=record.drivetrain,
        transmission=record.transmission,
        fuel=record.fuel,
    )


@router.get("/health", response_model=HealthResponse, responses={503: {"model": ErrorEnvelope}})
def health(request: Request) -> HealthResponse | JSONResponse:
    """Probe required storage tables. Return an ok health model or a 503 error response for
    recognized storage outages; unexpected database defects propagate. This synchronous route
    checks storage without depending on paid/external APIs. FastAPI runs ordinary def handlers
    in its thread pool for blocking database work.

    Called for GET /health.
    """
    try:
        check_storage(request.app.state.session_factory)
    except OperationalError as exc:
        if not is_storage_unavailable(exc):
            raise
        return _error(503, "storage_unavailable", "Inventory storage is unavailable.")
    return HealthResponse(status="ok")


@router.get(
    "/dealerships", response_model=DealershipListResponse, responses={503: ERROR_RESPONSES[503]}
)
def list_dealerships(request: Request) -> DealershipListResponse | JSONResponse:
    """Return the configured dealership list, or a 503 JSON error if storage is unavailable.

    Called for GET /dealerships.
    """
    try:
        records = _service(request).list_dealerships()
    except StorageUnavailableError:
        return _error(503, "storage_unavailable", "Inventory storage is unavailable.")
    return DealershipListResponse(
        items=[
            DealershipResponse(id=UUID(item.id), slug=item.slug, name=item.name) for item in records
        ]
    )


@router.get(
    "/dealerships/{dealership_id}/vehicles",
    response_model=InventoryPageResponse,
    responses=ERROR_RESPONSES,
)
def search_inventory(
    request: Request,
    dealership_id: UUID,
    query: Annotated[InventoryQuery, Query()],
) -> InventoryPageResponse | JSONResponse:
    """Translate validated query filters and return a vehicle page with its next cursor. Return 404
    for missing scope or 503 for unavailable storage.

    Called for GET /dealerships/{dealership_id}/vehicles after query validation.
    """
    # Convert public decimal prices to the integer-cent domain representation.
    # The same inventory service also serves model tools, keeping search rules shared.
    filters = InventoryFilters(
        make=query.make,
        model=query.model,
        body_type=query.body_type,
        year_min=query.year_min,
        year_max=query.year_max,
        price_min_cents=decimal_to_cents(query.price_min),
        price_max_cents=decimal_to_cents(query.price_max),
        after=None if query.after is None else str(query.after),
        limit=query.limit,
    )
    try:
        page = _service(request).search(str(dealership_id), filters)
    except InventoryNotFoundError:
        return _error(404, "not_found", "Dealership or vehicle was not found.")
    except StorageUnavailableError:
        return _error(503, "storage_unavailable", "Inventory storage is unavailable.")
    return InventoryPageResponse(
        items=[_vehicle_response(item) for item in page.items],
        next_after=None if page.next_after is None else UUID(page.next_after),
    )


@router.get(
    "/dealerships/{dealership_id}/vehicles/{vehicle_id}",
    response_model=VehicleDetailResponse,
    responses=ERROR_RESPONSES,
)
def get_vehicle(
    request: Request, dealership_id: UUID, vehicle_id: UUID
) -> VehicleDetailResponse | JSONResponse:
    """Return one dealership-scoped vehicle detail, or a 404/503 JSON error for missing
    inventory/unavailable storage.

    Called for GET /dealerships/{dealership_id}/vehicles/{vehicle_id}.
    """
    try:
        record = _service(request).get(str(dealership_id), str(vehicle_id))
    except InventoryNotFoundError:
        return _error(404, "not_found", "Dealership or vehicle was not found.")
    except StorageUnavailableError:
        return _error(503, "storage_unavailable", "Inventory storage is unavailable.")
    return _vehicle_detail_response(record)


@router.post(
    "/dealerships/{dealership_id}/conversations",
    response_model=ConversationResponse,
    status_code=201,
    responses=CHAT_ERROR_RESPONSES,
)
async def create_conversation(
    request: Request, dealership_id: UUID, _payload: CreateConversationRequest
) -> ConversationResponse | JSONResponse:
    """Create or recover a conversation using creation_id. Return its public identity under HTTP
    201, or the application error response; no message is submitted here.

    Called for POST /dealerships/{dealership_id}/conversations, normally before the first
    message of a new chat.
    """
    try:
        record = await _conversation_service(request).create(
            str(dealership_id), str(_payload.creation_id)
        )
    except ConversationApplicationError as exc:
        return JSONResponse(status_code=exc.outcome.status_code, content=exc.outcome.body)
    return ConversationResponse(
        id=UUID(record.id),
        dealership_id=UUID(record.dealership_id),
        created_at=datetime.fromisoformat(record.created_at),
        selected_vehicle_id=None,
    )


@router.post(
    "/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
    response_model=SubmitMessageResponse,
    responses={**CHAT_ERROR_RESPONSES, 202: {"model": AcceptedRequestResponse}},
)
async def submit_message(
    request: Request,
    dealership_id: UUID,
    conversation_id: UUID,
    payload: SubmitMessageRequest,
) -> JSONResponse:
    """Submit immutable request ID/text to the lifecycle service. Return JSON with 202 acceptance,
    a replayed terminal outcome, or an application error status. Chat routes await async
    orchestration. Submission can return 202 for admitted work or a stored terminal outcome for
    a retry; the service chooses that status.

    Called for every POST to a conversation messages collection, including retries. The
    conversation must already exist.
    """
    try:
        outcome = await _conversation_service(request).submit(
            str(dealership_id), str(conversation_id), str(payload.request_id), payload.text
        )
    except ConversationApplicationError as exc:
        outcome = exc.outcome
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.get(
    "/dealerships/{dealership_id}/conversations/{conversation_id}/requests/{request_id}",
    response_model=RequestStatusResponse,
    responses={404: CHAT_ERROR_RESPONSES[404], 503: CHAT_ERROR_RESPONSES[503]},
)
async def get_request_status(
    request: Request, dealership_id: UUID, conversation_id: UUID, request_id: UUID
) -> JSONResponse:
    """Return an uncached JSON status snapshot, including a terminal outcome when settled. Missing
    requests/storage failures return the application error response.

    Called when the browser polls GET requests/{request_id} for an admitted or uncertain turn.
    """
    try:
        outcome = await _conversation_service(request).status(
            str(dealership_id), str(conversation_id), str(request_id)
        )
    except ConversationApplicationError as exc:
        outcome = exc.outcome
    return JSONResponse(
        status_code=outcome.status_code,
        content=outcome.body,
        # Polling must observe current durable state rather than a cached active result.
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/dealerships/{dealership_id}/conversations/{conversation_id}/messages",
    response_model=ConversationHistoryResponse,
    responses=CHAT_ERROR_RESPONSES,
)
async def get_conversation_messages(
    request: Request,
    dealership_id: UUID,
    conversation_id: UUID,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ConversationHistoryResponse | JSONResponse:
    """Return a page of durable messages and a continuation sequence (None at the end), or a JSON
    application error. Failed user turns remain visible. History is the durable user-visible
    record, including failed user turns. It is distinct from the completed tool/model replay
    supplied to the LLM.

    Called when the browser loads, paginates, or reconciles conversation history.
    """
    try:
        page = await _conversation_service(request).history(
            str(dealership_id), str(conversation_id), after_sequence, limit
        )
    except ConversationApplicationError as exc:
        return JSONResponse(status_code=exc.outcome.status_code, content=exc.outcome.body)
    return ConversationHistoryResponse(
        conversation_id=UUID(page.conversation_id),
        selected_vehicle_id=(
            None if page.selected_vehicle_id is None else UUID(page.selected_vehicle_id)
        ),
        items=[
            ConversationMessageResponse(
                id=UUID(item.id),
                sequence=item.sequence,
                request_id=UUID(item.request_id),
                role=cast(Literal["user", "assistant"], item.role),
                text=item.text,
                created_at=datetime.fromisoformat(item.created_at),
                request_status=cast(
                    Literal["in_progress", "completed", "failed", "interrupted"],
                    item.request_status,
                ),
                error_code=item.error_code,
            )
            for item in page.items
        ],
        next_after_sequence=page.next_after_sequence,
    )
