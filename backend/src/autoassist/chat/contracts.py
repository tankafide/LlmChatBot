from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatRunRequest:
    dealership_id: str
    conversation_id: str
    request_id: str
    text: str
    selected_vehicle_id: str | None
    presented_vehicle_ids: tuple[str, ...]
    replay_units: tuple[str, ...]
    deadline: float | None = None


@dataclass(frozen=True, slots=True)
class ChatRunResult:
    reply: str
    replay_json: str
    presented_vehicle_ids: tuple[str, ...] | None = None
    selection_action: Literal["keep", "set", "clear"] = "keep"
    selected_vehicle_id: str | None = None


class ChatRunner(Protocol):
    async def run(self, request: ChatRunRequest) -> ChatRunResult:
        """Produce a grounded result for one admitted turn.

        Implemented by provider runners and called by ConversationService or evaluation.
        Resolve to ChatRunResult containing reply, replay, and proposed context updates;
        persistence belongs to the caller. Implementations may raise provider timeout/failure,
        storage errors, or cancellation.
        """
        ...

    async def close(self) -> None:
        """Release resources owned by a runner.

        Implemented by provider adapters and awaited during shutdown or startup cleanup.
        Resolve to None after closing clients; cleanup exceptions can propagate. This protocol
        declares the contract without providing an implementation.
        """
        ...


class ChatProviderError(RuntimeError):
    pass


class ChatProviderTimeoutError(ChatProviderError):
    pass
