from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from autoassist.db.database import (
    create_database_engine,
    initialize_schema,
    make_session_factory,
)
from autoassist.db.models import ChatRequest, Conversation, Dealership, Message


def test_database_enforces_one_active_request_and_request_message_scope(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'constraints.db'}")
    initialize_schema(engine)
    session_factory = make_session_factory(engine)
    dealership_id = str(uuid4())
    first_conversation = str(uuid4())
    second_conversation = str(uuid4())
    first_request = str(uuid4())
    now = "2026-09-10T00:00:00+00:00"
    try:
        with session_factory.begin() as session:
            session.add(
                Dealership(
                    id=dealership_id,
                    slug="test",
                    name="Test",
                    default_connection="test",
                )
            )
        with session_factory.begin() as session:
            session.add_all(
                [
                    Conversation(
                        id=conversation_id,
                        dealership_id=dealership_id,
                        connection_name="test",
                        provider="xai",
                        model="test-model",
                        created_at=now,
                    )
                    for conversation_id in (first_conversation, second_conversation)
                ]
            )
        with session_factory.begin() as session:
            session.add(
                ChatRequest(
                    id=first_request,
                    conversation_id=first_conversation,
                    client_request_id=str(uuid4()),
                    payload="first",
                    status="in_progress",
                    created_at=now,
                    updated_at=now,
                )
            )

        with pytest.raises(IntegrityError), session_factory.begin() as session:
            session.add(
                ChatRequest(
                    conversation_id=first_conversation,
                    client_request_id=str(uuid4()),
                    payload="second",
                    status="in_progress",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()

        with pytest.raises(IntegrityError), session_factory.begin() as session:
            session.add(
                Message(
                    conversation_id=second_conversation,
                    request_id=first_request,
                    sequence=1,
                    role="user",
                    text="wrong conversation",
                    created_at=now,
                )
            )
            session.flush()
    finally:
        engine.dispose()
