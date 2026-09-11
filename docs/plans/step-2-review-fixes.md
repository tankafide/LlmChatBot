# Step 2 review fixes

Confirmed by code tracing and isolated admission probes: admission cancellation/uncertain
commit can strand an active request; selection accepts arbitrary evidence; presentation
context is restored before byte trimming; input accounting runs only once.

Implement in scope:
- Drain owned admission/completion work before cancellation settlement. Reconcile uncertain
  admission by its internal identity without rerunning writes or touching another caller's turn.
- Validate explicit stock/list references and selected-context details; clarify unresolved choices.
- Use one whole-turn suffix for replay and presentation metadata.
- Guard every model request, including schemas and accumulated repair/tool messages.

Verify with deterministic provider fakes, gated worker threads, temporary SQLite, boundary
tests, existing backend tests and static checks. No schema change or development-data reset.
Document conservative reference syntax and byte-accounting boundary. Status: complete.

Verification: 21 focused regression cases pass, covering repeated cancellation during admission
and completion, duplicate ownership, uncertain admission commit, byte-trimmed presentations,
stock/list/selected references, scripted ordinal repair, exact request-size boundary and accumulated
tool/repair messages. Docker Compose verification passes all 72 tests plus Ruff lint/format and
strict mypy. Local focused tests and static checks also pass. Existing abrupt-process recovery
and assignment-import tests remain green. No live Grok call or development-volume change was made.

Scoped review: owned writes drain before permit release; duplicate classification never settles
another caller's turn; presentation and replay share count/byte rules; each non-streaming request
passes through the budget wrapper. Public API and database schema are unchanged. Reference
resolution intentionally supports stock/list forms and existing-selection follow-ups rather than
claiming general natural-language disambiguation.
