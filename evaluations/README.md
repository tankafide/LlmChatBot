# Model evaluation

The [original baseline](baseline.md) records the initial live failures.
The [model interface results](interface-results.md) record the fixes, repeated runs, and final retest.

The suite labels 20 customer conversations (22 turns): varied inventory filters,
selected-vehicle follow-ups, ambiguity, unsupported requests, and safety uncertainty.
The harness uses the production agent, all 127 source inventory rows in a temporary
SQLite database, and controlled NHTSA HTTP responses. It never uses development storage.

From the repository root:

```powershell
uv run --project backend autoassist-evaluate
uv run --env-file .env --project backend autoassist-evaluate --live --connection primary-openai
uv run --env-file .env --project backend autoassist-evaluate --live --repeats 3
uv run --env-file .env --project backend autoassist-evaluate --live --case ambiguous-pronoun
```

Without `--live`, only labels are validated. Live execution incurs provider usage and
keeps the agent's six-model-request/60-second turn budget. The JSON report defaults to
`evaluation-results/report.json`; override with `--output`. Exit code 1 indicates an
automatic failure, with the report still saved. Reports are ignored by Git and Docker.

The report includes provider/model, hashes of the suite, inventory and instructions,
per-turn inputs/replies, proposed tools and arguments, structured answers, category pass
rates, latency p50/p95, model-call counts, an interface source fingerprint, and bounded application
validation feedback. Strict pass still requires every labeled check. Functional pass separately
requires successful execution and all checks except tool choice; it is not a human factuality score. No exact prose match is required. Filter
checks reject missing or invented constraints. Tool choice is strict: unnecessary searches
or re-fetches can fail it even when the final answer is correct. Tool counts measure proposed
calls; model counts measure agent model requests, including requests that fail. The separate
`provider_attempts` counter also includes Gemini integration retries.

Automatic checks do not establish full semantic correctness. Review each turn's rubric
and record human scores separately: unsupported claims fail if any factual implication lacks
inventory/safety support; clarification quality passes if the reply asks for the missing
information and offers a usable next step. Null means unreviewed, never passed. Empty recall
results must not imply VIN applicability, repair completion, or a safety guarantee.

This development suite is small and not held out. Repeat runs to assess variability;
NHTSA fixtures measure interpretation, not upstream availability. Existing deterministic
tests separately prove persistence and API orchestration. The harness's own tests use a
FunctionModel and run inside the shared verifier without billed model requests.
