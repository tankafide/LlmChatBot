---
name: autoassist-backend-verification
description: Design, implement, or assess AutoAssist backend tests and verification evidence for service behavior, database integrity, HTTP contracts, concurrency, and recovery. Use when explicitly requested or selected by a project orchestrator for an affected backend slice.
---

# Backend verification

Read [AGENTS.md](../../../AGENTS.md) and the [shared baseline](../../../docs/stack-baseline.md), especially execution/session ownership and the chat lifecycle. Domain specialists define behavior; this skill owns how to prove it. Do not duplicate or revise the lifecycle here. Use only checks relevant to the changed boundary.

During planning, name each acceptance scenario, setup/fault, observable API and persisted result, and recovery check. During authorized development, write focused behavioral tests, execute checks, fix failures, and review the diff. During review, inspect or run existing evidence and report concrete gaps; review alone does not authorize fixes. Application scaffolding and executable check commands may not exist: inspect repository configuration before naming commands; describe a check to implement when absent.

## Test boundaries

- Separate service/unit, repository/integration, and HTTP API tests using the existing layout. Test decisions in ordinary services with injected dependencies; use deterministic LLM/NHTSA fakes at external boundaries without replacing the business behavior under test. Assert facts, state, calls/budgets, and error categories rather than exact generated prose or private helper call sequences.
- Repository and transactional tests use real SQLite files under pytest `tmp_path` for fast coverage and isolated real PostgreSQL for dialect, partial-index, row-lock, and cross-worker behavior. An in-memory database, mocked session, or outer rollback fixture is insufficient evidence for real commits, locks, constraints, or restart recovery. Synthetic vehicle fixtures must be labeled test data; they do not replace importer validation against `docs/context/inventory/data.csv`.
- HTTP tests exercise validation, status/body mapping, history, and dependency wiring through the application. For concurrent async tests use HTTPX ASGI transport with an explicit lifespan harness: AsyncClient alone does not run startup/shutdown. Construct loop-owned resources inside their lifespan. Close clients/engines, remove overrides/listeners, and join test tasks/threads in fixture cleanup even when assertions fail.
- Cover combined inventory filters and limits, specific-vehicle follow-ups and ambiguous references, invalid inputs/tool arguments, and selected-vehicle persistence. Include both recall and crash-rating paths, verified empty results, unavailable/partial data, mismatched vehicles, malformed upstream responses, and timeouts. Verify unsupported safety claims are not invented.
- Provider tests cover malformed outputs, transient versus permanent failures, retry/deadline/tool/context/output budget exhaustion, complete tool-call/result history, and exclusion of failed/interrupted turns from model replay. Prevent real provider requests in deterministic tests. Count total attempts across SDK and application retries; use controllable clocks/fakes where appropriate. Keep small optional live evaluations separate from CI and report provider/model configuration and factual expectations.

## Durability and concurrency evidence

For chat admission/completion changes, derive cases directly from the shared lifecycle and assert persisted rows/status, terminal HTTP status/body, message count, and provider-call count. Include invalid/unknown submissions, same-ID races, different-ID races, payload conflicts, and terminal replay while another request is active. Replay success and error outcomes through a fresh application using the same file; simulate a lost response after commit to prove no rerun or duplicate messages.

Use synchronization events/barriers and bounded waits to place faults at known boundaries, not scheduling sleeps. For PostgreSQL terminal transitions, gate the winning transaction and observe the contender waiting on its database lock; exercise completion versus recovery in both orders and serialized concurrent startup. Release gates and join outstanding work in `finally`; a timeout is a deadlock guard, not the intended coordination mechanism.

- Pause a database unit in its worker thread and prove unrelated event-loop work progresses before releasing it. Instrument session ownership for parallel tools and assert results remain usable after sessions close. Pause an external call and prove no database transaction/session spans the wait and another conversation can persist.
- Cancel before and during completion persistence; let outstanding thread work settle, then inspect durable state. Assert the baseline's committed-completion precedence and interruption behavior; do not equate client disconnect with server cancellation. Verify cleanup after exceptions, timeouts, and cancellation.
- Inject a mid-unit failure and a commit/write failure: preserve earlier committed data, roll back partial changes, release resources, and never return durable success without a confirmed commit. Exercise uniqueness/foreign-key constraints, index predicate rejection, bounded lock contention, and unavailable storage/startup failure, including a refused psycopg connection with no SQLSTATE. Resolve uncertain commit outcomes from durable request identity rather than blindly replaying writes.
- Once a runnable backend exists, perform a disposable subprocess/container abrupt-stop check in addition to application recreation. Gate after admission commit and before completion, terminate the owning process without graceful cleanup, then keep or start another worker on the same intact isolated PostgreSQL storage. Verify fresh-work protection, stale interruption recovery and terminal replay, prior completed data, no provider rerun, and recovery safe to repeat. Separately recreate the container with its test volume preserved. Never use/delete the development volume for these tests.

## Performance evidence

Measure SQL through the full response path, including serialization, with a scoped engine event listener such as `before_cursor_execute`. Seed fixtures before counting and remove the listener afterward. Compare multiple result sizes with multiple related records: require the intended bounded/batched query count, not one new query per row. Check SQL filtering/order/limits, bounded history/tool results, and materialized records without serialization-triggered lazy loads. Investigate a hot query's plan when evidence warrants it.

Assert configured concurrency, queue/overload, context, and run limits deterministically. Record realistic fixture sizes and targeted measurements for affected hot paths; separate latency/load measurements from timing-sensitive CI assertions. Lint/type checks and a fast tiny fixture do not establish event-loop responsiveness or scalability. Distinguish per-worker capacity from any global limit and report the remaining load-balancing/database capacity boundary.

## Completion

Discover the shared cross-platform Docker/Compose verification entry point and the GitHub Actions workflow; backend checks contribute pytest, Ruff lint/format, and strict mypy to the same entry point used by CI. Coordinate contract drift/frontend checks with their verification guidance when applicable; do not create a second automation system. Verify failure exit codes propagate and tests use isolated storage and fake externals. If container configuration changes, include clean build, readiness/API reachability, and persistent-volume recreation evidence with Docker guidance.

Report commands actually run, pass/fail outcomes, boundary of fakes versus real services/storage/processes, and remaining coverage gaps. Distinguish planned tests from executed checks; no passing claim for unavailable tooling. Fix affected failures during implementation without weakening assertions or suppressing checks merely to pass. Routine agent-run verification is not a human approval gate.

Optional background: [dated research and rationale](references/research.md).
