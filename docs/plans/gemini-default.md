# Gemini default provider

Use native Pydantic AI Google support alongside the existing xAI integration. Both
dealerships default to gemini-3.1-flash-lite through GEMINI_API_KEY. Preserve named
Grok connections so existing conversations retain their pinned provider identity.

Reuse the grounded runner and its tool, context, output, and whole-turn budgets.
Give Gemini a 30-second request timeout and one SDK attempt; own asynchronous client
cleanup in the existing runner lifecycle. Missing keys retain chat-unavailable behavior.
Add blank placeholders to the root local/example environment files without replacing secrets.

Verify provider dispatch, missing-key behavior, Gemini request/structured-tool support,
retry limits and cleanup with deterministic tests; run backend static checks and tests.
No database schema or public API changes are needed.

Live verification follow-up (2026-09-10, America/Chicago): the key authenticates.
Gemini rejected the grounded answer's nested maxItems schema with HTTP 400. The Google
wire transformer now describes array limits while retaining Pydantic validation and
output/token budgets. Regression coverage uses the real GroundedAnswer schema.

Completed: native adapter, provider dispatch, defaults, environment placeholders,
locked Google dependencies, README and architecture update. Verification: 146 backend
tests passed; Ruff lint/format and strict mypy passed. Docker image built from the lock.
Reviewed the adapter, schema, tests, and live-check changes. The live script uses --chat
and now exits nonzero on a failed step instead of reporting a successful process exit.

Live API evidence used the supplied CSV and temporary SQLite storage only:
- Search for 2022 Toyota RAV4: 200; AA-1001 ($26,335) and AA-1041 ($27,563) matched CSV.
- Select AA-1001: 200; returned the correct inventory details.
- Recall/crash follow-up: 200; live NHTSA campaign 22V519000 and FWD variant 16640,
  overall 5, frontal 4, side 5, rollover 4, with applicability/coverage qualifications.
- Final price follow-up: 502 provider_error in two runs; full four-turn check did not pass.
- Direct diagnosis confirmed Google 503 UNAVAILABLE: model experiencing high demand.
  A later run encountered the same error on its first search. No automatic retry or
  failover was added. Live model availability remains an external limitation.

The development database and credentials were not modified by these checks.
