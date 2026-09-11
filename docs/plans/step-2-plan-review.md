# Step 2 plan review

Reviewed: 2026-09-10 (America/Chicago).
Scope: pasted Step 2 plan, compared with the repository plan, shared baseline, representative foundation code, manifests, and selected planning guidance. No application changes or test execution.

Original verdict: close, but clarify the three contracts below before implementing phase B. Phase A has enough detail to begin. Preserve the accepted durability lifecycle.

Resolved in the implementation plan on 2026-09-10 following user authorization: successful turns persist the application-rendered presentation order; typed field references are rendered from retrieved values with fixed conversational templates; successful replay units are capped at the same 64 KiB as retained history. Added restart, adversarial-value, and byte-boundary acceptance cases. Findings below remain as review history, not open blockers. Application implementation and verification remain pending.

## Findings

1. **Displayed candidate order is not an authoritative contract** (plan lines 76–77). Tool retrieval order can differ from the order/subset in the public reply. If tools return A,B,C and the reply lists C,A, “the second one” means A. Run-local retrieval order and generic referenced IDs do not establish that mapping after restart. Define ordered presented vehicle IDs, persist them atomically with the successful turn, and make reply presentation agree with that order. Restore this evidence for follow-ups; clarify when unavailable. Test reordered/subset results and multiple searches in one turn, including after restart.

2. **Structured fact validation has no defined facts to validate** (lines 77–78, 118). The proposed answer has text, IDs, and a selection action, but acceptance requires rejection of unsupported structured facts. A valid vehicle ID can accompany an invented price. Define a small claim representation for supported inventory fields and its validation/rendering relationship to the public reply, or explicitly narrow deterministic guarantees to identity/selection and make textual factual accuracy an evaluation criterion. Do not assert deterministic price/specification rejection from ID validation alone. Test a valid ID paired with a wrong price and a null field presented as known.

3. **Successful turns can be too large to replay even as the newest turn** (lines 80, 90). A successful turn may occupy 256 KiB but model history allows only 64 KiB of whole turns. A newest 80 KiB turn must therefore be omitted entirely. The generic omission notice does not state whether this immediate loss of search context is intended. Prefer a successful-turn cap that fits the history budget, or explicitly accept immediate omission and retain the minimal presented-candidate/selection context separately. Test a newest turn over 64 KiB followed by an ordinal reference after restart.

## Scope and sequencing

The plan is substantially larger than a small implementation slice. Its durability requirements mostly come from the already accepted baseline, so silently deleting them would conflict with project decisions. Keep A–D as separately finishable milestones and describe the schedule accordingly. Phase A can start after these brief clarifications are recorded; no broad redesign is needed.

The provider import experiment is useful but does not prove every listed run guard. Make a focused pinned-version scripted exchange an early B check for structured output, per-request input accounting, timeout and retry configuration, and failed-tool attempt counting. Current Pydantic AI provider/history documentation was opened during review; no live provider or Linux compatibility pass is claimed.

Sources: [reviewed plan](step-2-conversational-inventory.md), [shared baseline](../stack-baseline.md), [Pydantic AI xAI](https://pydantic.dev/docs/ai/models/xai/), [message history](https://pydantic.dev/docs/ai/core-concepts/message-history/).
