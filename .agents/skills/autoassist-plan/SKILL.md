---
name: autoassist-plan
description: Plan AutoAssist features, fixes, or refactors as small finishable vertical slices with concrete acceptance and recovery criteria. Use for planning or design requests; planning alone does not authorize application implementation.
---

# AutoAssist planning

Always save every plan produced by this skill, including high-level product plans, implementation sub-plans, and meaningful revisions, as a Markdown file in the repository's `docs/plans/` directory before returning. Create the directory when absent, use a descriptive filename, and update the relevant existing plan for revisions rather than creating competing copies. Return a link to the saved plan; a chat-only plan does not complete this workflow.

Match the requested level of detail. For a high-level roadmap, use large logical chunks with outcomes, dependencies, and acceptance criteria; defer module-level steps and exact technical contracts to linked implementation sub-plans. The detailed step requirements below apply when writing those implementation sub-plans. Keep the required HTTP chatbot slice ahead of polish.

## Establish scope and evidence

Read applicable `AGENTS.md`, the requested scope, accepted relevant plans, and existing code/manifests/check entry points. Inspect representative implementations and callers before proposing new components. Distinguish current code from proposed paths and checks; do not describe planned tooling as runnable.

Project requirements remain in `AGENTS.md`. Read the relevant sections of the authoritative [shared stack baseline](../../../docs/stack-baseline.md), especially session ownership and the lifecycle for affected database/chat work; do not copy its lifecycle table into the plan. [tech-stack](../tech-stack/SKILL.md) remains an explicit-only stack decision workflow: do not load its body automatically. Inspect existing manifests, code, and accepted plans alongside the baseline to distinguish implemented facts from accepted future choices.

Resolve correctness-critical uncertainties now through repository searches, tool discovery, current primary documentation where needed, and focused feasibility experiments. Keep experiments isolated and within planning scope; do not implement the application feature. Choose routine reversible details using existing project decisions. Unknown local commands require inspection, not a request for the user to run tests. For genuinely unavailable inputs, identify the affected step, ask one precise question, and continue independent planning. The assignment inventory is preserved at `docs/context/inventory/data.csv`; synthetic test fixtures are not a substitute for that real import path.

## Delegate relevant guidance

Select only the specialists that affect the proposed slice. For each selection, start a dedicated specialist session that reads its own linked `SKILL.md` and any references that skill requires. Do not load specialist bodies into the planning orchestrator context.

Give the specialist the planning request, the planning-only authorization boundary, relevant accepted-plan and code paths, observed facts, unresolved decisions, and a concrete question. Ask for design constraints, affected ownership/contracts, failure and recovery cases, and acceptance or verification criteria. Dispatch relevant verification specialists early enough for their reports to shape the plan. Do not tell a specialist what conclusion to reach.

Run independent specialist sessions concurrently when possible. The planning orchestrator integrates their reports, resolves conflicts using repository evidence and the user’s scope, and writes the single coherent plan. Specialists do not implement the application during planning and do not invoke another orchestrator. Do not delegate unaffected domains merely to make the plan look comprehensive.

