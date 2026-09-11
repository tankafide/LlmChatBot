from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import psycopg
from sqlalchemy import Engine, create_engine, event, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from autoassist.db.models import Base

SessionFactory = sessionmaker[Session]


class SchemaMismatchError(RuntimeError):
    """Existing storage cannot safely serve this application version."""


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(database_url: str) -> Engine:
    _ensure_sqlite_parent(database_url)
    url = make_url(database_url)
    if url.drivername == "sqlite":
        engine = create_engine(
            database_url,
            connect_args={"autocommit": False, "check_same_thread": False, "timeout": 5.0},
        )
    elif url.drivername in {"postgresql", "postgresql+psycopg"}:
        engine = create_engine(
            url.set(drivername="postgresql+psycopg"),
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 5,
                "options": "-c lock_timeout=5000 -c statement_timeout=10000",
            },
        )
    else:
        raise ValueError("database URL must use SQLite or PostgreSQL")

    if url.drivername == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_connection(dbapi_connection: object, _connection_record: object) -> None:
            connection = cast(sqlite3.Connection, dbapi_connection)
            previous_autocommit = connection.autocommit
            connection.autocommit = True
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()
                connection.autocommit = previous_autocommit

    return engine


@contextmanager
def database_startup_lock(engine: Engine) -> Iterator[None]:
    """Serialize schema/bootstrap startup across PostgreSQL workers."""
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT pg_advisory_lock(47071120260911)")
        try:
            yield
        finally:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(47071120260911)")


def initialize_schema(engine: Engine) -> None:
    # create_all does not upgrade existing tables. Reject incompatible storage before
    # bootstrap or recovery can write to it; never repair/reset user data implicitly.
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    problems: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = set(table.columns.keys()) - columns
        if missing_columns:
            problems.append(f"{table.name} missing columns: {', '.join(sorted(missing_columns))}")
        indexes = {index["name"]: index for index in inspector.get_indexes(table.name)}
        for required in table.indexes:
            actual = indexes.get(required.name)
            expected_columns = [column.name for column in required.columns]
            dialect_name = engine.dialect.name
            predicate = required.dialect_options[dialect_name].get("where")
            expected_where = "" if predicate is None else str(predicate)
            dialect_where_key = f"{dialect_name}_where"
            actual_where = (
                ""
                if actual is None
                else str(actual.get("dialect_options", {}).get(dialect_where_key, ""))
            )
            predicate_matches = _index_predicate_matches(dialect_name, expected_where, actual_where)
            if (
                actual is None
                or actual["column_names"] != expected_columns
                or bool(actual["unique"]) != bool(required.unique)
                or not predicate_matches
            ):
                problems.append(f"{table.name} incompatible index: {required.name}")
    if problems:
        raise SchemaMismatchError(
            "Database schema is incompatible; back up and explicitly recreate "
            "the development database, then import the inventory CSV. " + "; ".join(problems)
        )
    Base.metadata.create_all(engine)


def _index_predicate_matches(dialect: str, expected: str, actual: str) -> bool:
    # PostgreSQL reflects this varchar comparison with explicit text casts and
    # parentheses. Accept that catalog spelling, not arbitrary SQL containing
    # the same words. Unfiltered indexes must also remain unfiltered.
    accepted = {expected}
    if dialect == "postgresql" and expected == "status = 'in_progress'":
        accepted.add("((status)::text = 'in_progress'::text)")
    return actual.strip() in accepted


def check_storage(session_factory: SessionFactory) -> None:
    with session_factory() as session:
        # Exercise every required column, including empty tables. A SELECT of only
        # the primary key masks old table shapes until a real request is made.
        for table in Base.metadata.sorted_tables:
            session.execute(select(table).limit(1)).first()


def is_storage_unavailable(error: OperationalError) -> bool:
    """Recognize database availability failures without hiding SQL/schema defects."""
    original = error.orig
    if isinstance(original, sqlite3.OperationalError):
        code = getattr(original, "sqlite_errorcode", None)
        if not isinstance(code, int):
            return False
        # Extended result codes retain their primary result code in the low byte.
        return code & 0xFF in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
            sqlite3.SQLITE_CANTOPEN,
            sqlite3.SQLITE_IOERR,
            sqlite3.SQLITE_FULL,
            sqlite3.SQLITE_READONLY,
        }
    sqlstate = getattr(original, "sqlstate", None)
    if isinstance(original, psycopg.OperationalError) and sqlstate is None:
        # Client-side connection failures have no server SQLSTATE (for example
        # refusal, DNS failure, or a connection lost before a server response).
        return True
    return isinstance(sqlstate, str) and (
        sqlstate.startswith(("08", "53"))
        or sqlstate in {"55P03", "57014", "57P01", "57P02", "57P03"}
    )


def make_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(bind=engine, expire_on_commit=False)
