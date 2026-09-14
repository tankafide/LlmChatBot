"""Serializable application outcomes shared by lifecycle and transaction units."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from autoassist.conversations.records import StoredRequestRecord


def utc_now() -> str:
    """Return the current UTC time as an ISO string with microseconds.

    Used for persisted display/audit timestamps. Lease ownership uses the database clock
    instead; this helper reads the worker clock.
    """
    return datetime.now(UTC).isoformat(timespec="microseconds")


def canonical_json(value: object) -> str:
    """Serialize a JSON-compatible value with deterministic key ordering.

    Used for persisted outcome and context bodies. Return compact Unicode JSON; unsupported
    objects or cyclic structures raise serialization errors rather than being coerced.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def error_body(code: str, message: str) -> dict[str, object]:
    """Build the standard public error envelope from a safe code and message.

    Used by lifecycle settlement and application exceptions. Return a new dictionary; this
    neither raises nor sanitizes arbitrary input.
    """
    return {"error": {"code": code, "message": message}}


@dataclass(frozen=True, slots=True)
class ConversationOutcome:
    status_code: int
    body: dict[str, Any]


class ConversationApplicationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        """Attach a public HTTP outcome to an application exception.

        Constructed by lifecycle validation/failure paths. Store the code/message envelope and
        return None; callers raise the instance and routes translate its outcome.
        """
        super().__init__(message)
        self.outcome = ConversationOutcome(status_code, error_body(code, message))


def terminal_outcome(request: StoredRequestRecord) -> ConversationOutcome:
    """Reconstruct a terminal HTTP outcome without rerunning the turn.

    Used for retries and competing terminal writers. Return the saved status and decoded
    object body. Raise RuntimeError for missing terminal fields/non-object JSON; malformed
    JSON raises its decoding error.
    """
    if request.terminal_http_status is None or request.terminal_body is None:
        raise RuntimeError("terminal request is missing its stored outcome")
    body = json.loads(request.terminal_body)
    if not isinstance(body, dict):
        raise RuntimeError("stored terminal outcome is invalid")
    return ConversationOutcome(request.terminal_http_status, body)
