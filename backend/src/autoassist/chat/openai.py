from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from autoassist.chat.grounded import PydanticChatRunner
from autoassist.inventory.service import InventoryService


def create_openai_runner(
    model_name: str, api_key: str, inventory: InventoryService
) -> PydanticChatRunner:
    """Construct an OpenAI Responses runner with explicit timeout and no SDK retries.

    Called by startup or live evaluation. Return a grounded runner that closes its client on
    shutdown. Construction wires dependencies; the provider is invoked only by a subsequent
    run.
    """
    client = AsyncOpenAI(api_key=api_key, timeout=30.0, max_retries=0)
    model = OpenAIResponsesModel(
        model_name,
        provider=OpenAIProvider(openai_client=client),
    )
    return PydanticChatRunner(model, inventory, close_callback=client)
