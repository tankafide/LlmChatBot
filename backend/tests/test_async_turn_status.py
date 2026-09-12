"""HTTP admission and durable status, independent from the lifetime of a POST."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from test_conversation_concurrency import GatedRunner

from autoassist.app import create_app
from autoassist.chat.contracts import ChatProviderError, ChatProviderTimeoutError
from autoassist.db.models import ChatRequest, Message


@pytest.fixture
async def running_app(application_settings, monkeypatch):
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    runner = GatedRunner()
    app = create_app(application_settings, runner_factory=lambda *_: runner)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        dealer = next(
            x["id"]
            for x in (await client.get("/dealerships")).json()["items"]
            if x["slug"] == "mia-motors"
        )
        conversation = (
            await client.post(
                f"/dealerships/{dealer}/conversations", json={"creation_id": str(uuid4())}
            )
        ).json()["id"]
        root = f"/dealerships/{dealer}/conversations/{conversation}"
        try:
            yield app, runner, client, root
        finally:
            runner.release.set()


async def test_admission_is_committed_and_same_id_does_not_start_another_run(running_app):
    app, runner, client, root = running_app
    body = {"request_id": str(uuid4()), "text": "Show SUVs"}
    response = await client.post(root + "/messages", json=body)
    assert response.status_code == 202
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ChatRequest)) == 1
        assert session.scalar(select(func.count()).select_from(Message)) == 1
    await asyncio.wait_for(runner.started.wait(), 2)
    status = await client.get(root + "/requests/" + body["request_id"])
    assert status.status_code == 200 and status.json() == response.json()
    assert status.headers["cache-control"] == "no-store"
    assert (await client.post(root + "/messages", json=body)).json() == response.json()
    conflict = await client.post(root + "/messages", json={**body, "text": "different"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "request_id_conflict"
    busy = await client.post(root + "/messages", json={**body, "request_id": str(uuid4())})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "conversation_busy"
    assert runner.calls == 1
    # A second HTTP caller sees the same durable record, not an in-memory task result.
    for wrong in (
        root.replace(root.split("/")[2], str(uuid4())),
        root.replace(root.split("/")[4], str(uuid4())),
        root,
    ):
        identity = str(uuid4()) if wrong == root else body["request_id"]
        missing = await client.get(wrong + "/requests/" + identity)
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    runner.release.set()
    await app.state.conversation_service._limiter.wait_idle(3)
    terminal = (await client.get(root + "/requests/" + body["request_id"])).json()
    replay = await client.post(root + "/messages", json=body)
    assert terminal["status"] == "completed" and terminal["outcome"] == replay.json()
    assert runner.calls == 1


@pytest.mark.parametrize(
    "error,code",
    [
        (ChatProviderError("secret"), "provider_error"),
        (ChatProviderTimeoutError("secret"), "provider_timeout"),
    ],
)
async def test_failed_status_has_canonical_sanitized_outcome(running_app, monkeypatch, error, code):
    app, runner, client, root = running_app

    async def fail(_request):
        raise error

    monkeypatch.setattr(runner, "run", fail)
    body = {"request_id": str(uuid4()), "text": "Find a car"}
    assert (await client.post(root + "/messages", json=body)).status_code == 202
    await app.state.conversation_service._limiter.wait_idle(3)
    status = await client.get(root + "/requests/" + body["request_id"])
    assert status.status_code == 200 and status.json()["status"] == "failed"
    assert status.json()["outcome"]["error"]["code"] == code
    assert "secret" not in status.text
    replay = await client.post(root + "/messages", json=body)
    assert status.json()["outcome"] == replay.json()
    assert len((await client.get(root + "/messages")).json()["items"]) == 1


async def test_task_launch_failure_is_settled_before_returning(running_app, monkeypatch):
    app, runner, client, root = running_app
    original = asyncio.create_task

    def cannot_launch(coroutine, **kwargs):
        if str(kwargs.get("name", "")).startswith("chat-turn:"):
            raise RuntimeError("private launch detail")
        return original(coroutine, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", cannot_launch)
    body = {"request_id": str(uuid4()), "text": "hello"}
    response = await client.post(root + "/messages", json=body)
    assert response.status_code == 500
    state = (await client.get(root + "/requests/" + body["request_id"])).json()
    assert state["status"] == "failed" and state["outcome"] == response.json()
    assert not app.state.conversation_service._tasks and runner.calls == 0
    assert app.state.conversation_service._limiter._active == 0


async def test_shutdown_cancels_and_joins_execution_before_closing_runner(running_app, monkeypatch):
    app, runner, client, root = running_app
    service = app.state.conversation_service
    body = {"request_id": str(uuid4()), "text": "hello"}
    assert (await client.post(root + "/messages", json=body)).status_code == 202
    await asyncio.wait_for(runner.started.wait(), 2)

    async def drain_expired(_timeout):
        raise TimeoutError

    monkeypatch.setattr(service._limiter, "wait_idle", drain_expired)
    closed = False

    async def close():
        nonlocal closed
        assert runner.active == 0 and not service._tasks
        closed = True

    monkeypatch.setattr(runner, "close", close)
    await service.shutdown()
    assert closed
    state = (await client.get(root + "/requests/" + body["request_id"])).json()
    assert state["status"] == "interrupted"
    assert state["outcome"]["error"]["code"] == "request_interrupted"
    assert (
        await client.post(root + "/messages", json={**body, "request_id": str(uuid4())})
    ).status_code == 503


async def test_terminal_status_query_count_does_not_scan_history(running_app):
    app, runner, client, root = running_app
    runner.release.set()
    counts = []
    for index in range(5):
        body = {"request_id": str(uuid4()), "text": str(index)}
        assert (await client.post(root + "/messages", json=body)).status_code == 202
        await app.state.conversation_service._limiter.wait_idle(3)
        queries = []

        def count(_connection, _cursor, statement, *_args, captured=queries):
            captured.append(statement)

        event.listen(app.state.engine, "before_cursor_execute", count)
        try:
            assert (await client.get(root + "/requests/" + body["request_id"])).status_code == 200
        finally:
            event.remove(app.state.engine, "before_cursor_execute", count)
        counts.append(len(queries))
        assert all("FROM messages" not in sql for sql in queries)
    assert counts == [2] * 5


async def test_other_worker_reads_active_and_completed_status(
    postgres_engine, application_settings, monkeypatch
):
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    settings = application_settings.model_copy(
        update={"database_url": postgres_engine.url.render_as_string(hide_password=False)}
    )
    owner, observer = GatedRunner(), GatedRunner()
    first = create_app(settings, runner_factory=lambda *_: owner)
    second = create_app(settings, runner_factory=lambda *_: observer)
    async with first.router.lifespan_context(first), second.router.lifespan_context(second):
        service = first.state.conversation_service
        other = second.state.conversation_service
        dealer = next(
            x.id for x in first.state.inventory_service.list_dealerships() if x.slug == "mia-motors"
        )
        conversation = await service.create(dealer, str(uuid4()))
        identity = str(uuid4())
        try:
            results = await asyncio.gather(
                service.submit(dealer, conversation.id, identity, "hello"),
                other.submit(dealer, conversation.id, identity, "hello"),
            )
            assert [r.status_code for r in results] == [202, 202]
            state = await other.status(dealer, conversation.id, identity)
            assert state.body["status"] == "in_progress"
        finally:
            owner.release.set()
            observer.release.set()
        await service._limiter.wait_idle(5)
        await other._limiter.wait_idle(5)
        state = await other.status(dealer, conversation.id, identity)
        assert state.body["status"] == "completed"
        assert owner.calls + observer.calls == 1
        assert len((await other.history(dealer, conversation.id, 0, 50)).items) == 2


async def test_graceful_shutdown_drains_a_completed_turn(running_app, monkeypatch):
    app, runner, client, root = running_app
    service = app.state.conversation_service
    body = {"request_id": str(uuid4()), "text": "hello"}
    assert (await client.post(root + "/messages", json=body)).status_code == 202
    await asyncio.wait_for(runner.started.wait(), 2)
    draining = asyncio.Event()
    original = service._limiter.wait_idle

    async def observe_drain(timeout):
        draining.set()
        await original(timeout)

    monkeypatch.setattr(service._limiter, "wait_idle", observe_drain)
    shutdown = asyncio.create_task(service.shutdown())
    try:
        await asyncio.wait_for(draining.wait(), 2)
        assert not shutdown.done() and runner.active == 1
    finally:
        runner.release.set()
        await asyncio.wait_for(shutdown, 3)
    status = await client.get(root + "/requests/" + body["request_id"])
    assert status.json()["status"] == "completed"
    assert not service._tasks and service._limiter._active == 0
