# Step 3 implementation review fixes

Created: 2026-09-10 (America/Chicago).
Status: complete; fixes and isolated verification passed.

Scope: trace the implemented safety transport, matching, grounded tools, presentation
replay, and existing atomic completion against the accepted step-three plan.

- Preserve explicit scoped stock references while NHTSA choices are pending. Pending
  variant ordinals must not resolve against an older inventory list. Use the same
  reference decision in tools and final selection validation; verify actual tool calls.
- Do not choose the first ID when displayed descriptions repeat. Require an ID, and
  distinguish an explicitly labeled ID from an ambiguous bare number. Verify discovery
  and detail call counts for both accepted and rejected choices.
- Run focused regressions, the full isolated backend suite, Ruff, and strict mypy.
  Record results and any remaining external verification limits here.
- Classify decoder recursion exhaustion from bounded but deeply nested upstream JSON
  as invalid-response unavailability, preserving the other branch and closing responses.

## Fixed findings

- Safety tools previously treated arbitrary whole-message descriptors as permission to
  replace an explicit stock reference with the prior selected vehicle. Rejected NHTSA
  ordinals could also fall through to an older inventory list. Tools and safety selection
  validation now use the same resolver, preserving stock priority and distinguishing
  explicit inventory references from pending variant ordinals. Tests include unknown stock,
  another model/stock, an explicit inventory ordinal, and rejected variant choices.
- Exact descriptions previously returned the first matching displayed ID. Duplicate
  descriptions now remain ambiguous with no detail GET; a subsequent explicit ID resolves
  the choice. Labeled small IDs also work when the same bare number would be ambiguous
  between an ID and a list position.
- JSON decoder recursion exhaustion previously escaped the transport boundary and failed
  the entire turn. It now becomes branch-level invalid-response unavailability. The
  regression retains the successful recall result and asserts both responses are closed.

## Verification

- Baseline: 132 local tests passed.
- Full local suite after the initial fixes: 141 passed in 42.64 seconds; the final expanded
  reference regression file passed all seven cases independently.
- Final Docker Compose verification: 142 passed in 29.54 seconds, plus Ruff lint/format
  and strict mypy (37 application files). Docker readiness, image rebuild, and quiet
  Compose configuration validation succeeded. The first verification stopped on formatting;
  formatting was corrected before the successful rerun.
- Local Ruff lint/format and strict mypy passed; tracked diff whitespace checks passed.
- Existing HTTP/restart and abrupt-process recovery tests ran in the full suite. Test
  databases and fake external services were isolated from development storage.
- README and architecture describe the clarified reference behavior. No schema, dependency,
  or lifecycle change was needed. Live NHTSA/Grok and the separate container-recreation
  acceptance script were not rerun for these fixes; the previously recorded live Grok
  upstream failure remains an external verification gap.
