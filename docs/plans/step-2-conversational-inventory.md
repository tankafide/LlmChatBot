# Step 2: Complete conversational inventory API with Grok

Created: 2026-09-10 (America/Chicago).
Status: implemented and deterministic acceptance verified; optional live Grok smoke pending.
Parent: [Product roadmap, step 2](product-roadmap.md#2-complete-conversational-inventory-api-with-grok).
Prerequisite: [Implemented step 1](step-1-foundation-inventory.md).

## Outcome and scope

A client creates a dealership conversation, sends text with a request ID, receives a grounded inventory reply, and asks vehicle follow-ups after restarting the server. Every admitted user message remains visible; successful replies, model/tool history, selected vehicle, and terminal request outcomes survive restart. Duplicate transport requests discover the original outcome without another model run.

Implement the required non-streaming HTTP slice. NHTSA integrations belong to step 3; the assistant must say safety lookup is not available yet when asked, without making recall or crash-rating claims. Frontend, authentication, connection administration, provider failover, automatic interrupted-run resumption, CI creation, and submission packaging remain outside this step.

The [shared baseline's session ownership and request lifecycle](../stack-baseline.md#chat-request-lifecycle) remain authoritative. This plan supplies implementation details, not a competing lifecycle. Complete the representative HTTP search/follow-up path first, then finish concurrency and recovery evidence before marking the step complete. The durability work is substantial; do not cut it silently to meet the assignment's overall 2–3 hour target.

## Existing foundation and planning evidence

- `backend/src/autoassist/app.py` owns lifespan/configuration/storage and constructs `InventoryService`. Existing synchronous routes already execute complete inventory units in worker threads.
- `inventory/service.py`, `repository.py`, and `records.py` provide dealership-scoped combined filters, stable vehicle UUIDs, materialized records, and cursor pagination. Reuse them for tools; do not query the API over HTTP or duplicate inventory SQL.
- `db/database.py` uses Python 3.13 explicit transaction mode, foreign keys, a five-second busy timeout, and `expire_on_commit=False`. `db/models.py` currently contains only dealerships and vehicles.
- `config.py` supports a mapping of named xAI connections and dealership defaults. `config/dealerships.json` currently has two named connections with placeholder models. No credential values were inspected during planning.
- Public application errors use `{ "error": { "code": "...", "message": "..." } }`; validation uses FastAPI's standard 422 response. Preserve both conventions.
- Step 1 records 29 passing tests and a verified 127-row assignment import. Those results were read, not rerun for this planning task. Reuse its temporary-file fixtures, process gates, and disposable-volume approach.
- An isolated `uv run --no-project --with ...` experiment resolved/imported `pydantic-ai-slim[xai]==2.42.0`, `xai-sdk==1.19.0`, Pydantic 2.12.5, FastAPI 0.116.1, and pydantic-settings 2.10.1. It confirmed `XaiModel`, `XaiProvider`, `UsageLimits`, history deserialization, and async SDK `close()`. No application manifest/lockfile, development database, or provider account was changed. This establishes Windows import feasibility, not Linux build compatibility or live model access.

Current [Pydantic AI xAI documentation](https://pydantic.dev/docs/ai/models/xai/) specifies the slim `xai` extra and explicit `XaiProvider` credentials. The native SDK uses gRPC and a client timeout; generic `ModelSettings.timeout` does not control this integration. Own and close an injected `xai_sdk.AsyncClient` explicitly. Do not add an OpenAI compatibility adapter or an HTTPX client merely for Grok. HTTPX remains available for API tests and the later NHTSA integration.

## Resolved contracts

### HTTP and connection selection

All conversation URLs are nested under `/dealerships/{dealership_id}`. IDs are UUIDs. A conversation belonging to another dealership returns the same 404 as an unknown one; no message, history, replay, or vehicle operation may bypass that scope.

| Operation | Input | Durable success / response |
| --- | --- | --- |
| `POST /dealerships/{dealership_id}/conversations` | Empty JSON object; reject extra fields | 201 with `id`, `dealership_id`, `created_at`, nullable `selected_vehicle_id`. Commit the conversation before returning. |
| `POST /dealerships/{dealership_id}/conversations/{conversation_id}/messages` | `request_id` UUID and `text` string, 1–4,000 characters; reject whitespace-only and extra fields | 202 with `conversation_id`, `request_id`, and `status: in_progress` after admission commit and task launch. Terminal replay returns the stored HTTP status/body. GET the scoped `requests/{request_id}` resource for durable status and terminal `outcome`. |
| `GET /dealerships/{dealership_id}/conversations/{conversation_id}/messages` | `after_sequence` nonnegative integer (default 0), `limit` 1–100 (default 50) | `conversation_id`, nullable `selected_vehicle_id`, ordered `items`, nullable `next_after_sequence`. Each item contains `id`, `sequence`, `request_id`, `role`, `text`, `created_at`, `request_status`, nullable `error_code`. |

Store UTC timestamps and expose timezone-bearing ISO 8601 strings. History uses a conversation-local increasing sequence, not timestamp ordering. Joined request state makes admitted failures/interruption visible without creating fictional assistant messages. Cursor pages reflect current committed data, not a frozen snapshot.

Preserve submitted text exactly after validation; payload equality compares exact decoded text with the canonical UUID identity. Whitespace changes are a different payload. No browser-supplied history, selection, provider, connection, credentials, or tool results are accepted. Creation uses the dealership's server-owned default; there is no connection override in this slice. Conversation creation requires a dealership-scoped creation_id; retrying a lost response returns the original conversation and pinned configuration.

Persist connection name plus provider/model identity on creation. A later dealership-default change affects new conversations only. Resolve credentials by the stored name through current server configuration; require its provider/model to match the stored identity. Credential rotation through the same environment reference is allowed. Changing/removing an existing connection must never silently reroute an old conversation: its history and stored terminal replay remain readable, but new admission returns 503 `connection_unavailable`. Use a new connection name for a different model.

Invalid configuration references still fail configuration loading. Missing credentials or an obvious placeholder model make that connection unavailable for chat, without breaking inventory/health/history. Validate the chosen connection before creation and before new message admission; do not contact the provider on health/startup or every creation. Unknown model access ultimately becomes a sanitized provider error on the live call; local validation cannot prove account entitlement. Check stored request identity/outcome before checking connection availability, capacity, or conversation busy state.

Declare the baseline's 404/409/422/502/504 outcomes in OpenAPI. Add 503 `connection_unavailable`, `server_busy`, and `storage_unavailable`. Before admission these append nothing and can be retried with the original ID. A storage error after admission returns 503 unless durable reconciliation finds a terminal outcome. If storage permits settlement, save a failed terminal 503; otherwise retain unfinished state for stale-request recovery. Unexpected internal errors must not be mislabeled as provider failures; settle a sanitized 500 `internal_error` if possible. Stored terminal status/body are replayed unchanged as JSON, without new timestamps or replay flags.

### Persistence and atomic units

Add models in `db/models.py`, application records/use cases under proposed `conversations/`, and repository helpers that accept a session without committing:

- `Conversation`: UUID, dealership FK, recorded connection identity, UTC creation time, nullable selected-vehicle FK, and next message sequence. Application lookups/selection writes enforce matching dealership; add an integration test for attempted cross-scope selection. A vehicle FK alone does not prove dealership ownership.
- `ChatRequest`: internal UUID, conversation FK, client request UUID, exact payload, status, timestamps, nullable terminal HTTP status/JSON body, nullable successful-turn replay JSON, and nullable presented-vehicle UUID list. A successful list presentation stores its ordered IDs (maximum 10); other successful replies store null. An empty list explicitly supersedes an earlier list after a no-match search. Enforce unique `(conversation_id, request_id)`, a unique partial index on `conversation_id WHERE status = 'in_progress'`, allowed-status checks, and terminal-field consistency.
- `Message`: UUID, conversation FK, owning request FK, sequence, user/assistant role, exact text, UTC timestamp. Enforce unique conversation sequence and at most one message of each role per request. Use a composite request/conversation FK or equivalent relational constraint so a message cannot attach a request from another conversation. Index history `(conversation_id, sequence)` and completed-turn lookup `(conversation_id, status, created_at, id)`.

The partial index is the durable conversation claim; do not maintain a second active-request pointer. All writes go through conversation application units:

1. **Create:** resolve dealership/default and validate local connection readiness; insert conversation and commit. Failure leaves no conversation or reports storage uncertainty without claiming success.
2. **Admit:** in one short transaction insert the request/user message and advance sequence. Establish the write claim before dependent reads (for example insert with a scoped `INSERT ... SELECT`); do not rely on a deferred read-then-write lock upgrade. Database uniqueness arbitrates races. After rollback, reread scoped durable identity/status to classify same ID, conflicting payload, or busy conversation. A bounded lock failure is 503, not a guessed conflict. Call the provider only after confirmed admission commit.
3. **Complete:** conditionally require `in_progress`, insert actual application-rendered assistant reply, advance sequence, persist this turn's entire model/tool history, ordered presented vehicle IDs, and staged selection, store the prevalidated terminal response, and mark completed in one transaction. Build/validate the response and enforce replay bytes before commit. Only the committed outcome is returned.
4. **Settle failure/cancellation:** conditionally update an active request and save sanitized terminal outcome, preserving its user message and previous selection/history. An already completed request wins. Reconcile uncertain commits by scoped request identity using a fresh session; never blindly rerun provider or writes.
5. **Startup recovery:** before readiness, atomically turn only stale active requests into interrupted terminal outcomes. Protect unexpired 120-second database-clock leases, renewed every 20 seconds; repeat scoped recovery on submission and sweep at most 100 expired requests every 30 seconds. Preserve prior completed data and user messages. Recovery is repeatable, and failure stops startup. The offline importer must not run conversation recovery.

Each unit creates/materializes/commits or rolls back/closes its session in one worker thread. Async orchestration receives typed values and session factories, never attached entities. No transaction spans a provider wait. Track outstanding thread units and await their completion under cancellation shielding before interruption settlement; cancelling an await does not stop a database write.

No migration framework or automatic reset. These tables are new, so `create_all` can add them to a step-one database without rewriting vehicles. If implementation requires altering existing constraints/schema, document explicit development recreation and real-file reimport; do not delete the user's volume as part of verification. Ordinary startup always preserves existing committed data.

### Grounded tools, follow-ups, and bounded runs

Keep the provider-specific code in proposed `integrations/chat.py` (connection/client construction, agent, exception translation, history serialization). Put typed wrappers/prompt definitions in `conversations/tools.py` or a small adjacent module. `conversations/service.py` owns admission/run/completion. Add `api/conversation_routes.py` and `api/conversation_schemas.py`; reuse the existing error envelope and inventory records. No generic provider framework or unrelated inventory refactor.

- `search_inventory`: constrained make/model/body-type and inclusive year/price ranges, cursor, limit default 5/max 10. Adapt to existing `InventoryFilters` and the same normalization/money rules. Return validated compact records with UUID/source ID, explicit nulls, and next cursor. Never report the first page as all available inventory.
- `get_vehicle`: UUID or exact stock/source ID, with a nullable identifier meaning the authoritative selected vehicle. Add only the missing scoped exact source-ID repository lookup needed for stock-number questions. UUID and source ID must be mutually exclusive. Missing selection asks for clarification; unknown/other-dealership records reveal no details.
- Run-local evidence tracks retrieved records; retrieval order is not presentation order. A search does not automatically select its first result. The internal answer chooses one ordered list of at most 10 distinct scoped vehicle IDs actually retrieved this run; the application renders that exact order with explicit numbering and stock IDs. Persist that ordered list with the reply. Multiple searches may contribute records, but only the final displayed list defines ordinal references. Do not infer it by parsing assistant prose or taking the last tool result.
- Resolve an ordinal such as “the second one” against the latest committed list presentation retained in the bounded completed history, never against retrieval order. Restore its IDs from the matching request record after restart. Ordinary detail/clarification replies do not replace that list; a no-match list replaces it with an empty list. If its turn was trimmed, the ordinal is out of range, or the user reference remains ambiguous, ask for clarification. Re-fetch the resolved vehicle in the current dealership before using its details or staging selection. An explicit stock number, an unambiguous list choice, or a question about the already selected vehicle can stage selection. A new list search clears prior selection on successful completion unless this same turn includes a separately validated explicit choice; no-match searches also clear it.
- Use a small typed internal answer with an intent (`list`, `details`, `clarify`, `no_match`, `safety_unavailable`, or `unsupported`), ordered vehicle entries, and a selection action (`keep`, `set`, `clear`; `set` requires an ID). Each entry contains a retrieved vehicle ID and requested field names from the existing `VehicleRecord` allowlist, not model-supplied factual values. Application validation requires every entry to exist in current run evidence and validates selection against the user reference and previous presentation. Application rendering supplies make/model/year/stock identity and requested price/specification values directly from these records, with consistent money formatting and explicit unknowns for nulls. Pagination wording comes from actual search evidence; only an empty search result permits `no_match`.
- Keep the public API text-only. A small renderer produces numbered listings, detail sentences, and fixed clarification/safety/unavailable wording from this internal answer; do not publish arbitrary model-authored prose or factual values in this slice. Reject extra answer fields, unsupported field names, and unsupported IDs through the bounded output-repair path. Persist the exact rendered text as the public assistant message and terminal reply. Supply rendered replies alongside the corresponding complete model turns when building future input so the model sees what the user actually saw; do not replace or split the library's tool-call/result messages. This deliberately trades stylistic freedom for auditable inventory facts without a second model judge or a generic claim-extraction system.
- Prompt the model to treat user/retrieved content as data rather than permission to change scope. Deterministic guarantees cover rendered inventory values, IDs, list order, and fixed safety wording; interpretation of user intent and relevance still require evaluation. Test valid IDs paired with attempted invented prices, null fields, unsupported fields, and adversarial scope overrides; evaluate relevant search and selection in the live smoke. Do not claim universal hallucination prevention. No native web/search tools are enabled.

Persist only the current successful run's new messages (including every tool call/result), avoiding duplication of incoming history. Serialize/deserialize at the integration boundary using the installed Pydantic AI adapter. Its [message-history API](https://pydantic.dev/docs/ai/core-concepts/message-history/) supports supplying history and retaining new run messages. Store full successful turns independently. Define each replay unit as the new library messages plus the exact public rendered reply and nullable ordered presentation IDs; use one canonical compact UTF-8 JSON serialization for byte accounting. Each successful replay unit must be at most 64 KiB. Build model input from at most the latest 10 complete successful units and a summed unit-byte budget of 64 KiB, selecting a contiguous newest suffix and dropping oldest whole units. Thus the newest successful unit always fits. Enforce the unit limit before successful completion; an oversized unit settles as 502 `provider_error`, preserving the user message and prior committed context without an assistant reply. Failed/interrupted user messages stay in public history but are excluded from model replay. Persist selected identity separately and explicitly tell the model when older context was omitted. Count replay annotations, instructions, current messages, and tool schemas/results again under the total provider-input limit using the actual input construction; serialization overhead is not exempt.

Initial prototype limits, enforced and tested rather than claimed as throughput measurements:

| Boundary | Decision |
| --- | --- |
| Active model turns | 4 process-wide; no waiting queue. Nonblocking permit before new admission; saturation returns 503 `server_busy`. Release on every exit. Database uniqueness remains the per-conversation authority. |
| Provider/run deadline | SDK client RPC timeout 30 seconds; outer model/tool phase deadline 60 seconds. Database settlement is outside that deadline and retains the existing bounded lock wait. |
| Requests/tools | At most 6 model requests, 8 successful tool calls, and 8 total tool invocations including failed ones; sequential tools initially simplify evidence/selection ownership. |
| Retries | At most 1 validation repair per tool/output, within the shared limits. No application or SDK/transport automatic request retry; disable gRPC retries through client channel options and verify the pinned SDK path does not add another loop. Provider failure settles the turn. |
| Input/output | User text 4,000 characters; tool result 16 KiB; total serialized model input 128 KiB including instructions/tool schemas/replay annotations/current tool results; per-response generation cap 2,048 tokens; public reply 8,000 characters; successful replay unit maximum 64 KiB, using the same accounting as the 64 KiB retained-history budget. |

Enforce input bytes before every provider request, including newly appended tool results. Never truncate inside tool pairs or silently clip a reply/history needed for replay. Oversized/malformed output, exhausted budget, or unrepairable tool arguments settle as 502 `provider_error`; overall/provider timeout is 504 `provider_timeout`. Pydantic AI [usage limits](https://pydantic.dev/docs/ai/core-concepts/agent/) help bound requests/tools; application guards also cover unsuccessful attempts and serialized sizes. Byte limits are deterministic resource bounds, not token estimates.

Own async clients in lifespan, one per ready named connection, with explicit credentials and no conversation-specific metadata on shared clients. Shutdown stops new admission, drains for a bounded interval, cancels remaining runs, settles after outstanding database units, then closes clients/engine. Set Uvicorn graceful shutdown to 10 seconds and Compose stop grace to 30 seconds; abrupt-stop recovery remains required when graceful cleanup cannot finish. Log IDs, duration, categorized outcome, attempt counts, and usage when available; exclude credentials and raw prompts/provider payloads.

## Ordered implementation phases

### A. Persist one complete HTTP turn with an injected agent

Prerequisite: step-one schema/session/configuration services.

1. Add the conversation/request/message models, records, repository, and transactional units above. Test constraints and real commits using temporary SQLite files before wiring a live provider. Implement startup recovery in the app lifespan and keep it separate from importer bootstrap.
2. Add creation, submission, and paged history schemas/routes, including all status/error documentation. Inject a small chat-runner boundary returning reply/history/staged selection. Use a deterministic runner for the first HTTP turn; this is a test dependency, not a production fallback.
3. Implement exact-ID replay/conflict classification, conditional completion/failure, and prevalidated terminal responses. Share stored response construction with initial return so replay cannot drift.
4. Update architecture/README with the implemented API and lifecycle examples as this phase lands.

Exit: HTTP create/submit/history succeeds against a real temporary database; a fresh app replays the same response with no extra messages or runner call. Injected failure preserves the user message and old selection. Unknown/cross-dealership/invalid submissions append nothing. Creation and terminal response never report success on injected commit failure.

### B. Connect Grok and deliver grounded inventory follow-ups

Prerequisite: A's durable HTTP path and test replacement boundary.

1. Add pinned `pydantic-ai-slim[xai]==2.42.0` and lock dependencies using uv; verify the Windows feasibility result in the Linux image. Use the inspected SDK 1.19.0 lock resolution unless compatibility verification justifies a recorded change. Do not install unused provider extras.
2. Build named connection resolution, explicit async SDK ownership/timeouts, provider error translation, and bounded agent execution. Test multiple named connections, changed defaults, credential isolation, missing configuration, and old conversation identity mismatch without contacting xAI.
3. Add typed inventory tools and exact stock lookup using existing services. Implement evidence validation, typed answer intents/field references, application text rendering, durable presentation order, staged selection, clarification, and complete-turn serialization/trimming. Exercise scripted Pydantic AI model/tool exchanges as well as the runner fake; a fake final string alone cannot prove tool wiring/history behavior. Verify the pinned-version structured output and per-request byte/attempt guards before extending the full integration.
4. Extend README configuration and API examples with search, stock-number selection, follow-up, no-match, ambiguity, and the explicit step-three safety limitation.

Exit: deterministic HTTP search → chosen vehicle → price/specification follow-up succeeds before and after restart; tool arguments and retrieved facts are correct. Unknown/null values remain unknown. Multiple candidates trigger clarification. Invalid IDs, unsupported structured facts, and forced scope overrides cannot publish another dealership's data. History round-trips tool messages without duplication and excludes failed turns. Locked image imports the provider successfully; live access is verified separately in D.

### C. Prove concurrency, bounded work, and crash recovery

Prerequisite: A/B behavior. Add focused tests under proposed `test_conversation_api.py`, `test_conversation_persistence.py`, `test_chat_agent.py`, and `test_conversation_recovery.py`; extend existing responsiveness tests where useful.

| Setup/action | Required API/state evidence |
| --- | --- |
| Event-gated provider; race same ID/same text, same ID/different text, and different IDs | Baseline 409 distinctions, one admitted user message and one provider run. A terminal retry still replays while another ID is active. |
| Two dealerships and at least two named connections | Correct configured routing; all conversation/history/tool/selection/replay paths scoped. A third named connection works without changing routing code. |
| Pause a DB unit in its worker thread; separately pause the external call | Unrelated event-loop work progresses; another conversation commits while provider waits; no session/transaction survives that wait. Results remain usable after session close. |
| Fill four turn permits, then submit a fifth; fail/cancel one | Fifth is unadmitted 503; no queue or orphan messages; permit reclaimed. Identity replay still works under saturation. |
| Inject timeout, provider rejection, malformed output, budget exhaustion | Sanitized terminal status stored, user retained, no fabricated reply/selection/history. Same-ID retry replays; a deliberate new ID can proceed. |
| Inject admission/completion mid-write and commit failures; hold competing SQLite lock | Atomic rollback and bounded 503; zero provider calls before admission commit; no partial completion. Fresh-session reconciliation handles a commit that succeeded before an exception. |
| Cancel during provider wait and while completion thread is gated | Wait for outstanding DB work before settling. Completed commit wins; otherwise stored interruption preserves user and prior selection. All resources/permits are released. |
| Lose HTTP response after completion commit; recreate app | Identical terminal body/status with zero extra messages/model calls. Repeat for terminal failure. |
| Abruptly terminate gated subprocess after admission, and after completion writes before commit | Wait for process exit, restart sole owner on same temporary file; active turn becomes interrupted, no partial assistant/history/selection, prior completed turn preserved, no automatic rerun. Repeated recovery is safe. |
| Terminate after committed completion | Restart retains completion and selected context; same-ID replay returns success without rerun. |
| Seed long histories and increasing page sizes | SQL applies cursor/order/limit; bounded/batched query count through serialization, no per-message query or full history scan in application memory. Whole-turn input limits hold without orphan tool results; full public history remains pageable. |
| Retrieve A,B,C but present C,A; also use several searches in one turn; restart and ask for “the second one” | Public numbering and durable presentation IDs are C,A; selection resolves to A and re-fetches its scoped record. Detail replies preserve the last list, no-match lists supersede it, and trimmed/out-of-range references clarify. |
| Return a valid vehicle ID with an invented price field/value, an unsupported specification name, or a null inventory value | Extra model values/invalid fields are rejected within repair limits; only repository values reach rendered facts and nulls render as unknown. Exhausted repairs commit no assistant reply or selection change. |
| Serialize replay units at 64 KiB and above 64 KiB, including rendered reply/presentation metadata; restart after the accepted boundary case | The accepted newest unit is retained whole and its ordinal follow-up works; the oversized unit becomes terminal provider_error with prior context unchanged. Multiple units trim oldest first, and provider-input accounting includes the replay annotations. |

Use synchronization events with bounded deadlock guards, not sleep-based race assumptions. Block real provider calls in deterministic tests. Install crash gates through test harnesses rather than production debug endpoints. Release/join all tasks, threads, subprocesses, and listeners in cleanup. If tools are later parallelized, add independent-session instrumentation before enabling that behavior.

Exit: all affected deterministic tests and static checks pass, including actual process termination/reopen evidence. Record query-count/resource results separately from any latency measurements; four permits do not establish production throughput.

### D. Container acceptance, live smoke, and documentation

Prerequisite: A–C; only the live smoke requires a supported account-accessible Grok model and runtime API key.

1. Update Docker dependency build and shutdown settings. Start Docker through its supported CLI and confirm engine readiness. Use the existing verification service with temporary files and fakes, never the development volume.
2. Add a disposable container acceptance harness using an explicitly separate project/volume, test configuration, and deterministic model. Import the preserved assignment CSV for `mia-motors`, create/search/select/follow up through HTTP, recreate the container retaining its volume, and continue/replay. Stop the old process fully before replacement. The implemented command is `.\scripts\verify-chat-container.ps1`.
3. Run a separate opt-in live HTTP smoke on isolated storage with runtime Grok configuration: combined-filter search, explicit stock choice, detail follow-up, restart, continued follow-up. Compare factual values with the imported record, not memorized expected prose. Record provider/model/package versions, factual observations, and any model/tool compatibility failure; never record keys. A missing key/model leaves only this live acceptance item pending, not the deterministic suite.
4. Finish README and `docs/architecture.md`: routes/examples, original-ID transport retry versus new-ID deliberate retry, visible failed messages, connection pinning, history limits, missing safety capability, PostgreSQL worker coordination, disconnect/cancellation semantics, explicit reset instructions if applicable, and the live-validation boundary. Link implementation evidence here and update roadmap status only when supported by results.

Commands already available, from repository root:

```powershell
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
uv run --project backend mypy backend/src
uv run --project backend pytest backend/tests -q
docker desktop start --detach --timeout 120
docker info
docker compose config --quiet
docker compose --profile verify run --build --rm verify
```

Use `docker compose up --build -d backend` only for the intended runtime/configuration, after accounting for any schema change. The acceptance harness must override project/volume/port/configuration to isolate its storage. Normal shutdown is `docker compose down`; cleanup may remove only the verified disposable test volume. Do not print expanded secret-bearing Compose configuration.

Exit: locked container verification and disposable-volume conversation preservation pass; live smoke passes or is explicitly recorded as the sole remaining external validation gap. Review the scoped diff for missing lifecycle branches, leaks, unbounded work, and obsolete documentation. No frontend generation/browser test or CI workflow is required for this backend-only step.

## Handoff and remaining input

Implementation can proceed using this plan without another product decision. Supply a real supported Grok model in server configuration and its API key through the configured environment variable immediately before phase D's opt-in live smoke (or earlier only when intentionally running real chat). Phases A–C and deterministic container verification do not need a key. The current secondary dealership can remain chat-unavailable until its connection is configured. Deterministic tests inject both connections and do not need either key.

For the existing Docker workflow, the user privately edits the repository-root `.env` in their own editor and sets `XAI_API_KEY` for `primary-grok`; `.env.example` documents the variable name and Compose already injects `.env` at runtime. `config/dealerships.json` now selects `grok-4`; live use still depends on account access. Do not overwrite an existing `.env` to copy the example. `.env` is excluded from Git and Docker build context, but these exclusions do not prevent an agent with filesystem access from reading it. During implementation/live verification, do not read secret files, inspect process/container environments, print expanded Compose configuration, log provider headers, or request the key in chat. The user can report only that configuration is ready; validate presence and sanitized request outcomes without displaying values. For enforced isolation from the agent, the user must supply the key and run live acceptance in a separate environment the agent cannot access; an ignored local file alone is not that boundary.

Implementation validation (2026-09-10): application-rendered factual replies and durable displayed
order replace unconstrained factual prose. Ruff lint/format, strict mypy, and 51 local tests passed.
The locked Linux verification image passed the same 51 tests with `pydantic-ai-slim[xai]` 2.42.0
and `xai-sdk` 1.19.0. The disposable container harness imported all 127 assignment records, completed
search/selection/follow-up requests, recreated the backend with its volume intact, replayed the exact
terminal selection outcome, and removed the isolated project volume. No live Grok request was made;
account/model access is the sole external validation gap.
