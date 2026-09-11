---
name: autoassist-persistence
description: Design, implement, or review AutoAssist PostgreSQL/SQLite schema, SQLAlchemy queries, transaction integrity, and durable conversation storage. Use when explicitly selected for persistence work.
---

# AutoAssist persistence

Read [AGENTS.md](../../../AGENTS.md) and the authoritative [stack baseline](../../../docs/stack-baseline.md), especially session ownership and the chat lifecycle, before persistence work. Preserve the requested phase: planning defines changes and checks; development implements authorized changes; review reports defects without unsolicited fixes. Inspect existing models, repositories, callers, and tests before adding a parallel path.

## Session and transaction boundaries

- Use the accepted synchronous SQLAlchemy 2 typed ORM. Inject a session factory, not a session. Offload the complete database unit from async orchestration: create session, execute/materialize, commit or roll back, and close inside one worker thread. Return application records/plain values, never attached entities or lazy results. Separate parallel tools' sessions; serialize tools that mutate shared run context.
- Application services own transaction boundaries; repositories do not independently commit. End units before external awaits. A thread-safe connection setting does not make a shared Session safe. Account for post-commit expiration while materializing results; do not trigger hidden reloads after crossing the boundary.
- Inspect the chosen Python/sqlite3 transaction mode at implementation time. SQLAlchemy context managers alone do not correct every driver legacy-transaction behavior. Configure the documented supported mode for the pinned runtime and verify rollback semantics, including schema setup when relevant.

## Integrity and durable outcomes

Use the baseline lifecycle as the sole status/retry specification rather than redefining it here. For each changed write path, name its durable state, atomic unit, commit point, and recovery action.

- Enforce foreign keys on every connection and test that enforcement. Use database uniqueness for request identity and one active request per conversation; a unique partial index on active requests is one suitable implementation. Validate required index predicates as well as columns and uniqueness; reject changed operators or additional conditions. Add applicable non-null/check constraints and deterministic message ordering. Do not rely on a preceding read or in-memory lock for integrity.
- Admission must atomically claim the conversation and insert the request/user message. Look up identity/payload before busy classification so terminal replay still works while another request runs. Handle races through constraints/conditional writes and reread durable state after rollback to classify conflicts; never turn all integrity errors into the same duplicate response.
- Completion commits the actual assistant reply, complete replay history, selected-vehicle state, terminal response, and claim release together. Failure/interruption settlement must be conditional on the request still being active: committed completion wins. Required persistence must finish before success is acknowledged.
- Classify psycopg connection failures without SQLSTATE as storage unavailability while preserving server SQL/schema errors. Bound lock waits and any safe transient retries. Do not blindly rerun a unit after an uncertain commit; reconcile using the durable request identity and state. A cancelled await can leave thread work running: await/coordinate outstanding database work before settlement, then inspect durable state. Storage failure must never become claimed durable success or an in-memory fallback.
- Recovery runs before traffic and is safe across workers: protect fresh bounded work and settle only stale requests. Treat the age threshold as recovery policy, not worker-liveness detection or a renewable lease; account for host-clock assumptions. Preserve completed records and admitted user messages. Fail startup if storage/recovery fails; never reset on startup. Document explicit development database recreation for schema changes, with no migration framework. Container data-volume ownership belongs with Docker guidance.

## Query shape and bounded reads

- Build parameterized, application-owned SQL filters for supported inventory attributes; never execute model-generated SQL. Apply combined filters, stable ordering, projection, and bounded limits in SQL rather than loading inventory into Python. Index demonstrated filter/order and integrity paths; inspect a hot query's plan when justified.
- Materialize needed relationships with explicit joins or eager/batched loads. Count SQL through response serialization on growing multi-record fixtures: query growth must be bounded/batched, not one fetch per result. Account for collection joins duplicating rows when applying limits or counting results.
- Keep full persisted history but load bounded complete successful turns for model input, plus the current user message; do not split tool-call/result pairs. Keep selected-vehicle context authoritative independently. Bound history-page and tool-result sizes without deleting durable history. Failed/interrupted turns remain available to display under the baseline rules.
- The real inventory is preserved at `docs/context/inventory/data.csv`. Clearly labeled synthetic fixtures are appropriate for query and durability tests, not substitutes for validating the assignment import.

## Evidence and handoff

Choose focused checks using temporary SQLite files for fast behavior and isolated real PostgreSQL for cross-worker coordination. Cover combined filters/order/limits and growing query counts for query changes; foreign-key/uniqueness violations and mid-unit rollback for schema/writes. For chat writes, use synchronization events to exercise same/different-ID races, provider-call/message counts, terminal replay after recreation, cancellation versus commit, and repeated stale recovery. A paused external call must hold no transaction; a paused database unit must leave the event loop responsive. Exercise bounded lock contention and storage failure without false success where affected.

Coordinate failure injection and an abrupt-process-stop check with backend verification when implemented; application-object recreation alone proves neither crash recovery nor container-volume preservation. Discover actual commands; do not claim planned checks ran. Record observed results and gaps, plus relevant reset/guarantee limitations in README and pending work in plans. PostgreSQL constraints and row locks own cross-worker correctness; per-worker execution limits are not a global admission cap.

Read [research notes](references/research.md) when revisiting transaction configuration, query loading, or integrity mechanisms.
