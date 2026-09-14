# Weekly GitHub verification

- Replace push/pull-request triggers with a Monday 14:17 UTC schedule and manual
  dispatch, retaining the complete shared verifier and a 20-minute job timeout.
- Fix observed runner timing failures: position restored history only after the
  runtime renders its last stored message; await retry completion before asserting
  that no assistant message exists. Preserve the existing behavioral assertions.
- Verify focused browser scenarios repeatedly, run frontend checks, review the
  scoped diff, push the changes, and manually dispatch the full GitHub verifier.
- Acceptance: a successful manual GitHub run and only weekly/manual triggers.
  If verification still fails, inspect its actual failure before deciding whether
  further repair is small enough for this slice.
