---
name: autoassist-review
description: Review an AutoAssist diff, implementation, or specified code scope for actionable defects and verification gaps. Use for code-review requests; fixes require the request to include them.
---

# AutoAssist review

Produce an evidence-based review of the requested scope, proportionate to this focused prototype. Follow repository AGENTS.md, accepted plans, and actual contracts. Read existing manifests, implementation, tests, and the relevant section of docs/architecture.md when present; documentation describes intended behavior, while execution and code establish what exists.

Read the relevant parts of the authoritative [shared stack baseline](../../../docs/stack-baseline.md), including its session and request lifecycle contracts when affected. [Tech-stack](../tech-stack/SKILL.md) remains the explicit-only stack decision workflow; do not implicitly read its body. Do not invent lifecycle semantics or duplicate the baseline's lifecycle table.

## Select evidence and guidance

Establish the requested diff/base or code scope from the request and repository state. Preserve unrelated working changes. Read changed code and the relevant callers, dependencies, and tests beyond diff context. Separate introduced defects from pre-existing issues outside scope. If a revision is ambiguous, inspect local branches and status first; ask only if the intended comparison still cannot be resolved.

Load only the applicable specialist bodies below as supporting guidance. Load affected verification guidance early, before choosing checks. Selection does not create subagents or recursively invoke another orchestrator. Specialists remain explicitly invocable; their disabled implicit policy prevents independent automatic activation.

| Specialist and path | Purpose and selection trigger |
| --- | --- |
| [backend-architecture](../autoassist-backend-architecture/SKILL.md) | Backend services, repositories, or agent behavior added/extended, or structural quality in scope; inspect responsibility placement as well as declared boundary, dependency, transaction or state changes. |
| [frontend-architecture](../autoassist-frontend-architecture/SKILL.md) | Components, hooks, adapters, reuse or browser state ownership changed. |
| [docker](../autoassist-docker/SKILL.md) | Images, Compose, mounts, networking, runtime configuration or container check execution changed. |
| [backend](../autoassist-backend/SKILL.md) | HTTP handling, validation, services, dependency setup or errors changed. |
| [persistence](../autoassist-persistence/SKILL.md) | Queries, database sessions, atomic writes, stored context or recovery changed. |
| [chat-agent](../autoassist-chat-agent/SKILL.md) | Model/tools, grounded answers, follow-ups, budgets or replay changed. |
| [nhtsa](../autoassist-nhtsa/SKILL.md) | Recall/crash-rating retrieval, matching or unavailable/partial data changed. |
| [api-contract](../autoassist-api-contract/SKILL.md) | Public schemas, status semantics, OpenAPI or generated types changed. |
| [ui-style](../autoassist-ui-style/SKILL.md) | Visual design, CSS, typography, spacing, component appearance, or visible state treatments changed. |
| [frontend](../autoassist-frontend/SKILL.md) | Browser interactions, rendering, accessibility, transport or visible request state changed. |
| [backend-verification](../autoassist-backend-verification/SKILL.md) | Any backend behavior or backend check evidence in scope. |
| [frontend-verification](../autoassist-frontend-verification/SKILL.md) | UI behavior/checks, or API type drift once the frontend exists. |

Use both architecture skills for responsibility changes crossing the API boundary, plus api-contract for schema consequences. A local CSS fix needs frontend, ui-style, and frontend-verification, not persistence; a repository boundary change needs backend-architecture without frontend-architecture. Running existing container checks alone need not load docker.

## Review behavior across boundaries

Trace the affected path from its entry point through services, persistence and integrations to its returned or rendered result. Assess correctness, simplicity, design, readability, performance and scalability using actual workload assumptions and consequences. Search existing reusable behavior before suggesting another service/helper; distinguish same-looking code with different semantics. Do not demand unrelated refactors, generic frameworks, style preferences or hypothetical infrastructure.

For affected async paths, follow reachable blocking I/O and substantial CPU operations; verify execution boundaries, cancellation and resource ownership. For data access, inspect filters/order/limits, serialization-triggered lazy queries, N+1 growth and unbounded history/results. Check concurrency/deadline/retry budgets and evidence for stated capacity. Lint and typing do not establish event-loop responsiveness, bounded queries or scalability. Do not presume single-worker SQLite can scale horizontally or prescribe extra workers without coordination/storage analysis.

For each affected write path, identify durable state, atomic unit, commit point, failure outcome and recovery action. Check constraints, rollback, acknowledgment after commit, ambiguous commits, safe retries, cleanup, storage readiness and nondestructive repeatable startup recovery. Review durable request replay and preserved selected-vehicle context against available accepted contracts. Check backend durability beyond the LLM path; limit the suite to affected behavior. Validate the real import against `docs/context/inventory/data.csv`; invented data is not a substitute.

Check vehicle and safety assertions against retrieved records. Unavailable recalls or ratings must remain distinguishable from verified empty results. Inspect provider/tool failure behavior and diagnostic evidence without logging secrets or unnecessary conversation content.

## Verify and report

Discover runnable commands from repository configuration; run focused applicable checks in isolated test data. Inspect behavioral assertions, not merely green status: would they catch the reported failure? Use deterministic synchronization/fakes for races and external failures, real temporary SQLite for transactional evidence, and process/container restart evidence where crash recovery is claimed. An application-object recreation alone does not prove crash recovery. Do not fabricate executable commands or completed tests when scaffolding is absent.

For visible UI behavior, use available browser tools to exercise the affected scenario and inspect supported console/network evidence. Do routine exploratory review yourself. If tooling or access is absent, try an appropriate alternative and state the exact remaining gap; do not default to asking the user to perform manual QA. Keep optional live external checks separate from deterministic local evidence.

Finish after scoped code tracing and feasible focused verification. Lead with actionable findings ordered by impact. Each finding states a verified file/line, concrete trigger, consequence, evidence and smallest adequate fix direction. Mark uncertainty as uncertainty; a coverage gap alone is not proof of a defect. Deduplicate shared root causes. Separate optional suggestions from defects and state tested scope, observed outcomes and remaining verification gaps. If none were found, say so without implying exhaustive correctness. Apply fixes only when the request includes them; then verify the correction and distinguish fixed issues from unresolved findings.

Optional background: [research and rationale](references/research.md).
