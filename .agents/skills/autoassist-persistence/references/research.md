# Persistence research

Researched 2026-09-10 (America/Chicago). Primary documentation consulted for skill authoring; verify runtime-specific APIs against installed versions during implementation.

| Source | Agent failure mode and decision |
| --- | --- |
| [SQLAlchemy Session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) | A Session is mutable transaction state, and commit normally expires ORM attributes. Keep sessions local to complete worker-thread units and materialize boundary records before close; use explicit transaction framing. |
| [SQLAlchemy SQLite dialect](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) | Python sqlite3 legacy transaction control has non-obvious SELECT, DDL, and savepoint behavior. Inspect the pinned driver/runtime and configure supported transaction behavior; test rollback rather than assuming a context manager guarantees it. |
| [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html) | Declaring foreign keys is insufficient when enforcement is disabled. Enable and verify it per connection, outside an active transaction. |
| [SQLite partial indexes](https://www.sqlite.org/partialindex.html) | A unique partial index can enforce uniqueness only for rows matching a predicate. This is a small mechanism for one active request per conversation without an in-memory lock. |
| [SQLite transactions](https://www.sqlite.org/lang_transaction.html) | SQLite permits only one concurrent writer; deferred read-to-write upgrades and commits can encounter contention. Bound waits, keep transactions short, and distinguish known-safe retries from ambiguous commit outcomes. |
| [SQLAlchemy relationship loading](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html) | Attribute access can silently issue SQL. Explicit eager/batched loading prevents per-row queries; measure serialization too. Select-in loading may use multiple batches, so require bounded/batched growth rather than a universal exact query count. |
| [SQLite EXPLAIN QUERY PLAN](https://www.sqlite.org/eqp.html) | Inspect scan/search/index use for demonstrated hot paths. Explain output is diagnostic and can change; avoid brittle tests comparing its complete text. |

The synchronous thread-unit model, single-worker volume, admission/replay semantics, terminal status/body storage, cancellation reconciliation, interrupted-run recovery, inventory-import constraints, and no-migration policy are **project decisions** in [the shared baseline](../../../../docs/stack-baseline.md) and AGENTS.md. Upstream sources establish mechanisms and constraints; they do not prescribe this application lifecycle. The assignment inventory became available after these notes were authored and is now preserved at `docs/context/inventory/data.csv`. No application code, installed dependency compatibility, or runtime behavior was verified during skill authoring.
