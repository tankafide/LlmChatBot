"""Serializable application outcomes shared by lifecycle and transaction units."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from autoassist.conversations.records import StoredRequestRecord


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def error_body(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message}}


@dataclass(frozen=True, slots=True)
class TerminalOutcome:
    status_code: int
    body: dict[str, Any]


class ConversationApplicationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.outcome = TerminalOutcome(status_code, error_body(code, message))


def terminal_outcome(request: StoredRequestRecord) -> TerminalOutcome:
    if request.terminal_http_status is None or request.terminal_body is None:
        raise RuntimeError("terminal request is missing its stored outcome")
    body = json.loads(request.terminal_body)
    if not isinstance(body, dict):
        raise RuntimeError("stored terminal outcome is invalid")
    return TerminalOutcome(request.terminal_http_status, body)
