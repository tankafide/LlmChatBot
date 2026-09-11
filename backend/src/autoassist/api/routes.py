from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from autoassist.api.schemas import (
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
    return cast(InventoryService, request.app.state.inventory_service)


def _conversation_service(request: Request) -> ConversationService:
    return cast(ConversationService, request.app.state.conversation_service)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def _vehicle_response(record: VehicleRecord) -> VehicleResponse:
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
    try:
        record = await _conversation_service(request).create(str(dealership_id))
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
    responses=CHAT_ERROR_RESPONSES,
)
async def submit_message(
    request: Request,
    dealership_id: UUID,
    conversation_id: UUID,
    payload: SubmitMessageRequest,
) -> SubmitMessageResponse | JSONResponse:
    try:
        outcome = await _conversation_service(request).submit(
            str(dealership_id), str(conversation_id), str(payload.request_id), payload.text
        )
    except ConversationApplicationError as exc:
        outcome = exc.outcome
    if outcome.status_code != 200:
        return JSONResponse(status_code=outcome.status_code, content=outcome.body)
    return SubmitMessageResponse.model_validate(outcome.body)


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
