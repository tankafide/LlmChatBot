---
name: autoassist-nhtsa
description: Plan, implement, or review AutoAssist NHTSA recalls and crash ratings, vehicle matching, safety-result semantics, and HTTPX integration failures.
---

# AutoAssist NHTSA

Use as explicit specialist guidance or when selected by a project orchestrator. Preserve the requested phase: planning defines behavior and checks; development implements the authorized slice; review reports concrete defects without unsolicited fixes. Read [AGENTS.md](../../../AGENTS.md) and the [shared baseline](../../../docs/stack-baseline.md). Do not load tech-stack automatically.

Keep NHTSA access in an injected ordinary service, with thin chat-tool wrappers. Inspect existing clients, result types, and callers before adding equivalents. Keep transport payloads out of public schemas; return typed application results with lookup identity, source, and retrieval time. Optional [research](references/research.md) records verified endpoints and rationale; recheck the official docs when changing concrete integration details.

## Match before claiming

- Resolve the inventory vehicle from authoritative conversation context. Normalize harmless spelling/case differences through explicit mappings; do not substitute a nearby model year or guess a trim. Missing vehicle identity produces a focused clarification, not a speculative lookup.
- Recalls use the year/make/model endpoint. Crash ratings require variant discovery followed by its NHTSA VehicleId. Match available body/drivetrain details; a sole result still must fit the inventory record. Multiple plausible variants remain ambiguous; return candidate descriptions for clarification rather than selecting the first or highest-rated result. Do not fetch every variant or every inventory result automatically.
- Keep recall and crash outcomes independent. A validated successful empty recall response means no campaigns returned for that lookup. A timeout, error, malformed payload, unresolved identity, or unsupported lookup never becomes an empty success. Crash outcomes distinguish no matching record, ambiguous variant, explicitly unrated fields, partial ratings, and unavailable service. Preserve useful results when the other endpoint fails.

## Validate and bound the boundary

- Use fixed NHTSA endpoint templates, HTTPX query parameters, and encoded path segments. Do not accept model-generated URLs. Validate HTTP status, JSON envelope, required fields, identities, and result/count consistency before claiming completeness. Recall `results` and ratings `Results` are distinct endpoint shapes; missing collections are invalid, not default empty lists. Allow unrelated upstream fields without weakening required-field checks.
- Parse star ratings as validated 1–5 values or explicit unavailable/unrated state. Never coerce `Not Rated`, null, blank, or an invalid value into zero stars. Preserve category-specific safety concerns and recall consequence/remedy or urgent flags when present; do not silently discard malformed records and claim a complete result.
- Own one pooled HTTPX AsyncClient in application lifespan, inject it, and close it. Configure connection, read, write, and pool timeouts plus connection limits. A per-operation timeout is not the entire chat deadline: apply remaining run time to discovery, detail, retry backoff, and concurrent requests. Bound lookup count, concurrent work, and response/tool-output size; mark truncation explicitly so an excerpt does not imply completeness.
- Coordinate attempts with the chat run's budget. Retry only classified transient safe GET failures with bounded backoff and remaining time; honor applicable retry guidance. Do not multiply transport, service, and tool retries or retry permanent input/schema errors. Propagate cancellation and clean up owned work. Keep database transactions closed during network waits, following the shared lifecycle.
- Log correlation ID, endpoint category, duration, attempt count, and sanitized outcome; avoid raw conversation or upstream payload logging by default. Do not introduce a cache, extra service, or fallback provider without an actual requirement and documented freshness/failure semantics.

## Ground the reply

Attribute results to NHTSA and the resolved vehicle/variant. No returned campaigns is not a guarantee of safety or proof that this VIN has no unrepaired recalls; year/make/model campaigns do not establish VIN applicability or repair completion. Preserve unavailable-data qualifications in tool results and the final answer. Do not turn crash ratings into a guarantee. For overall/frontal comparisons, require compatible class and weight within 250 pounds; otherwise report individual ratings without ranking. An unrated category supplies no star judgment.

## Evidence for the affected slice

Use injected service fakes for chat behavior and HTTPX MockTransport for actual request construction/parsing. With [backend verification](../autoassist-backend-verification/SKILL.md), cover successful records, verified empty recalls, one-service failure, malformed envelopes, incorrect identity, ambiguous body/drivetrain, unrated versus invalid stars, timeout and exhausted retry budgets. Assert lookup/call counts and preserved distinctions rather than exact prose. Include a cancellation/deadline test when changing async execution. Deterministic CI must not call NHTSA; optional live checks are separate and do not prove future availability. Report the tests actually run and record relevant failure semantics/omissions in README during implementation.
