"""Application-owned synchronous transaction units; never hold a session across an await."""

from __future__ import annotations

import threading
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, OperationalError

from autoassist.chat.contracts import ChatProviderError, ChatRunResult
from autoassist.conversations.completion import (
    completed_outcome,
    completion_presentation,
    validate_completion_selection,
)
from autoassist.conversations.outcomes import (
    ConversationApplicationError,
    ConversationOutcome,
    canonical_json,
    error_body,
    terminal_outcome,
    utc_now,
)
from autoassist.conversations.records import (
    ConversationRecord,
    MessagePage,
    MessageRecord,
    RunContextRecord,
    StoredRequestRecord,
)
from autoassist.conversations.repository import ConversationNotFoundError, ConversationRepository
from autoassist.db.database import SessionFactory
from autoassist.observability import event


# Each method is a complete synchronous database unit. begin() commits on normal
# exit and rolls back on error; repository helpers never commit independently.
# Return plain records so async callers do not trigger lazy ORM database access.
class ConversationStore:
    def __init__(
        self,
        session_factory: SessionFactory,
        repository: ConversationRepository,
        *,
        lease_seconds: float = 0.0,
    ) -> None:
        """Store the session factory/repository and configure the local write lock and lease
        duration. Return None; sessions are opened by individual units.

        Constructed during app startup and injected into ConversationService.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        self._session_factory = session_factory
        self._repository = repository
        # This lock covers one store instance only. PostgreSQL constraints and row
        # locks coordinate writes across separate instances and server processes.
        self._write_lock = threading.Lock()
        self._lease_seconds = lease_seconds

    def recover_interrupted(self, conversation_id: str | None = None) -> int:
        """Commit recovery of one bounded batch of expired requests, optionally scoped to a
        conversation. Return the number changed; storage errors propagate.

        Called at startup, by the sweeper, and through scoped stale recovery.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        now = utc_now()
        body = canonical_json(
            error_body("request_interrupted", "The request was interrupted before completion.")
        )
        with self._session_factory.begin() as session:
            count = self._repository.recover_interrupted(session, now, body, conversation_id)
        event("stale_recovery", recovered_count=count)
        return count

    def recover_stale(self, conversation_id: str) -> int:
        """Recover expired work for one conversation and return the count. Return zero without
        database work when leases are disabled.

        Called during submission/status checks to recover expired work in that conversation.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        if self._lease_seconds <= 0:
            return 0
        return self.recover_interrupted(conversation_id)

    def renew_lease(self, internal_id: str) -> bool:
        """Commit a conditional lease extension. Return True only if the request is active and its
        old lease is still live; otherwise return False.

        Called periodically by renew_owner in a worker thread.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory.begin() as session:
            return self._repository.renew_lease(session, internal_id, self._lease_seconds)

    @property
    def leases_enabled(self) -> bool:
        """Return whether a positive lease duration enables scoped renewal/recovery.

        Read by startup and execution to enable or skip lease maintenance.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        return self._lease_seconds > 0

    def find_creation(self, dealership_id: str, creation_id: str) -> ConversationRecord | None:
        """Return a plain conversation record for the scoped creation ID, or None if absent. Close
        the read session before returning.

        Used by service creation and store creation reconciliation.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory() as session:
            return self._repository.find_creation(session, dealership_id, creation_id)

    def dealership_connection(self, dealership_id: str) -> str | None:
        """Return the dealership default connection name, or None if the dealership does not exist.

        Called by ConversationService.create if creation_id has no saved conversation.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory() as session:
            dealership = self._repository.get_dealership(session, dealership_id)
            return None if dealership is None else dealership.default_connection

    def create(
        self,
        dealership_id: str,
        connection_name: str,
        provider: str,
        model: str,
        creation_id: str,
    ) -> ConversationRecord:
        """Return the existing or newly committed conversation for the creation ID. Reconcile
        competing inserts/uncertain acknowledgements; propagate unresolved database failures.

        Called by ConversationService.create through database_write.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._write_lock:
            existing = self.find_creation(dealership_id, creation_id)
            if existing is not None:
                return existing
            try:
                return self._create_unit_locked(
                    dealership_id, connection_name, provider, model, creation_id
                )
            # A competing creation or lost commit acknowledgement may already have saved
            # this creation_id. A fresh session finds the durable winner.
            except (IntegrityError, OperationalError):
                existing = self.find_creation(dealership_id, creation_id)
                if existing is not None:
                    return existing
                raise

    def _create_unit_locked(
        self, dealership_id: str, connection_name: str, provider: str, model: str, creation_id: str
    ) -> ConversationRecord:
        """Insert and commit a conversation with pinned configuration. Return its plain record; the
        caller must hold this store write lock.

        Called by create while the local write lock is held.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory.begin() as session:
            record = self._repository.create_conversation(
                session, dealership_id, connection_name, provider, model, utc_now(), creation_id
            )
        return record

    def inspect(
        self, dealership_id: str, conversation_id: str, request_id: str
    ) -> tuple[StoredRequestRecord | None, ConversationRecord | None]:
        """Return (request or None, conversation or None) as plain records. Missing conversation
        scope returns (None, None); no lifecycle mutation occurs.

        Used for submission/status checks, admission races, and uncertain-commit reconciliation.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory() as session:
            conversation = self._repository.get_conversation(
                session, dealership_id, conversation_id
            )
            if conversation is None:
                return None, None
            request = self._repository.get_request(
                session, dealership_id, conversation_id, request_id
            )
            return (
                None if request is None else self._repository.stored_request(request),
                self._repository.conversation_record(conversation),
            )

    def admit(
        self, dealership_id: str, conversation_id: str, request_id: str, text: str
    ) -> tuple[StoredRequestRecord, bool]:
        """Commit a request/user message and return (request, True). Reconcile an uncertain
        acknowledgement by internal ID; uniqueness conflicts propagate for service
        classification.

        Called by the service admission task before launching provider work.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._write_lock:
            internal_id = str(uuid4())
            try:
                return self._admit_unit_locked(
                    dealership_id, conversation_id, request_id, text, internal_id
                )
            except OperationalError:
                # Fresh-session identity reconciliation handles a commit whose acknowledgement
                # failed. The internal ID distinguishes our write from a competing caller's.
                existing, _ = self.inspect(dealership_id, conversation_id, request_id)
                if existing is not None and existing.id == internal_id:
                    return existing, True
                raise

    def _admit_unit_locked(
        self,
        dealership_id: str,
        conversation_id: str,
        request_id: str,
        text: str,
        internal_id: str,
    ) -> tuple[StoredRequestRecord, bool]:
        """Atomically insert the request and user message. Return (new record, True) after commit;
        raise 404 for missing scope. Caller holds the local write lock.

        Called by admit while the local write lock is held.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        # Request admission and its user message share one transaction. Provider work
        # can start only after this unit has committed successfully.
        now = utc_now()
        message_id = str(uuid4())
        with self._session_factory.begin() as session:
            try:
                self._repository.admit(
                    session,
                    dealership_id,
                    conversation_id,
                    request_id,
                    text,
                    internal_id,
                    message_id,
                    now,
                    self._lease_seconds,
                )
            except ConversationNotFoundError as exc:
                raise ConversationApplicationError(
                    404, "not_found", "Conversation was not found."
                ) from exc

        return (
            StoredRequestRecord(
                id=internal_id,
                client_request_id=request_id,
                payload=text,
                status="in_progress",
                terminal_http_status=None,
                terminal_body=None,
            ),
            True,
        )

    def load_context(self, dealership_id: str, conversation_id: str) -> RunContextRecord | None:
        """Return the conversation and retained completed-turn context, or None for a missing
        scoped conversation. Close the session before the model uses it.

        Called by the owned execution task before provider work.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory() as session:
            return self._repository.load_run_context(session, dealership_id, conversation_id)

    def history(
        self,
        dealership_id: str,
        conversation_id: str,
        after_sequence: int,
        limit: int,
    ) -> MessagePage | None:
        """Return a plain message page, or None for a missing scoped conversation; a present
        conversation may have an empty page.

        Called by ConversationService.history in a worker thread.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory() as session:
            return self._repository.history(
                session, dealership_id, conversation_id, after_sequence, limit
            )

    def complete(
        self, dealership_id: str, internal_request_id: str, result: ChatRunResult
    ) -> ConversationOutcome:
        """Serialize local completion work and return the committed outcome or an earlier terminal
        winner. Invalid evidence or database errors propagate.

        Called through database_write after runner output validation.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._write_lock:
            return self._complete_unit_locked(dealership_id, internal_request_id, result)

    def _complete_unit_locked(
        self, dealership_id: str, internal_request_id: str, result: ChatRunResult
    ) -> ConversationOutcome:
        """Under a request row lock, validate and commit reply, replay, and selection together.
        Return completion or the existing terminal outcome; invalid evidence rolls back.

        Called by complete while the local write lock is held.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        now = utc_now()
        assistant_id = str(uuid4())
        with self._session_factory.begin() as session:
            # Lock before checking status: if another terminal writer already won, replay
            # its outcome instead of overwriting it with this late model result.
            request = self._repository.require_request(session, internal_request_id)
            if request.status != "in_progress":
                return terminal_outcome(self._repository.stored_request(request))
            conversation = self._repository.get_conversation(
                session, dealership_id, request.conversation_id
            )
            if conversation is None:
                raise RuntimeError("conversation scope changed")
            selected = conversation.selected_vehicle_id
            if result.selection_action == "clear":
                selected = None
            elif result.selection_action == "set":
                valid_selection = (
                    result.selected_vehicle_id is not None
                    and self._repository.vehicle_belongs_to_dealership(
                        session, dealership_id, result.selected_vehicle_id
                    )
                )
                if not valid_selection:
                    raise ChatProviderError("invalid selected vehicle")
                selected = result.selected_vehicle_id
            # Check persisted selection and replay presentation together before writing.
            # Follow-up context must agree with the vehicle evidence used for completion.
            presentation = completion_presentation(result.replay_json)
            validate_completion_selection(
                conversation.selected_vehicle_id,
                selected,
                presentation,
                None
                if presentation is None or presentation.presentation is None
                else self._repository.vehicle_identity(session, dealership_id, selected),
            )
            presented_json = (
                None
                if result.presented_vehicle_ids is None
                else canonical_json(list(result.presented_vehicle_ids))
            )
            user = self._repository.user_message(session, request)
            assistant = MessageRecord(
                id=assistant_id,
                sequence=conversation.next_message_sequence,
                request_id=request.client_request_id,
                role="assistant",
                text=result.reply,
                created_at=now,
                request_status="completed",
                error_code=None,
            )
            outcome = completed_outcome(conversation.id, selected, user, assistant)
            # The assistant message, selected vehicle, model history, and replayable HTTP
            # body become durable in the same commit or all remain unapplied.
            self._repository.save_completion(
                session,
                request,
                conversation,
                result,
                selected,
                assistant,
                presented_json,
                canonical_json(outcome.body),
            )
        return outcome

    def settle_failure(
        self,
        internal_request_id: str,
        status_code: int,
        body: dict[str, object],
        request_status: str,
    ) -> ConversationOutcome:
        """Serialize failure settlement locally and return the stored failure or an earlier
        terminal winner. Database errors propagate rather than claiming durable failure.

        Called by service failure/cancellation settlement through database_write.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._write_lock:
            return self._settle_failure_unit_locked(
                internal_request_id, status_code, body, request_status
            )

    def _settle_failure_unit_locked(
        self,
        internal_request_id: str,
        status_code: int,
        body: dict[str, object],
        request_status: str,
    ) -> ConversationOutcome:
        """Lock the request and commit its failure unless already terminal. Return the winning
        outcome; preserve the user message and add no assistant message.

        Called by settle_failure while the local write lock is held.

        Used by conversation orchestration as a synchronous database unit in a worker thread.
        Its sessions close before returning; unresolved database errors propagate.
        """
        with self._session_factory.begin() as session:
            request = self._repository.require_request(session, internal_request_id)
            if request.status != "in_progress":
                return terminal_outcome(self._repository.stored_request(request))
            # Keep the admitted user message, but add no fabricated assistant reply.
            # Leaving in_progress releases the database-enforced active-request claim.
            self._repository.set_terminal(
                request, request_status, utc_now(), status_code, canonical_json(body)
            )
        return ConversationOutcome(status_code, dict(body))
