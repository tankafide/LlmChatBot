---
name: autoassist-frontend-architecture
description: Define or assess AutoAssist frontend module boundaries, semantic reuse, hooks, state ownership, and backend adapter responsibilities during planning, implementation, or review. Use for structural frontend changes; ordinary local styling fixes need no architecture exercise.
---

# Frontend architecture

Read [the shared baseline](../../../docs/stack-baseline.md) for accepted stack and chat lifecycle. Follow the requested phase: planning produces decisions and acceptance criteria; authorized development implements them; review reports evidence without unsolicited fixes. This specialist adds no implementation authorization or agent fanout.

## Inspect before choosing structure

Search existing components, hooks, transport functions, adapters, types, and their callers before adding equivalents. Trace one representative affected interaction from user action through the API response to rendering. Read actual manifests and implementation; no frontend exists merely because the baseline describes one.

Reuse a helper when meaning, validation, errors, and lifecycle match. Similar syntax is insufficient: history-loading cancellation and an admitted message submission have different consequences. Extract cohesive behavior when real callers share semantics and a reason to change; keep feature-specific behavior local. Avoid generic lifecycle hooks, miscellaneous utility buckets, speculative layers, and refactoring outside the requested behavior. An authorized replacement updates affected callers/tests and removes its obsolete path.

## Assign one owner at each boundary

| Responsibility | Placement and evidence |
| --- | --- |
| Public request/response shape | Generated OpenAPI types consumed by transport. Derive aliases from generated types; do not copy API interfaces or manually edit generation output. UI-only view models may differ when an explicit mapping gives them a purpose. |
| HTTP mechanics | Existing fetch boundary owns URL construction, serialization, status/error interpretation, and transport signals. Keep it independent of JSX and assistant-ui message formats; expose enough structured error information for lifecycle decisions. Make transport replaceable in tests. |
| Chat runtime integration | Custom assistant-ui adapter owns conversion between API data and runtime messages/actions. Verify installed runtime interfaces before coding. LocalRuntime is the baseline; use ExternalStoreRuntime only when application-owned frontend state simplifies the actual implementation. Do not add a second message store merely to support it. |
| UI interaction and rendering | Components and focused hooks own draft input, selection of displayed conversation, and pending/error presentation. Submission runs from its action handler/runtime callback, not an Effect observing the draft. |
| Durable history and vehicle context | Backend remains authoritative. Browser state projects persisted outcomes, including failed/interrupted messages. Runtime convenience features do not authorize edit, regenerate, or cancel controls without implemented backend semantics. |

Name the minimal owner of each state value. Derive filtered messages, labels, and flags where possible instead of synchronizing copies through Effects. Hooks share logic, not a single state instance: two hook calls must not independently own one conversation's submission state. Lift ownership to the nearest suitable existing owner and pass values/actions where needed; do not introduce global state by default.

Keep request identity and retry decisions in one cohesive submission path, following the baseline rather than creating new semantics. Reconcile optimistic display with persisted results without duplicate messages. History loads and late responses must remain associated with their originating conversation; ignore stale results or clean up requests when views change. Browser abort does not establish server cancellation.

## Record decisions and verify boundaries

For structural work, record placement, reuse candidates, state/dependency implications, and observable checks. During implementation maintain the frontend and shared API-boundary sections in `docs/architecture.md` (relative to repository root). Create this short document with the first implemented slice, adding frontend details when implemented; do not create a speculative architecture map during skill authoring. Once present, consult its `Frontend` and `Shared API boundary` sections and keep representative paths current. Keep significant tradeoffs in README and pending work in plans.

Read [API contract guidance](../autoassist-api-contract/SKILL.md) when public schemas/generated types change, and [backend architecture](../autoassist-backend-architecture/SKILL.md) when responsibility crosses the API boundary. A frontend-only hook extraction does not need backend architecture. Use [frontend verification](../autoassist-frontend-verification/SKILL.md) for test design/evidence and [frontend implementation](../autoassist-frontend/SKILL.md) for UI coding details.

Verify affected behavior, not file layout: shared callers retain intended semantics; derived state stays consistent; switching conversations cannot display a stale response; retry/reconciliation does not duplicate messages; transport uses generated contract types. Discover existing checks and report actual outcomes or concrete coverage gaps. A small local fix needs only proportionate inspection and validation.

Read [research rationale](references/research.md) when revisiting these choices or checking upstream behavior.
