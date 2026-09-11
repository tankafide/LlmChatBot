---
name: autoassist-backend-architecture
description: Design or assess AutoAssist backend responsibility, dependency, transaction, execution, and state ownership. Use when adding or extending backend services, repositories, or agent behavior, and for structural reviews; keep checks scoped to affected code.
---

# Backend architecture

Apply this guidance within the requested planning, development, or review scope. Read AGENTS.md, the affected plan, and the [shared baseline](../../../docs/stack-baseline.md) for current technology choices and lifecycle contracts. Consult [architecture.md](../../../docs/architecture.md) and actual code for the current implementation. Keep technology choices and file maps in those documents; this skill defines principles that survive changes to them. Do not implicitly invoke `tech-stack`.

## Place behavior by responsibility

Before extending a component, identify what the new behavior owns, what would cause it to change, and why the proposed owner is appropriate. Inspect the affected component and its immediate collaborators, not only the insertion point. Proximity to a caller or an existing large class is not sufficient justification.

- Group behavior that enforces the same rules and changes for the same reasons. Separate responsibilities that evolve independently, such as transport mapping, business policy, workflow coordination, persistence mechanics, and external-service adaptation.
- Keep orchestration focused on sequencing collaborators and handling outcomes. Delegate substantive querying, transformation, and business decisions to their appropriate owners. A short workflow can remain together when an extraction would add no meaningful boundary.
- Keep business rules usable without an HTTP request, database session, or provider SDK when those dependencies are not intrinsic to the rule. Translate external representations and errors at their boundaries.
- Give each invariant and mutable state a clear authoritative owner. Other entry points should invoke that owner rather than implement competing versions of the rule. Validate that data is relevant and authorized for the operation, not merely well-formed or available somewhere in memory.

## Make dependencies and contracts explicit

Construct and inject dependencies at an application boundary. Avoid hidden globals, import-time I/O, shared live sessions, and dependencies acquired implicitly from unrelated components.

Keep dependency direction understandable: application policy should not need transport-specific types or knowledge of provider internals. Define inputs, outputs, errors, side effects, and resource ownership at meaningful boundaries. Do not expose lazy or resource-bound values beyond the lifetime of their owner.

Introduce an interface when it protects a real boundary or supports a real alternative, not merely because every class could have one. Avoid cycles, access to another component's private internals, and long chains of forwarding methods that add no policy or isolation.

## Detect structural drift as code grows

Look for components accumulating unrelated reasons to change, workflows absorbing low-level implementation details, repeated rules diverging across callers, and helpers that require increasing knowledge of their caller's internal state. Length, nesting, and dependency count are prompts to inspect cohesion, not automatic failures or fixed limits.

Extract a cohesive responsibility with an explicit contract when doing so reduces coupling or makes ownership clearer. Moving a mixed component to another file does not resolve its design. Avoid splitting every method into a class or requiring the same number of layers for every feature.

Share code when meaning, validation, failure behavior, and reasons to change match. Similar syntax alone does not justify a shared abstraction. Keep distinct policies separate when unifying them would introduce flags, exceptions, or weaker semantics.

## Preserve execution and failure ownership

For affected state changes, identify the atomic operation, commit point, failure outcome, and recovery owner. Keep transaction ownership explicit; subordinate persistence operations must not independently commit fragments of the same atomic change. A durable-success response must follow a confirmed commit.

Account for blocking work, concurrency, cancellation, and resource lifetime across the complete operation. Do not hold scarce resources while waiting on unrelated external work. Cancellation of an await does not necessarily stop underlying work. Bound externally driven work and retries, and preserve the project's documented reconciliation and recovery contracts.

During extraction, preserve observable behavior and atomicity unless the task explicitly changes them. Update callers and fault-injection points to the real new owner; do not retain obsolete wrappers just to satisfy old tests. Choose scaling or caching changes from demonstrated needs and ownership implications, rather than adding infrastructure speculatively.

## Verify the structure as well as behavior

Before completing affected work, trace a representative request through the final collaborators. Check that responsibilities have clear owners, dependencies follow those boundaries, rules are not duplicated, and transaction/resource lifetimes remain explicit. Passing lint, typing, and tests does not establish good architecture.

Use [backend verification](../autoassist-backend-verification/SKILL.md) for behavioral evidence appropriate to the change. Test observable contracts and failure outcomes rather than filenames, line counts, or method layout. Structural extraction affecting persistence or concurrency requires evidence that the corresponding commit, replay, cancellation, and recovery behavior still holds.

During development, correct drift introduced by the change and update affected architecture documentation. During planning, record placement decisions and meaningful tradeoffs. During review, report concrete concerns and the smallest adequate correction; review alone does not authorize edits. Keep unrelated concerns separate rather than expanding the task.

Consult [persistence](../autoassist-persistence/SKILL.md), [backend](../autoassist-backend/SKILL.md), or [API contract](../autoassist-api-contract/SKILL.md) guidance when their boundaries are affected. Use [frontend architecture](../autoassist-frontend-architecture/SKILL.md) only when browser responsibilities also change. These links select guidance, not agents or approval gates. Read [research notes](references/research.md) only when revisiting underlying rationale.
