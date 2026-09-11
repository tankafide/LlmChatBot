---
name: autoassist-backend
description: Guide AutoAssist FastAPI request handling, async execution, settings, dependency lifespan, and startup/shutdown behavior during planning, implementation, or review.
---

# AutoAssist backend

Read [AGENTS.md](../../../AGENTS.md) and the [shared baseline](../../../docs/stack-baseline.md) first. Apply its [session ownership](../../../docs/stack-baseline.md#database-execution-and-session-ownership) and [chat lifecycle](../../../docs/stack-baseline.md#chat-request-lifecycle) directly; do not invent alternate admission or retry semantics. Keep the current task's mode: planning defines the change and evidence; development implements the authorized slice; review reports defects without unsolicited fixes.

Inspect existing routes, dependencies, settings, and callers before adding another path. Keep HTTP validation and response mapping in routes/adapters, with application services handling use cases. Use [backend-architecture](../autoassist-backend-architecture/SKILL.md) when changing responsibilities or execution boundaries, [persistence](../autoassist-persistence/SKILL.md) for database mechanics, and [api-contract](../autoassist-api-contract/SKILL.md) for public schema/error changes. Read only relevant guidance; loading skills does not spawn agents.

## Request boundaries

- Define bounded Pydantic v2 request fields and explicit response schemas separate from ORM entities and model-library messages. Reject invalid inputs before admission. Preserve the baseline's request IDs, status mapping, stored terminal replay, and distinct busy/conflict cases; a retry must not silently become a new provider run.
- Type service inputs, outputs, and injected dependencies for the baseline's strict mypy checks. Validate untyped external data at its integration boundary; avoid broad `Any`, unchecked casts, or ignored diagnostics that conceal mismatched contracts.
- Map expected application/integration failures into sanitized HTTP errors at the boundary. Keep request-validation errors distinct from internal response-validation defects; do not turn server bugs into client 422 errors. Correlate diagnostics using conversation/request IDs without logging secrets or full provider payloads.
- A response claiming durable success follows the commit. Do not put required persistence in BackgroundTasks or an untracked task. Storage failure must not become success or an in-memory fallback. Preserve NHTSA unavailable-versus-empty semantics rather than turning every upstream problem into a generic empty result.

## Async and resource ownership

- Await network I/O using injected async clients. A synchronous helper called from an async route still blocks: offload each complete synchronous database unit, including session creation through close, to its worker thread. Inject session factories rather than live sessions and return materialized records. Never hold a transaction across external awaits.
- Keep trivial pure helpers synchronous. Threads protect responsiveness for blocking I/O; they are not a general CPU scaling strategy. Identify substantial CPU work and worker saturation before adding machinery.
- Own reusable HTTPX clients in lifespan and close them there; do not instantiate clients per tool call or in loops. Set connect/read/write/pool timeouts and bounded connection limits. HTTPX phase timeouts are not a whole-turn deadline: bound total run duration and concurrent work separately, coordinating provider/tool budgets with [chat-agent](../autoassist-chat-agent/SKILL.md).
- Bound admission/queued work and document overload behavior for the affected path. Keep the accepted single-worker, exclusive SQLite-volume assumption; additional workers require a separate coordination/storage decision, not a throughput toggle.

## Startup, shutdown, and configuration

- Construct dependencies explicitly through application setup and lifespan. Avoid import-time I/O so schema generation and tests can build the app without external calls. Validate essential runtime settings using pydantic-settings before serving writes; keep runtime secrets out of diagnostics and allow injected test settings.
- Before readiness, open persistent storage and complete repeatable startup recovery using persistence-owned operations. Fail startup clearly when storage or recovery fails. Never reset data during ordinary startup. Health/readiness checks describe local service/storage state without contacting LLM or NHTSA.
- Coordinate bounded shutdown drain with server/container configuration. Stop accepting new work before closing dependencies. Thread work may outlive cancellation: settle observed cancellation only after outstanding database work finishes, with committed completion winning as specified in the baseline. Startup recovery remains necessary after abrupt termination; disconnect alone does not promise cancellation.

## Evidence and handoff

Use [backend-verification](../autoassist-backend-verification/SKILL.md) for affected tests. Require observable evidence for the changed boundary: invalid input makes no admission writes, error responses reveal no secrets, paused database work leaves the event loop responsive, lifespan closes resources after failure, failed startup serves no writes, and stored outcomes survive restart. Test cancellation and graceful/abrupt shutdown when changing those paths; app recreation alone does not prove crash recovery.

Discover actual commands from repository configuration; do not invent commands before scaffolding. Report changed behavior, checks actually run, and remaining limits. Update configuration/run instructions and significant failure decisions in README when implementing them. Optional background: [research and rationale](references/research.md).
