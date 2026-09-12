# Async turn-status API assessment

Created: 2026-09-12. Status: implemented and verified on 2026-09-12.

## Outcome

Message `POST` commits admission and returns `202 Accepted`; the browser then reads the request state until it becomes completed, failed, or interrupted. The existing database remains the authority for status, history, leases, and terminal replay.

This is a medium-sized workflow/API refactor, not a low-risk one-line route change. The persistent data model already has the necessary request states and terminal bodies, so no schema change is expected. The risky part is transferring ownership of the model run from the request coroutine to a service-owned tracked task without weakening cancellation, graceful shutdown, lease renewal, replay, or two-worker behavior.

## Implemented contract

The chat transport exposes admission and durable request status:

```text

POST /dealerships/{dealership_id}/conversations/{conversation_id}/messages

{ request_id, text }

  -> 202 { conversation_id, request_id, status: "in_progress" }

GET /dealerships/{dealership_id}/conversations/{conversation_id}/requests/{request_id}

  -> 200 { conversation_id, request_id, status, outcome? }

```

Use a `requests` resource rather than `/messages/{request_id}`: a request is the durable execution/outcome object, while `messages` remains the transcript collection. The terminal `outcome` is the existing stored response body: it contains the completed user/assistant messages or the sanitized terminal error. An active result contains no fabricated assistant reply. Same-ID/different-text remains `409 request_id_conflict`; a different ID while active remains `409 conversation_busy`; a same active ID returns the in-progress representation instead of an error. A terminal same-ID submission returns its stored terminal outcome rather than starting another run.

## Small vertical slice

### 1. Separate admission/status from execution

**Outcome:** `ConversationService` admits a new turn in the existing atomic request-plus-user-message transaction, returns its durable in-progress record, and starts a service-owned execution task only after that commit.

- Refactor `conversations/service.py` so the existing runner, renewal, completion, failure settlement, and reconciliation code runs from a tracked task keyed by the internal request ID. Reuse `ConversationStore.admit`, `load_context`, `complete`, and `settle_failure`; do not add a second admission path or commit in a repository.

- The admission route must return only after the admission commit. If task launch cannot be confirmed after admission, conditionally settle the owned request to a sanitized terminal failure; never return a durable acceptance for work that cannot be owned.

- `ConversationService.shutdown` stops admission, waits a bounded time for its tracked tasks, and retains the existing lease/recovery behavior for abrupt termination. Tasks must not be anonymous `asyncio.create_task` calls that survive lifecycle cleanup unobserved.

- The existing `chat_requests` row is the durable status source. No table or migration is required; `in_progress`, terminal status/body, selection, replay, and messages retain their existing commit rules.

**Acceptance:** after `202`, the database contains exactly one active request and one user message; model work runs with no database transaction held; a terminal completion still atomically saves assistant message, selection, replay and body. A worker death leaves the request recoverable only after its database-clock lease expires, and never automatically reruns the provider.

### 2. Add the status contract and generated frontend types

**Outcome:** a bounded, dealership-scoped `GET .../requests/{request_id}` maps the stored request to either active status or its canonical terminal outcome.

- Add dedicated Pydantic request-status schemas and an API route in `api/{schemas,routes}.py`; map through the conversation service/store rather than querying ORM state in the route. Do not expose replay JSON, internal request IDs, provider configuration, or credentials.

- Update OpenAPI responses and regenerate `frontend/src/api/generated.ts` through the existing generator. Update `frontend/src/api/client.ts` runtime guards and error decoding at the same time.

- README and `docs/architecture.md` describe admission, polling, terminal replay, and interruption behavior.

**Acceptance:** the status endpoint returns the exact persisted terminal body after app recreation without invoking a runner, distinguishes active from all three terminal states, and rejects wrong dealership/conversation/request scope with the existing sanitized contract.

### 3. Change the browser flow to bounded polling

**Outcome:** the UI submits once, displays server-confirmed in-progress state, then polls the status resource with bounded backoff until terminal; reload resumes from the saved request ID.

- Keep `useConversation.ts` as the sole owner of pending request identity and server-message projection. Use `202` admission followed by a poll loop scoped to the current view/conversation generation.

- Poll only while a persisted request is active; abort/ignore stale browser work when the view changes; use a finite/backing-off cadence and retain the existing explicit Check reply recovery after network/poll failure. Do not fabricate an assistant message or automatically use a new request ID.

