"""Bound each non-streaming request at the model integration boundary."""

import json
import logging

from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from autoassist.chat.contracts import ChatProviderError, ChatProviderTimeoutError

MAX_PROVIDER_INPUT_BYTES = 128 * 1024
PARAMETERS = TypeAdapter(ModelRequestParameters)


def request_bytes(
    messages: list[ModelMessage],
    settings: ModelSettings | None,
    parameters: ModelRequestParameters,
) -> bytes:
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


class BudgetedModel(WrapperModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        settings, parameters = self.prepare_request(model_settings, model_request_parameters)
        if len(request_bytes(messages, settings, parameters)) > MAX_PROVIDER_INPUT_BYTES:
            raise ChatProviderError("provider input exceeds limit")
        try:
            return await self.wrapped.request(messages, settings, parameters)
        except TimeoutError as exc:
            raise ChatProviderTimeoutError from exc
        except ChatProviderError:
            raise
        except Exception as exc:
            # Only the external model call belongs here, never application tools.
            logging.getLogger(__name__).warning(
                "Chat provider failure: type=%s cause_type=%s status=%s",
                type(exc).__name__,
                type(exc.__cause__).__name__,
                exc.status_code if isinstance(exc, ModelHTTPError) else None,
            )
            if isinstance(exc, ModelHTTPError) and exc.status_code == 504:
                raise ChatProviderTimeoutError from exc
            raise ChatProviderError from exc
