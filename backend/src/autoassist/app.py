from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from autoassist.api.routes import router
from autoassist.chat.contracts import ChatRunner
from autoassist.chat.gemini import create_gemini_runner
from autoassist.chat.grok import create_grok_runner
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.chat.openai import create_openai_runner
from autoassist.config import Settings, load_runtime_config
from autoassist.conversations.repository import ConversationRepository
from autoassist.conversations.service import ConversationService
from autoassist.conversations.store import ConversationStore
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import (
    check_storage,
    create_database_engine,
    initialize_schema,
    make_session_factory,
)
from autoassist.integrations.nhtsa import NhtsaClient, create_client
from autoassist.inventory.repository import InventoryRepository
from autoassist.inventory.service import InventoryService
from autoassist.safety.service import SafetyService

RunnerFactory = Callable[[str, str, InventoryService], ChatRunner]


def create_app(
    settings: Settings | None = None, *, runner_factory: RunnerFactory | None = None
) -> FastAPI:
    configured_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_settings = configured_settings or Settings()
        runtime_config = load_runtime_config(runtime_settings.config_file)
        engine = create_database_engine(runtime_settings.database_url)
        session_factory = make_session_factory(engine)
        nhtsa_client = create_client()
        runners: dict[str, ChatRunner] = {}
        try:
            app.state.safety_service = SafetyService(NhtsaClient(nhtsa_client))
            initialize_schema(engine)
            bootstrap_dealerships(session_factory, runtime_config)
            check_storage(session_factory)
            app.state.engine = engine
            app.state.session_factory = session_factory
            inventory_service = InventoryService(session_factory, InventoryRepository())
            app.state.inventory_service = inventory_service
            for name, connection in runtime_config.connections.items():
                api_key = os.environ.get(connection.api_key_env)
                if api_key and not connection.model.startswith("REPLACE_WITH_"):
                    factory = (
                        runner_factory
                        or {
                            "google": create_gemini_runner,
                            "openai": create_openai_runner,
                            "xai": create_grok_runner,
                        }[connection.provider]
                    )
                    runner = factory(connection.model, api_key, inventory_service)
                    if isinstance(runner, PydanticChatRunner):
                        runner.set_safety_service(app.state.safety_service)
                    runners[name] = runner
            conversation_store = ConversationStore(session_factory, ConversationRepository())
            conversation_service = ConversationService(
                conversation_store,
                runtime_config,
                runners,
            )
            conversation_store.recover_interrupted()
            app.state.conversation_service = conversation_service
            yield
        finally:
            active_service = getattr(app.state, "conversation_service", None)
            try:
                if isinstance(active_service, ConversationService):
                    await active_service.shutdown()
                else:
                    results = await asyncio.gather(
                        *(runner.close() for runner in runners.values()), return_exceptions=True
                    )
                    for result in results:
                        if isinstance(result, BaseException):
                            logging.getLogger(__name__).warning(
                                "Startup cleanup failure: type=%s", type(result).__name__
                            )
            finally:
                await nhtsa_client.aclose()
                engine.dispose()

    app = FastAPI(
        title="AutoAssist API",
        version="0.1.0",
        description="Durable dealership inventory and conversational search API.",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app
