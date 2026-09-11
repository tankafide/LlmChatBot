# Backend presentation readiness review — 2026-09-11

## Scope and changes

Reviewed the current code, including the manual-session selection and Gemini retry fixes,
before editing. This review covers responsibility placement and the reported search gap;
it is not an exhaustive correctness or production-readiness claim.

- Fixed list grounding in `chat/answers.py`: returned IDs must belong to the latest inventory
  search. Earlier turn evidence and an earlier search in the same turn cannot leak into the
  current list. Four scripted-model tests use real temporary SQLite and inventory tools;
  all failed before the fix and passed after repair validation was added. They cover current
  search results being empty and nonempty.
- `conversations/service.py` now coordinates the asynchronous lifecycle (823 to 402 lines).
  `store.py` owns complete synchronous session/transaction units and serialized writes;
  `repository.py` owns SQL and ORM mutations without independent commits. `completion.py`
  owns completion invariants/response assembly; `execution.py` owns draining and capacity;
  `outcomes.py` holds serializable terminal outcomes. These are concrete responsibilities,
  not a generic service hierarchy. Startup recovers through the store before traffic.
- `chat/grounded.py` now owns agent execution, history conversion and final result staging
  (572 to 231 lines). `answers.py` owns schemas, grounding and inventory rendering;
  `tools.py` owns model-tool adapters; `context.py` owns per-turn evidence/tool budgets.
  Safety-aware reference resolution now sits beside inventory reference resolution in
  `selection.py`. Validation errors become model repair requests only at the runner boundary.
- Found and separated import SQL from the CSV parser/import use case into
  `inventory/import_repository.py`. Import records live with inventory records, and the
  import service retains transaction ownership. Consolidated three identical inventory
  projections into one scoped query builder; filters, ordering, limits and query counts
  retain their behavior.
- Reconciled README test/feature status, health behavior and architecture descriptions.
  Setup now avoids overwriting an existing `.env` on repeated use of the setup example.

## Placement audit and preservation

Traced HTTP -> lifecycle -> transaction units -> repository -> provider/tools -> validated
completion, plus CSV import and the NHTSA boundary. Routes remain HTTP adapters, inventory
queries remain parameterized and dealership-scoped, and NHTSA transport/parsing/matching/
rendering retain their established separate owners. No further actionable placement defect
was identified within the reviewed scope.

Kept completion selection checks inside the same transaction as the reply/outcome write.
Only materialized records/outcomes cross from store to async service. Repository ORM values
are consumed within the owning store session. No session crosses a provider await. There is
no database schema change, migration, startup reset, compatibility re-export, or provider fallback.

Compared the principal lifecycle methods against a before-edit snapshot: control flow is
unchanged after normalizing relocated store calls and terminal-outcome helpers. The manual
session's Gemini retry implementation, provider error classification, and regression tests
were unchanged. Existing selection behavior remains covered by those tests.

## Verification

- New search regressions: 4 failed before correction, 4 passed after correction.
- Local backend suite: 176 passed.
- Shared `python scripts/verify.py`: passed; Ruff lint/format, strict mypy (46 source files),
  176 backend tests, TypeScript/ESLint/Prettier, generated OpenAPI drift, production build,
  and 25 Playwright tests. Existing dependency deprecation/bundler warnings were nonfatal.
- Coverage includes imported assignment CSV, real temporary SQLite, write/commit failures,
  request races, same-ID replay, cancellation draining, event-loop responsiveness, killed
  subprocess recovery, and real-backend browser restoration after process restart.
- Scoped source review and `git diff --check` passed. Most project files are still untracked
  from prior work, so the scoped review also compared files against a before-edit snapshot.

## Live rehearsal

Uses the existing `compose.safety-live.yaml` command and temporary SQLite, with the real
assignment inventory and configured Gemini model. Development data is not used for tests.

- 07:16 America/Chicago: direct NHTSA recalls and crash ratings succeeded. Inventory search
  returned AA-1001 ($26,335) and AA-1041 ($27,563), matching the CSV. Selection then exhausted
  the turn deadline after an observed Gemini 503 and returned truthful HTTP 504
  `provider_timeout`; the smoke process exited nonzero. This is not a passing four-turn run.
- 07:19 America/Chicago: direct NHTSA lookups again succeeded. Search recovered from observed
  upstream 504/503 responses and returned both correct RAV4 records. Selection encountered
  another upstream 504 and exhausted the turn deadline, returning HTTP 504 `provider_timeout`.
  The second smoke process also exited nonzero. Neither fresh rehearsal completed all four
  steps; the earlier successful manual-session run remains historical evidence only.

Current limitation: sustained Gemini slowness/overload can exhaust the existing retry budget
and deadline. Adding retries indefinitely or silently changing provider would weaken the
explicit bounds or change the configured behavior. No such workaround was added. The code,
deterministic complete flow, and failure behavior are verified; an uninterrupted fresh live
four-turn flow could not be verified during this task.

## Local runtime

After the shared checks passed, rebuilt/recreated only the backend using
`docker compose up --build -d --no-deps backend`. The container reports healthy, the frontend
remains running, and the existing named development volume remains mounted. No data reset
or migration occurred; all automated and live rehearsals used separate temporary storage.
