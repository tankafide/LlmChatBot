"""Payload-free operational events and task-local model counters."""

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(slots=True)
class TurnMetrics:
    """Hold mutable counters and correlation IDs for one executing turn.

    A ContextVar associates these values with async work; this is operational metadata, not
    durable request state.
    """

    conversation_id: str
    request_id: str
    model_calls: int = 0
    provider_attempts: int = 0
    tool_calls: int = 0


current_turn: ContextVar[TurnMetrics | None] = ContextVar("current_turn", default=None)
logger = logging.getLogger("autoassist.events")


def configure_events() -> None:
    """Configure the application event logger once without duplicating handlers.

    Called at startup. Install a plain stream handler if absent, enable INFO, and disable
    propagation. Return None; existing handlers are retained.
    """
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def event(name: str, **fields: str | int | float | None) -> None:
    """Emit one structured event with optional current-turn correlation IDs.

    Called throughout lifecycle and integration code. Explicit fields override context fields,
    then compact JSON is logged. Return None. Callers must pass metadata only: this helper
    does not redact secrets or payload text.
    """
    metrics = current_turn.get()
    values: dict[str, str | int | float | None] = {"event": name}
    if metrics is not None:
        values.update(conversation_id=metrics.conversation_id, request_id=metrics.request_id)
    values.update(fields)
    logger.info(json.dumps(values, separators=(",", ":"), sort_keys=True))
