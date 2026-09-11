"""Browser smoke support: reuse safety fakes and choose a stable imported stock number."""

from container_acceptance_app import DeterministicAcceptanceRunner

from autoassist.app import create_app
from autoassist.chat.contracts import ChatRunRequest, ChatRunResult
from autoassist.inventory.service import InventoryService


class BrowserAcceptanceRunner(DeterministicAcceptanceRunner):
    async def run(self, request: ChatRunRequest) -> ChatRunResult:
        if request.text.startswith("stock "):
            return await self._safety_runner.run(request)
        return await super().run(request)


def runner_factory(
    _model_name: str, _api_key: str, inventory: InventoryService
) -> BrowserAcceptanceRunner:
    return BrowserAcceptanceRunner(inventory)


app = create_app(runner_factory=runner_factory)
