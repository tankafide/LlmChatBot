"""Per-turn tool state and budgets, owned by the agent adapter."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from pydantic_ai import ModelRetry

from autoassist.chat.budget import MAX_PROVIDER_INPUT_BYTES
from autoassist.chat.contracts import ChatRunRequest
from autoassist.integrations.nhtsa import LookupBudget
from autoassist.inventory.records import VehicleRecord
from autoassist.inventory.service import InventoryService
from autoassist.safety.records import Presentation
from autoassist.safety.service import SafetyRun, SafetyService

MAX_TOOL_RESULT_BYTES = 16 * 1024


@dataclass(slots=True)
class ChatDependencies:
    inventory: InventoryService
    request: ChatRunRequest
    safety: SafetyService | None = None
    safety_run: SafetyRun = field(
        default_factory=lambda: SafetyRun(LookupBudget(time.monotonic() + 60))
    )
    safety_presentation: Presentation | None = None
    evidence: dict[str, VehicleRecord] = field(default_factory=dict)
    search_executed: bool = False
    last_search_ids: tuple[str, ...] = ()
    tool_invocations: int = 0
    tool_result_bytes: int = 0

    def register_tool_result(self, value: object) -> None:
        self.tool_invocations += 1
        if self.tool_invocations > 8:
            raise ModelRetry("The tool invocation budget is exhausted.")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_TOOL_RESULT_BYTES:
            raise ModelRetry("The tool result is too large.")
        self.tool_result_bytes += len(encoded)
        if self.tool_result_bytes > MAX_PROVIDER_INPUT_BYTES // 2:
            raise ModelRetry("The total tool result budget is exhausted.")
