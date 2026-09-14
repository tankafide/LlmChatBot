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
from autoassist.conversations.leases import stop_task, sweep_stale
from autoassist.conversations.repository import ConversationRepository
from autoassist.conversations.service import ConversationService
from autoassist.conversations.store import ConversationStore
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import (
    check_storage,
    create_database_engine,
    database_startup_lock,
    initialize_schema,
    make_session_factory,
)
from autoassist.integrations.nhtsa import NhtsaClient, create_client
from autoassist.inventory.repository import InventoryRepository
from autoassist.inventory.service import InventoryService
from autoassist.observability import configure_events
from autoassist.safety.service import SafetyService

RunnerFactory = Callable[[str, str, InventoryService], ChatRunner]


def create_app(
    settings: Settings | None = None, *, runner_factory: RunnerFactory | None = None
) -> FastAPI:
    """Build the FastAPI application and register its routes and resource lifespan.

    Called by main.py when constructing the server, or by tests with injected settings
    and a fake runner factory. Resource initialization occurs when lifespan starts.
    Return the configured FastAPI instance; this factory does not run a chat turn.
    """
    configured_settings = settings
    run_timeout_seconds = 60.0

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own the per-worker services for the lifetime of the running application.

        FastAPI enters this context at startup and exits it at shutdown. Initialize storage,
        provider runners, and recovery tasks, then yield None while requests are served.
        On exit, drain conversation work and close resources covered by the cleanup blocks.
        Configuration, startup, or cleanup failures propagate; yield is not a chat result.
        """
        configure_events()
        sweeper: asyncio.Task[None] | None = None
        runtime_settings = configured_settings or Settings()
        runtime_config = load_runtime_config(runtime_settings.config_file)
        engine = create_database_engine(runtime_settings.database_url)
        session_factory = make_session_factory(engine)
        nhtsa_client = create_client()
        runners: dict[str, ChatRunner] = {}
        try:
            app.state.safety_service = SafetyService(NhtsaClient(nhtsa_client))
            # Multiple workers may start together. The database startup lock serializes
            # schema/bootstrap work; ordinary startup preserves existing conversations.
            with database_startup_lock(engine):
                initialize_schema(engine)
                bootstrap_dealerships(session_factory, runtime_config)
            check_storage(session_factory)
            app.state.engine = engine
            app.state.session_factory = session_factory
            inventory_service = InventoryService(session_factory, InventoryRepository())
            app.state.inventory_service = inventory_service
            # Build runners only for configured credentials/models. Missing provider setup
            # does not prevent inventory/history access; new chat execution checks availability.
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
            conversation_store = ConversationStore(
                session_factory,
                ConversationRepository(),
                lease_seconds=120.0 if engine.dialect.name == "postgresql" else 0.0,
            )
            conversation_service = ConversationService(
                conversation_store,
                runtime_config,
                runners,
                run_timeout_seconds=run_timeout_seconds,
            )
            # Recover expired requests before serving traffic, then sweep periodically.
            # Fresh PostgreSQL leases protect turns still owned by another worker.
            await asyncio.to_thread(conversation_store.recover_interrupted)
            if conversation_store.leases_enabled:
                sweeper = asyncio.create_task(sweep_stale(conversation_store))
            app.state.conversation_service = conversation_service
            yield
        finally:
            active_service = getattr(app.state, "conversation_service", None)
            try:
                # Drain owned conversation work before closing clients or the database pool.
                # If startup failed earlier, close any runners already constructed instead.
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
                await stop_task(sweeper)
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
