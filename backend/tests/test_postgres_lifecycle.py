from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from conftest import write_config
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from autoassist.chat.contracts import ChatRunResult
from autoassist.config import load_runtime_config
from autoassist.conversations.repository import ConversationRepository
from autoassist.conversations.store import ConversationStore
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import (
    SchemaMismatchError,
    create_database_engine,
    database_startup_lock,
    initialize_schema,
    make_session_factory,
)
from autoassist.db.models import Base, ChatRequest, Dealership


def wait_for_database_lock(engine: Engine, application_name: str) -> None:
    """Observe real server-side contention before releasing the winning transaction."""
    deadline = time.monotonic() + 4
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            waiting = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name = :name AND wait_event_type = 'Lock'"
                ),
                {"name": application_name},
            )
            connection.commit()
            if waiting:
                return
            time.sleep(0.01)
    raise AssertionError("contending operation never waited for a PostgreSQL lock")


@pytest.mark.parametrize(
    "predicate",
    [
        "status != 'in_progress'",
        "status = 'in_progress' AND payload = 'only some requests'",
        "status = 'in_progress' OR status = 'completed'",
        "",
    ],
)
def test_postgres_rejects_incompatible_active_index(
    postgres_engine: Engine, predicate: str
) -> None:
    initialize_schema(postgres_engine)  # Accept the actual catalog's valid reflected form.
    with postgres_engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_chat_request_active_conversation")
        where = f" WHERE {predicate}" if predicate else ""
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_chat_request_active_conversation "
            f"ON chat_requests (conversation_id){where}"
        )
    with pytest.raises(SchemaMismatchError, match="incompatible index"):
        initialize_schema(postgres_engine)


def test_postgres_rejects_predicate_added_to_unfiltered_index(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_message_conversation_sequence")
        connection.exec_driver_sql(
            "CREATE INDEX ix_message_conversation_sequence ON messages "
            "(conversation_id, sequence) WHERE role = 'user'"
        )
    with pytest.raises(SchemaMismatchError, match="incompatible index"):
        initialize_schema(postgres_engine)


@pytest.mark.parametrize("winner", ["completion", "recovery"])
def test_postgres_completion_and_recovery_preserve_winning_transaction(
    postgres_engine: Engine, winner: str
) -> None:
    locked = Event()
    release = Event()

    class GatedRepository(ConversationRepository):
        def require_request(self, session: Session, internal_request_id: str) -> ChatRequest:
            request = super().require_request(session, internal_request_id)
            locked.set()
            assert release.wait(10), "completion lock was not released"
            return request

        def recover_interrupted(
            self,
            session: Session,
            now: str,
            stale_before: str,
            encoded_body: str,
            conversation_id: str | None = None,
        ) -> int:
            count = super().recover_interrupted(
                session, now, stale_before, encoded_body, conversation_id
            )
            locked.set()
            assert release.wait(10), "recovery lock was not released"
            return count

    factory = make_session_factory(postgres_engine)
    with factory.begin() as session:
        dealership = Dealership(slug="race", name="Race Test", default_connection="test")
        session.add(dealership)
        session.flush()
        dealership_id = dealership.id
    name = "autoassist-terminal-contender"
    contender_engine = create_database_engine(
        postgres_engine.url.update_query_dict({"application_name": name}).render_as_string(
            hide_password=False
        )
    )
    first = ConversationStore(factory, GatedRepository(), stale_request_seconds=120)
    second = ConversationStore(
        make_session_factory(contender_engine), ConversationRepository(), stale_request_seconds=120
    )
    conversation = first.create(dealership_id, "test", "openai", "test-model")
    request, _ = first.admit(dealership_id, conversation.id, "request", "Hello")
    with factory.begin() as session:
        session.execute(
            update(ChatRequest)
            .where(ChatRequest.id == request.id)
            .values(updated_at="2000-01-01T00:00:00+00:00")
        )
    result = ChatRunResult(reply="Saved reply", replay_json="[]")
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                if winner == "completion":
                    completed = executor.submit(first.complete, dealership_id, request.id, result)
                    assert locked.wait(5)
                    recovered = executor.submit(second.recover_stale, conversation.id)
                else:
                    recovered = executor.submit(first.recover_stale, conversation.id)
                    assert locked.wait(5)
                    completed = executor.submit(second.complete, dealership_id, request.id, result)
                wait_for_database_lock(postgres_engine, name)
            finally:
                release.set()
            outcome = completed.result(timeout=10)
            assert recovered.result(timeout=10) == (0 if winner == "completion" else 1)
        assert outcome.status_code == (200 if winner == "completion" else 409)
        record, _ = second.inspect(dealership_id, conversation.id, "request")
        assert record is not None
        assert record.status == ("completed" if winner == "completion" else "interrupted")
        page = second.history(dealership_id, conversation.id, 0, 10)
        assert page is not None
        assert [message.role for message in page.items] == (
            ["user", "assistant"] if winner == "completion" else ["user"]
        )
        assert second.complete(dealership_id, request.id, result) == outcome
        assert second.recover_stale(conversation.id) == 0
    finally:
        release.set()
        contender_engine.dispose()


def test_postgres_serializes_schema_and_bootstrap_startup(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    Base.metadata.drop_all(postgres_engine)
    config = load_runtime_config(write_config(tmp_path / "config.json"))
    name = "autoassist-startup-contender"
    contender = create_database_engine(
        postgres_engine.url.update_query_dict({"application_name": name}).render_as_string(
            hide_password=False
        )
    )
    locked = Event()
    release = Event()

    def startup(engine: Engine, gated: bool) -> None:
        with database_startup_lock(engine):
            if gated:
                locked.set()
                assert release.wait(10)
            initialize_schema(engine)
            bootstrap_dealerships(make_session_factory(engine), config)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                first = executor.submit(startup, postgres_engine, True)
                assert locked.wait(5)
                second = executor.submit(startup, contender, False)
                wait_for_database_lock(postgres_engine, name)
            finally:
                release.set()
            first.result(timeout=10)
            second.result(timeout=10)
        with make_session_factory(postgres_engine)() as session:
            assert set(session.scalars(select(Dealership.slug))) == {"mia-motors", "lakeview-auto"}
    finally:
        release.set()
        contender.dispose()
