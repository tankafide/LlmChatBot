# Step 3 plan readiness review

Reviewed: 2026-09-10 (America/Chicago).
Scope: supplied Step 3 plan, compared with the matching repository plan and current source. Review only; no application implementation or plan rewrite.

Original verdict: close, but resolve the clarification and durable-context contracts before integration. The basic transport, independent branch outcomes, grounding, and reuse of the existing completion transaction are sound.

Resolution: all four findings below are addressed in the revised [Step 3 plan](step-3-nhtsa-safety.md). The plan now defines application-owned current-message choice resolution, durable keep/set/clear presentation actions, one safety answer supporting combined evidence and ambiguity, and the observed partial Step 2 foundation. Added acceptance cases cover descriptor narrowing, confirmation, invalidation, trimming, and combined replies across restart. Implementation and Step 2 verification remain pending; the findings below preserve the original review record.

## Findings

1. **P1 — Descriptor clarification has no defined input path.** Step 3 lines 101–109 promise clarification for unknown qualifiers and filtering when discovery has more than five variants, but the tool accepts only inventory ID and variant ID. The model cannot reference an undisplayed sixth candidate, and the plan does not specify how an explicit user descriptor reaches the matcher. Define a bounded descriptor/choice input and its validation against the current user message, or have application-owned resolution read that message explicitly. Distinguish user confirmation of a missing attribute from an impermissible override of a known conflicting inventory attribute. Test six candidates, a descriptor identifying a previously undisplayed candidate, restart, and an unknown suffix; prove the conversation can reach a valid detail lookup without trusting an invented ID.

2. **P1 — Persisted choice invalidation needs durable semantics.** Lines 103–104 require invalidation on selection changes but store only nullable presentation metadata in successful turns. Looking backward for the latest matching presentation can resurrect choices after A → B → A, or after a list clears selection and A is selected again. Specify an explicit keep/set/clear presentation action or an equivalent durable invalidation boundary in replay units. Restore by applying those semantics in order, with safe behavior after history trimming. Test both sequences across restart. No new table is required.

3. **P2 — Combined success plus clarification needs one explicit answer shape.** Lines 113–119 introduce separate `safety` and `clarify_safety_variant` intents while requiring useful recall results to survive crash ambiguity. State whether `safety` accepts an ambiguous crash result and renders its choices alongside recalls, or whether clarification can also reference recall evidence. The renderer must persist exactly the choices it displays. Add a combined-request → recall success plus crash ambiguity → restart → variant selection acceptance case. Existing partial-failure tests alone do not settle the output contract.

4. **P2 — Foundation observations are stale.** Lines 18–21 say there are no conversation tables or chat runner and describe `conversations/service.py` as proposed. Current source already has conversation persistence, a service with admission/completion/replay handling, and `chat/contracts.py` with `ChatRunner`, `ChatRunRequest`, and `ChatRunResult`. Refresh the observed/proposed split and attach safety integration to these actual boundaries. This does not establish that all Step 2 prerequisites have passed; retain that verification prerequisite.

## Scope and verification

This is a large specification for a 2–3 hour assignment. Keep the existing A/B vertical slices, reuse Step 2 recovery tests, and avoid making optional category expansion or performance experiments prerequisites to demonstrating the required recalls and four summary ratings. This is a scope recommendation, not a separate correctness finding.

Inspected the supplied plan, repository Step 3/Step 2 plans, shared baseline, inventory/module layout, dependency manifest, chat contracts, and conversation persistence/service code. Used AutoAssist planning, NHTSA, architecture, and backend verification guidance. No application tests were run for this document-only review. A read-only request to the official RAV4 recall endpoint confirmed the example envelope; browser retrieval of the crash-detail example failed, so no renewed crash-payload validation is claimed.

The subsequent plan revision resolves findings 1–4 at the specification level. Verify Step 2 before integrating Step 3; planned tests are not executed evidence.
