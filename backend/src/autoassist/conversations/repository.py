from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import insert, literal, select, update
from sqlalchemy.orm import Session

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


class ConversationRepository:
    """Scoped SQL and ORM mutations; the caller owns session lifetime and commit."""

    def get_dealership(self, session: Session, dealership_id: str) -> Dealership | None:
        return session.scalar(select(Dealership).where(Dealership.id == dealership_id))

    def get_conversation(
        self, session: Session, dealership_id: str, conversation_id: str
    ) -> Conversation | None:
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
        rows.reverse()
        replay_units = tuple(row.replay_json for row in rows if row.replay_json is not None)
        replay_units = retain_replay(replay_units)
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
    ) -> ConversationRecord:
        conversation = Conversation(
            id=str(uuid4()),
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
    ) -> None:
        scoped_conversation = select(
            literal(internal_id),
            Conversation.id,
            literal(request_id),
            literal(text),
            literal("in_progress"),
            literal(now),
            literal(now),
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
                ],
                scoped_conversation,
            )
        )
        if inserted.rowcount == 0:
            raise ConversationNotFoundError
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
        request.status = "completed"
        request.updated_at = assistant.created_at
        request.replay_json = result.replay_json
        request.presented_vehicle_ids_json = presented_json
        request.terminal_http_status = 200
        request.terminal_body = encoded_body

    def require_request(self, session: Session, internal_request_id: str) -> ChatRequest:
        request = session.get(ChatRequest, internal_request_id)
        if request is None:
            raise RuntimeError("admitted request disappeared")
        return request

    def user_message(self, session: Session, request: ChatRequest) -> MessageRecord:
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
        request.status = status
        request.updated_at = now
        request.terminal_http_status = http_status
        request.terminal_body = encoded_body

    def recover_interrupted(self, session: Session, now: str, encoded_body: str) -> int:
        requests = list(
            session.scalars(select(ChatRequest).where(ChatRequest.status == "in_progress"))
        )
        for request in requests:
            self.set_terminal(request, "interrupted", now, 409, encoded_body)
        return len(requests)
