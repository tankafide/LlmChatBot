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
    async def run(self, request: ChatRunRequest) -> ChatRunResult: ...

    async def close(self) -> None: ...


class ChatProviderError(RuntimeError):
    pass


class ChatProviderTimeoutError(ChatProviderError):
    pass
