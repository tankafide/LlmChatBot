from __future__ import annotations

import importlib

from pydantic_ai.models.xai import XaiModel
from pydantic_ai.providers.xai import XaiProvider

from autoassist.chat.budget import MAX_PROVIDER_INPUT_BYTES
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.inventory.service import InventoryService


def create_grok_runner(
    model_name: str, api_key: str, inventory: InventoryService
) -> PydanticChatRunner:
    """Construct a Grok-backed grounded runner with bounded transport settings.

    Called by startup or live evaluation. Return the runner with client cleanup attached.
    Import the optional xai SDK here, disable transport retries, and cap outgoing message
    size; missing SDK or invalid client configuration raises before any chat turn.
    """
    xai_sdk = importlib.import_module("xai_sdk")
    client = xai_sdk.AsyncClient(
        api_key=api_key,
        timeout=30.0,
        channel_options=[
            ("grpc.enable_retries", 0),
            ("grpc.max_send_message_length", MAX_PROVIDER_INPUT_BYTES),
        ],
    )
    provider = XaiProvider(xai_client=client)
    model = XaiModel(model_name, provider=provider)
    return PydanticChatRunner(model, inventory, close_callback=client)
