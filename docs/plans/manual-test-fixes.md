# Manual-test fixes — 2026-09-11

Status: implemented and verified. Scope: the findings in `docs/reviews/2026-09-11-manual-browser-testing.md`, plus the upstream HTTP 504 discovered during the fix verification.

## Reproduced before fixing

- A real-agent/temporary-SQLite regression returned correct AA-1001 details but a null selected_vehicle_id. The next pronoun could not resolve. Covered omitted, keep, and clear model selection actions.
- Isolated live diagnostics reproduced Google HTTP 503 UNAVAILABLE, with a high-demand explanation. Direct NHTSA recall/crash lookups succeeded. A test using the real Google SDK with fake HTTP reproduced failure on a temporary 503 followed by successful responses.
- The first rebuilt browser check encountered upstream HTTP 504, incorrectly surfaced as generic provider_error. Two additional fake-HTTP regressions failed before the final refinement.

## Final changes

1. Validated detail responses derive and retain selection from application reference resolution. Model defaults cannot discard the subject. Selection, reply, and replay commit together through the existing transaction; ambiguity/failure behavior and schema remain unchanged.
2. Gemini retries only generation HTTP 503/504 failures, up to three attempts with 1s/2s backoff, within the unchanged 60s turn deadline. SDK retries stay disabled. Short numeric Retry-After is honored; larger/date/malformed values are not retried early. Six logical model requests permit at most eighteen generation attempts. Completed tools and database writes are never rerun by this retry loop.
3. Exhausted upstream HTTP 504 uses the existing provider_timeout / HTTP 504 outcome. Sanitized diagnostics include upstream status, without error bodies or credentials. Other HTTP and ambiguous transport failures remain terminal. No model fallback was added.

Regression coverage includes overload/timeout recovery, exhaustion, permanent errors, sanitized logs, cancellation during backoff, Retry-After, real inventory tool execution once, one durable outcome, same-ID replay without new provider requests, and restored selected-vehicle context.

## Final validation

- Focused regressions/provider tests: **21 passed**.
- `python scripts/verify.py`: **passed** after final changes — Ruff, formatting, mypy (38 source files), **172 backend tests**, frontend TypeScript/ESLint/Prettier, generated-API drift, production build, and **25 Playwright tests**. Browser coverage includes imported CSV, real API, safety fakes, and a real process restart with retained isolated storage. Existing dependency warnings were nonfatal.
- Isolated live four-step run completed inventory, explicit selection, recalls plus crash ratings, and a price follow-up, recovering from two observed 503s. An earlier run completed its first three steps but failed the final price request; the successful rerun does not establish zero provider/model failure rate.
- Final rebuilt browser: exact original Toyota SUV search -> third-item details -> reload -> pronoun safety question **passed**. AA-1001 retained its context and returned both NHTSA branches, including campaign 22V519000 and variant 16640. The successful safety response remains visible in the app.
- Public transcript: `docs/reviews/2026-09-11-fixed-browser-conversation.json`, conversation `cfb75f79-23b3-4baf-b29b-e3e504ef1266`. Its initial failure predates the final 504 refinement; subsequent three submissions completed.
- Scoped code review and `git diff --check` completed. Temporary diagnostic script removed.

The running backend was rebuilt/recreated without deleting the development volume. Existing conversations survived. Automated checks used isolated storage; no schema migration, reset, or unrelated application change was required. Sustained provider outages can still exhaust the bounded retry/deadline and remain truthful failed requests.
