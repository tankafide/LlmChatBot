# PostgreSQL multi-worker slice

## Goal

Coordinate the durable chat lifecycle through PostgreSQL when more than one backend worker
or instance shares the database. Preserve the public HTTP contract, grounding behavior, and explicit database recreation policy.

## Implementation

1. Add the PostgreSQL driver and dialect-aware engine/schema setup. Keep SQLite support only for
   fast isolated tests and local test fixtures. Serialize concurrent schema/bootstrap startup with
   a PostgreSQL advisory lock.
2. Enforce the one-active-request constraint in PostgreSQL. Recover only requests older than
   the 120-second threshold. Lock terminal writes so completion, failure settlement, and
   recovery cannot overwrite one another across processes.
3. Run PostgreSQL in Compose, start two Uvicorn workers, persist durable data in a PostgreSQL volume,
   and give the isolated verifier its own PostgreSQL service. Keep secrets/configuration explicit.
4. Add a real-PostgreSQL concurrency/recovery test while retaining the existing SQLite behavioral
   suite. Update README, architecture, shared baseline, reset/import commands, and verification
   evidence.

## Acceptance

- Two independent stores racing different request IDs for one conversation admit exactly one.
- Starting another worker does not interrupt a fresh active request; an expired request is
  deterministically settled and releases the conversation.
- Terminal mutation locks the request row and preserves one terminal outcome.
- Compose starts PostgreSQL before the backend, the backend runs with two workers, inventory and
  conversations survive backend recreation, and the shared verifier uses isolated storage.
- Focused pytest, Ruff, formatting, mypy, Compose validation/build, and the shared verification
  entry point pass. No development SQLite/PostgreSQL data is used by tests.

## Recovery and limits

Schema changes require explicit database recreation and reimport from
`docs/context/inventory/data.csv`; ordinary startup preserves data. Requests become recoverable
after the stale age threshold. PostgreSQL coordinates shared state across workers. Authentication,
load balancing across hosts, database HA/backups, and a durable job engine remain out of scope.

## Completion evidence

- Implemented 2026-09-11. PostgreSQL 17.6, psycopg 3.2.10, dialect-aware schema checks,
  PostgreSQL startup advisory locking, portable partial uniqueness, row-locked terminal writes,
  and 120-second stale recovery are active.
- The production Compose backend started two worker processes, imported all 127 source inventory
  rows, returned healthy inventory, preserved a created conversation across backend restart, and
  preserved inventory/conversation reads across PostgreSQL container restart.
- `python scripts/verify.py` passed: 202 backend tests (including real PostgreSQL coordination and crash recovery),
  Ruff, formatting, strict mypy, API drift/build checks, and 30 Playwright tests.
- Storage review fixes and expanded verification are recorded in
  [PostgreSQL coordination and storage verification](postgres-review-fixes.md).
