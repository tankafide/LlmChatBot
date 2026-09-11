import asyncio
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.profiles.google import GoogleJsonSchemaTransformer, GoogleModelProfile
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings

from autoassist.chat.grounded import PydanticChatRunner
from autoassist.inventory.service import InventoryService


class GeminiModel(GoogleModel):
    """Retry rejected generations, never a whole agent turn or executed tools."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        for attempt in range(1, 4):
            try:
                return await super().request(messages, model_settings, model_request_parameters)
            except ModelHTTPError as exc:
                if exc.status_code not in {503, 504} or attempt == 3:
                    raise
                delay = float(attempt)
                headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
                if "retry-after" in headers:
                    # Do not retry earlier than the provider asks. Long or date-form
                    # waits are left to a later user attempt, within the 60s turn cap.
                    try:
                        requested = float(headers["retry-after"])
                    except ValueError:
                        raise exc from None
                    if not 0 <= requested <= 5:
                        raise
                    delay = max(delay, requested)
                logging.getLogger(__name__).warning(
                    "Gemini transient failure: status=%d attempt=%d retry_delay=%.1f",
                    exc.status_code,
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
        raise AssertionError("Unreachable retry state")


class GeminiSchemaTransformer(GoogleJsonSchemaTransformer):
    def transform(self, schema: dict[str, Any]) -> dict[str, Any]:
        schema = super().transform(schema)
        # Gemini rejects our nested bounded arrays with HTTP 400. Keep the bound
        # as model guidance here; Pydantic still enforces it on every tool/output.
        if (maximum := schema.pop("maxItems", None)) is not None:
            description = schema.get("description", "")
            schema["description"] = f"{description} At most {maximum} items.".strip()
        return schema


def create_gemini_runner(
    model_name: str, api_key: str, inventory: InventoryService
) -> PydanticChatRunner:
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    model = GeminiModel(
        model_name,
        provider=GoogleProvider(client=client),
        profile=GoogleModelProfile(json_schema_transformer=GeminiSchemaTransformer),
    )
    return PydanticChatRunner(model, inventory, close_callback=client.aio)
