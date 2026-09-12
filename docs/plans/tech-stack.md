# Tech stack decisions

The [shared stack baseline](../stack-baseline.md) owns runtime choices and lifecycle contracts. The tech-stack skill is the explicit-only decision workflow.

- FastAPI exposes the HTTP API. Pydantic AI adapts configured OpenAI, Google, and xAI models through thin tools over inventory/NHTSA services. Server configuration selects the default connection; provider message formats stay separate from public schemas.
- PostgreSQL and synchronous SQLAlchemy own inventory, conversations, messages, selected-vehicle context, and durable request replay. Two Uvicorn workers share the database. Constraints enforce one active request per conversation; row locks protect terminal transitions; an advisory lock serializes schema/bootstrap startup.
- Recovery interrupts expired PostgreSQL TIMESTAMPTZ leases at startup, on scoped submissions, or in bounded background sweeps. The database clock grants 120 seconds; owning turns renew every 20 seconds. Completed outcomes remain replayable and external work is not automatically resumed.
- Complete database units run in worker threads with independent sessions. Application services own short transactions, and no transaction spans an external-service wait.
- React and assistant-ui ExternalStoreRuntime present backend-owned conversation state. Native fetch consumes generated openapi-typescript types with runtime validation. The shared verifier checks API drift and runs Playwright browser tests.
- Docker Desktop and Compose are the standard workflow. Start Desktop with `docker desktop start --detach --timeout 120` and verify `docker info`. PostgreSQL owns its named volume; ordinary restart/recreation preserves data. Schema changes require explicit development database recreation without a migration framework.
- Verification uses isolated PostgreSQL for coordination/recovery and temporary SQLite for focused behavioral tests. The importer reads all 127 source rows from `docs/context/inventory/data.csv`. `python scripts/verify.py` is the shared local/CI check entry point.

See the README for current setup, import, run, verification, and database recreation commands.
