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
from autoassist.conversations.leases import renew_owner, stop_task
from autoassist.conversations.outcomes import (
    ConversationApplicationError,
    ConversationOutcome,
    error_body,
    terminal_outcome,
)
from autoassist.conversations.records import ConversationRecord, MessagePage, StoredRequestRecord
from autoassist.conversations.store import ConversationStore
from autoassist.db.database import is_storage_unavailable
from autoassist.inventory.service import StorageUnavailableError
from autoassist.observability import TurnMetrics, current_turn, event

MAX_REPLAY_UNIT_BYTES = MAX_HISTORY_BYTES
MAX_PUBLIC_REPLY_CHARS = 8_000


# Reading path: submit -> admission commit -> tracked _execute task -> completion.
# The HTTP request waits only for admission; status/history expose the durable result.
# Store calls run in worker threads so synchronous SQL does not block the event loop.
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
        """Wire storage/configuration/runners and initialize per-process capacity and task
        tracking. Return None; no provider call or database write occurs.

        Constructed by app lifespan once per server worker.
        """
        self._store = store
        self._runtime_config = runtime_config
        self._runners = runners
        # This limits work in this process. Database constraints separately enforce
        # one active request per conversation across all server workers.
        self._limiter = ActiveTurnLimiter(max_active_turns)
        self._run_timeout_seconds = run_timeout_seconds
        self._accepting = True
        self._tasks: dict[str, asyncio.Task[ConversationOutcome]] = {}
        self._admissions: set[asyncio.Task[object]] = set()

    async def create(self, dealership_id: str, creation_id: str) -> ConversationRecord:
        """Return the existing or newly committed conversation for creation_id. Raise
        ConversationApplicationError for missing scope, unavailable configuration, or recognized
        storage failure.

        Called by the create-conversation HTTP route before the first message of a new chat;
        same creation-ID retries recover that conversation.
        """
        try:
            existing = await asyncio.to_thread(
                self._store.find_creation, dealership_id, creation_id
            )
            # Recover a previous creation before checking provider availability: retrying
            # a lost creation response should not require a working model connection.
            if existing is not None:
                return existing
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
            return await database_write(
                self._store.create,
                dealership_id,
                connection_name,
                connection.provider,
                connection.model,
                creation_id,
            )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc

    async def history(
        self, dealership_id: str, conversation_id: str, after_sequence: int, limit: int
    ) -> MessagePage:
        """Return a materialized message page. Raise a 404 application error if the conversation is
        missing, or 503 for recognized storage failure.

        Called by the history HTTP route for page loads, pagination, and recovery.
        """
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
    ) -> ConversationOutcome:
        """Track a message submission until admission transfers ownership or finishes.

        Called by routes.submit_message for every message POST, including the first message
        of an existing conversation and retries. Register the current asyncio task so shutdown
        cannot overlook a user-message commit that has not launched background execution yet.
        Delegate admission to _submit and always remove the task from _admissions afterward.
        This method does not create a conversation or wait for the model reply.

        Returns:
            A ConversationOutcome containing HTTP status and response body: 202 for a newly
            admitted or already-active request, a stored success/failure for a terminal retry,
            or a settled launch/shutdown failure. A returned outcome can itself represent error.

        Raises:
            ConversationApplicationError: Missing conversation (404), conflicting request text
                or busy conversation (409), unavailable connection/storage or process capacity
                (503). The route converts this exception into an HTTP response.
            asyncio.CancelledError: Caller cancellation, after owned admission reconciliation.
            AssertionError: Invoked without a current asyncio task.
            Other unexpected database/programming errors propagate rather than claiming success.
        """
        task = asyncio.current_task()
        assert task is not None
        # Track admission too, so shutdown can drain the gap before execution starts.
        self._admissions.add(task)
        try:
            return await self._submit(dealership_id, conversation_id, request_id, text)
        finally:
            self._admissions.discard(task)

    async def _submit(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> ConversationOutcome:
        """Classify a retry or admit one new message and launch its background turn.

        Called by submit while the admission task is tracked for shutdown. Inspect durable
        state, recover stale work, and resolve an existing request ID before capacity checks.
        For new work, reserve a process slot, commit admission, then transfer the slot to the
        tracked execution task. A same-ID retry never launches a second model run.

        Returns:
            202 for new or already-active work; the saved terminal HTTP outcome for a retry;
            or the outcome from settling interruption (409) or task-launch failure (500).
            A competing terminal writer can determine the returned settlement outcome.

        Raises:
            ConversationApplicationError: not_found (404), request_id_conflict or
                conversation_busy (409), or server_busy/connection_unavailable/
                storage_unavailable (503).
            asyncio.CancelledError: Cancellation after reconciliation of any owned admission.
            RuntimeError: Inconsistent stored state; unclassified database errors also propagate.

        Release the capacity slot here unless ownership transferred to background execution.
        """
        try:
            existing, conversation = await asyncio.to_thread(
                self._store.inspect, dealership_id, conversation_id, request_id
            )
            if conversation is not None and self._store.leases_enabled:
                await database_write(self._store.recover_stale, conversation_id)
                existing, conversation = await asyncio.to_thread(
                    self._store.inspect, dealership_id, conversation_id, request_id
                )
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc
        if conversation is None:
            raise ConversationApplicationError(404, "not_found", "Conversation was not found.")
        # Resolve retries before checking capacity or provider availability. An existing
        # ID returns its stored outcome or active status without another model run.
        replay = self._classify_existing(existing, text, conversation_id)
        if replay is not None:
            return replay
        if not self._accepting:
            raise ConversationApplicationError(503, "server_busy", "The server is shutting down.")
        runner = self._runner_for(conversation)
        if not await self._limiter.try_acquire():
            raise ConversationApplicationError(503, "server_busy", "The chat server is busy.")

        admitted: StoredRequestRecord | None = None
        # The submitter owns the capacity slot until execution takes it over. Exactly
        # one of this method or _execute must release that slot.
        transferred = False
        try:
            admitted, admitted_new = await self._admit_with_reconciliation(
                dealership_id, conversation_id, request_id, text
            )
            replay = (
                None if admitted_new else self._classify_existing(admitted, text, conversation_id)
            )
            if not admitted_new:
                if replay is None:
                    raise RuntimeError("terminal request has no replay outcome")
                return replay

            if not self._accepting:
                return await self._settle_failure(
                    admitted.id,
                    409,
                    "request_interrupted",
                    "The request was interrupted before completion.",
                    "interrupted",
                )
            coroutine = self._execute_observed(
                dealership_id, conversation_id, request_id, text, admitted, runner
            )
            try:
                task = asyncio.create_task(coroutine, name=f"chat-turn:{admitted.id}")
            except Exception:
                coroutine.close()
                return await self._settle_failure(
                    admitted.id,
                    500,
                    "internal_error",
                    "The request could not be completed.",
                    "failed",
                )
            # Own the task independently of the POST connection. Admission has committed;
            # 202 acknowledges the user message, not a saved assistant reply.
            self._tasks[admitted.id] = task
            # On task completion, remove tracking/log errors and return None to asyncio.
            task.add_done_callback(lambda done: self._execution_done(admitted.id, done))
            transferred = True
            return self._accepted(conversation_id, request_id)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc
        finally:
            if not transferred:
                await self._limiter.release()

    def _execution_done(self, internal_id: str, task: asyncio.Task[ConversationOutcome]) -> None:
        """Remove a finished owned task and log its exception type if it failed. Return None; this
        callback does not alter durable request state.

        Registered as the done callback on the tracked background execution task.
        """
        self._tasks.pop(internal_id, None)
        if not task.cancelled() and task.exception() is not None:
            logging.getLogger(__name__).error(
                "Owned chat task failed: request_id=%s type=%s",
                internal_id,
                type(task.exception()).__name__,
            )

    @staticmethod
    def _accepted(conversation_id: str, request_id: str) -> ConversationOutcome:
        """Return a 202 ConversationOutcome carrying conversation/request IDs and in_progress.
        Constructing it does not itself admit a request.

        Used when constructing acceptance responses and the base status representation.
        """
        return ConversationOutcome(
            202,
            {
                "conversation_id": conversation_id,
                "request_id": request_id,
                "status": "in_progress",
            },
        )

    async def status(
        self, dealership_id: str, conversation_id: str, request_id: str
    ) -> ConversationOutcome:
        """Return HTTP 200 with durable request status and any terminal body, recovering stale
        active work first. Raise an application error for missing/unavailable storage.

        Called by the request-status HTTP route when the browser checks a pending reply.
        """
        try:
            existing, conversation = await asyncio.to_thread(
                self._store.inspect, dealership_id, conversation_id, request_id
            )
            if conversation is None or existing is None:
                raise ConversationApplicationError(404, "not_found", "Request was not found.")
            if existing.status == "in_progress":
                await asyncio.to_thread(self._store.recover_stale, conversation_id)
                existing, _ = await asyncio.to_thread(
                    self._store.inspect, dealership_id, conversation_id, request_id
                )
            if existing is None:
                raise ConversationApplicationError(404, "not_found", "Request was not found.")
            # Status GET itself succeeds with 200; status and the nested stored outcome
            # describe whether the underlying turn completed, failed, or was interrupted.
            body = dict(self._accepted(conversation_id, request_id).body)
            body["status"] = existing.status
            if existing.status != "in_progress":
                body["outcome"] = terminal_outcome(existing).body
            return ConversationOutcome(200, body)
        except OperationalError as exc:
            if not is_storage_unavailable(exc):
                raise
            raise self._storage_unavailable() from exc

    async def _execute_observed(
        self,
        dealership_id: str,
        conversation_id: str,
        request_id: str,
        text: str,
        admitted: StoredRequestRecord,
        runner: ChatRunner,
    ) -> ConversationOutcome:
        """Run the owned turn and return its outcome while recording duration and call metrics.
        Restore the previous metrics context even on failure or cancellation.

        Launched as an owned background task only after a new request is durably admitted.
        """
        metrics = TurnMetrics(conversation_id, request_id)
        token = current_turn.set(metrics)
        started = time.monotonic()
        outcome = "cancelled"
        status = None
        try:
            result = await self._execute(
                dealership_id, conversation_id, request_id, text, admitted, runner
            )
            status = result.status_code
            outcome = (
                "completed"
                if status == 200
                else str(result.body.get("error", {}).get("code", "terminal_error"))
            )
            return result
        except ConversationApplicationError as exc:
            status = exc.outcome.status_code
            outcome = str(exc.outcome.body["error"]["code"])
            raise
        except Exception:
            outcome = "internal_error"
            raise
        finally:
            event(
                "turn_finished",
                outcome=outcome,
                http_status=status,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                model_calls=metrics.model_calls,
                provider_attempts=metrics.provider_attempts,
                tool_calls=metrics.tool_calls,
            )
            current_turn.reset(token)

    async def _execute(
        self,
        dealership_id: str,
        conversation_id: str,
        request_id: str,
        text: str,
        admitted: StoredRequestRecord,
        runner: ChatRunner,
    ) -> ConversationOutcome:
        """Load context, run the model within a deadline, and commit completion or failure. Return
        the winning terminal outcome; propagate cancellation/storage uncertainty and always
        release capacity.

        Called by _execute_observed after admission. The POST can already have returned 202
        while this work continues.
        """
        renewal: asyncio.Task[None] | None = None
        try:
            event("request_admitted", outcome="in_progress")
            if self._store.leases_enabled:
                renewal = asyncio.create_task(renew_owner(self._store, admitted.id))
            # Load plain records and close the read session before waiting on the model.
            # Replay contains completed turns; run_request adds the current user text.
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
            # Commit reply, replay, and selection together. database_write drains its
            # worker thread on cancellation because cancelling an await cannot stop SQL.
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
                # A commit may succeed even when its acknowledgement is lost. Read the stored
                # terminal outcome before declaring uncertainty; do not rerun the provider.
                reconciled = await self._reconcile_terminal(
                    dealership_id, conversation_id, request_id, text
                )
                if reconciled is not None:
                    return reconciled
                raise self._storage_unavailable() from exc
        except asyncio.CancelledError:
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
            # Storage uncertainty is recovered from the durable request and its lease.
            raise
        except Exception as exc:
            if isinstance(exc, OperationalError) and is_storage_unavailable(exc):
                reconciled = await self._reconcile_terminal(
                    dealership_id, conversation_id, request_id, text
                )
                if reconciled is not None:
                    return reconciled
                raise self._storage_unavailable() from exc
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
        finally:
            await stop_task(renewal)
            await self._limiter.release()

    async def shutdown(self) -> None:
        """Stop admission, allow a grace period, then cancel and await owned work. Execution
        cancellation handlers settle requests before provider clients close. Stop new
        admissions, allow a grace period, then cancel/drain tracked work and close runners.
        Return None after cleanup; cleanup errors may propagate.

        Called by application lifespan cleanup before disposing clients and database resources.
        """
        self._accepting = False
        with suppress(TimeoutError):
            await self._limiter.wait_idle(20.0)
        admissions = tuple(self._admissions)
        for admission in admissions:
            admission.cancel()
        if admissions:
            await asyncio.gather(*admissions, return_exceptions=True)
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(runner.close() for runner in self._runners.values()))

    async def _admit_with_reconciliation(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> tuple[StoredRequestRecord, bool]:
        """Admit safely when cancellation can race a database commit.

        Called by _submit after reserving a capacity slot and before execution is launched.
        Run _admit_and_classify in a shielded task so caller cancellation cannot abandon its
        result while a worker thread continues to commit.

        Returns:
            (stored_request, True) when this caller owns a newly admitted request, including
            a reconciled successful commit. (stored_request, False) when a competing caller
            already admitted the same client ID; _submit still checks payload compatibility.

        Raises:
            ConversationApplicationError: Missing conversation or a different active request.
            Database errors: Admission/reconciliation could not establish a usable outcome.
            asyncio.CancelledError: After waiting for admission, interrupt only a newly owned
                request, never a duplicate caller's turn, then re-raise cancellation. Cleanup
                errors are suppressed here; unfinished durable work remains recoverable by lease.
        """
        task = asyncio.create_task(
            self._admit_and_classify(dealership_id, conversation_id, request_id, text)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:

            async def cleanup() -> None:
                """A cancelled await does not stop a thread or roll back its transaction. Settle
                only a turn owned by this caller, never a duplicate's active turn. Wait for the
                admission result and settle it as interrupted only if newly admitted by this
                caller. Return None; a duplicate caller never settles another owner here.

                Runs only after caller cancellation during admission; protects the gap between a
                committed user message and an execution owner.
                """
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
        """Attempt atomic admission and return (request, is_new). After a uniqueness race, return
        the existing request with False or raise 404/conversation_busy.

        Runs inside the task created by _admit_with_reconciliation.
        """
        try:
            return await asyncio.to_thread(
                self._store.admit, dealership_id, conversation_id, request_id, text
            )
        # The initial read cannot prevent another worker winning admission. Database
        # constraints decide the race; a fresh read distinguishes a duplicate from busy.
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
    ) -> ConversationOutcome:
        """Persist a sanitized terminal failure and return its outcome, or an earlier terminal
        winner. Raise storage_unavailable when settlement cannot be confirmed.

        Used by launch failure, execution failure, and cancellation cleanup to settle an
        admitted request.
        """
        body = error_body(code, message)
        try:
            return await database_write(
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
    ) -> ConversationOutcome | None:
        """Read back a matching ID/payload after uncertain storage work. Return its terminal
        outcome, or None if absent, mismatched, or still active; database errors propagate.

        Called after a storage error when the completion commit may already have succeeded.
        """
        existing, _ = await asyncio.to_thread(
            self._store.inspect, dealership_id, conversation_id, request_id
        )
        if existing is None or existing.payload != text or existing.status == "in_progress":
            return None
        return terminal_outcome(existing)

    def _runner_for(self, conversation: ConversationRecord) -> ChatRunner:
        """Return the runner matching the conversation pinned configuration. Raise
        connection_unavailable if that configuration or runner no longer matches.

        Called before new admission to select the pinned runner.
        """
        self._validate_pinned_connection(conversation)
        runner = self._runners.get(conversation.connection_name)
        if runner is None:
            raise self._connection_unavailable()
        return runner

    def _validate_pinned_connection(self, conversation: ConversationRecord) -> None:
        """Check the saved provider/model against current configuration. Return None on success;
        raise connection_unavailable rather than silently switching models.

        Called before admission and again after restoring execution context.
        """
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
        """Check reply/replay sizes and selection shape before persistence. Return None when valid;
        raise ChatProviderError for invalid results.

        Called after runner.run and before completion persistence.
        """
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
        existing: StoredRequestRecord | None, text: str, conversation_id: str
    ) -> ConversationOutcome | None:
        """Return None for an unused ID, 202 for an active retry, or the stored terminal outcome.
        Raise request_id_conflict if the same ID carries different text.

        Called before admission and after admission races to distinguish retries from new work.
        """
        if existing is None:
            return None
        # A request ID identifies immutable text. An intentional new attempt needs a new ID.
        if existing.payload != text:
            raise ConversationApplicationError(
                409,
                "request_id_conflict",
                "The request ID was already used with different text.",
            )
        if existing.status == "in_progress":
            return ConversationService._accepted(conversation_id, existing.client_request_id)
        return terminal_outcome(existing)

    @staticmethod
    def _connection_unavailable() -> ConversationApplicationError:
        """Construct and return a 503 ConversationApplicationError for unavailable pinned
        configuration; callers decide when to raise it.

        Used by creation and pinned-runner checks; the returned exception is raised by its
        caller.
        """
        return ConversationApplicationError(
            503, "connection_unavailable", "The configured chat connection is unavailable."
        )

    @staticmethod
    def _storage_unavailable() -> ConversationApplicationError:
        """Construct and return a sanitized 503 ConversationApplicationError for
        uncertain/unavailable storage; this helper does not raise it.

        Used after recognized storage outages or uncertain commit outcomes.
        """
        return ConversationApplicationError(
            503, "storage_unavailable", "Conversation storage is unavailable."
        )
