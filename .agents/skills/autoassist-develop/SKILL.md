---
name: autoassist-develop
description: Implement or fix an authorized AutoAssist feature, refactor, or configuration slice, selecting affected project specialists and completing tests, documentation, and scoped diff review. Use for development requests, not planning-only or review-only requests.
---

# AutoAssist development

Deliver the requested working slice with evidence that its completion criteria pass. Keep this orchestrator thin: select the supporting specialists below and invoke each selected specialist in a separate agent session. Do not recursively invoke another orchestrator.

## Establish the slice

Read the applicable `AGENTS.md`, current request, relevant accepted plan in `docs/plans/`, and affected code/configuration. Inspect working-tree changes so user work remains intact. Discover actual commands in manifests, scripts, and CI; do not invent commands or claim nonexistent scaffolding works. If the request only asks for a plan or review, produce that output without application edits.

Project-wide requirements remain in `AGENTS.md`. Read the relevant sections of the authoritative [shared stack baseline](../../../docs/stack-baseline.md) for accepted stack and lifecycle decisions, checking actual code/manifests and accepted plans for implementation facts. [tech-stack](../tech-stack/SKILL.md) remains an **explicit-only decision workflow**; do not load its body through this orchestrator unless the user explicitly invokes it. Reuse the shared lifecycle rather than inventing competing semantics or copying its table here.

Keep a short, current implementation plan in `docs/plans/`, proportionate to the change. For each meaningful step identify the concrete behavior and affected modules/contracts, dependencies, approach, success/failure outcome, and verification. Follow existing exit criteria and revise the plan when implementation evidence changes them. Resolve locally discoverable commands and routine reversible choices yourself. Use `docs/context/inventory/data.csv` for the real import path; clearly labeled synthetic test fixtures may test queries but cannot stand in for that attachment.

## Delegate applicable specialists

Select only specialists whose triggers apply. For each selection, start a dedicated specialist session that is instructed to read its own linked `SKILL.md` and the references that skill requires. Do not load specialist bodies into the orchestrator context.

Give every specialist the user goal, authorized scope, relevant accepted-plan paths, the affected files or contracts, observed repository facts, and a concrete assignment. Ask it to return decisions, risks, affected paths, and acceptance or verification evidence relevant to its specialty. Give verification specialists their assignment before implementation is designed. Do not preload a conclusion that the specialist should independently assess.

Run independent specialist sessions concurrently when their work does not depend on another report. The orchestrator remains responsible for resolving conflicts, preserving the user’s scope, integrating the reports, and completing the implementation. A specialist may make a bounded, non-overlapping change only when the assignment clearly grants it ownership; otherwise it reports its guidance for the orchestrator to apply. Keep specialist sessions focused: do not dispatch every specialist by default or use a specialist to invoke another orchestrator.

| Specialist and path | Purpose and selection trigger |
| --- | --- |
| [Backend architecture](../autoassist-backend-architecture/SKILL.md) | Adding or extending backend services, repositories, or agent behavior; module, dependency, transaction, execution, or state ownership changes. Check affected responsibility placement even when no refactor was initially planned. |
| [Frontend architecture](../autoassist-frontend-architecture/SKILL.md) | Component/hook/adapter boundaries, shared behavior or frontend state ownership changes; initial UI structure. |
| [Docker](../autoassist-docker/SKILL.md) | Scaffolding or changes to images, Compose, mounts, networking, runtime configuration, or container check execution. Existing check execution alone does not trigger it. |
| [Backend](../autoassist-backend/SKILL.md) | HTTP handling, schemas/settings, application services, dependencies, async execution, and expected errors. |
| [Persistence](../autoassist-persistence/SKILL.md) | SQL queries, schema, transactions, stored history/context, admission, recovery, or database recreation. |
| [Chat agent](../autoassist-chat-agent/SKILL.md) | Tools, provider orchestration, grounded replies, follow-up context, replay, and run budgets. |
| [NHTSA](../autoassist-nhtsa/SKILL.md) | Recall/crash-rating retrieval, vehicle matching, unavailable or partial results, and integration errors. |
| [API contract](../autoassist-api-contract/SKILL.md) | Public request/response/status changes, OpenAPI, generated types, and adapter compatibility. |
| [UI style](../autoassist-ui-style/SKILL.md) | Visual design, CSS, typography, spacing, component appearance, or visible state treatments. Transport-only and backend-only changes do not trigger it. |
| [Frontend](../autoassist-frontend/SKILL.md) | UI interactions, rendering, assistant-ui adapter, history, accessibility, and responsive CSS. |
| [Backend verification](../autoassist-backend-verification/SKILL.md) | Affected backend behavior, integration/storage checks, and backend static verification. |
| [Frontend verification](../autoassist-frontend-verification/SKILL.md) | Affected UI/adapter behavior and browser checks; API changes also need generated-type drift checks once frontend exists. |

A frontend hook extraction delegates frontend architecture and applicable frontend/verification guidance, not database guidance. A repository boundary change delegates backend architecture, persistence, and backend verification. Changing conversation ownership across the API boundary delegates both architecture skills and API contract. Persistent follow-ups delegate chat-agent, persistence, backend, and backend verification; add other skills only for changed boundaries. A local CSS fix delegates frontend, UI style, and frontend verification and stays local.

## Implement and verify

- Search representative implementations and callers before introducing helpers. Reuse matching semantics; keep materially different validation/failure behavior separate. Keep HTTP, application, persistence, provider, and UI adaptation responsibilities readable. Update affected callers/tests/docs together for authorized replacements, without unrelated refactoring or speculative abstractions.
- For each new blocking I/O or substantial CPU operation reachable from async code, choose and verify its execution boundary. Inspect SQL and serialization for N+1 behavior and unbounded loading. Bound context, result sizes, concurrency, retries, and total run duration where affected; route the mechanics to their owners above.
- For affected writes, implement the planned atomic unit, commit point, integrity constraints, failure response, and recovery action. Check cancellation/resource cleanup and restart preservation across the backend, not just provider calls. Preserve the accepted lifecycle; unavailable safety data must not become an empty successful result.
- Run focused behavioral checks and relevant static checks, fix failures, and inspect the final diff against completion criteria. Include resource/query evidence for affected hot paths; lint/type success does not prove responsiveness, durability, or scalability. Use deterministic external fakes and real temporary persistence where required; keep optional live checks separate.
- Perform agent-owned exploratory/browser checks when UI behavior is affected: discover available browser tools, exercise the scenario, inspect supported console/network evidence, and verify relevant responsive/accessibility behavior. Use another available verification path if tooling is unavailable and state the remaining gap. Do not substitute a routine user-run QA request for checks you can perform.
- Update README for changed commands, configuration, API examples, design tradeoffs, and omissions. Architecture specialists maintain the relevant sections of `docs/architecture.md` when implementation exists. Keep shared verification in the existing common entry point/CI workflow rather than adding parallel systems.

## Completion

Finish each step only after its focused behavior checks and scoped diff review. Continue through authorized remaining work without artificial phase approvals. For a genuine external dependency, name the exact affected step and missing input after investigating available paths; complete independent work first.

Report notable behavior changes, verification actually run and observed outcomes, and material remaining limits. Distinguish implemented, verified, and pending work; do not report unrun checks as passed. Assess simplicity, design/readability, performance, capacity bounds, and recovery only to the extent affected by this slice.

Optional authoring rationale and dated primary sources: [research](references/research.md).
