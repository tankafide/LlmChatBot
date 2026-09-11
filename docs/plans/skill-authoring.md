# Project skill authoring

Status: complete. All 14 skills were researched and authored by separate subagents, then integrated and independently evaluated. Application implementation remains out of scope. Native model-turn matching remains unverified for the tooling reason below.

## Outcome and steps

1. Give each proposed skill its own research/authoring subagent, in batches limited by available concurrency. Read the agreed proposal and current project decisions; consult current primary documentation for the domain. Done when each skill has focused instructions, invocation metadata, and traceable research.
2. Integrate the skills against the proposal. Preserve AGENTS.md and tech-stack ownership, explicit-only specialists, and thin implicit orchestrators. Resolve shared-baseline access without silently changing tech-stack invocation. Done when cross-links and routing agree and no application scaffolding is introduced.
3. Run skill-creator validation, inspect reference resolution and invocation metadata, and exercise representative routing/behavior scenarios. Check actual Codex discovery where available; distinguish static validation from live invocation evidence. Fix observed defects and record remaining verification limits.

## Shared authoring brief

Each agent owns only its assigned `.agents/skills/<name>/` directory. Do not edit shared plans, README, AGENTS.md, tech-stack, or another skill. Do not log delegated instructions as new user prompts. Read the complete proposal at `docs/plans/project-skills.md` and the supplied attachment if they differ. Read `C:/Users/shane/.codex/skills/.system/skill-creator/SKILL.md` and its `references/openai_yaml.md`. Read `docs/stack-baseline.md` for authoritative shared facts and lifecycle decisions. Its extraction is user-approved. Preserve tech-stack as the explicit-only workflow for explaining/revising decisions; do not automatically load its body or duplicate the lifecycle table.

Research current official primary sources with web tools, open the relevant pages, and distill domain-specific agent failure modes into decision rules and observable evidence. Put a short dated source/rationale record in the skill's `references/research.md`, linked as optional background. Distinguish project decisions from upstream advice. No copied manuals or generic tutorials. Use concise SKILL.md and only necessary supporting references. Create `agents/openai.yaml` with `policy.allow_implicit_invocation: true` for plan/develop/review and false for the 11 specialists. No automatic subagent fanout in authored skills.

Validate using skill-creator's quick_validate.py if Python is available. Report files, sources, validation, and unresolved contradictions. Keep instructions useful across planning/development/review and proportional to a focused prototype. At authoring time application code/tests did not yet exist, so this plan prohibited inventing executable commands, a selected provider, imported inventory, or completed checks; current implementation facts now live in the active plan and README.

## Accepted clarification

The user approved extracting shared stack facts and the lifecycle into `docs/stack-baseline.md`. All skills may read that reference directly. Preserve tech-stack explicit-only invocation; do not duplicate the lifecycle table.

## Validation results — 2026-09-10

- Skill-creator validation passes for all 14 new skills and the updated tech-stack skill. All relative Markdown links resolve. Metadata enables implicit invocation only for plan/develop/review.
- A fresh local Codex app-server `skills/list` scan discovers all 15 repository skills with no project loading errors. Discovery does not establish natural-language matching or policy enforcement during a model turn.
- An isolated CLI natural-language test could not start: the installed CLI reports that the configured model requires a newer Codex version. No CLI upgrade or model override was made. Independent in-session agents checked scoped behavior in temporary fixtures instead.

The independent agents completed these checks in isolated temporary workspaces, without implementing the real application:

| Check | Observed outcome |
| --- | --- |
| CSS-only planning task | Selected plan, frontend, and frontend-verification bodies only; produced finishable narrow-screen steps and verification; original HTML/CSS unchanged. |
| CSS-only development task | Selected develop, frontend, and frontend-verification only; changed the width rule and completed scoped review. Headless Edge at 320px/1280px verified no horizontal overflow with long text, preserved 720px desktop content width, reachable controls, keyboard focus, and no console/page errors. A narrow-screen screenshot was visually inspected. |
| Review-only source fixture | Selected review and affected backend/frontend specialists; identified eight evidenced defects: recall failure disguised as empty, new retry IDs, unlimited provider retries, blocking ORM calls, unbounded/N+1 query shape, HTTP error handling, stale conversation updates, and duplicate sends. Application sources unchanged. No runnable backend fixture environment was supplied; runtime backend checks were correctly reported as gaps. |
| Inventory import planning | Kept the real attachment as the specific import dependency while completing independent transaction/validation decisions; did not fabricate inventory. |
| Async/query and scaling scenarios | Required complete DB offload and bounded/batched query evidence; required evidence for startup recovery and worker coordination. |
| Backend/frontend reuse scenarios | Reused matching transport semantics while keeping admitted-send cancellation distinct from history reads, and fuzzy search distinct from exact safety matching. Kept transaction and model serialization outside HTTP handlers. |
| Direct Docker specialist use | Worked without an orchestrator or implicit tech-stack load; identified destructive normal shutdown and Compose-only browser DNS in the supplied proposal. No destructive command executed. |

One wording ambiguity was found and fixed: backend architecture now explicitly allows a user-authorized architecture/capacity change without requiring the user to name `tech-stack`, while preserving explicit-only skill invocation and keeping planning-only proposals in plans. Independent recheck confirmed the distinction.

These checks establish selected-body behavior in independent agents, not native automatic matching or exhaustive skill reliability. Discovery and metadata checks are separate evidence. Real application, provider, database, and container behavior still require the implementation-slice tests described by the skills. Each skill's linked research notes contain the current primary sources and project-specific rationale.
