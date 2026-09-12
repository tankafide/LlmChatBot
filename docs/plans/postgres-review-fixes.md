# PostgreSQL coordination and storage verification

## Scope

- Classify psycopg connection failures without SQLSTATE as unavailable storage while preserving SQL/schema errors. Verify the HTTP 503 contract.
- Validate index predicates against their exact dialect reflection, including unfiltered indexes; reject reversed and expanded predicates before startup writes.
- Exercise PostgreSQL completion/recovery contention in both orders, serialized startup, and abrupt worker death followed by fresh protection, stale recovery, and durable replay. Use only isolated verification storage.
- Align README, architecture, baseline, plans, and project skills with PostgreSQL shared storage and renewable database-clock leases. Keep accurate SQLite test-fixture documentation.

## Acceptance

Focused storage tests, backend static checks, and the shared verifier pass. Schema and connection failures have regression coverage; concurrency checks synchronize actual lock contention. Schema changes require explicit development database recreation; verification uses isolated storage.

## Status

Completed 2026-09-11.

- Fixed psycopg availability classification and strict dialect-aware index predicate validation. PostgreSQL URLs select the installed psycopg driver.
- Added isolated schema/error regressions, actual PostgreSQL lock-contention tests in both completion/recovery orders, concurrent startup verification, and PostgreSQL abrupt-worker-stop coverage preserving prior completion and repeated replay.
- Audited README, AGENTS.md, architecture, baseline, project plans, and skill instructions/references. PostgreSQL is described as the current runtime; SQLite references describe test fixtures and their evidence. Recovery uses renewable PostgreSQL TIMESTAMPTZ leases and bounded skip-locked sweeps.
- Focused storage/recovery run: 24 passed. Shared `python scripts/verify.py`: 202 backend tests and 30 Playwright tests passed; Ruff, formatting, strict mypy, frontend typing/lint/formatting, API drift, and production build passed.
- Eight affected skill packages passed skill-creator validation; final diff checks passed. No development data was used by checks or reset.
- Scoped review: storage classification preserves SQL/schema defects; index validation rejects reversed/expanded predicates and unexpected filtering; terminal contention tests observe real database waits and release gates in cleanup. Transactions remain inside the existing store/repository boundaries.
