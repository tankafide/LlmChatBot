# Model interface reliability results

Measured 2026-09-11 using the same configured OpenAI `gpt-5.6-luna` model,
unchanged 20-conversation / 22-turn labels, all 127 inventory rows in isolated storage,
and controlled NHTSA HTTP fixtures. No provider/model upgrade or retry-budget increase.
The [original baseline](baseline.md) remains unchanged.

| Measurement | Original baseline | Interface fix, three repetitions | Final wording, full suite |
| --- | --- | --- | --- |
| Strict automatic passes | 13/22 (59.1%) | 65/66 (98.5%) | 22/22 (100%) |
| Model-output failures | 4/22 | 0/66 | 0/22 |
| Functional automatic passes | Not separately reported | 66/66 | 22/22 |
| Median latency | 5.82s | 3.66s | 4.18s |
| p95 latency | 11.44s | 8.40s | 6.32s |
| Model calls per 22-turn suite | 64 | 45, 46, 45 | 45 |

The first three repetitions passed 22/22, 21/22 and 22/22. The one strict failure
was an unnecessary `lookup_recalls` call on “How much is it?” without a selected
vehicle. The public reply correctly requested a vehicle; there was no safety evidence
or NHTSA request. The final prompt/tool descriptions make clear that safety tools are
not an inventory-clarification mechanism. After that refinement, the complete suite
passed 22/22 and five additional repetitions of the ambiguous-pronoun case passed 5/5,
with exactly one model request and zero tool calls each. No validation repairs occurred
in these live reports. All three stages are retained; the failed observation is not discarded.

## What changed

- Model-visible instructions, schema descriptions and tool results explain tool prerequisites,
  intent meanings, and stopping conditions. A missing stock asks for clarification; no_match
  means an empty filtered search. Safety clarification is distinct from safety evidence.
- Selection is application policy derived from validated evidence and the existing conservative
  reference resolver. The model cannot write keep/set/clear state. Existing atomic completion
  still persists selection, reply and replay together.
- Selected/list vehicle evidence is freshly read and included in the current prompt. Follow-ups
  reuse that evidence without another stock lookup, even if facts changed since the last turn.
- Strict evaluation scoring is unchanged. Functional scoring separately excludes tool-choice
  efficiency, and local reports retain bounded validation feedback and interface fingerprints.

See [the implementation/research plan](../docs/plans/model-interface-reliability.md) for
primary sources, acceptance criteria and verification evidence.

## Interpretation and limits

The same model performed substantially better with a clearer interface. This supports
fixing the integration before changing models; it does not isolate the contribution of
prompt text, schema descriptions and application-owned selection individually.

These are development cases, not a held-out benchmark or a production reliability estimate.
Latency varies with provider load. Functional automatic scoring is not a human factuality
score. Human rubric scores remain unset. Agent inspection found correctly grounded filter/
follow-up replies and appropriate safety uncertainty in the sampled output; clarification
and unsupported replies remain generic deterministic templates. Lists can be verbose and
field selection varies between runs. Broader natural-language and usability evaluation remain
useful, and occasional unnecessary calls are still possible despite the passing final retest.
NHTSA fixtures establish interpretation, not live service availability.

## Reproduction and provenance

```powershell
uv run --env-file .env --project backend autoassist-evaluate --live --repeats 3 --output evaluation-results/interface-report.json
uv run --env-file .env --project backend autoassist-evaluate --live --output evaluation-results/interface-final-report.json
uv run --env-file .env --project backend autoassist-evaluate --live --case ambiguous-pronoun --repeats 5 --output evaluation-results/interface-clarification-report.json
```

Current code reproduces the final interface; the initial three-repetition report predates
its small safety-tool wording refinement. Reports are local ignored artifacts.

- Suite SHA-256: `f1aea97db21b4724c89e61e29cef68e5acbc188cecb7209b0730a9946c82518f`
- Inventory SHA-256: `121d2fe11f03cac4f00d75ba9d2db418765f52c7bb810c81251fb8996f65fe4e`
- Initial instructions SHA-256: `9a357d6aab2ac18ae89b49f0746ee037a6364ebee40e2be30fa10f3de5443ed9`
- Initial interface SHA-256: `3f7ab585d00fd860f9895167146f3edef3ad8b60a0c3baef170c81b513c2ae2f`
- Final instructions SHA-256: `c30ce8ad7f8a3744cffa9ddd2d1d2aed2350ec30205e281677a2088b5cff9b9b`
- Final interface SHA-256: `41f2e7cc20ed9801eb7f9faa00fcc22a348c632ff308050aa36c1ca2ae9d57ce`
