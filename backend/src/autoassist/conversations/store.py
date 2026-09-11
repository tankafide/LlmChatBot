"""Application-owned synchronous transaction units; never hold a session across an await."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from autoassist.chat.contracts import ChatProviderError, ChatRunResult
from autoassist.conversations.completion import (
    completed_outcome,
    completion_presentation,
    validate_completion_selection,
)
from autoassist.conversations.outcomes import (
    ConversationApplicationError,
    TerminalOutcome,
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


class ConversationStore:
    def __init__(
        self,
        session_factory: SessionFactory,
        repository: ConversationRepository,
        *,
        stale_request_seconds: float = 0.0,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._write_lock = threading.Lock()
        self._stale_request_seconds = stale_request_seconds

    def recover_interrupted(self, conversation_id: str | None = None) -> int:
        now = utc_now()
        stale_before = (
            datetime.now(UTC) - timedelta(seconds=self._stale_request_seconds)
        ).isoformat(timespec="microseconds")
        body = canonical_json(
            error_body("request_interrupted", "The request was interrupted before completion.")
        )
        with self._session_factory.begin() as session:
            return self._repository.recover_interrupted(
                session, now, stale_before, body, conversation_id
            )

    def recover_stale(self, conversation_id: str) -> int:
        if self._stale_request_seconds <= 0:
            return 0
        return self.recover_interrupted(conversation_id)

    def dealership_connection(self, dealership_id: str) -> str | None:
        with self._session_factory() as session:
            dealership = self._repository.get_dealership(session, dealership_id)
            return None if dealership is None else dealership.default_connection

    def create(
        self,
        dealership_id: str,
        connection_name: str,
        provider: str,
        model: str,
    ) -> ConversationRecord:
        with self._write_lock:
            return self._create_unit_locked(dealership_id, connection_name, provider, model)

    def _create_unit_locked(
        self, dealership_id: str, connection_name: str, provider: str, model: str
    ) -> ConversationRecord:
        with self._session_factory.begin() as session:
            record = self._repository.create_conversation(
                session, dealership_id, connection_name, provider, model, utc_now()
            )
        return record

    def inspect(
        self, dealership_id: str, conversation_id: str, request_id: str
    ) -> tuple[StoredRequestRecord | None, ConversationRecord | None]:
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
        with self._session_factory() as session:
            return self._repository.load_run_context(session, dealership_id, conversation_id)

    def history(
        self,
        dealership_id: str,
        conversation_id: str,
        after_sequence: int,
        limit: int,
    ) -> MessagePage | None:
        with self._session_factory() as session:
            return self._repository.history(
                session, dealership_id, conversation_id, after_sequence, limit
            )

    def complete(
        self, dealership_id: str, internal_request_id: str, result: ChatRunResult
    ) -> TerminalOutcome:
        with self._write_lock:
            return self._complete_unit_locked(dealership_id, internal_request_id, result)

    def _complete_unit_locked(
        self, dealership_id: str, internal_request_id: str, result: ChatRunResult
    ) -> TerminalOutcome:
        now = utc_now()
        assistant_id = str(uuid4())
        with self._session_factory.begin() as session:
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
    ) -> TerminalOutcome:
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
    ) -> TerminalOutcome:
        with self._session_factory.begin() as session:
            request = self._repository.require_request(session, internal_request_id)
            if request.status != "in_progress":
                return terminal_outcome(self._repository.stored_request(request))
            self._repository.set_terminal(
                request, request_status, utc_now(), status_code, canonical_json(body)
            )
        return TerminalOutcome(status_code, dict(body))
