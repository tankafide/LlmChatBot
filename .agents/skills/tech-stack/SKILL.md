---
name: tech-stack
description: Apply, explain, or revise AutoAssist's project tech stack and development tooling only when the user explicitly invokes the tech-stack skill. Do not activate for ordinary coding or dependency questions without an explicit skill request.
---

# AutoAssist tech stack

Use this skill only when explicitly requested by name, `$tech-stack`, or selection through the skill picker. It is scoped to this repository.

Use the [shared baseline](../../../docs/stack-baseline.md) as the single source of truth for the preferred project stack, lifecycle, deferred tools, testing priorities, and research sources. This explicit-only skill governs explaining and revising those decisions.

## Apply the baseline

- Match the user's requested action: explain a decision, review a proposed dependency, revise the stack, or implement a specified slice. Invocation alone is not a request to scaffold the entire app or install every listed package.
- Preserve Python/FastAPI on the server and TypeScript in the browser. Treat the other listed tools as the preferred small-project baseline, subject to explicit user changes. The LLM provider remains unselected.
- Inspect existing dependency manifests and code before making implementation recommendations. Explain meaningful divergence from the baseline; avoid speculative replacements or extra infrastructure.
- Keep the required HTTP API, relational inventory search, persistent conversations, and both NHTSA integrations ahead of UI polish. Respect the repository's assignment timebox and use the preserved inventory at `docs/context/inventory/data.csv` for the real import path.
- When scaffolding is requested, verify compatible runtime/package versions, commit lockfiles, and provide concrete setup and verification commands. Use the baseline's focused static checks and behavioral tests; add optional tools only for a demonstrated need.
- For new or changed technology recommendations, consult current official documentation. Do not repeat the entire research exercise merely to explain the saved baseline.
- Record meaningful accepted stack changes in the shared baseline and update affected code, configuration, tests, and README within the requested scope. Report notable changes and validation briefly.

If invoked without a specific task, summarize the baseline and pending choices concisely; do not change application files.

## Shared decisions

Read [docs/stack-baseline.md](../../../docs/stack-baseline.md) when applying, explaining, or revising the stack. Update that reference for accepted changes; keep this skill explicit-only. Ordinary orchestrators and specialists may read the reference without invoking this skill.