- Status display may say "accepted and preparing reply" but must not claim tool or provider progress absent server-side progress events. A later SSE feature is a separate enhancement, not part of this slice.

**Acceptance:** a slow admitted request survives reload and displays exactly one user message; terminal success/failure/interruption updates that same request; no duplicate provider call or duplicate transcript row occurs; a lost poll response leaves recovery explicit and bounded.

## Verification plan

- Backend HTTP/service tests: admission returns `202` only after user-message commit; status active/terminal shapes; same-ID replay; changed-payload conflict; task-launch failure settlement; provider failure/timeout; cancellation and graceful shutdown of tracked tasks.

- Persistence/PostgreSQL tests: same/different-ID races, cross-worker completion versus stale recovery in both lock orders, and abrupt worker stop after admission. Assert persisted status/body/message count and no extra provider execution.

- Frontend Playwright tests with deterministic API responses: accepted polling to completion, reload while active, bounded poll failure/Check reply, terminal errors, stale view responses, and no duplicate polling after completion.

- Regenerate/check OpenAPI types, then run the existing focused backend/frontend checks and `python scripts/verify.py` against isolated Compose storage. Do not use the development PostgreSQL volume.

## Effort and risk

Estimated implementation effort: roughly 1–3 focused engineering days, assuming the existing tests/fixtures remain usable. A superficial `create_task` version would be less than a day but is not acceptable: it would make task ownership, shutdown, cancellation, and observability unreliable. The durable database foundation makes this materially lower risk than building a queue/job system from scratch, but the lifecycle refactor crosses the HTTP, application, API contract, and browser boundaries. The main residual risk is a regression in the existing admission/cancellation/recovery contract, not SQL scale or model-tool behavior.

## Implementation refinements

- Status GET validates dealership/conversation scope before scoped expiry recovery, then reads the durable request. No provider call and no transcript scan.

- POST returns 202 for new/active requests; terminal POST preserves its canonical stored HTTP status/body. GET always wraps known request state in 200, with the exact stored body as outcome.

- Track execution by internal request ID, including capacity ownership. Shutdown stops admission, drains for 20 seconds, then cancels and joins remaining work before closing runners. Outstanding database writes finish before settlement.

- Poll at most 20 times with capped exponential backoff (0.5-5 seconds), with a 15-second timeout per HTTP operation. Resume confirmed active history on reload; uncertain admission remains an explicit same-ID Check reply.


## Completion evidence (2026-09-12)

- Implemented committed 202 admission, same-active-ID replay, scoped durable status GET, tracked execution, task-launch settlement, and shutdown drain/cancellation. Terminal POST/GET bodies match stored JSON exactly, including timestamps.
- Browser uses bounded polling and reload recovery with the same request ID. Tests cover poll exhaustion, malformed status, terminal failure/interruption, late responses after view changes, and exactly one transcript projection.
- `python scripts/verify.py` passed against isolated Compose storage: 235 backend tests and 33 Playwright/schema tests; Ruff, format checks, strict mypy, TypeScript, ESLint, Prettier, OpenAPI drift, and Vite build passed. PostgreSQL cases cover two-worker admission, both terminal lock orders, renewable leases, and abrupt process loss after HTTP 202. No development database was used.
- Final naming cleanup changed the shared response value to ConversationOutcome because it now also represents admission/status; all backend static checks and 28 focused tests passed afterward (the PostgreSQL fixture was skipped in that local-only run, having passed in Compose).
- Exploratory in-app browser check against a temporary backend with a four-second deterministic runner: keyboard submit, visible accepted state, GET polling, reload with one user/assistant pair, no console warnings/errors. Temporary browser/server sessions closed.
- Terminal status query count remains two queries at 1 through 5 completed turns, with no transcript query. External runner gates and capacity tests confirm other conversations can proceed; cancellation tests drain admitted/completed writes before releasing capacity.
- Updated README, architecture, canonical stack lifecycle, generated API types, and HTTP acceptance scripts. PowerShell script parses and Python script compilation passes; optional live safety smoke was updated but not run.
- Docker startup recovery confirmed engine 29.7.2 after preserving/recreating stale runtime socket directories. Saved the full procedure in C:/Users/shane/.codex/AGENTS.md and linked it from project guidance. This is verified recovery, not a claim of permanently fixing Docker's underlying defect.

No schema change, automatic provider resumption, SSE, or live provider evaluation was introduced.
