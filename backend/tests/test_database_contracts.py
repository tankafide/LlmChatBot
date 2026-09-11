from __future__ import annotations

import socket
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from autoassist.api import routes
from autoassist.app import create_app
from autoassist.config import Settings
from autoassist.db.database import (
    SchemaMismatchError,
    create_database_engine,
    initialize_schema,
    is_storage_unavailable,
)


def test_refused_postgres_connection_returns_storage_unavailable(
    application_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reserve a local port without listening: no external database or DNS needed.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        engine = create_database_engine(
            f"postgresql+psycopg://test:test@127.0.0.1:{port}/autoassist_verify"
        )
        try:
            with pytest.raises(OperationalError) as caught, engine.connect():
                pytest.fail("a non-listening socket accepted a connection")
        finally:
            engine.dispose()
    assert caught.value.orig.sqlstate is None
    assert is_storage_unavailable(caught.value)

    def unavailable(_factory: object) -> None:
        raise caught.value

    with TestClient(create_app(application_settings)) as client:
        monkeypatch.setattr(routes, "check_storage", unavailable)
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        (psycopg.OperationalError("connection lost"), True),
        (psycopg.errors.LockNotAvailable("lock timeout"), True),
        (psycopg.errors.QueryCanceled("statement timeout"), True),
        (psycopg.errors.UndefinedTable("bad schema"), False),
        (psycopg.errors.SyntaxError("bad SQL"), False),
        (psycopg.errors.InvalidPassword("bad credentials"), False),
        (RuntimeError("unrelated error"), False),
    ],
)
def test_storage_classifier_preserves_database_defects(original: Exception, expected: bool) -> None:
    assert is_storage_unavailable(OperationalError(None, None, original)) is expected


@pytest.mark.parametrize(
    "predicate",
    [
        "status != 'in_progress'",
        "status = 'in_progress' AND payload = 'only some requests'",
        "status = 'in_progress' OR status = 'completed'",
        "",
    ],
)
def test_sqlite_rejects_incompatible_active_index(tmp_path: Path, predicate: str) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    try:
        initialize_schema(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_chat_request_active_conversation")
            where = f" WHERE {predicate}" if predicate else ""
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_chat_request_active_conversation "
                f"ON chat_requests (conversation_id){where}"
            )
        with pytest.raises(SchemaMismatchError, match="incompatible index"):
            initialize_schema(engine)
    finally:
        engine.dispose()
