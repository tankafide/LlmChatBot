from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    """Provide strict, frozen Pydantic safety records that reject extra fields.

    Subclasses validate evidence boundaries; frozen field assignment does not recursively
    freeze nested dictionaries.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Identity(Record):
    """Identify a year/make/model safety lookup from inventory data.

    This is not a VIN identity and does not establish vehicle-specific recall repair status.
    """

    year: int
    make: str
    model: str


class Candidate(Record):
    """Represent one discovered NHTSA crash variant with its numeric upstream ID and bounded
    description.

    It is distinct from the inventory vehicle UUID.
    """

    vehicle_id: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=300)


class Presentation(Record):
    """Persist the bounded NHTSA variant menu actually shown for one inventory vehicle.

    Includes lookup identity, timestamp, displayed candidates, and full candidate count for
    later choice resolution.
    """

    inventory_vehicle_id: str
    lookup_identity: Identity
    candidates: tuple[Candidate, ...] = Field(min_length=1, max_length=5)
    total_candidate_count: int = Field(ge=1, le=100)
    retrieved_at: datetime

    @model_validator(mode="after")
    def consistent(self) -> Self:
        """Validate a displayed NHTSA candidate menu after field parsing.

        Pydantic calls this when constructing/restoring Presentation. Return self if IDs are
        unique and total count covers displayed choices; otherwise raise ValueError.
        """
        if self.total_candidate_count < len(self.candidates):
            raise ValueError("candidate count is smaller than displayed choices")
        if len({item.vehicle_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate displayed candidate")
        return self


class PresentationUpdate(Record):
    """Describe a keep, clear, or set update to pending safety choices.

    Only set carries a Presentation; successful completion persists this instruction alongside
    model replay.
    """

    action: Literal["keep", "clear", "set"]
    presentation: Presentation | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        """Require presentation data exactly when the action is set.

        Pydantic calls this when validating replay metadata. Return self for a consistent
        keep/clear/set update; raise ValueError when the action and payload disagree.
        """
        if (self.action == "set") != (self.presentation is not None):
            raise ValueError("only set carries a presentation")
        return self


class Category(Record):
    """Represent rated, not_rated, missing, or invalid crash data without conflating uncertainty
    with zero stars.

    Only rated carries a validated 1–5 star value.
    """

    status: Literal["rated", "not_rated", "missing", "invalid"]
    stars: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        """Require stars exactly when a rating category is rated.

        Pydantic calls this after individual fields are checked. Return self on consistency;
        raise ValueError for stars attached to uncertainty or missing from a rated category.
        """
        if (self.status == "rated") != (self.stars is not None):
            raise ValueError("only rated categories have stars")
        return self


class Campaign(Record):
    """Carry validated recall campaign details and optional urgent flags.

    clipped_fields records excerpted source fields; absent optional data does not prove
    absence of a concern.
    """

    campaign_number: str
    component: str | None
    summary: str | None
    consequence: str | None
    remedy: str | None
    report_date: date | None
    notes: str | None
    park_it: bool | None
    park_outside: bool | None
    clipped_fields: tuple[str, ...] = ()


class Provenance(Record):
    """Bind safety evidence to inventory identity, NHTSA source URL, and attempt/retrieval times.

    A missing retrieved_at distinguishes an attempt from confirmed retrieval.
    """

    inventory_vehicle_id: str
    stock_id: str
    lookup_identity: Identity
    source: Literal["NHTSA"] = "NHTSA"
    source_url: str
    attempted_at: datetime
    retrieved_at: datetime | None = None


Reason = Literal[
    "http_error",
    "transport_error",
    "timeout",
    "invalid_response",
    "response_limit",
    "budget_exhausted",
    "unsupported_identity",
]


class RecallResult(Provenance):
    """Represent available, verified-empty, or unavailable recall evidence with provenance.

    Counts track displayed/omitted campaigns and urgent flags; validation prevents successful
    data from being mixed with an unavailable status.
    """

    status: Literal["available", "empty", "unavailable"]
    reason: Reason | None = None
    total_count: int | None = Field(default=None, ge=0)
    campaigns: tuple[Campaign, ...] = Field(default=(), max_length=5)
    omitted_count: int = Field(default=0, ge=0)
    urgent_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        """Validate recall status, provenance, and campaign counts together.

        Pydantic calls this when building recall evidence. Return self for a valid
        available/empty/unavailable result. Raise ValueError if unavailable contains success
        data, success lacks provenance, empty contains campaigns, or totals disagree.
        """
        if self.status == "unavailable":
            if self.reason is None or self.total_count is not None or self.campaigns:
                raise ValueError("unavailable recalls cannot contain success data")
        elif self.reason is not None or self.retrieved_at is None:
            raise ValueError("successful recalls require retrieval provenance")
        elif self.status == "empty":
            if self.total_count != 0 or self.campaigns or self.omitted_count:
                raise ValueError("empty requires zero campaigns")
        elif not self.campaigns or self.total_count != len(self.campaigns) + self.omitted_count:
            raise ValueError("campaign counts disagree")
        return self


class CrashResult(Provenance):
    """Represent crash ratings, ambiguity, no record, or unavailable evidence with provenance.

    Categories distinguish missing/unrated/invalid values; validators align status with
    summary data. Concern coverage remains explicitly incomplete.
    """

    status: Literal[
        "available", "partial", "unrated", "no_ratings", "no_record", "ambiguous", "unavailable"
    ]
    reason: Reason | None = None
    matched_variant: Candidate | None = None
    candidates: tuple[Candidate, ...] = Field(default=(), max_length=5)
    total_candidate_count: int = Field(default=0, ge=0, le=100)
    categories: dict[str, Category] = Field(default_factory=dict)
    notes: dict[str, str | bool] = Field(default_factory=dict)
    concern_coverage_incomplete: bool = True
    concern_notes_omitted: int = Field(default=0, ge=0)
    dynamic_tip_result: str | bool | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        """Validate crash status against provenance, candidates, and summary ratings.

        Pydantic calls this when building crash evidence. Return self when fields agree; raise
        ValueError for success data on unavailable, missing success provenance, misplaced
        candidates, missing matched/category data, inconsistent summary status, or invalid
        candidate totals.
        """
        if self.status == "unavailable":
            if self.reason is None or self.categories or self.candidates:
                raise ValueError("unavailable crash result has success data")
        elif self.reason is not None or self.retrieved_at is None:
            raise ValueError("successful lookup requires retrieval provenance")
        if (self.status == "ambiguous") != bool(self.candidates):
            raise ValueError("only ambiguity carries candidates")
        if self.status in {"available", "partial", "unrated", "no_ratings"} and (
            self.matched_variant is None or not self.categories
        ):
            raise ValueError("ratings require identified categories")
        if self.categories:
            keys = {"overall", "frontal", "side", "rollover"}
            if not keys.issubset(self.categories):
                raise ValueError("summary categories missing")
            states = [self.categories[key].status for key in keys]
            expected = (
                "available"
                if all(value == "rated" for value in states)
                else "partial"
                if "rated" in states
                else "unrated"
                if all(value == "not_rated" for value in states)
                else "no_ratings"
            )
            if self.status != expected:
                raise ValueError("crash status disagrees with categories")
        if self.status == "ambiguous" and self.total_candidate_count < len(self.candidates):
            raise ValueError("crash candidate count mismatch")
        return self
