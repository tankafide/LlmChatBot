# Localhost frontend plan review

Reviewed: 2026-09-10 (America/Chicago).
Scope: supplied localhost chat frontend plan and current API/lifecycle code. Review only; no application implementation or plan rewrite.

Verdict: sound architecture and scope, with two recovery contracts to clarify before phase B implementation.

## Findings

1. **P2 — Explicitly refresh mutable request status (B.2, B.4–6).** History pagination advances by immutable message sequence, but request_status/error_code on an already loaded user message can change. A provider failure or interruption adds no assistant message. Incremental reads after the last loaded sequence therefore cannot discover that transition, and deduplication must not discard updates to existing IDs. Specify upsert semantics, terminal state precedence over stale in-progress reads, and reconciliation that re-reads the unresolved user message (for example from its sequence minus one) or applies the authoritative same-ID terminal response. Test an in-progress user becoming failed/interrupted without any new sequence and a late in-progress read arriving after completion.

2. **P2 — Resolve missing-conversation recovery versus the New chat lock (B.2, B.6).** B.2 offers New chat for a missing conversation, while B.6 disables it whenever a pending outcome is unresolved. A saved pending request whose conversation returns 404 after development database recreation could leave no usable recovery action. Specify that a definitive missing-conversation response permits explicitly clearing that obsolete local pointer/pending record and starting fresh, preserving the text as an editable draft. Do not automatically post it into a new conversation. Test pointer plus pending record followed by 404 and successful explicit new-chat recovery.

## Assessment

The backend-owned transcript, same-ID transport retry, deliberately new IDs for terminal retries, proxy networking, generated API types, and isolated restart smoke are appropriate. ExternalStoreRuntime supports application-owned messages and capability-based callbacks according to its current official documentation: https://www.assistant-ui.com/docs/runtimes/custom/external-store . No backend endpoint/schema redesign is indicated.

Phase A can proceed; clarify the two recovery contracts before phase B. The complete browser matrix and restart harness are substantial optional follow-on work for the original take-home timebox. Keep required API verification ahead of UI polish.

Evidence: inspected the supplied plan, repository frontend plan, stack baseline, frontend guidance, API schemas/routes, application factory, conversation service/repository, Compose, and step-four verification plan; checked the linked assistant-ui, Vite, and openapi-typescript documentation. No dependency installation, build, browser run, or behavioral tests were performed. Compatibility remains an implementation check.

Resolution: both findings are addressed in frontend-local-chat.md, phase B, including regression acceptance cases. This resolves the planning gaps; application implementation and execution of those checks remain pending.
