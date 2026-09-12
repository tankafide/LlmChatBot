# Evaluation and operations

Implement a small labeled live-model evaluation suite with isolated imported inventory,
controlled NHTSA responses, exact tool/filter and context assertions, human-review rubrics,
and latency/call-count reports. Keep live execution opt-in and deterministic harness tests
in the shared verifier.

Use database-clock TIMESTAMPTZ leases: admission grants
120 seconds, the owner renews every 20 seconds, and each worker sweeps at most 100 expired
requests every 30 seconds using skip-locked rows. Terminal row locking fences late writes;
renewal cannot resurrect an expired request. Database failures leave recoverable state.

Emit payload-free JSON events at admission, model, NHTSA, and terminal boundaries.
Require a dealership-scoped creation UUID and retain it in the browser across uncertain
responses and reloads. Replay creation without repinning its configured model.

Verify labeled scoring, privacy, lease renewal/expiry/races and bounded recovery on isolated
PostgreSQL, creation races/replay and browser retries, then run the shared verifier.
Update README, architecture, baseline and affected skills to describe current behavior.
Schema changes require explicit development database recreation; do not reset user data.
## Completion evidence

- Implemented all four boundaries, with 20 labeled conversations / 22 turns and opt-in live
  execution against isolated imported inventory. Evaluation-only vehicle IDs are deterministic.
- Shared `python scripts/verify.py` passed: 213 backend tests, including real PostgreSQL
  creation races, clock skew, renewal/expiry, skip-locked bounded batches, terminal races and
  abrupt process recovery; 31 Playwright tests, including lost creation response/reload retry.
  Ruff, format, mypy, frontend type/lint/format, API drift and build checks passed.
- Final logging-status refinement passed eight focused evaluation/event/background-task tests
  and backend static checks. The edited persistence skill passed its structural validator.
- Live baseline: 13/22 strict checks passed, all seven filter cases and all four stock/follow-up
  resolution checks passed. Four model-output validation failures remain visible in the report.
  Median 5.82 seconds, p95 11.44 seconds, 64 model requests. See `evaluations/baseline.md` for
  exact scope and limits; pending human semantic review is not counted as passed.
- Scoped review kept SQL in the repository, commit/reconciliation in the store, task lifetime in
  the service/lifespan, and payload-free counters at integration boundaries. Recovery samples
  PostgreSQL time for an indexed range scan and locks at most 100 candidates per transaction.
- Development storage was neither used by checks nor recreated. Updated serving requires explicit
  development database recreation because the schema adds creation identity and lease expiration.
