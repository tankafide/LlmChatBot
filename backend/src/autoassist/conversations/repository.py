from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, insert, literal, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from autoassist.chat.contracts import ChatRunResult
from autoassist.chat.history import retain_replay
from autoassist.conversations.records import (
    ConversationRecord,
    MessagePage,
    MessageRecord,
    RunContextRecord,
    StoredRequestRecord,
)
from autoassist.db.models import ChatRequest, Conversation, Dealership, Message, Vehicle


class ConversationNotFoundError(LookupError):
    pass


# The store owns the transaction. ORM rows stay inside it; record helpers copy
# values that callers can safely use after the session closes.
class ConversationRepository:
    """Scoped SQL and ORM mutations; the caller owns session lifetime and commit."""

    def get_dealership(self, session: Session, dealership_id: str) -> Dealership | None:
        """Return the attached dealership ORM row, or None if absent; the caller owns the session.

        Called by store.dealership_connection.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return session.scalar(select(Dealership).where(Dealership.id == dealership_id))

    def find_creation(
        self, session: Session, dealership_id: str, creation_id: str
    ) -> ConversationRecord | None:
        """Return a plain record for the dealership/creation ID pair, or None if no conversation
        matches.

        Called by store.find_creation during idempotent creation.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        row = session.scalar(
            select(Conversation).where(
                Conversation.dealership_id == dealership_id, Conversation.creation_id == creation_id
            )
        )
        return None if row is None else self.conversation_record(row)

    def get_conversation(
        self, session: Session, dealership_id: str, conversation_id: str
    ) -> Conversation | None:
        """Return the attached conversation row within dealership scope, or None if absent/out of
        scope.

        Used by scoped context/history reads, store inspection, and completion.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.dealership_id == dealership_id,
            )
        )

    def get_request(
        self,
        session: Session,
        dealership_id: str,
        conversation_id: str,
        client_request_id: str,
    ) -> ChatRequest | None:
        """Return the attached request matching dealership, conversation, and client ID, or None if
        no scoped match exists.

        Called by store.inspect to find the client request identity.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return session.scalar(
            select(ChatRequest)
            .join(Conversation, Conversation.id == ChatRequest.conversation_id)
            .where(
                Conversation.dealership_id == dealership_id,
                ChatRequest.conversation_id == conversation_id,
                ChatRequest.client_request_id == client_request_id,
            )
        )

    def has_active_request(self, session: Session, conversation_id: str) -> bool:
        """Return True if an in_progress request exists for this conversation, otherwise False.
        This read alone cannot reserve admission.

        Available as a read helper; the current application path does not call it. Admission
        relies on a database unique constraint instead.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return (
            session.scalar(
                select(ChatRequest.id).where(
                    ChatRequest.conversation_id == conversation_id,
                    ChatRequest.status == "in_progress",
                )
            )
            is not None
        )

    def vehicle_belongs_to_dealership(
        self, session: Session, dealership_id: str, vehicle_id: str
    ) -> bool:
        """Return whether the vehicle ID exists within the specified dealership; no selection is
        changed.

        Called during completion before accepting a set-selection action.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return (
            session.scalar(
                select(Vehicle.id).where(
                    Vehicle.id == vehicle_id, Vehicle.dealership_id == dealership_id
                )
            )
            is not None
        )

    def load_run_context(
        self, session: Session, dealership_id: str, conversation_id: str
    ) -> RunContextRecord | None:
        """Return plain conversation/replay/list-reference context, or None for missing scope. Only
        completed turns are retained, subject to count and byte limits.

        Called by store.load_context before execution.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        conversation = self.get_conversation(session, dealership_id, conversation_id)
        if conversation is None:
            return None
        rows = list(
            session.execute(
                select(ChatRequest.replay_json, ChatRequest.presented_vehicle_ids_json)
                .where(
                    ChatRequest.conversation_id == conversation_id,
                    ChatRequest.status == "completed",
                    ChatRequest.replay_json.is_not(None),
                )
                .order_by(ChatRequest.created_at.desc(), ChatRequest.id.desc())
                .limit(10)
            )
        )
        # Fetch the newest bounded window, then restore chronological replay order.
        # Failed/interrupted turns remain visible in history but are excluded from replay.
        rows.reverse()
        replay_units = tuple(row.replay_json for row in rows if row.replay_json is not None)
        replay_units = retain_replay(replay_units)
        # Align list-reference context with the turns retained by the replay byte budget.
        rows = rows[-len(replay_units) :] if replay_units else []
        presented: tuple[str, ...] = ()
        for row in reversed(rows):
            if row.presented_vehicle_ids_json is not None:
                values = json.loads(row.presented_vehicle_ids_json)
                if isinstance(values, list) and all(isinstance(item, str) for item in values):
                    presented = tuple(values)
                break
        return RunContextRecord(
            conversation=self.conversation_record(conversation),
            replay_units=replay_units,
            presented_vehicle_ids=presented,
        )

    def history(
        self,
        session: Session,
        dealership_id: str,
        conversation_id: str,
        after_sequence: int,
        limit: int,
    ) -> MessagePage | None:
        """Return a materialized MessagePage, or None for missing scope. next_after_sequence is
        None at the end; an existing conversation can return zero items.

        Called by store.history for public pagination.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        conversation = self.get_conversation(session, dealership_id, conversation_id)
        if conversation is None:
            return None
        rows = list(
            session.execute(
                select(
                    Message.id,
                    Message.sequence,
                    ChatRequest.client_request_id,
                    Message.role,
                    Message.text,
                    Message.created_at,
                    ChatRequest.status,
                    ChatRequest.terminal_body,
                )
                .join(ChatRequest, ChatRequest.id == Message.request_id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.sequence > after_sequence,
                )
                .order_by(Message.sequence)
                .limit(limit + 1)
            )
        )
        # Fetch one extra row to detect another page without a count query. Sequence
        # numbers provide stable ordering even when a request status changes later.
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            MessageRecord(
                id=row.id,
                sequence=row.sequence,
                request_id=row.client_request_id,
                role=row.role,
                text=row.text,
                created_at=row.created_at,
                request_status=row.status,
                error_code=self._error_code(row.terminal_body),
            )
            for row in visible
        )
        return MessagePage(
            conversation_id=conversation.id,
            selected_vehicle_id=conversation.selected_vehicle_id,
            items=items,
            next_after_sequence=items[-1].sequence if has_more else None,
        )

    @staticmethod
    def stored_request(request: ChatRequest) -> StoredRequestRecord:
        """Copy retry identity/status/outcome fields from an attached ORM row into a plain
        StoredRequestRecord.

        Used by inspection and terminal replay to detach request fields.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return StoredRequestRecord(
            id=request.id,
            client_request_id=request.client_request_id,
            payload=request.payload,
            status=request.status,
            terminal_http_status=request.terminal_http_status,
            terminal_body=request.terminal_body,
        )

    @staticmethod
    def conversation_record(conversation: Conversation) -> ConversationRecord:
        """Copy identity, pinned configuration, and selection into a plain ConversationRecord safe
        to use after session close.

        Used by store/repository reads to detach conversation fields.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        return ConversationRecord(
            id=conversation.id,
            dealership_id=conversation.dealership_id,
            connection_name=conversation.connection_name,
            provider=conversation.provider,
            model=conversation.model,
            created_at=conversation.created_at,
            selected_vehicle_id=conversation.selected_vehicle_id,
        )

    @staticmethod
    def _error_code(terminal_body: str | None) -> str | None:
        """Extract a string error code from stored terminal JSON. Return None for no body, no
        string code, or malformed/unexpected JSON shape.

        Called while projecting public message history.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        if terminal_body is None:
            return None
        try:
            value = json.loads(terminal_body)
            code = value.get("error", {}).get("code")
            return code if isinstance(code, str) else None
        except (AttributeError, json.JSONDecodeError):
            return None

    def create_conversation(
        self,
        session: Session,
        dealership_id: str,
        connection_name: str,
        provider: str,
        model: str,
        created_at: str,
        creation_id: str,
    ) -> ConversationRecord:
        """Stage a new conversation ORM row and return its plain record. The caller must commit;
        the returned record alone is not proof of persistence.

        Called by the store creation transaction.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        conversation = Conversation(
            id=str(uuid4()),
            creation_id=creation_id,
            dealership_id=dealership_id,
            connection_name=connection_name,
            provider=provider,
            model=model,
            created_at=created_at,
            selected_vehicle_id=None,
            next_message_sequence=1,
        )
        session.add(conversation)
        return self.conversation_record(conversation)

    def admit(
        self,
        session: Session,
        dealership_id: str,
        conversation_id: str,
        request_id: str,
        text: str,
        internal_id: str,
        message_id: str,
        now: str,
        lease_seconds: float,
    ) -> None:
        """Insert the scoped active request, reserve sequence, and stage its user message. Return
        None; caller commits. Missing scope raises ConversationNotFoundError; constraints may
        reject races.

        Called by the store admission transaction.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        # INSERT ... SELECT admits only an existing scoped conversation. Schema uniqueness
        # rejects duplicate client IDs and a second active request; a Python precheck
        # alone could not prevent races between workers.
        scoped_conversation = select(
            literal(internal_id),
            Conversation.id,
            literal(request_id),
            literal(text),
            literal("in_progress"),
            literal(now),
            literal(now),
            self.lease_deadline(session, lease_seconds),
        ).where(
            Conversation.id == conversation_id,
            Conversation.dealership_id == dealership_id,
        )
        inserted = session.execute(
            insert(ChatRequest).from_select(
                [
                    ChatRequest.id,
                    ChatRequest.conversation_id,
                    ChatRequest.client_request_id,
                    ChatRequest.payload,
                    ChatRequest.status,
                    ChatRequest.created_at,
                    ChatRequest.updated_at,
                    ChatRequest.lease_expires_at,
                ],
                scoped_conversation,
            )
        )
        if inserted.rowcount == 0:
            raise ConversationNotFoundError
        # Reserve message order with an atomic increment. Request, counter, and user
        # message roll back together if any part of admission fails.
        next_sequence = session.scalar(
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.dealership_id == dealership_id,
            )
            .values(next_message_sequence=Conversation.next_message_sequence + 1)
            .returning(Conversation.next_message_sequence)
        )
        if next_sequence is None:
            raise RuntimeError("admitted conversation disappeared")
        session.add(
            Message(
                id=message_id,
                conversation_id=conversation_id,
                request_id=internal_id,
                sequence=next_sequence - 1,
                role="user",
                text=text,
                created_at=now,
            )
        )

    def save_completion(
        self,
        session: Session,
        request: ChatRequest,
        conversation: Conversation,
        result: ChatRunResult,
        selected: str | None,
        assistant: MessageRecord,
        presented_json: str | None,
        encoded_body: str,
    ) -> None:
        """Stage assistant message, replay, selected vehicle, and terminal response mutations.
        Return None; all changes depend on the caller committing the transaction.

        Called after the store locks and validates completion.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        session.add(
            Message(
                id=assistant.id,
                conversation_id=conversation.id,
                request_id=request.id,
                sequence=assistant.sequence,
                role="assistant",
                text=assistant.text,
                created_at=assistant.created_at,
            )
        )
        conversation.next_message_sequence += 1
        conversation.selected_vehicle_id = selected
        # This status change releases the partial unique-index claim on the conversation.
        # Saving the terminal body lets retries replay without another provider call.
        request.status = "completed"
        request.updated_at = assistant.created_at
        request.replay_json = result.replay_json
        request.presented_vehicle_ids_json = presented_json
        request.terminal_http_status = 200
        request.terminal_body = encoded_body

    def require_request(self, session: Session, internal_request_id: str) -> ChatRequest:
        """Return the request ORM row locked FOR UPDATE until transaction end. Raise RuntimeError
        if an admitted request has unexpectedly disappeared.

        Called by completion and failure settlement to serialize terminal writers.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        # FOR UPDATE holds the row until the transaction ends. The store checks status
        # under this lock so completion, failure, and recovery cannot overwrite each other.
        request = session.scalar(
            select(ChatRequest).where(ChatRequest.id == internal_request_id).with_for_update()
        )
        if request is None:
            raise RuntimeError("admitted request disappeared")
        return request

    def user_message(self, session: Session, request: ChatRequest) -> MessageRecord:
        """Return the admitted user message as a plain record, using current request status. Raise
        RuntimeError if the required message is missing.

        Called when building the completion outcome.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        user = session.scalar(
            select(Message).where(Message.request_id == request.id, Message.role == "user")
        )
        if user is None:
            raise RuntimeError("admitted request has no user message")
        return MessageRecord(
            id=user.id,
            sequence=user.sequence,
            request_id=request.client_request_id,
            role="user",
            text=user.text,
            created_at=user.created_at,
            request_status=request.status,
            error_code=None,
        )

    def vehicle_identity(
        self,
        session: Session,
        dealership_id: str,
        vehicle_id: str | None,
    ) -> tuple[int, str, str] | None:
        """Return (year, make, model) for a scoped vehicle, or None if its ID is absent/None/out of
        scope.

        Called during completion validation of safety presentation identity.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        row = session.execute(
            select(Vehicle.year, Vehicle.make, Vehicle.model).where(
                Vehicle.id == vehicle_id,
                Vehicle.dealership_id == dealership_id,
            )
        ).one_or_none()
        return None if row is None else (row.year, row.make, row.model)

    @staticmethod
    def set_terminal(
        request: ChatRequest,
        status: str,
        now: str,
        http_status: int,
        encoded_body: str,
    ) -> None:
        """Mutate the attached request status, timestamp, and terminal HTTP outcome. Return None;
        the caller owns locking and commit.

        Called by the store failure transaction.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        request.status = status
        request.updated_at = now
        request.terminal_http_status = http_status
        request.terminal_body = encoded_body

    @staticmethod
    def database_now(session: Session) -> ColumnElement[datetime]:
        """Return a SQL expression for the database clock, not an already-evaluated Python
        datetime. PostgreSQL uses wall-clock time within the transaction.

        Used in lease deadline, renewal, and recovery SQL.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        # Database time avoids worker clock skew. PostgreSQL clock_timestamp advances
        # during a transaction rather than freezing at its start.
        return (
            func.clock_timestamp()
            if session.get_bind().dialect.name == "postgresql"
            else func.current_timestamp()
        )

    @classmethod
    def lease_deadline(cls, session: Session, seconds: float) -> ColumnElement[datetime]:
        """Return a database SQL expression for now plus the lease duration, using dialect-specific
        date arithmetic; it performs no query itself.

        Used by request admission and lease renewal.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        if session.get_bind().dialect.name == "postgresql":
            return cls.database_now(session) + timedelta(seconds=seconds)
        return func.datetime("now", f"+{seconds} seconds")

    def renew_lease(self, session: Session, internal_id: str, seconds: float) -> bool:
        """Conditionally update an unexpired active request and return whether one row changed. The
        caller must commit the extension.

        Called by the store heartbeat write unit.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        # An expired lease cannot be renewed, even before a sweep marks it interrupted.
        result = session.execute(
            update(ChatRequest)
            .where(
                ChatRequest.id == internal_id,
                ChatRequest.status == "in_progress",
                ChatRequest.lease_expires_at > self.database_now(session),
            )
            .values(lease_expires_at=self.lease_deadline(session, seconds))
        )
        return result.rowcount == 1

    def recover_interrupted(
        self,
        session: Session,
        now: str,
        encoded_body: str,
        conversation_id: str | None = None,
        batch_size: int = 100,
    ) -> int:
        """Lock a bounded expired batch and stage interrupted outcomes. Return the changed count
        (zero if none); caller commits. Active locks are skipped.

        Called by the store recovery transaction at startup, on sweeps, or for scoped recovery.

        Used within ConversationStore database units. The caller owns the session and commit;
        database errors propagate and uncommitted writes are not durable.
        """
        cutoff = session.scalar(select(self.database_now(session)))
        if cutoff is None:
            raise RuntimeError("database clock is unavailable")
        # Bound recovery work and skip rows another writer has locked. Expiry makes a
        # request eligible for recovery; completion can still win the terminal row lock.
        candidates = (
            select(ChatRequest.id)
            .where(
                ChatRequest.status == "in_progress",
                ChatRequest.lease_expires_at <= cutoff,
            )
            .order_by(ChatRequest.lease_expires_at, ChatRequest.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        if conversation_id is not None:
            candidates = candidates.where(ChatRequest.conversation_id == conversation_id)
        ids = list(session.scalars(candidates))
        if not ids:
            return 0
        result = session.execute(
            update(ChatRequest)
            .where(
                ChatRequest.id.in_(ids),
                ChatRequest.status == "in_progress",
                ChatRequest.lease_expires_at <= self.database_now(session),
            )
            .values(
                status="interrupted",
                updated_at=now,
                terminal_http_status=409,
                terminal_body=encoded_body,
            )
        )
        return result.rowcount
