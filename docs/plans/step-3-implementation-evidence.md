# Step 3 implementation evidence

Follow-up: [implementation review fixes and 142-test verification](step-3-review-fixes.md).

Date: 2026-09-10, America/Chicago (UTC-05:00).

Implemented the accepted plan using existing `chat/grounded.py`, `chat/selection.py`,
`chat/history.py`, and `conversations/service.py`, with new `safety/` modules and
`integrations/nhtsa.py`. HTTPX 0.28.1 is now a locked runtime dependency. No schema change,
development database recreation, new public endpoint, cache, retry, or alternate lifecycle.

## Executed verification

- Baseline before safety edits: 72 tests passed.
- Latest full local suite before the five additional output-grounding assertions: 127 passed.
  Those five assertions also passed independently.
- Ruff lint/format and strict mypy passed (37 application source files).
- Docker Desktop readiness and quiet Compose validation passed. Locked Compose verification
  passed with all 132 tests in 28.99 seconds, plus Ruff lint/format and strict mypy.
- `./scripts/verify-chat-container.ps1` passed: imported 127 actual CSV rows in the separately
  named `autoassist-step3-acceptance` volume, selected AA-1001, committed combined recall/variant
  evidence, stopped/recreated the container, replayed the original reply, resolved ID 202, and
  continued inventory detail. Synthetic NHTSA/model behavior runs real safety tools, validation,
  rendering and persistence. Only that disposable project's volume was removed.
- `test_safety_recovery.py` killed a real subprocess during a gated NHTSA await after admission.
  An unrelated conversation write and health request succeeded during the wait. Two subsequent
  application startups retained the earlier committed safety reply and choices, replayed it
  exactly, and replayed the interrupted request without model/NHTSA calls.
- Transport/service tests cover endpoint casing/count/identity failures, duplicate campaigns,
  conflicting/unknown variants, all four rating statuses, warning omissions, urgency/excerpts,
  transport statuses/timeouts/cancellation, response closure, byte limits, and exact GET limits.
  Four concurrent gated lookups all reached the external wait before release.
- HTTP and history checks cover combined empty-recall/ambiguous-crash replies, restart and exact
  replay, explicit choice revalidation, A-to-B-to-A invalidation, stale bare IDs, suffix trimming,
  and finding an undisplayed sixth variant before a separate confirmation turn.
- A 524,288-byte synthetic JSON envelope containing 200 records parsed in 0.667 ms on this Windows
  runtime. This bounded parse remains synchronous; no latency threshold is a CI assertion and
  no production throughput claim is made. Existing worker-thread SQL and lifecycle tests remain
  in the shared suite.

## Live checks and limitation

`docker compose -f compose.safety-live.yaml run --build --rm safety-live` uses a temporary SQLite
database and the actual importer. Docker supplies runtime credentials; no secret file, container
environment, header, or key was inspected or printed.

At 2026-09-11 04:26 UTC (September 10 locally), NHTSA returned a valid recall result for AA-1001
(2022 Toyota RAV4 FWD) and discovered/matched VehicleId 16640. The detail had summary stars
overall/front/side/rollover 5/4/5/4 and an explicit additional unrated category. One model-level
campaign was returned then; neither this count nor those stars are frozen into live CI assertions.
Sources: [recalls](https://api.nhtsa.gov/recalls/recallsByVehicle?make=Toyota&model=RAV4&modelYear=2022),
[detail](https://api.nhtsa.gov/SafetyRatings/VehicleId/16640?format=json).

The configured live Grok flow failed at its first inventory question with HTTP 502
`provider_error`. Sanitized diagnostics identified `ModelHTTPError` caused by `AioRpcError`.
Thus live Grok search/selection/safety follow-up is **not verified**; no successful end-to-end
live model claim is made. Packages: Pydantic AI slim 2.42.0, xAI SDK 1.19.0, HTTPX 0.28.1;
configured model `grok-4`. Deterministic model and real NHTSA checks succeeded independently.

## Scoped review

Reviewed matching, branch independence, grounding, stale ordinals, budgets, resource ownership,
atomic completion, and replay byte accounting. Fixed bare stale-ID lookup, shared deadline,
HTTPX transport pool limits, completion identity validation, and aggregate warning omissions.
Application result validators reject inconsistent state/category combinations. Existing user
work remains uncommitted; no unrelated source reorganization or CI packaging was performed.
