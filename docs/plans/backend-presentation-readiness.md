# Backend presentation readiness — 2026-09-11

Scope: fix search grounding, clarify backend responsibility ownership, reconcile current
documentation, and verify the demo without undoing the manual-session fixes.

Implementation complete; shared verification passed. Live rehearsal results and final
review are recorded in `docs/reviews/2026-09-11-backend-presentation-readiness.md`.

1. Require list answers to reference the latest search result set. Reproduce stale
   prior-turn and earlier-search evidence with a scripted model, including empty results;
   verify repair and valid current results through real inventory services.
2. Separate conversation lifecycle orchestration from synchronous transaction units and
   repository SQL. Keep transactions owned by the application store, repository methods
   commit-free, records materialized before return, and cancellation/uncertain-commit
   reconciliation unchanged. No schema or public API change. Run concurrency, rollback,
   replay, responsiveness, cancellation, and abrupt-process recovery coverage.
3. Separate agent answer policy/rendering and tools from provider orchestration. Audit
   adjacent modules for concrete misplaced responsibilities; avoid generic abstractions
   or splitting code solely to shorten files. Preserve manual-session selection/retry fixes.
4. Update README and architecture ownership/verification claims. Run backend checks and
   shared isolated Docker verification, then the existing temporary-storage live rehearsal.
   Record external failure honestly; do not reset development data or add provider fallback.

Completion requires scoped diff review and recorded check outcomes. The current manual-test
plan already reports successful live checks and bounded Gemini 503/504 retries; revalidate
that behavior rather than implementing competing retry logic.

Delivered: list validation plus four regressions; conversation store/repository/completion
boundaries; agent answers/tools/context extraction; import repository extraction; shared
inventory SQL projection; current README and architecture map. No schema/API change.
Existing manual-session retry and detail-selection changes were preserved. Recovery and
cancellation test hooks now target the store's actual transaction units.

Validation: four new cases failed before the fix and passed afterward. Local backend suite
passed (176 tests). `python scripts/verify.py` passed with Ruff, strict mypy (46 source files),
176 backend tests, frontend static checks, generated API drift, production build, and 25
Playwright tests. Tests use isolated storage and external fakes. The live rehearsal is separate.

Final live outcome: both fresh rehearsals returned correct search results and successful direct
NHTSA data, but selection exhausted the Gemini deadline after upstream 503/504 responses.
Recorded both failed runs; the remaining limitation is external provider availability, not a
claimed passing live demo. The tested backend was rebuilt and reports healthy with its named
development volume preserved. Scoped review completed without further placement findings.
