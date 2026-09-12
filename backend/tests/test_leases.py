from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select, update

from autoassist.conversations.repository import ConversationRepository
from autoassist.conversations.store import ConversationStore
from autoassist.db.database import make_session_factory
from autoassist.db.models import ChatRequest, Conversation, Dealership


def setup_stores(engine):
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        dealer = Dealership(slug="lease-test", name="Lease test", default_connection="test")
        session.add(dealer)
        session.flush()
        dealer_id = dealer.id
    return (
        sessions,
        dealer_id,
        [
            ConversationStore(sessions, ConversationRepository(), lease_seconds=120)
            for _ in range(2)
        ],
    )


def test_postgres_creation_race_is_dealership_scoped(postgres_engine):
    sessions, dealer, stores = setup_stores(postgres_engine)
    gate = Barrier(2)
    creation_id = str(uuid4())

    def create(store):
        gate.wait(timeout=5)
        return store.create(dealer, "test", "openai", "test-model", creation_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(create, stores))
    assert first == second
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 1
    with sessions.begin() as session:
        other = Dealership(slug="other", name="Other", default_connection="test")
        session.add(other)
        session.flush()
        other_id = other.id
    assert stores[0].create(other_id, "test", "openai", "test-model", creation_id).id != first.id


def test_postgres_database_clock_renewal_expiry_and_terminal_fencing(postgres_engine, monkeypatch):
    sessions, dealer, (owner, other) = setup_stores(postgres_engine)
    # Audit timestamp skew cannot change lease decisions.
    monkeypatch.setattr(
        "autoassist.conversations.store.utc_now", lambda: "2099-01-01T00:00:00+00:00"
    )
    conversation = owner.create(dealer, "test", "openai", "model", str(uuid4()))
    request, _ = owner.admit(dealer, conversation.id, str(uuid4()), "hello")
    with sessions() as session:
        expiry, now = session.execute(
            select(ChatRequest.lease_expires_at, func.clock_timestamp()).where(
                ChatRequest.id == request.id
            )
        ).one()
        assert expiry.tzinfo is not None and 110 < (expiry - now).total_seconds() <= 120
    with sessions.begin() as session:
        session.execute(
            update(ChatRequest)
            .where(ChatRequest.id == request.id)
            .values(lease_expires_at=func.clock_timestamp() + timedelta(seconds=10))
        )
    assert owner.renew_lease(request.id)
    assert other.recover_interrupted() == 0
    with sessions.begin() as session:
        session.execute(
            update(ChatRequest)
            .where(ChatRequest.id == request.id)
            .values(lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
    assert not owner.renew_lease(request.id)
    assert other.recover_interrupted() == 1
    assert not owner.renew_lease(request.id)
    assert (
        owner.settle_failure(
            request.id, 502, {"error": {"code": "provider_error"}}, "failed"
        ).status_code
        == 409
    )


def test_postgres_sweeper_skips_locked_rows_and_bounds_batch(postgres_engine):
    sessions, dealer, (owner, other) = setup_stores(postgres_engine)
    ids = []
    for _ in range(102):
        conversation = owner.create(dealer, "test", "openai", "model", str(uuid4()))
        request, _ = owner.admit(dealer, conversation.id, str(uuid4()), "hello")
        ids.append(request.id)
    with sessions.begin() as session:
        session.execute(
            update(ChatRequest).values(lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
    with sessions.begin() as locked:
        locked.execute(select(ChatRequest).where(ChatRequest.id == ids[0]).with_for_update()).one()
        assert other.recover_interrupted() == 100
        assert other.recover_interrupted() == 1
        assert other.recover_interrupted() == 0
    assert other.recover_interrupted() == 1
