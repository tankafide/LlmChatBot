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
    """Carry a public machine-readable error code and human-readable message.

    Consumers use the code to distinguish retry, rejection, and terminal failure behavior.
    """

    code: str
    message: str


class ErrorEnvelope(BaseModel):
    """Wrap a public application error under the error key for consistent HTTP handling."""

    error: ErrorDetail


class HealthResponse(BaseModel):
    """Represent the successful storage health response.

    It does not claim external model or NHTSA availability.
    """

    status: str


class DealershipResponse(BaseModel):
    """Expose a dealership UUID, configured slug, and display name without internal connection
    settings.
    """

    id: UUID
    slug: str
    name: str


class DealershipListResponse(BaseModel):
    """Wrap the publicly listed dealership records; items may be empty."""

    items: list[DealershipResponse]


class VehicleResponse(BaseModel):
    """Expose an inventory summary with decimal price text and dealership-local stock number.

    Nullable price/body fields represent unknown inventory data, not zero or empty facts.
    """

    id: UUID
    source_id: str
    make: str
    model: str
    year: int
    price: str | None
    body_type: str | None


class VehicleDetailResponse(VehicleResponse):
    """Extend the public vehicle summary with supported specifications.

    Unknown optional facts remain null so clients cannot mistake missing data for confirmed
    values.
    """

    trim: str | None
    condition: str | None
    mileage: int | None
    exterior_color: str | None
    drivetrain: str | None
    transmission: str | None
    fuel: str | None


class InventoryPageResponse(BaseModel):
    """Carry one public inventory page and its continuation UUID.

    next_after is null at the end; an empty items list is a valid search result.
    """

    items: list[VehicleResponse]
    next_after: UUID | None


class InventoryQuery(BaseModel):
    """Validate HTTP inventory filters before repository access.

    Bounds are inclusive, decimal prices have at most two places, and minimums cannot exceed
    maximums. Unknown query fields are rejected.
    """

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
        """Reject price filters with more than two decimal places.

        Pydantic calls this while parsing inventory query prices. Return the Decimal
        unchanged, or None for an omitted bound; raise ValueError for excessive precision so
        HTTP validation can reject the request.
        """
        if value is not None:
            exponent = value.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -2:
                raise ValueError("price must have at most two decimal places")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> InventoryQuery:
        """Reject contradictory inventory bounds after individual field validation.

        Return self if supplied minimums do not exceed maximums. Raise ValueError otherwise;
        FastAPI reports request validation failures before searching inventory.
        """
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
    """Convert an already-validated public price filter into integer cents.

    Called by the inventory HTTP route. Return None for an omitted bound; otherwise return
    value times 100 as an integer. Precision must have been validated first, since int would
    truncate extra fractional cents.
    """
    return None if value is None else int(value * 100)


class CreateConversationRequest(BaseModel):
    """Identify a conversation-creation attempt independently of message submission.

    Reusing creation_id within a dealership recovers the same conversation after an uncertain
    response.
    """

    creation_id: UUID

    model_config = ConfigDict(extra="forbid")


class ConversationResponse(BaseModel):
    """Expose the created or recovered conversation identity and public selection field.

    Provider configuration and model replay stay internal.
    """

    id: UUID
    dealership_id: UUID
    created_at: datetime
    selected_vehicle_id: UUID | None


class SubmitMessageRequest(BaseModel):
    """Validate one immutable client request ID and its message text.

    Whitespace-only text is rejected without trimming valid payloads, preserving equality for
    same-ID retries.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    text: str = Field(min_length=1, max_length=4_000)

    @field_validator("text")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        """Require meaningful text without rewriting the submitted payload.

        Pydantic calls this for message POST bodies. Return the original string, preserving
        whitespace for retry identity; raise ValueError if it contains no non-whitespace
        character.
        """
        if not value.strip():
            raise ValueError("text must contain a non-whitespace character")
        return value


class ConversationMessageResponse(BaseModel):
    """Expose a saved user or assistant message with server sequence and request status.

    A failed/interrupted user message remains visible even when no assistant reply exists.
    """

    id: UUID
    sequence: int
    request_id: UUID
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    request_status: Literal["in_progress", "completed", "failed", "interrupted"]
    error_code: str | None


class SubmitMessageResponse(BaseModel):
    """Represent the stored completed-turn response used for terminal replay.

    Includes both messages and resulting selection; new asynchronous admission is represented
    separately.
    """

    conversation_id: UUID
    request_id: UUID
    status: Literal["completed"]
    user_message: ConversationMessageResponse
    assistant_message: ConversationMessageResponse
    selected_vehicle_id: UUID | None


class ConversationHistoryResponse(BaseModel):
    """Expose a page of durable conversation history and current selection.

    next_after_sequence is null at the end; history includes admitted unsuccessful user turns.
    """

    conversation_id: UUID
    selected_vehicle_id: UUID | None
    items: list[ConversationMessageResponse]
    next_after_sequence: int | None


class AcceptedRequestResponse(BaseModel):
    """Acknowledge durable admission with status in_progress and request identity.

    It does not promise completion; clients poll the request status for the final outcome.
    """

    conversation_id: UUID
    request_id: UUID
    status: Literal["in_progress"]


class CompletedRequestStatus(BaseModel):
    """Represent a successful terminal result inside the status endpoint response.

    Its completed discriminator carries the full saved completion outcome.
    """

    conversation_id: UUID
    request_id: UUID
    status: Literal["completed"]
    outcome: SubmitMessageResponse


class FailedRequestStatus(BaseModel):
    """Represent failed or interrupted execution in a successful status lookup.

    The nested error explains the turn failure; HTTP status retrieval can still return 200.
    """

    conversation_id: UUID
    request_id: UUID
    status: Literal["failed", "interrupted"]
    outcome: ErrorEnvelope


RequestStatusResponse = Annotated[
    AcceptedRequestResponse | CompletedRequestStatus | FailedRequestStatus,
    Field(discriminator="status"),
]
