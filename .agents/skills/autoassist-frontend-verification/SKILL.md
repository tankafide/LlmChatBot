---
name: autoassist-frontend-verification
description: Design, implement, or review AutoAssist frontend behavioral checks, browser evidence, static checks, and generated API-type drift verification when selected by an orchestrator or explicitly requested.
---

# AutoAssist frontend verification

Read [AGENTS.md](../../../AGENTS.md) and the [shared baseline](../../../docs/stack-baseline.md), especially its chat lifecycle, before choosing affected checks. Domain guidance supplies behavior; this skill owns test structure and evidence. Application code and test commands may not exist yet: inspect package scripts, configuration, and the shared verification entry point before naming runnable commands.

## Match the requested phase

- Planning: state each affected scenario, controlled inputs, observable outcome, and verification boundary. Identify a check to implement when no command exists. A plan does not authorize UI scaffolding.
- Development: add or update focused checks and run them; perform browser exploration and scoped diff review. Fix failures within the authorized slice.
- Review: compare changed behavior with existing evidence and report concrete defects or coverage gaps. Do not apply unsolicited fixes or confuse an unexecuted check with a passing one.

## Keep coverage small and separated

Separate focused adapter/interaction cases from a small Playwright smoke suite once the UI exists and the timebox permits. No component/unit runner is selected: inspect existing tooling and justify a runner only if focused behavioral coverage warrants it. Do not add multiple frameworks to test one conversion helper.

Use deterministic API responses for UI-specific states and inspect outgoing requests where transport identity matters. Keep selected end-to-end flows on the real local backend with fake LLM/NHTSA integrations and isolated test data. A mocked browser response proves rendering and adapter behavior, not database persistence or provider-call counts; coordinate those assertions with [backend verification](../autoassist-backend-verification/SKILL.md).

Prefer accessible role/name or label locators, visible messages, enabled/disabled controls, and semantic outcomes. Await observable transitions using retrying assertions; avoid arbitrary sleeps, CSS-class assertions, private hook state, or snapshots that only copy implementation. Isolate browser storage and conversations per test so order and retries do not hide shared state.

## Choose affected chat scenarios

Use the baseline lifecycle as the outcome oracle; do not invent alternate retry semantics.

- Submit a message and display its actual reply; while pending, show progress and prevent duplicate submission. For rejection, distinguish a draft/unaccepted message from admitted history.
- Lose a response after submission, then retry: capture that the adapter preserves the original request ID and payload, reconciles the returned outcome, and renders one user message and one actual reply. A deliberate new attempt after a terminal failure uses a new ID. Keep retries bounded; transport loss does not prove server cancellation.
- Exercise busy/in-progress and terminal error responses separately. Show understandable failure/interruption state without synthesizing an assistant reply or silently resubmitting a terminal request.
- Reload history from the backend and reconcile any optimistic entries without duplicates. Include completed, failed, and interrupted requests; verify ordering and actual assistant replies. Verify a late history/submission response cannot replace a newly selected conversation when switching is supported.
- Check implemented actions only. Edit, regenerate, and cancel controls must be absent or unavailable until backend semantics exist. Verify safety-data unavailability remains visibly distinct from a verified empty result when that UI is affected.

For restart claims, use a real backend restart with retained isolated storage and browser reload; mocked history and frontend remounts alone cannot prove durability.

## Browser evidence belongs to the agent

For appearance changes, use [UI style](../autoassist-ui-style/SKILL.md) to select the intended component/state treatment and token pairings. Verify rendered contrast, focus and control boundaries, reflow, and consistency with the reference; do not require pixel identity across platform fonts or use screenshots alone to prove accessibility.

Discover available browser tools, launch through the repository's actual run path, and exercise the changed flow. Inspect relevant console/network errors when supported. Check narrow and wide layouts, long message/error content, scrolling, and composer reachability when layout changes; avoid asserting incidental pixel values.

Exercise keyboard-only submission and focus movement, visible focus, control names, and exposed busy/error status. Automated accessibility scans can supplement these checks if tooling exists; they do not establish full accessibility or screen-reader behavior. Record what was actually exercised. If browser access fails, investigate an available alternative and report the remaining gap instead of assigning routine QA to the user.

## Shared verification and evidence

Include TypeScript strict checking, ESLint typed rules, Prettier check mode, and generated API-type drift in the existing cross-platform Docker/Compose verification entry point. The one CI workflow runs that same entry point; do not create separate frontend automation. Playwright transpilation and a Vite build are not substitutes for TypeScript checking, including test files where configured.

With [API contract guidance](../autoassist-api-contract/SKILL.md), export current local FastAPI OpenAPI without live external calls and check the committed generated types using the pinned generator/options. Use supported drift checking or deterministic temporary regeneration/comparison; stale types must fail verification rather than be silently rewritten. Compile the adapter against the generated contract. Generated types do not validate runtime JSON; error and unexpected-response behavior still needs observable checks.

Report exact executed checks, outcomes, fake/live boundaries, and material gaps. Preserve nonzero failures through the shared entry point. Fix causes rather than weakening rules, deleting behavioral assertions, or accepting retries as evidence of reliability. Keep optional live-service checks separate from deterministic CI.

For source rationale or tooling changes, consult [research](references/research.md).
