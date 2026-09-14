from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    """Detach conversation identity, pinned provider configuration, and selection from an ORM
    session.

    The immutable snapshot can cross worker-thread/async boundaries without lazy database
    access.
    """

    id: str
    dealership_id: str
    connection_name: str
    provider: str
    model: str
    created_at: str
    selected_vehicle_id: str | None


@dataclass(frozen=True, slots=True)
class StoredRequestRecord:
    """Detach request retry identity, payload, status, and stored terminal outcome.

    id is internal ownership identity; client_request_id is the browser retry identity.
    Terminal fields are absent while active.
    """

    id: str
    client_request_id: str
    payload: str
    status: str
    terminal_http_status: int | None
    terminal_body: str | None


@dataclass(frozen=True, slots=True)
class RunContextRecord:
    """Package the durable context loaded before provider execution.

    Contains the conversation snapshot, bounded completed replay, and ordered last-presented
    inventory IDs.
    """

    conversation: ConversationRecord
    replay_units: tuple[str, ...]
    presented_vehicle_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """Represent a saved message independently of an ORM session.

    Sequence defines order, request_id is the client identity, and request status/error
    explain failed user turns without inventing assistant replies.
    """

    id: str
    sequence: int
    request_id: str
    role: str
    text: str
    created_at: str
    request_status: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class MessagePage:
    """Carry a materialized history page and current vehicle selection.

    next_after_sequence is None when exhausted; items may be empty for an existing
    conversation.
    """

    conversation_id: str
    selected_vehicle_id: str | None
    items: tuple[MessageRecord, ...]
    next_after_sequence: int | None
