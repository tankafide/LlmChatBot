# Live-model evaluation baseline

Measured 2026-09-11 with the configured OpenAI `gpt-5.6-luna` model, one repetition,
the real inventory CSV in isolated storage, and controlled NHTSA HTTP fixtures.

Strict automatic result: **13/22 turns (59.1%)**.
Median latency: **5.82s**; p95: **11.44s**.
Model requests: **64**; provider attempts: **64**.

| Category | Strict passes / turns |
| --- | --- |
| clarification | 0 / 3 |
| filters | 7 / 7 |
| follow_up | 2 / 4 |
| safety | 3 / 5 |
| unsupported | 1 / 3 |

Strict pass means every labeled automatic check passed. It is not an estimate of overall
customer satisfaction or factual accuracy. All seven inventory-filter cases passed. All four
stock/follow-up resolution checks passed, although two follow-ups made unnecessary stock
lookups and therefore failed strict tool choice. Four turns failed model-output validation.
The remaining strict failures include unnecessary searches and an unexpected intent.

Human semantic review remains pending. Deterministic rendering constrains factual output,
but phrase checks do not prove absence of every unsupported implication. The small development
suite is not a held-out benchmark; repeated runs and additional labels are needed before
making production reliability claims. These results identify concrete prompt/tool-policy work
without changing the labels to fit the model.

| Failed case / turn | Observed automatic failure |
| --- | --- |
| stock-details / 2 | tool_choice |
| selected-transmission / 2 | tool_choice |
| ambiguous-pronoun / 1 | tool_choice |
| ambiguous-safety / 1 | ChatProviderError |
| missing-stock / 1 | ChatProviderError |
| finance-guarantee / 1 | tool_choice |
| prompt-injection / 1 | tool_choice, intent |
| recalls-empty / 1 | ChatProviderError |
| safety-both / 1 | ChatProviderError |

Reproduce with the commands in [the evaluation guide](README.md). The complete local report
is `evaluation-results/final-report.json`; reports are ignored by Git.

Input provenance:

- Suite SHA-256: `f1aea97db21b4724c89e61e29cef68e5acbc188cecb7209b0730a9946c82518f`
- Inventory SHA-256: `121d2fe11f03cac4f00d75ba9d2db418765f52c7bb810c81251fb8996f65fe4e`
- Instructions SHA-256: `28fe0f2f614f74bccf0bc9eebee4e1dfb92bf8244a1d16de32baa310005af228`