| Specialist | Load when planning | Use its output for |
| --- | --- | --- |
| [backend-architecture](../autoassist-backend-architecture/SKILL.md) | Initial backend design or changed responsibilities, reuse, dependencies, transactions, or state owner | Module placement and dependency/state decisions |
| [frontend-architecture](../autoassist-frontend-architecture/SKILL.md) | Initial frontend design or changed component/hook/adapter responsibilities and state | UI boundaries and reuse decisions |
| [docker](../autoassist-docker/SKILL.md) | Scaffolding or image, Compose, mounts, runtime/network, or container-check changes | Reproducible execution and storage plan |
| [backend](../autoassist-backend/SKILL.md) | HTTP handling, validation, settings, application services, async/lifespan behavior | Server success/failure contracts |
| [persistence](../autoassist-persistence/SKILL.md) | Queries, transactions, inventory, history, selected vehicle, or recovery | Data invariants and atomic units |
| [chat-agent](../autoassist-chat-agent/SKILL.md) | Tools, LLM integration, follow-ups, grounding, model history, or run budgets | Conversation behavior and provider boundary |
| [nhtsa](../autoassist-nhtsa/SKILL.md) | Recalls, crash ratings, matching, or safety failures | Safety result distinctions and external cases |
| [api-contract](../autoassist-api-contract/SKILL.md) | Public schema/status changes or generated API types | Public contract and drift checks |
| [ui-style](../autoassist-ui-style/SKILL.md) | Visual design, CSS, typography, spacing, component appearance, or visible state treatments | Shared tokens, visual reference, and appearance acceptance criteria |
| [frontend](../autoassist-frontend/SKILL.md) | Browser behavior, assistant-ui adapter, styling, or accessibility | User flows and supported controls |
| [backend-verification](../autoassist-backend-verification/SKILL.md) | Any affected server behavior, storage, integration, or runtime path | Behavioral, failure, and static acceptance checks |
| [frontend-verification](../autoassist-frontend-verification/SKILL.md) | Any affected UI behavior; API schema changes once frontend exists | Browser/adapter checks and generated-type drift |

Delegate both architecture skills only when responsibilities cross the API boundary; a local fix needs no broad redesign. A frontend hook extraction delegates frontend architecture and verification, not database guidance. Persistent vehicle follow-ups delegate backend, persistence, chat-agent, and backend verification; add architecture for state ownership changes and contract/frontend guidance only for affected boundaries. A CSS-only plan delegates frontend, UI style, and frontend verification.

## Write finishable steps

Lead with the observable outcome, scope, relevant existing paths, and resolved decisions with brief rationale. Prefer the smallest complete vertical slice. Each phase has its outcome, real prerequisites, ordered steps, and agent-verifiable exit criterion; a small fix can be one phase. Each step specifies:

- The concrete change, affected modules/contracts, reuse candidates, dependencies, and sufficient implementation approach to finish it.
- Expected success and failure behavior. For writes, name durable state, atomic unit and commit point, failure state/API outcome, and recovery action. Reuse accepted request semantics rather than designing competing retry rules.
- Relevant execution boundaries, query shape and limits, resource ownership, and workload assumptions. Address blocking work reachable from async code, bounded history/tool work and retry budgets, query growth, and cleanup only where affected.
- Observable verification: setup/input, action, expected result, and evidence. Name exact commands and working directories when present; otherwise specify the check to implement and its purpose. Include affected docs and tests in the step.

Evaluate simplicity, sound design, readability, performance, scalability, and backend durability against this behavior. Prefer bounded work and efficient queries within stated prototype capacity to speculative infrastructure. For a request beyond current capacity, investigate measurable limits and name the coordination/storage change needed; verify PostgreSQL coordination across workers and distinguish per-worker capacity limits from global admission control. Separate deterministic resource/query assertions from measured latency checks.

For a state-changing backend slice, include failure injection and real temporary-database checks at the relevant commit boundaries, with restart evidence appropriate to the guarantee. An application-object recreation check alone does not prove abrupt process recovery. Distinguish preserved committed data from automatic interrupted-run resumption. A read-only fix need not inherit the full durability suite.

For a browser-visible slice, assign exploratory/browser inspection to the implementing agent: specify flow, expected visible outcome, and relevant console/network or responsive/accessibility observations. Discover available browser tools; use deterministic external fakes for local flows where appropriate and state that boundary. If browser access is unavailable, specify an available alternative and the remaining gap. Do not substitute routine human QA or live-provider access for repeatable API/database checks.

## Complete the plan

Walk every step as the future implementer: can it finish without guessing a critical contract, unavailable command, or unnamed dependency? Resolve avoidable gaps, remove unrelated refactors and artificial approval phases, and ensure phase exits cover the intended behavior and failure recovery. Record any exact external input still required only against the affected step.

Save meaningful changes in the plan and distinguish observed feasibility evidence from future implementation checks. Return the plan path, key decisions, and any real dependency. Planning-only work ends with the plan; if the user also authorized implementation, continue that authorized work using the development workflow without inventing an approval gate.

For maintenance rationale and source provenance, optionally read [research notes](references/research.md).
