from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

FilterText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MAX_SQLITE_PRICE = Decimal("92233720368547758.07")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str


class DealershipResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class DealershipListResponse(BaseModel):
    items: list[DealershipResponse]


class VehicleResponse(BaseModel):
    id: UUID
    source_id: str
    make: str
    model: str
    year: int
    price: str | None
    body_type: str | None


class VehicleDetailResponse(VehicleResponse):
    trim: str | None
    condition: str | None
    mileage: int | None
    exterior_color: str | None
    drivetrain: str | None
    transmission: str | None
    fuel: str | None


class InventoryPageResponse(BaseModel):
    items: list[VehicleResponse]
    next_after: UUID | None


class InventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    make: FilterText | None = None
    model: FilterText | None = None
    body_type: FilterText | None = None
    year_min: int | None = Field(default=None, ge=1886, le=2100)
    year_max: int | None = Field(default=None, ge=1886, le=2100)
    price_min: Decimal | None = Field(default=None, ge=0, le=MAX_SQLITE_PRICE)
    price_max: Decimal | None = Field(default=None, ge=0, le=MAX_SQLITE_PRICE)
    limit: int = Field(default=20, ge=1, le=100)
    after: UUID | None = None

    @field_validator("price_min", "price_max")
    @classmethod
    def validate_price_precision(cls, value: Decimal | None) -> Decimal | None:
        if value is not None:
            exponent = value.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -2:
                raise ValueError("price must have at most two decimal places")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> InventoryQuery:
        if (
            self.year_min is not None
            and self.year_max is not None
            and self.year_min > self.year_max
        ):
            raise ValueError("year_min must not exceed year_max")
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min must not exceed price_max")
        return self


def decimal_to_cents(value: Decimal | None) -> int | None:
    return None if value is None else int(value * 100)


class CreateConversationRequest(BaseModel):
    creation_id: UUID

    model_config = ConfigDict(extra="forbid")


class ConversationResponse(BaseModel):
    id: UUID
    dealership_id: UUID
    created_at: datetime
    selected_vehicle_id: UUID | None


class SubmitMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    text: str = Field(min_length=1, max_length=4_000)

    @field_validator("text")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain a non-whitespace character")
        return value


class ConversationMessageResponse(BaseModel):
    id: UUID
    sequence: int
    request_id: UUID
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    request_status: Literal["in_progress", "completed", "failed", "interrupted"]
    error_code: str | None


class SubmitMessageResponse(BaseModel):
    conversation_id: UUID
    request_id: UUID
    status: Literal["completed"]
    user_message: ConversationMessageResponse
    assistant_message: ConversationMessageResponse
    selected_vehicle_id: UUID | None


class ConversationHistoryResponse(BaseModel):
    conversation_id: UUID
    selected_vehicle_id: UUID | None
    items: list[ConversationMessageResponse]
    next_after_sequence: int | None


class AcceptedRequestResponse(BaseModel):
    conversation_id: UUID
    request_id: UUID
    status: Literal["in_progress"]


class CompletedRequestStatus(BaseModel):
    conversation_id: UUID
    request_id: UUID
    status: Literal["completed"]
    outcome: SubmitMessageResponse


class FailedRequestStatus(BaseModel):
    conversation_id: UUID
    request_id: UUID
    status: Literal["failed", "interrupted"]
    outcome: ErrorEnvelope


RequestStatusResponse = Annotated[
    AcceptedRequestResponse | CompletedRequestStatus | FailedRequestStatus,
    Field(discriminator="status"),
]
