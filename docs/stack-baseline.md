# AutoAssist shared stack baseline

Authoritative accepted stack, execution boundaries, and chat lifecycle. Extracted with user approval on 2026-09-10 and revised for PostgreSQL multi-worker operation on 2026-09-11. This reference is available to all project skills; `tech-stack` remains the explicit-only workflow for explaining or revising these decisions. These are implementation requirements, not claims that the application exists.

## Stack baseline

Assumption: TypeScript runs in the browser and Python on the server. Clarify if a Python frontend framework was intended.

## Small working slice

- Backend: FastAPI, Uvicorn, Pydantic v2, pydantic-settings.
- Persistence: PostgreSQL and SQLAlchemy 2 typed ORM; separate API schemas from database models. Use synchronous database access consistently. SQLite is used for fast isolated tests. Recreate the development database explicitly after schema changes; never reset it on ordinary startup. No migration framework.
- Integrations: HTTPX for NHTSA; Pydantic AI for LLM orchestration, typed tools, validated outputs, and model history. Use its supported integration for the chosen provider, installing only the needed provider dependencies. The provider remains unselected. Set explicit timeouts and bounded tool calls; validate tool arguments and never execute model-generated SQL.
- Frontend: React, TypeScript strict mode, Vite, assistant-ui, plain CSS, native fetch, local component state. Connect assistant-ui to FastAPI through a custom backend adapter. Implement after the required API slice works.
- API contract: openapi-typescript as a frontend development dependency. Generate frontend request/response types from FastAPI's OpenAPI schema and use them in the custom fetch adapter; do not hand-maintain duplicate API types. Keep generation reproducible from the local application without live LLM/NHTSA calls. Commit the generated type file and check for schema/type drift in the shared verification command. These are compile-time types, not runtime response validation.
- Dependency tooling: uv and uv.lock for Python; npm and package-lock.json for frontend. Pin runtime versions during scaffolding and verify dependency compatibility.
- Containers: Docker Desktop on the Windows development machine with Docker Compose is the standard build, run, and verification workflow. Compose owns PostgreSQL, backend, and frontend services. Keep uv and npm inside their respective images, install from committed lockfiles, and pin compatible base-image/runtime versions. Start Desktop with `docker desktop start --detach --timeout 120`, then confirm `docker info` succeeds; the internal `desktop-linux` context name is not a separate installation requirement.
- Container persistence/configuration: mount PostgreSQL data on a named volume so data survives container recreation and image rebuilds. Never reset data on startup; document explicit development database reset separately from ordinary shutdown. Supply secrets at runtime, exclude secrets/local databases/host dependencies from image build contexts with .dockerignore, and keep host .venv/node_modules from masking container dependencies. Use a non-root application runtime user.
- Container networking: distinguish browser-accessible URLs from Compose service names. Prefer relative browser API requests through the frontend development proxy to the backend service. Bind container servers to 0.0.0.0 and publish development ports to localhost. Use a local health endpoint that does not call live LLM/NHTSA services.
- Static checks: Ruff lint/format, mypy strict for application code, TypeScript compiler, ESLint with typescript-eslint typed rules, Prettier. Start with focused rules; avoid overlapping Python linters/formatters.
- Tests: pytest with injected LLM/NHTSA fakes, HTTPX/FastAPI API tests, temporary SQLite files, and isolated PostgreSQL coordination/recovery tests, and Playwright browser tests.
- Automation: one cross-platform verification entry point invoking checks in Docker/Compose and one GitHub Actions workflow running that same entry point. Keep test databases isolated from the development data volume and propagate failing check exit codes. Validate Compose configuration, image builds, API reachability, and persistence across container recreation once scaffolded. Keep secrets, disposable generated files, and local databases out of Git; commit the generated API type file as specified above.

## Chatbot library boundaries

- Keep inventory queries and NHTSA behavior in ordinary Python functions/services with thin Pydantic AI tool wrappers. Keep library-specific orchestration and message conversion at the integration boundary; avoid a speculative provider abstraction framework.
- Own conversation IDs, API schemas, database models, and selected-vehicle context in the application. PostgreSQL is authoritative for conversations and messages. Persist the model history needed for replay, including tool calls/results; isolate its library-specific serialization from the public API. Never trust browser-supplied history as authoritative tool results.
- Start with assistant-ui's LocalRuntime and a custom fetch adapter; use ExternalStoreRuntime when application-owned frontend message state makes it simpler. Connect history loading/saving to the backend. Expose edit, regenerate, and cancel controls only when their backend semantics are implemented. No hosted chat service or Vercel AI SDK protocol is required.
- Required durability means stored conversations survive restarts. Automatic resumption of an interrupted LLM run is deferred, along with durable execution engines such as Temporal or DBOS. Document interrupted-request behavior explicitly.

## Database execution and session ownership

- Use async chat orchestration with synchronous SQLAlchemy database units executed in worker threads. Offload the entire unit: session creation, queries, result materialization, commit/rollback, and close. Calling a synchronous helper directly from async code does not offload it.
- Inject a session factory into chat/tool dependencies, never a live session. Each unit creates and closes its session in its worker thread. Return plain values or typed application records, not attached ORM objects or lazy queries. Parallel tools use independent sessions; tools mutating shared run context execute sequentially.
- Application services own transaction boundaries; repository helpers participate without independent commits. Close transactions and sessions before waiting on LLM/NHTSA calls. Read context, close the read unit, call external services, then save results in a new transaction. Never hold a transaction for the entire chat turn.

## Chat request lifecycle

