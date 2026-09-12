from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

from sqlalchemy import Engine, update
from sqlalchemy.exc import IntegrityError

from autoassist.conversations.repository import ConversationRepository
from autoassist.conversations.store import ConversationStore
from autoassist.db.database import (
    make_session_factory,
)
from autoassist.db.models import ChatRequest, Dealership


def test_postgres_coordinates_admission_recovery_and_terminal_writes(
    postgres_engine: Engine,
) -> None:
    session_factory = make_session_factory(postgres_engine)
    with session_factory.begin() as session:
        dealership = Dealership(
            slug="postgres-test",
            name="PostgreSQL Test",
            default_connection="test",
        )
        session.add(dealership)
        session.flush()
        dealership_id = dealership.id

    first = ConversationStore(session_factory, ConversationRepository(), lease_seconds=120.0)
    second = ConversationStore(session_factory, ConversationRepository(), lease_seconds=120.0)
    conversation = first.create(dealership_id, "test", "openai", "test-model", str(uuid4()))

    admission_gate = Barrier(2)

    def admit(store: ConversationStore, request_id: str) -> str:
        admission_gate.wait(timeout=5)
        try:
            request, _ = store.admit(dealership_id, conversation.id, request_id, request_id)
            return request.id
        except IntegrityError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda item: admit(*item),
                (
                    (first, "00000000-0000-0000-0000-000000000001"),
                    (second, "00000000-0000-0000-0000-000000000002"),
                ),
            )
        )
    admitted_ids = [item for item in outcomes if item != "conflict"]
    assert len(admitted_ids) == 1
    assert outcomes.count("conflict") == 1
    assert second.recover_interrupted() == 0

    first.settle_failure(
        admitted_ids[0],
        409,
        {"error": {"code": "request_interrupted", "message": "test cleanup"}},
        "interrupted",
    )

    stale, _ = first.admit(
        dealership_id,
        conversation.id,
        "00000000-0000-0000-0000-000000000003",
        "stale",
    )
    with session_factory.begin() as session:
        session.execute(
            update(ChatRequest)
            .where(ChatRequest.id == stale.id)
            .values(lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
    assert second.recover_interrupted() == 1
    recovered, _ = second.inspect(
        dealership_id,
        conversation.id,
        "00000000-0000-0000-0000-000000000003",
    )
    assert recovered is not None
    assert recovered.status == "interrupted"

    terminal, _ = first.admit(
        dealership_id,
        conversation.id,
        "00000000-0000-0000-0000-000000000004",
        "terminal race",
    )
    terminal_gate = Barrier(2)

    def settle(
        store: ConversationStore, status_code: int, code: str
    ) -> tuple[int, dict[str, object]]:
        terminal_gate.wait(timeout=5)
        outcome = store.settle_failure(
            terminal.id,
            status_code,
            {"error": {"code": code, "message": code}},
            "failed",
        )
        return outcome.status_code, outcome.body

    with ThreadPoolExecutor(max_workers=2) as executor:
        terminal_outcomes = tuple(
            executor.map(
                lambda item: settle(*item),
                ((first, 502, "provider_error"), (second, 504, "provider_timeout")),
            )
        )
    assert terminal_outcomes[0] == terminal_outcomes[1]
