# Critical readiness and error-boundary fixes

2026-09-11, America/Chicago. User authorized tests first, repairs, and related review.

1. Reproduce stale-schema startup/health, lost uniqueness indexes, and local tool
   failures mislabeled as provider failures in isolated tests; record failing results.
2. Validate existing schemas before startup/import writes; retain explicit database
   recreation (no migrations). Keep provider conversion at the model boundary and
   settle local tool failures durably with correct error categories. Test replay and
   continuation, not just exception text. Review startup cleanup on partial failure.
3. Verify import/setup separately from health. Back up the outdated development
   database before replacing it, import the assignment CSV, and check the actual
   inventory-backed localhost flow. Never run pytest against development storage.
4. Run focused checks then shared Docker verification/browser tests; document
   red/green evidence, related findings, remaining limits, and retained backup.

Red evidence: seven original regression cases ran before repairs: six failed
(stale columns, missing concurrency index, health blind spot, and three local-tool
error classifications), one genuine-provider case passed. A separate partial-startup
cleanup test then failed before its fix. First focused green run: 29 passed covering
new regressions plus inventory import and existing schema/error regressions.

Related review found partial-startup provider clients were not closed; fixed with
owned cleanup. Added an operator setup check and extended real-backend browser
acceptance to reject empty inventory before import and pass after importing the CSV.

A ninth regression reproduced corrupt persisted model history being classified as
502 provider_error even with zero provider calls. Changed it to internal_error;
all nine targeted regressions now pass. Local application errors are logged by
request ID and exception type without raw SQL, prompt text, or credentials.

Development recovery: stopped both services, retained `/data/autoassist.db` under
`/data/backups/20260911T112912Z/autoassist.db` in the existing
`llmchatbot_autoassist-data` volume (no files/volumes deleted). Imported the actual
CSV: inserted=127, updated=0, unchanged=0. Restarted healthy backend/frontend;
`python scripts/check-setup.py` passed against the actual running backend.
Old conversation pointers require explicit New chat because this is a fresh database;
the previous conversations remain in the retained backup.

First shared Docker run passed: 154 backend tests, 25 Playwright tests, Ruff/format,
strict mypy/TypeScript, ESLint/Prettier, build and fresh OpenAPI drift checks. Final
rerun adds the persisted-history regression. Source schema/API shapes are unchanged.

Live integration evidence: the first disposable Gemini/NHTSA smoke returned a
grounded inventory list (200), then a genuine provider ModelHTTPError/ServerError
on selection (502). A separate fresh smoke completed all four turns with HTTP 200:
inventory search, AA-1001 selection, actual NHTSA recalls/crash ratings, and price
follow-up ($26,335). This is a successful live flow, not a claim that provider
availability is guaranteed. Both runs used temporary databases, not development
storage; scripts returned nonzero on the failed run and zero on the successful run.

Review scope: startup/readiness, stale table/index shapes, inventory setup,
provider versus application/storage failures, terminal settlement/replay/claim
release, partial startup resource ownership, and corrupt persisted replay. This is
focused hardening, not exhaustive certification of the repository. Existing shared
tests additionally cover concurrency, interruption, grounding, pagination and browser
recovery. No migrations, automatic inventory reseeding, or silent provider fallback
were added. Empty inventory remains a valid server state but fails demo setup checks.

Final verification: the shared Compose verifier, using the final backend source and
tests mounted read-only, passed **155 backend tests and 25 Playwright tests**, plus
Ruff lint/format, mypy, TypeScript, ESLint, Prettier, build, and OpenAPI drift.
No retries were configured to hide test failures. The final application image was
rebuilt/restarted and the operator setup check passed again.

The stopped database backup was also copied out of Docker to
`data/backups/autoassist-before-readiness-20260911T112912Z.db` (Git-ignored), SHA-256
`71944a39d37e02c00f3a3983be77abeb1c320822b3637f13b893748ff1b32a9c`.
