# Step 1 review fixes

Created: 2026-09-10 (America/Chicago).
Status: complete.

Scope: confirm and fix the three reviewed readiness, SQLite error classification, and
normalized connection-name defects. Preserve the existing API envelopes and database schema.

1. Add regression tests using isolated file-backed SQLite and temporary configuration files.
   Confirm that an exclusive lock incorrectly passes health, schema defects become 503,
   and whitespace-normalized duplicate connection names overwrite configuration.
2. Make health read a bounded application-table query. Share a narrow SQLite error-code
   classifier between health and inventory services; expected availability failures remain
   sanitized 503, while unexpected errors propagate for server diagnostics.
3. Reject connection-name collisions before Pydantic normalizes dictionary keys. Invalid
   configuration must fail before startup writes; valid trimmed names remain supported.
4. Run regression tests and the shared Docker verifier, inspect the scoped changes, and
   update README with the confirmed behavior and validation results.

Validation: before fixes, the new regression module produced six failures and four passes,
confirming all three reported defects across the affected endpoints. After fixes,
`docker compose --profile verify run --rm verify` passed Ruff lint/format, strict mypy for
17 source files, and all 39 tests, including ten regression cases. SQLite tests use isolated
temporary files and verify lock recovery, schema-error propagation, and unchanged stored
dealerships after rejected configuration. Reviewed affected source and documentation; no
schema changes or development database recreation were required. The existing third-party
Starlette/AnyIO deprecation warning remains.
