from __future__ import annotations

import json

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo


class ScriptedSafety:
    """Scripted model calls real application tools and the real output validator."""

    async def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        context = None
        current: list[ToolReturnPart] = []
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                        context = json.loads(part.content.split(": ", 1)[1])
                        current = []
                    elif isinstance(part, ToolReturnPart):
                        current.append(part)
        assert context is not None
        text = context["user_text"]
        completed = {part.tool_name for part in current}
        if text.startswith("stock"):
            if "get_vehicle_by_stock" not in completed:
                return ModelResponse(
                    [ToolCallPart("get_vehicle_by_stock", {"stock_number": text.split()[1]})]
                )
            vehicle_id = current[-1].content["vehicle"]["vehicle_id"]
            answer = {
                "intent": "details",
                "vehicles": [{"vehicle_id": vehicle_id}],
            }
        else:
            needed = (
                ["lookup_recalls", "lookup_crash_ratings"]
                if text == "both"
                else ["lookup_recalls"]
                if text == "recalls"
                else ["lookup_crash_ratings"]
            )
            for tool in needed:
                if tool not in completed:
                    return ModelResponse([ToolCallPart(tool, {})])
            ids = [part.content["evidence_id"] for part in current if "evidence_id" in part.content]
            answer = {"intent": "safety" if ids else "clarify", "safety_evidence_ids": ids}
        return ModelResponse([ToolCallPart(info.output_tools[0].name, answer)])