Use non-streaming replies and PostgreSQL-backed coordination across workers. The development container runs two Uvicorn workers; additional stateless instances may share the database. Startup schema/bootstrap uses an advisory lock. Automatic external-run resumption remains deferred. The 120-second recovery threshold measures request age, not worker liveness; it has no renewal heartbeat and assumes synchronized host clocks. Terminal row locking prevents a late completion from overwriting recovery.

Create a conversation before submitting its first message. Each submission supplies a client-generated `request_id`, unique within that conversation. Persist its payload, status (`in_progress`, `completed`, `failed`, or `interrupted`), and terminal HTTP status/body. PostgreSQL enforces unique `(conversation_id, request_id)` and at most one active request per conversation. Admission atomically claims the conversation and inserts the request/user message; avoid check-then-insert races and in-memory-only locks.

| Case | Persisted state | API outcome |
| --- | --- | --- |
| New valid request, conversation idle | Commit request/user message before calling provider. On success, atomically save assistant reply, complete tool/model replay history, selected-vehicle context, and terminal response; mark completed and release claim. | 200 only after completion commit. |
| Different request while conversation active | Do not admit or append second message. Other conversations can proceed. | 409 `conversation_busy`; resubmit the unaccepted request later with its original ID. |
| Same ID/payload while active | No new messages or provider run. | 409 `request_in_progress`; retry later with same ID. |
| Same ID/payload after terminal outcome, including lost response or restart | Read stored outcome; no new messages or provider run. Check existing ID/payload before conversation-busy admission. | Replay stored terminal status/body. |
| Same ID, different payload | No changes. | 409 `request_id_conflict`. |
| Provider failure or timeout after admission | Keep user message; mark failed, store sanitized error, release claim. No fabricated assistant reply or partial selected-vehicle update. | 502 `provider_error` or 504 `provider_timeout`; same-ID retry replays error. Deliberate new attempt uses a new ID. |
| Worker stops before completion commit | Keep fresh active requests protected so another worker startup cannot interrupt live work. After the 120-second stale window, startup or a scoped submission check marks the request interrupted, preserves its user message, stores the terminal error, and releases the claim. | Before expiry, same-ID retry returns `request_in_progress`; afterward it returns stored 409 `request_interrupted`. New work uses a new ID; no automatic rerun. |

Invalid submissions return 422 and unknown conversations 404 before admission, without appending messages. Rejected submissions are not conversation messages. History exposes admitted user messages with request status and only actual assistant replies. Subsequent model input uses completed turns plus the current user message; failed/interrupted turns remain visible but are excluded from replay. Successful turns retain complete tool-call/result history; partial in-memory tool history may be lost on interruption. Exactly-once provider execution and preservation of uncommitted provider output are not promised.

Transport retries reuse the same ID/payload; a new ID means intentional new submission. The frontend disables duplicate submission while busy and displays failed/interrupted state. Disconnect does not guarantee cancellation: retry the same ID to discover state. On observed server cancellation, settle as interrupted after outstanding database work finishes; an already committed completion wins. If storage is unavailable, do not claim durable success; leave unfinished state for startup recovery.

Focused implementation tests use temporary SQLite files plus isolated PostgreSQL, external fakes, and synchronization events rather than sleeps: a paused database unit leaves the event loop responsive; parallel tools use independent sessions and materialized results; a paused external call holds no transaction and another conversation can persist; racing same/different IDs produces the specified message/provider-call counts; PostgreSQL coordinates independent store instances and terminal row locks; terminal outcomes replay after app recreation; failures, timeouts, cancellation, and stale interruption recovery preserve the specified state.

## Agent workflow

Keep AGENTS.md short and add exact setup/run/check commands once scaffolded. Build one representative path before expanding. Work in small vertical slices with observable acceptance criteria. Require meaningful behavioral tests and diff review; do not suppress checks merely to pass. Record tradeoffs in README and implementation plans in docs/plans/. No custom agent orchestration or new MCP integrations are needed initially.

Essential tests: combined inventory filters, specific-vehicle follow-ups, persistence across application recreation, recalls and crash ratings, unavailable safety data versus verified empty results, invalid tool arguments, external timeouts. Use clearly labeled test fixtures and use `docs/context/inventory/data.csv` for the real import path. Keep a small optional live conversation evaluation set separate from deterministic CI tests.

Defer Redis/Celery, LangChain/LangGraph, vector databases, Next.js, global frontend state, large UI kits, Kubernetes, and comprehensive observability infrastructure. PostgreSQL solves shared durable coordination; it does not itself provide load balancing, database high availability, backups, or durable external-job resumption.

## Research sources

- https://docs.docker.com/compose/
- https://docs.docker.com/engine/storage/volumes/
- https://docs.docker.com/build/building/best-practices/

- https://learn.chatgpt.com/guides/best-practices
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://docs.astral.sh/uv/
- https://docs.astral.sh/ruff/
- https://fastapi.tiangolo.com/tutorial/sql-databases/
- https://docs.sqlalchemy.org/en/20/orm/quickstart.html
- https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
- https://vite.dev/guide/
- https://typescript-eslint.io/getting-started/typed-linting/
- https://www.typescriptlang.org/tsconfig/strict.html
- https://mypy.readthedocs.io/en/stable/getting_started.html
- https://www.python-httpx.org/
- https://pydantic.dev/docs/ai/core-concepts/agent/
- https://pydantic.dev/docs/ai/core-concepts/message-history/
- https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/
- https://www.assistant-ui.com/docs/runtimes/custom/overview
- https://docs.pytest.org/en/stable/
- https://prettier.io/docs/
- https://developers.openai.com/api/docs/guides/function-calling
- https://openapi-ts.dev/introduction
- https://playwright.dev/docs/intro

