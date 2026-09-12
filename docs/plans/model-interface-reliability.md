# Model interface reliability

Fix the observed tool-policy and output-contract failures without changing the configured
model, external API, storage schema, or turn budgets. Preserve the existing evaluation labels.

1. Describe intent meanings, tool prerequisites and stopping conditions in the model-visible
   schema, instructions and tool results. A missing exact stock asks for clarification;
   `no_match` means an empty filtered search. Safety clarification is not safety evidence.
2. Remove model-authored selection state. Derive selection from validated answers and the
   existing conservative reference resolver; persist through the existing atomic completion.
   Supply refreshed current vehicle evidence in the prompt so follow-ups can safely reuse it.
3. Add deterministic regressions for selection, missing stocks, ambiguous safety, evidence
   reuse and refusal of unsupported output. Keep strict evaluation scoring and additionally
   distinguish functional checks from tool efficiency. Add useful bounded repair diagnostics
   to local evaluation reports without putting model content into operational logs.
4. Run focused tests/static checks and the isolated shared verifier. Run the unchanged live
   suite with the configured model for three repetitions, record results and remaining limits,
   and update architecture/README. No development database reset or writes.

Research (2026-09-11):
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling#best-practices-for-defining-functions): explain when tools apply, expose predictable contracts, and derive known arguments/state in code.
- [Pydantic AI output](https://pydantic.dev/docs/ai/core-concepts/output/): descriptions communicate structured output meaning; validators enforce evidence and use bounded ModelRetry feedback.
- [Pydantic AI tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/): function docstrings and parameter descriptions form the model-visible interface.

Acceptance: deterministic grounding and restart tests pass; no model selection field remains;
unchanged labels expose residual failures honestly. A live score is evidence, not a reason to
relax grounding checks or increase retry budgets. Review final code and execution boundaries.

## Completion evidence

- Implemented model-visible tool/intent contracts, refreshed prompt evidence, application-owned
  selection, and actionable missing-stock/safety repair feedback. No external API, database schema,
  provider configuration, or retry-budget changes. Existing working-tree improvements were preserved.
- Focused contract/evaluation tests pass. `python scripts/verify.py` passes 227 backend tests
  (including isolated PostgreSQL and process recovery), 31 Playwright tests, Ruff, format, mypy,
  frontend type/lint/format, generated API drift checks, and the production frontend build.
- Same-model live comparison: 65/66 strict and 66/66 functional checks over three full runs,
  with zero model-output failures. An unnecessary recall lookup on a non-safety ambiguous question
  led to one final tool-description/prompt clarification. Final full run: 22/22 strict; five more
  repetitions of that question: 5/5 strict with no tools. Labels stayed unchanged.
- [Results and provenance](../../evaluations/interface-results.md) retain both the initial residual
  failure and the final retest, latency/call metrics, research links, and limits. Human rubric scores
  remain unset; these development cases do not establish production reliability or polished prose.
- Final review traced answer validation, selection staging, safety presentation invalidation,
  atomic completion, and restored follow-ups. SQL/session ownership and bounded execution remain
  unchanged; shared evidence serialization is reused rather than copied. No further scoped defects
  found. Development database and running development services were left untouched.
