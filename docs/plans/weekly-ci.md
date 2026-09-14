# Push-triggered GitHub verification

- Run the complete shared verifier on every push, retaining the 20-minute job
  timeout. Pull requests do not trigger a separate run.
- Fix observed runner timing failures: position restored history only after the
  runtime renders its last stored message; await retry completion before asserting
  that no assistant message exists. Preserve the existing behavioral assertions.
- Verify focused browser scenarios repeatedly, run frontend checks, review the
  scoped diff, push the changes, and confirm the push-triggered GitHub verifier.
- Acceptance: a successful push-triggered GitHub run. If verification still fails,
  inspect its actual failure before deciding whether further repair is small enough
  for this slice.
