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
from autoassist.observability import current_turn


class GeminiModel(GoogleModel):
    """Retry rejected generations, never a whole agent turn or executed tools.

    Adds bounded handling for Gemini transient HTTP errors while the surrounding runner owns
    the total deadline.
    """

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Retry only a rejected Gemini generation within the surrounding turn deadline.

        Called by the model wrapper for each generation. Return ModelResponse on success.
        Retry HTTP 503/504 up to three attempts with bounded Retry-After handling; other
        errors, exhausted retries, unsupported delays, and cancellation propagate. Executed
        application tools are not rerun here.
        """
        for attempt in range(1, 4):
            metrics = current_turn.get()
            if attempt > 1 and metrics is not None:
                metrics.provider_attempts += 1
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
    """Adapt output/tool JSON schemas to Gemini limitations.

    Moves array-size guidance into descriptions while local Pydantic validation continues
    enforcing the original bounds.
    """

    def transform(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Adapt a JSON schema to Gemini while retaining local validation limits.

        Called by Google model schema preparation. Return the parent-transformed schema with
        maxItems moved into description text. Pydantic still enforces the original array
        bound; this changes provider guidance, not application validation.
        """
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
    """Construct a Gemini-backed grounded runner with explicit retry ownership.

    Called by startup or live evaluation. Return a PydanticChatRunner whose close callback
    owns the async client. SDK retries are disabled in favor of GeminiModel retries;
    constructing the runner does not execute a chat turn.
    """
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
