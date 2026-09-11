"""Conversation lifecycle: admission, provider execution, replay and failure settlement."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from sqlalchemy.exc import IntegrityError, OperationalError

from autoassist.chat.contracts import (
    ChatProviderError,
    ChatProviderTimeoutError,
    ChatRunner,
    ChatRunRequest,
    ChatRunResult,
)
from autoassist.chat.history import MAX_HISTORY_BYTES
from autoassist.config import RuntimeConfig
from autoassist.conversations.execution import ActiveTurnLimiter, database_write, finish_task
from autoassist.conversations.outcomes import (
    ConversationApplicationError,
    TerminalOutcome,
    error_body,
    terminal_outcome,
)
from autoassist.conversations.records import ConversationRecord, MessagePage, StoredRequestRecord
from autoassist.conversations.store import ConversationStore
from autoassist.db.database import is_storage_unavailable
from autoassist.inventory.service import StorageUnavailableError

MAX_REPLAY_UNIT_BYTES = MAX_HISTORY_BYTES
MAX_PUBLIC_REPLY_CHARS = 8_000


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        runtime_config: RuntimeConfig,
        runners: dict[str, ChatRunner],
        *,
        max_active_turns: int = 4,
        run_timeout_seconds: float = 60.0,
    ) -> None:
        self._store = store
        self._runtime_config = runtime_config
        self._runners = runners
        self._limiter = ActiveTurnLimiter(max_active_turns)
        self._run_timeout_seconds = run_timeout_seconds
        self._accepting = True

    async def create(self, dealership_id: str) -> ConversationRecord:
        try:
            dealership_connection = await asyncio.to_thread(
                self._store.dealership_connection, dealership_id
            )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc
        if dealership_connection is None:
            raise ConversationApplicationError(404, "not_found", "Dealership was not found.")
        connection_name = dealership_connection
        connection = self._runtime_config.connections.get(connection_name)
        if connection is None or connection_name not in self._runners:
            raise self._connection_unavailable()
        try:
            return await asyncio.to_thread(
                self._store.create,
                dealership_id,
                connection_name,
                connection.provider,
                connection.model,
            )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc

    async def history(
        self, dealership_id: str, conversation_id: str, after_sequence: int, limit: int
    ) -> MessagePage:
        try:
            page = await asyncio.to_thread(
                self._store.history, dealership_id, conversation_id, after_sequence, limit
            )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc
        if page is None:
            raise ConversationApplicationError(404, "not_found", "Conversation was not found.")
        return page

    async def submit(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> TerminalOutcome:
        try:
            await asyncio.to_thread(self._store.recover_stale, conversation_id)
            existing, conversation = await asyncio.to_thread(
                self._store.inspect, dealership_id, conversation_id, request_id
            )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc
        if conversation is None:
            raise ConversationApplicationError(404, "not_found", "Conversation was not found.")
        replay = self._classify_existing(existing, text)
        if replay is not None:
            return replay
        if not self._accepting:
            raise ConversationApplicationError(503, "server_busy", "The server is shutting down.")
        runner = self._runner_for(conversation)
        if not await self._limiter.try_acquire():
            raise ConversationApplicationError(503, "server_busy", "The chat server is busy.")

        admitted: StoredRequestRecord | None = None
        try:
            admitted, admitted_new = await self._admit_with_reconciliation(
                dealership_id, conversation_id, request_id, text
            )
            replay = None if admitted_new else self._classify_existing(admitted, text)
            if not admitted_new:
                if replay is None:
                    raise RuntimeError("terminal request has no replay outcome")
                return replay

            context = await asyncio.to_thread(
                self._store.load_context, dealership_id, conversation_id
            )
            if context is None:
                return await self._settle_failure(
                    admitted.id,
                    500,
                    "internal_error",
                    "The request could not be completed.",
                    "failed",
                )
            self._validate_pinned_connection(context.conversation)
            run_request = ChatRunRequest(
                dealership_id=dealership_id,
                conversation_id=conversation_id,
                request_id=request_id,
                text=text,
                selected_vehicle_id=context.conversation.selected_vehicle_id,
                presented_vehicle_ids=context.presented_vehicle_ids,
                replay_units=context.replay_units,
                deadline=time.monotonic() + self._run_timeout_seconds,
            )
            try:
                async with asyncio.timeout(self._run_timeout_seconds):
                    result = await runner.run(run_request)
                self._validate_run_result(result)
            except (TimeoutError, ChatProviderTimeoutError):
                return await self._settle_failure(
                    admitted.id,
                    504,
                    "provider_timeout",
                    "The chat provider timed out.",
                    "failed",
                )
            except ChatProviderError:
                return await self._settle_failure(
                    admitted.id,
                    502,
                    "provider_error",
                    "The chat provider could not complete the request.",
                    "failed",
                )
            except StorageUnavailableError:
                # Tool read failed, but request storage may still be available.
                # Persist a terminal result to release the claim. If that commit
                # also fails, the outer storage recovery path retains uncertainty.
                return await self._settle_failure(
                    admitted.id,
                    503,
                    "storage_unavailable",
                    "Inventory storage is unavailable.",
                    "failed",
                )
            try:
                return await database_write(
                    self._store.complete, dealership_id, admitted.id, result
                )
            except ChatProviderError:
                return await self._settle_failure(
                    admitted.id,
                    502,
                    "provider_error",
                    "The chat provider could not complete the request.",
                    "failed",
                )
            except OperationalError as exc:
                if not is_storage_unavailable(exc):
                    raise
                reconciled = await self._reconcile_terminal(
                    dealership_id, conversation_id, request_id, text
                )
                if reconciled is not None:
                    return reconciled
                raise self._storage_unavailable() from exc
        except asyncio.CancelledError:
            if admitted is not None:
                await finish_task(
                    asyncio.create_task(
                        self._settle_failure(
                            admitted.id,
                            409,
                            "request_interrupted",
                            "The request was interrupted before completion.",
                            "interrupted",
                        )
                    )
                )
            raise
        except ConversationApplicationError:
            raise
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                if admitted is not None:
                    logging.getLogger(__name__).error(
                        "Chat application failure: request_id=%s type=%s",
                        request_id,
                        type(exc).__name__,
                    )
                    return await self._settle_failure(
                        admitted.id,
                        500,
                        "internal_error",
                        "The request could not be completed.",
                        "failed",
                    )
                raise
            if admitted is not None:
                reconciled = await self._reconcile_terminal(
                    dealership_id, conversation_id, request_id, text
                )
                if reconciled is not None:
                    return reconciled
            raise self._storage_unavailable() from exc
        except Exception as exc:
            if admitted is not None:
                logging.getLogger(__name__).error(
                    "Chat application failure: request_id=%s type=%s",
                    request_id,
                    type(exc).__name__,
                )
                return await self._settle_failure(
                    admitted.id,
                    500,
                    "internal_error",
                    "The request could not be completed.",
                    "failed",
                )
            raise
        finally:
            await self._limiter.release()

    async def shutdown(self) -> None:
        self._accepting = False
        with suppress(TimeoutError):
            await self._limiter.wait_idle(20.0)
        await asyncio.gather(*(runner.close() for runner in self._runners.values()))

    async def _admit_with_reconciliation(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> tuple[StoredRequestRecord, bool]:
        task = asyncio.create_task(
            self._admit_and_classify(dealership_id, conversation_id, request_id, text)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled await does not stop a thread or roll back its transaction.
            # Settle only a turn owned by this caller, never a duplicate's active turn.
            async def cleanup() -> None:
                admitted, is_new = await finish_task(task)
                if is_new:
                    await self._settle_failure(
                        admitted.id,
                        409,
                        "request_interrupted",
                        "The request was interrupted before completion.",
                        "interrupted",
                    )

            with suppress(Exception):
                await finish_task(asyncio.create_task(cleanup()))
            raise

    async def _admit_and_classify(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> tuple[StoredRequestRecord, bool]:
        try:
            return await asyncio.to_thread(
                self._store.admit, dealership_id, conversation_id, request_id, text
            )
        except IntegrityError:
            existing, conversation = await asyncio.to_thread(
                self._store.inspect, dealership_id, conversation_id, request_id
            )
            if conversation is None:
                raise ConversationApplicationError(
                    404, "not_found", "Conversation was not found."
                ) from None
            if existing is not None:
                return existing, False
            raise ConversationApplicationError(
                409, "conversation_busy", "Another request is active for this conversation."
            ) from None

    async def _settle_failure(
        self,
        internal_request_id: str,
        status_code: int,
        code: str,
        message: str,
        request_status: str,
    ) -> TerminalOutcome:
        body = error_body(code, message)
        try:
            return await asyncio.to_thread(
                self._store.settle_failure,
                internal_request_id,
                status_code,
                body,
                request_status,
            )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc

    async def _reconcile_terminal(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> TerminalOutcome | None:
        existing, _ = await asyncio.to_thread(
            self._store.inspect, dealership_id, conversation_id, request_id
        )
        if existing is None or existing.payload != text or existing.status == "in_progress":
            return None
        return terminal_outcome(existing)

    def _runner_for(self, conversation: ConversationRecord) -> ChatRunner:
        self._validate_pinned_connection(conversation)
        runner = self._runners.get(conversation.connection_name)
        if runner is None:
            raise self._connection_unavailable()
        return runner

    def _validate_pinned_connection(self, conversation: ConversationRecord) -> None:
        connection = self._runtime_config.connections.get(conversation.connection_name)
        if (
            connection is None
            or connection.provider != conversation.provider
            or connection.model != conversation.model
            or conversation.connection_name not in self._runners
        ):
            raise self._connection_unavailable()

    @staticmethod
    def _validate_run_result(result: ChatRunResult) -> None:
        if not result.reply or len(result.reply) > MAX_PUBLIC_REPLY_CHARS:
            raise ChatProviderError("invalid public reply")
        if len(result.replay_json.encode("utf-8")) > MAX_REPLAY_UNIT_BYTES:
            raise ChatProviderError("replay unit exceeds limit")
        if result.presented_vehicle_ids is not None and len(result.presented_vehicle_ids) > 10:
            raise ChatProviderError("too many presented vehicles")
        if result.selection_action == "set" and result.selected_vehicle_id is None:
            raise ChatProviderError("missing selected vehicle")

    @staticmethod
    def _classify_existing(
        existing: StoredRequestRecord | None, text: str
    ) -> TerminalOutcome | None:
        if existing is None:
            return None
        if existing.payload != text:
            raise ConversationApplicationError(
                409,
                "request_id_conflict",
                "The request ID was already used with different text.",
            )
        if existing.status == "in_progress":
            raise ConversationApplicationError(
                409, "request_in_progress", "This request is still in progress."
            )
        return terminal_outcome(existing)

    @staticmethod
    def _connection_unavailable() -> ConversationApplicationError:
        return ConversationApplicationError(
            503, "connection_unavailable", "The configured chat connection is unavailable."
        )

    @staticmethod
    def _storage_unavailable() -> ConversationApplicationError:
        return ConversationApplicationError(
            503, "storage_unavailable", "Conversation storage is unavailable."
        )
