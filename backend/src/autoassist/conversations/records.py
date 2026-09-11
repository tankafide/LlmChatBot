from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: str
    dealership_id: str
    connection_name: str
    provider: str
    model: str
    created_at: str
    selected_vehicle_id: str | None


@dataclass(frozen=True, slots=True)
class StoredRequestRecord:
    id: str
    client_request_id: str
    payload: str
    status: str
    terminal_http_status: int | None
    terminal_body: str | None


@dataclass(frozen=True, slots=True)
class RunContextRecord:
    conversation: ConversationRecord
    replay_units: tuple[str, ...]
    presented_vehicle_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessageRecord:
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
    conversation_id: str
    selected_vehicle_id: str | None
    items: tuple[MessageRecord, ...]
    next_after_sequence: int | None
