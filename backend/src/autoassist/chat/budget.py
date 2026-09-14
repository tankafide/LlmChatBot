"""Bound each non-streaming request at the model integration boundary."""

import json
import logging
import time

from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from autoassist.chat.contracts import ChatProviderError, ChatProviderTimeoutError
from autoassist.observability import current_turn, event

MAX_PROVIDER_INPUT_BYTES = 128 * 1024
PARAMETERS = TypeAdapter(ModelRequestParameters)


def request_bytes(
    messages: list[ModelMessage],
    settings: ModelSettings | None,
    parameters: ModelRequestParameters,
) -> bytes:
    """Serialize messages, settings, and request parameters into bytes for size accounting. Return
    the complete application envelope; this does not send a provider request.

    Called by BudgetedModel.request before sending provider input.
    """
    # Count the complete serialized envelope, including instructions, both tool schemas,
    # all tool/repair messages and JSON delimiters; never count just content strings.
    return (
        b'{"messages":'
        + ModelMessagesTypeAdapter.dump_json(messages)
        + b',"settings":'
        + json.dumps(settings or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b',"parameters":'
        + PARAMETERS.dump_json(parameters)
        + b"}"
    )


# Wrap each provider request, including model repair attempts, with the same
# input-size boundary and instrumentation.
class BudgetedModel(WrapperModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Check input size, invoke the wrapped provider, and return ModelResponse. Raise
        ChatProviderError/ChatProviderTimeoutError on size/provider failure; record metrics on
        attempted calls.

        Called by Pydantic AI for each model request.
        """
        # Measure effective settings and schemas too. History limits alone do not
        # bound instructions, current tool evidence, or other request overhead.
        settings, parameters = self.prepare_request(model_settings, model_request_parameters)
        if len(request_bytes(messages, settings, parameters)) > MAX_PROVIDER_INPUT_BYTES:
            raise ChatProviderError("provider input exceeds limit")
        started = time.monotonic()
        outcome = "error"
        metrics = current_turn.get()
        if metrics is not None:
            metrics.model_calls += 1
            metrics.provider_attempts += 1
        try:
            response = await self.wrapped.request(messages, settings, parameters)
            # Count proposed tool calls separately from the final-answer tool. This metric
            # describes model output, not proof that every proposed tool executed successfully.
            count = sum(
                isinstance(part, ToolCallPart) and part.tool_name != "final_result"
                for part in response.parts
            )
            if metrics is not None:
                metrics.tool_calls += count
            outcome = "received"
            return response
        # Convert external model errors into domain errors used by conversation
        # settlement. Application tool execution occurs outside this exception boundary.
        except TimeoutError as exc:
            outcome = "timeout"
            raise ChatProviderTimeoutError from exc
        except ChatProviderError:
            raise
        except Exception as exc:
            # Only the external model call belongs here, never application tools.
            # Log error classifications rather than raw exception text that could contain
            # sensitive provider payloads or request details.
            logging.getLogger(__name__).warning(
                "Chat provider failure: type=%s cause_type=%s status=%s",
                type(exc).__name__,
                type(exc.__cause__).__name__,
                exc.status_code if isinstance(exc, ModelHTTPError) else None,
            )
            if isinstance(exc, ModelHTTPError) and exc.status_code == 504:
                raise ChatProviderTimeoutError from exc
            raise ChatProviderError from exc

        finally:
            event(
                "provider_request",
                outcome=outcome,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
