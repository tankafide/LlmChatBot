# Step 3: NHTSA safety answers in the same conversation

Created: 2026-09-10 (America/Chicago).
Status: implemented; deterministic acceptance verified. Live NHTSA passed; live Grok returned an upstream provider error. See [implementation evidence](step-3-implementation-evidence.md).
Parent: [Product roadmap, step 3](product-roadmap.md#3-nhtsa-safety-answers-in-the-same-conversation).
Prerequisite: [Step 2 conversational inventory plan](step-2-conversational-inventory.md), implemented and verified before this slice is integrated.

## Outcome and scope

A user selects an inventory vehicle, asks about recalls, crash-test ratings, or both, and receives attributed, data-grounded text through the existing conversation message endpoint. Ambiguous crash variants produce a useful clarification that can be answered after restart. If one safety source fails, the reply retains the other source's useful result. Completed safety replies and their evidence survive restart and request replay.

Implement one-vehicle safety lookup through the existing non-streaming chat API. Reuse the [shared lifecycle and session ownership](../stack-baseline.md#database-execution-and-session-ownership), step-two selected-vehicle resolution, structured answer validation, application rendering, and durable replay. Do not introduce a second request lifecycle, public safety endpoint, cache, new database table, VIN service, bulk inventory scan, background refresh, frontend, or provider fallback. Ranking vehicles by safety, crash media, complaints/investigations, and repair-status lookup are outside this slice.

This is a detailed sub-plan, not authorization to implement application code. Its limits and module names are implementation decisions; upstream observations are identified separately below.

## Observed foundation and prerequisite contract

- Current source includes inventory and a partial step-two foundation: conversation/request/message persistence, `conversations/service.py` admission/completion/replay/recovery, `conversations/repository.py`, and `chat/contracts.py` with `ChatRunner`, `ChatRunRequest`, and `ChatRunResult`. `app.py` owns application lifespan and services; `inventory/service.py` performs scoped reads and returns materialized `VehicleRecord` values. Reuse these boundaries. NHTSA modules do not yet exist; source presence does not prove all step-two acceptance criteria have passed.
- `VehicleRecord` already supplies UUID, stock/source ID, year, make, model, trim, body type, drivetrain, and fuel. The real `docs/context/inventory/data.csv` includes those matching attributes, including distinct FWD/AWD/4WD/RWD values and distinct model names such as RAV4 and RAV4 Hybrid. It contains no VIN or curb weight. Do not invent either or strip Hybrid/Prime suffixes.
- `backend/pyproject.toml` pins Python 3.13 and has HTTPX 0.28.1 only in development dependencies. Move HTTPX 0.28.1 into runtime dependencies and update `backend/uv.lock` when implementing this slice. Retain the step-two Pydantic AI/xAI integration; NHTSA HTTPX ownership is independent of the Grok SDK.
- Step two still proposes `conversations/tools.py` and `integrations/chat.py`, plus a structured internal answer and an application renderer. Reconcile their final locations before wiring safety tools into the existing `ChatRunner` boundary. Replace step two's planned fixed `safety_unavailable` intent for supported lookups; do not create another conversation service or assume the production model runner is complete.
- Before integration, require step-two admission/completion/replay, scoped selected-vehicle and displayed-list resolution, complete-turn serialization, deadline/tool guards, injected runner, and process-recovery test harness. Standalone NHTSA parsing/matching work can be prepared first; HTTP acceptance depends on that foundation. Reconcile final step-two names with this plan without creating duplicate services.
- Existing checks are Ruff, strict mypy, pytest, and the Compose `verify` service. The latter uses isolated `/tmp` storage and does not mount the development database volume. No step-three tests or chat acceptance harness ran during this planning task.

## Verified upstream contracts

NHTSA documents year/make/model recall queries and two-stage crash lookup: discover variants, then request the selected VehicleId. Use these three fixed HTTPS templates, query parameters for recalls, and percent-encoded make/model path segments for ratings. Never accept a URL or free-form upstream identity from the model. [Official API documentation](https://www.nhtsa.gov/nhtsa-datasets-and-apis).

| Operation | Request |
| --- | --- |
| Recalls | `GET https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}` |
| Crash discovery | `GET https://api.nhtsa.gov/SafetyRatings/modelyear/{year}/make/{make}/model/{model}?format=json` |
| Crash detail | `GET https://api.nhtsa.gov/SafetyRatings/VehicleId/{vehicle_id}?format=json` |

Read-only HTTPS probes during planning observed:

- [2022 Toyota RAV4 discovery](https://api.nhtsa.gov/SafetyRatings/modelyear/2022/make/Toyota/model/RAV4?format=json): `Count`, `Message`, and capitalized `Results`; two descriptions, AWD/16665 and FWD/16640.
- [AWD detail](https://api.nhtsa.gov/SafetyRatings/VehicleId/16665?format=json): a single identified record, stars encoded as strings, overall/front/side/rollover fields, other category fields, and `Not Rated` in an additional rollover field.
- [2013 Acura RDX detail](https://api.nhtsa.gov/SafetyRatings/VehicleId/7520?format=json): identified record with explicit `Not Rated` categories. This is an upstream contract example, not assignment inventory.
- [2022 Toyota RAV4 recalls](https://api.nhtsa.gov/recalls/recallsByVehicle?make=Toyota&model=RAV4&modelYear=2022): `Count`, `Message`, lowercase `results`, year as a string, campaign identifier, component/summary/consequence/remedy, `parkIt`/`parkOutSide` booleans, and day/month/year report date. One campaign was observed; do not freeze that as a live acceptance count.

Browser retrieval of one ratings example failed, but direct HTTPS requests from this workspace succeeded. These probes establish current response-shape feasibility, not ongoing availability or complete assignment-model coverage. Synthetic fixtures must be clearly labeled; record provenance/date for any captured upstream fixture and keep CI expectations independent of future live data.

NHTSA distinguishes model-level campaigns from individual VIN recall status. Render that limitation with recall answers. [NHTSA recall search](https://www.nhtsa.gov/recalls). Ratings can coexist with safety concerns, and an unrated category supplies no star judgment. Overall/frontal comparisons require compatible class and weight within 250 pounds; because this inventory lacks weight, this slice reports individual ratings without ranking. [NHTSA ratings explanations](https://www.nhtsa.gov/ratings).

## Module and dependency placement

All paths in this table are under `backend/src/autoassist/`; new paths remain proposed until implementation.

| Module | Responsibility and reuse |
| --- | --- |
| `safety/records.py` (new) | Strict application result models, rating categories, provenance, bounded variant choices, error reasons; no HTTP or SDK dependencies. |
| `integrations/nhtsa.py` (new) | Fixed request construction, HTTP status/size/deadline handling, endpoint-specific payload validation, conversion to typed records. Small injected client boundary supports HTTPX MockTransport. |
| `safety/matching.py` (new) | Pure conservative identity normalization, description matching, explicit candidate resolution. Keep separate from fuzzy inventory search. |
| `safety/service.py` (new) | Lookup orchestration for one already-scoped `VehicleRecord`, independent branch outcomes, per-run result reuse and budget accounting. No SQL or commits. |
| `conversations/tools.py` (step two) | Thin safety tools: resolve scoped inventory identity using existing rules, await service, record validated evidence; no transport parsing. |
| `conversations/answers.py` (new only if step two has no equivalent) | Extend existing structured answer/evidence validation and renderer. Keep one renderer; do not add parallel inventory rendering. |
| `integrations/chat.py` / conversation replay helpers (step two) | Inject safety dependencies/deadline; persist and restore candidate presentation metadata alongside complete successful model turns. |
| `chat/contracts.py`, `conversations/service.py` (existing) | Reuse `ChatRunRequest.text` and replay units for choice resolution, and `ChatRunResult.replay_json` for staged metadata. Validate metadata against staged selection at the existing atomic completion boundary; include inventory-only selection changes in safety invalidation. |
| `app.py` | Construct and close one pooled NHTSA AsyncClient inside lifespan; inject service through chat dependencies. Startup and health make no NHTSA request. |

No ORM or public API schema changes are intended. Extend the application-owned internal successful-turn JSON with a discriminated `safety_presentation_update`: `keep`, `clear`, or `set` carrying the presentation below. Every newly completed turn, including inventory-only turns, records an action; existing inventory `presented_vehicle_ids` remains specific to inventory lists. Before finalizing implementation, prove byte accounting includes this new metadata and rendered text. Do not add a migration framework or reset storage on startup.

## Application result contracts

Use discriminated, runtime-validated results, rejecting impossible combinations. All lookup results carry inventory vehicle UUID/stock ID; exact requested year/make/model; source `NHTSA`; source URL built by the application; UTC `attempted_at`; nullable successful `retrieved_at`; and branch status. Crash results additionally carry the matched VehicleId/description where established. Error results contain a sanitized reason, not raw response text or exception strings. Retrieval time means when the response was obtained, not when NHTSA last changed its database.

### Recalls

- `available`: a valid nonempty campaign collection, `total_count`, displayed campaigns, and explicit truncation indicators.
- `empty`: only a valid successful envelope with `Count == 0` and an actual empty `results` list. Wording: no campaigns returned for this year/make/model at retrieval time. Never say recall-free, safe, or no open VIN recalls.
- `unavailable`: HTTP/transport failure, schema or identity failure, excessive response, budget exhaustion, or unsupported identity. Never populate a success count of zero for this state.
- Each campaign has campaign number, component, summary, consequence, remedy, nullable report date/notes, and nullable urgent `park_it`/`park_outside` flags. Preserve absence as unknown. Do not infer urgency from a false/missing flag, and do not infer repair completion from remedy text. Attribute quoted/excerpted upstream text as NHTSA data.

Require count to be a nonnegative integer (reject booleans), correct collection casing, and count/list agreement. Require campaign number, year/make/model identity, and the named component/summary/consequence/remedy keys for each record; explicit null/blank explanatory fields become unavailable text, while missing keys or invalid types fail the branch. Parse digit-only year strings explicitly. Accept optional date only as validated observed day/month/year or ISO date; malformed dates invalidate the record. Extra unrelated upstream fields may be ignored. Duplicate campaign numbers or any malformed/mismatched record invalidate this branch; do not silently drop a bad record and claim complete coverage. Verify every record before producing a display excerpt.

### Crash variants and ratings

Discovery requires capitalized `Results`, consistent `Count`, unique positive integral VehicleIds, and nonempty bounded descriptions. Detail requires zero or one record: zero is `no_record`; one must match the chosen ID and requested year/make/model and remain consistent with the discovery description. More than one or inconsistent identities is `unavailable: invalid_response`.

Crash branch states:

| State | Meaning / rendered outcome |
| --- | --- |
| `available` | All four summary categories have valid stars; report exact individual categories. |
| `partial` | At least one summary category has stars, but another is unrated/missing/invalid; preserve valid values and explain gaps. |
| `unrated` | All four summary categories explicitly say `Not Rated`; report that distinction. |
| `no_ratings` | Identified detail record exists but has no valid summary stars and at least one missing/invalid category; say ratings data is unavailable/incomplete, not explicitly untested. |
| `no_record` | Valid discovery/detail yields no compatible record; do not substitute another year/model. |
| `ambiguous` | Multiple plausible variants or insufficient attributes; show bounded choices and ask which description applies. No detail calls yet. |
| `unavailable` | Transport/envelope/identity/budget failure; preserve the independent recall result. |

Summary field mapping: `OverallRating` → overall, `OverallFrontCrashRating` → frontal, `OverallSideCrashRating` → side, `RolloverRating` → rollover. Allow numeric integer 1–5 or strings exactly representing 1–5 after whitespace trimming; reject booleans, zero, six, fractions, NaN, and arbitrary strings. Each category stores `rated` with stars, `not_rated`, `missing` (absent/null/blank), or `invalid`. An invalid category is an explicit partial-data issue, never a zero-star value. Keep optional driver/passenger, barrier/pole, and second-rollover category values under a fixed upstream-key mapping with the same validation; the normal reply presents the four summary categories. Do not derive overall stars or replace the recall endpoint with detail's `RecallsCount`.

Preserve upstream concern/warning fields when supplied: store bounded field-name/value entries for keys containing `concern` or `warning` case-insensitively, apart from the known driver-assistance equipment field `NHTSAForwardCollisionWarning`. Accept scalar text/boolean values; malformed or oversized warning data marks concern coverage incomplete. Render nonempty/nonfalse values as source-labeled supplemental notes with their original field labels rather than inventing category interpretations. Keep `dynamicTipResult` as a separately labeled result. For known category labels, attach notes to that category; otherwise show them as unclassified NHTSA notes. The sampled API payload did not expose explicit category concern flags: missing notes never establish an absence of safety concerns. Document this API coverage limitation and always include the NHTSA ratings source link. Do not fetch arbitrary media or note URLs.

## Vehicle matching and follow-up decisions

1. Resolve the vehicle through step-two scoped `get_vehicle`/selection logic, including exact stock IDs and previously presented inventory ordinals. Re-fetch through `InventoryService.get(dealership_id, vehicle_id)` in a complete worker-thread unit before network work. Unknown or other-dealership identity reveals no details and triggers no NHTSA call. No selected vehicle or multiple possible inventory vehicles returns a fixed clarification.
2. Normalize only case, outer/repeated whitespace, and explicit harmless punctuation forms. Retain semantic model tokens, year, fuel distinction, and drivetrain. No fuzzy matching, nearest year, Hybrid-to-base fallback, general AWD/4WD equivalence, or external free-text search. Start without semantic model aliases; add one only with captured official evidence and a specific matching test. An exact-name lookup failure is an explained limitation, not a reason to try guessed alternatives.
3. For crash descriptions, verify the leading year and full make/model token sequence. Parse remaining tokens against a small known vocabulary for SUV/sedan/hatchback/coupe/wagon/van/pickup and FWD/AWD/4WD/RWD. Explicit nonmatching body/drivetrain/fuel descriptors exclude a candidate. Preserve any unrecognized suffix as unresolved rather than deleting it. Trim alone does not prove equivalence to an upstream variant.
4. Automatically choose only a sole compatible candidate whose described differentiating attributes are supported by inventory. A sole result with an unknown qualifier or an attribute absent in inventory still needs clarification. Zero compatible candidates produces `no_record`; multiple plausible candidates produce `ambiguous`. Do not fetch every variant to compare ratings.
5. On ambiguity, sort by description then VehicleId, present at most five labeled NHTSA variants (descriptions and IDs), and keep total candidate count. More than five produces an explicit subset notice and requests a distinguishing description. A follow-up descriptor filters a fresh complete discovery set, bounded at 100 entries; excess becomes unavailable. If filtering identifies a previously undisplayed candidate, present it for explicit confirmation in a completed reply before any detail call, even if it is the sole result. An ID or ordinal alone can select only a displayed candidate. A descriptor with zero or multiple matches produces another clarification, never a guessed variant.
6. Persist exactly the displayed choices only with a completed reply using `safety_presentation_update = {action: "set", presentation: {inventory_vehicle_id, lookup_identity, candidates:[{vehicle_id, description}], total_candidate_count, retrieved_at}}`. `keep` and `clear` have no presentation payload. Start restoration with no presentation and fold the retained contiguous successful-turn suffix oldest to newest: `keep` preserves, `clear` removes, and `set` replaces. Do not search backward for a presentation matching the current stock vehicle. If the original `set` has been trimmed, later `keep` actions cannot restore it. Final presentation identity must match authoritative selection.
7. Derive the update in application code: a staged selection change or inventory list clearing selection first invalidates prior choices; a newly rendered ambiguity for the final selected vehicle may then `set` new choices, otherwise record `clear`. A completed crash detail/no-record result also clears pending choices; an unrelated reply or transient lookup failure with unchanged selection keeps them. Failed/interrupted turns apply no update. All inventory-only turns participate, so A → B → A and A → list-clears-selection → A cannot resurrect A's old choices. Complete the action and assistant text in the existing transaction. No separate selected-variant column or write is needed.
8. Resolve choice input in an application-owned helper using the current `ChatRunRequest.text`, authoritative selection, and restored presentation; do not ask the model to invent a descriptor. Accept a bounded, whole-message choice grammar after harmless whitespace/case normalization: an explicit displayed NHTSA ID, a clear displayed ordinal, an exact displayed description, or a literal descriptor optionally wrapped as “the … one”. Bound the descriptor to 200 characters and match complete tokens against descriptions. Reject negation, alternatives, conflicting qualifiers, multiple commands, and unsupported phrasing with fixed guidance to reply with the exact displayed ID or description. Do not extract a convenient substring from arbitrary prose. An exact description can confirm an unknown qualifier; a descriptor can confirm a missing known attribute only when it uniquely identifies the displayed candidate and covers its unresolved differentiators. User confirmation never overrides a known inventory conflict or alters inventory data.
9. Re-run discovery after an accepted choice and require the candidate still exists with the same description, remains nonconflicting, and matches that choice before detail. Stale/changed candidates produce fresh choices for confirmation. Unknown qualifiers remain quoted NHTSA labels rather than inferred attributes; otherwise insufficient confirmation re-clarifies. A bare ordinal resolves only when its referent is clear; if inventory and safety lists both plausibly apply, ask for an explicit NHTSA ID. No valid retained presentation means rediscover and present choices before accepting a variant reference. Do not reuse inventory list order for crash choices or follow a model-supplied ID without independently resolved user choice.
10. Same-ID terminal replay returns the stored answer with its original provenance and makes zero new calls. A deliberate new safety question uses fresh lookup data. Historical safety text can be discussed as dated history, but cannot become current-run evidence for a new safety claim.

## Tool, evidence, and text contracts

Expose two thin tools, `get_vehicle_recalls(vehicle_id: UUID | None)` and `get_vehicle_crash_ratings(vehicle_id: UUID | None)`. Omitted vehicle means current authoritative selection. The crash wrapper passes the application-resolved choice from the current message to the service; neither variant IDs nor descriptors are model-controlled tool arguments. With no choice, use conservative automatic matching or display clarification. Resolve input once per run and reuse discovery/results within the existing three-GET budget; filtering does not trigger extra discovery requests in that turn. No make/model/year/dealership/URL arguments are model-controlled.

Keep tools sequential as in step two; all share the same run context and budgets. For a question about both capabilities, call both. An expected failure returns a typed branch result so the second lookup and final answer can proceed. Unexpected programming/storage errors continue through step-two error settlement; do not catch every exception as an NHTSA outage.

Use one internal `safety` answer shape with scoped `vehicle_id`, nullable `recall_evidence_id`, and nullable `crash_evidence_id`; at least one reference is required, and every requested branch must have its reference. Crash evidence can have any defined status, including `ambiguous`. Do not introduce a separate `clarify_safety_variant` intent. The application renderer emits each branch's result and, for ambiguity, the exact bounded candidate list and clarification prompt from crash evidence. Derive the persisted `set` presentation from that same rendered list, never from separate model-supplied candidates. Thus recalls plus ambiguous ratings is one completed answer containing useful recalls and choices.

Evidence IDs are run-local application-generated references. The model supplies no campaign facts, rating values, source URLs, dates, or free-form safety prose. Validate every reference against this run's typed result, including unavailable and ambiguous outcomes. Render each requested branch's status automatically; the model cannot omit a failed branch from a combined answer or omit urgent flags. If an answer requests a branch without evidence, use step-two bounded output repair, then fail rather than inventing data. A subsequent variant-only clarification requests crash evidence only; previously rendered recalls remain dated history and are not fetched again unless requested.

Render stock identity/year/make/model, recall counts and campaign excerpts, or matched variant and category stars, followed by source/time and required limitations. Always distinguish missing/unrated/invalid values. Include validated consequence/remedy excerpts and urgent flags before low-priority notes. No “safe to drive,” “safest,” recall-free, repair-completed, or universally safe wording. Current source text is data; it cannot alter prompts or tool privileges. Preserve and label excerpts, escape control/markup characters as appropriate for text consumers, and never follow instructions embedded in an upstream field.

For combined answers, render the useful branch even if the other branch times out or is ambiguous. Both unavailable can still be a completed HTTP 200 conversation reply explaining the unavailable data. That is a successful conversation outcome, not successful safety retrieval. If the overall model deadline expires or no valid answer is produced, retain step-two 504/502 semantics. Admission, persistence failures, and cancellation retain the baseline's established outcomes.

## Bounds, execution, and cleanup

These are local prototype choices, not NHTSA published quotas. Keep step-two limits: four active turns, six model requests, eight total tool attempts, sequential tools, 60-second model/tool deadline, 16-KiB tool result, 128-KiB provider input, 64-KiB successful replay unit, and 8,000-character public reply.

| Boundary | Implementation decision |
| --- | --- |
| Client | One lifespan-owned HTTPX AsyncClient, fixed HTTPS host, `follow_redirects=False`, transport retries zero, eight connections/four keepalive connections. Do not pass Grok headers/credentials to it. |
| HTTP timeouts | Connect 2 s, read 5 s, write 2 s, pool 1 s. Also bound the whole streamed request to 7 s or remaining budget, whichever is lower. |
| Safety budget | At most 20 s cumulative NHTSA wall time per turn; stop starting work once less than 10 s remains in the outer run deadline. This reserves time for final rendering/model response but does not guarantee provider completion. |
| Attempts | At most three outbound GETs per turn: recalls, crash discovery, one detail. No automatic NHTSA retries in this slice, including 429/5xx; surface transient unavailability. Same-turn repeat tools reuse their typed result, including failure, without another GET. |
| Response bytes | Stream and stop at 512 KiB of decoded bytes per response, regardless of Content-Length; close response on every path. Bound/validate at most 100 discovery entries or 200 recall records. Larger valid collections return limit-related unavailable, not empty. |
| Tool output | Each rendered tool record stays below 16 KiB including provenance/status. Allocate at most 12 KiB to recall campaign excerpts and at most 8 KiB to crash detail/choices, leaving metadata headroom; measure actual canonical UTF-8 JSON, not characters. |
| Recall excerpts | Display at most five campaigns, urgent flags first then report date descending/campaign ID. Bound summary/consequence/remedy to 300 characters each, notes to 150; mark every clipped field and omitted campaign count. Retain aggregate urgent-campaign count across all validated records. Source link permits further review. |
| Public rendering | Keep the exact complete reply below 8,000 characters. Reduce low-priority excerpt lengths deterministically before rendering; never clip identity, branch status, urgent notices, uncertainty, or provenance. If mandatory content alone cannot fit, fail validation rather than silently removing it. |

Use a single monotonic run deadline supplied by the chat runner. The safety service checks it before each HTTP request and wraps the await with the tighter remaining safety/request budget. Local request/safety timeout becomes branch unavailability; outer task cancellation propagates. Client pool waits count against the budget. A read trickle cannot extend the whole-request timeout. Same-turn memoization is bounded per-run evidence reuse, not a cross-request freshness cache. Reject attempts to switch inventory vehicles during this one-vehicle safety slice with clarification; do not spend three calls per vehicle.

HTTPX distinguishes phase timeouts and supports injected transports. Pooling/timeouts are transport controls; the application supplies total deadlines and response bounds. [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/), [HTTPX transports](https://www.python-httpx.org/advanced/transports/).

Do all scoped SQL reads in worker-thread units; close sessions before HTTP awaits. Offload bounded JSON parsing/validation to a worker if responsiveness measurements show it materially blocks the event loop; measure the 512-KiB boundary during implementation before choosing that optimization. Responses close with async context managers; no untracked tasks or detached lookup work. Lifespan shutdown drains/cancels chat using step-two rules, then closes the NHTSA client even if another resource failed to initialize.

Log request/conversation correlation IDs, endpoint category, elapsed time, call count, and categorized result. Do not log user text, raw upstream bodies, keys, provider headers, or environment values. Status/type/identity errors are expected integration errors; a malformed programming contract is not silently treated as successful missing data.

## Durability and recovery

All safety lookups are read-only. Their in-memory results become durable only in the existing atomic successful completion: rendered assistant message, full bounded model/tool turn, safety presentation metadata, validated staged inventory selection, and terminal HTTP response commit together. Do not commit variant choices in a tool. Complete tool history means exactly the bounded typed tool output supplied to the model, including truncation metadata; storing the whole raw NHTSA response is not required.

On model failure/cancellation/completion rollback, retain the admitted user message and prior committed selection/presentation; publish no new safety reply or partial evidence. On storage uncertainty, reconcile using the existing request identity. Startup interruption recovery and replay are unchanged. No automatic lookup resumption after process death. An old completed safety answer keeps its original data/time, even if NHTSA later changes or goes offline. Fresh-ID refresh is an intentional new request.

## Ordered implementation phases

### A. Implement typed transport and a complete recall slice

Prerequisites: step-one inventory records; step-two chat foundation for tool/API wiring.

1. Add runtime HTTPX dependency/lock update, lifespan client ownership, and injectable safety service. Implement settings as typed internal defaults above; do not expose configurable arbitrary base URLs in chat/config. Tests inject a transport/client directly. Update architecture dependency map when code lands.
2. Add endpoint-specific envelopes, bounded streamed GET helper, source/error records, and recall parser. Implement status/type/count/identity validation and result-size guards before text rendering. Add synthetic MockTransport fixtures for success, empty, malformed, wrong identity, timeout, and urgent campaigns.
3. Add the recall tool using scoped vehicle resolution and current-run evidence. Extend answer validation/rendering for recall statuses, attribution, excerpts, urgency, and model-level limitations. Use scripted model/tool exchanges to drive actual HTTP submissions against a temporary SQLite file.
4. Verify no selection makes zero HTTP calls; selecting real-shaped stock data then asking about recalls produces a committed attributed reply. Inject HTTP failure and confirm a completed unavailable reply is distinct from empty. Update README with the implemented recall behavior and expected failure semantics.

Exit: transport construction/parsing tests and deterministic HTTP recall tests pass; committed replay restores exact text with no extra model/NHTSA calls. Client closes after lifespan failure/shutdown. No DB transaction spans a gated HTTP wait.

### B. Add crash matching and persistent clarification

Prerequisite: A's shared boundary, budgets, and evidence renderer.

1. Add discovery/detail validators, category mapping, concern-note preservation, and pure candidate matching. Use the actual RAV4 FWD/AWD shapes plus labeled synthetic incompatible/ambiguous cases; no account or live NHTSA access is needed.
2. Implement crash tool and typed branch states; fetch one detail only after exact matching or a validated user choice. Exercise a sole incompatible candidate, missing inventory attribute, unknown suffix, model suffix differences, and matching candidate with missing/unrated stars.
3. Add `safety_presentation_update` to the step-two replay unit and shared byte accounting. Implement chronological restoration, application-derived keep/set/clear actions for every successful turn, invalidation/revalidation, and the bounded current-message choice resolver. Reuse existing completion transaction; add no independent write path.
4. Extend answer renderer and README with variant descriptions, category statuses, explicit clarification examples, and rating limitations. Replace the obsolete step-two “safety lookup not implemented” runtime behavior for supported branches; keep out-of-scope requests explicitly unsupported.

Exit: HTTP select → ratings ambiguity → restart → explicit variant choice yields the right detail ID and committed response. One variant cannot leak across stock vehicles/dealerships. A sole conflicting result triggers no detail call. Replay restores choices and exact text without live lookup.

### C. Prove combined answers, resource bounds, and failure recovery

Prerequisites: A/B plus step-two process gates and temporary-file recovery harness.

Implement the following checks under proposed `backend/tests/test_nhtsa_client.py`, `test_safety_matching.py`, `test_safety_conversation.py`, and focused additions to step-two chat/recovery tests. Keep these paths descriptive if step-two test layout changes; do not duplicate its complete lifecycle suite.

| Setup / action | Observable expected result |
| --- | --- |
| Valid nonempty and verified-empty recall payloads | Different typed statuses and rendered text; empty success requires the actual zero-count envelope. |
| Wrong casing, missing list, count mismatch, duplicate campaign/variant, invalid JSON/HTML, wrong year/model/ID, malformed required record | Affected branch unavailable; never empty, cross-vehicle stars, or falsely complete campaign list. |
| Stars 1/5, `Not Rated`, null/blank/missing, 0/6/bool/garbage; mixed summary categories | Correct per-field states and overall available/partial/unrated/no_ratings; valid categories remain visible. |
| Concern notes and urgent campaigns beyond the first five; long text | Notes/urgent aggregate retained, explicit excerpts/omissions, byte and reply bounds satisfied; no “no concerns” inference. |
| FWD inventory with AWD/FWD discovery; only AWD; Hybrid versus base; unknown qualifier | Correct single detail or clarification/no_record; no AWD↔4WD or Hybrid substitution. |
| Two dealerships and multiple named LLM connections | Same scoped vehicle/connection as step two; fabricated other-dealership ID makes zero NHTSA calls and reveals no identity. |
| Both branches requested; recalls succeed/crash timeout and reverse; both fail | Useful branch survives, failed branch is acknowledged; valid explanatory replies commit as 200, with distinct tool outcomes. |
| Both requested; recalls succeed and crash discovery is ambiguous; restart, then choose a displayed variant | One `safety` reply contains recall evidence and exact displayed choices; the same choices commit atomically. Follow-up re-discovers and fetches only the selected detail, without refreshing recalls; original-ID replay performs no external calls. |
| Six plausible variants; restart after displaying five; descriptor matches the undisplayed sixth; confirm its newly displayed ID | Descriptor reaches the application matcher through current request text; fresh discovery filters the full bounded set, displays the sixth for confirmation, and makes no detail call until the next explicit choice. Each turn stays within the GET budget. |
| Sole unknown suffix or missing attribute; exact-description confirmation; known conflicting drivetrain; negated or multi-choice text | Explicit confirmation resolves uncertainty only for a nonconflicting candidate. Known conflicts and unsupported choice grammar never trigger a detail call or mutate inventory. |
| Present choices for A; select B then A, or clear selection with a new list then select A; restart after each sequence | Durable clear actions prevent restoration of old choices; a bare old ID cannot trigger detail. Fresh choices are required. |
| Trim the original set action; retain keep actions, or retain clear then keep; replay after restart | Restoration begins empty and never resurrects discarded choices. A retained newer set restores only its own displayed list. |
| Direct 429/404/500, connect/read/pool errors, slow streamed body | Single attempt per endpoint, sanitized unavailable reason, response closed. No redirect/retry loop. |
| Repeated tools, exhausted three-GET or cumulative/outer time budget | Exact outbound call bounds and typed local exhaustion; outer deadline keeps step-two 504. No model retries can bypass counters. |
| Near/above response/tool/replay/input/public-reply byte limits | Explicit bounded excerpt or prescribed failure, never a split tool pair or falsely complete output. Successful safety presentation counts toward replay trimming. |
| Model invents star/campaign/source, omits failure, references old evidence, or upstream text requests arbitrary URLs | Schema/evidence rejection or fixed rendering; no invented values, no extra-host requests, no scope override. |
| Pending choices survive app recreation; choose displayed variant, fabricated ID, stale variant, or ambiguous ordinal | Valid choice re-discovered before detail; invalid/stale/unclear choice clarifies with zero inappropriate detail calls. |
| Gated NHTSA await; issue another conversation write and health request | No live DB session/transaction across wait; other work progresses. Four admitted turns still bound client work. |
| Cancel while awaiting response, then while completion DB unit is gated | Network response cleanup; completion thread settles before interruption handling; committed completion wins; no leaked permit/client task. |
| Inject failure after inserting assistant but before completion commit | Fresh SQLite session sees no partial assistant/evidence/presentation; prior selection/history intact. Never return durable success. |
| Commit succeeds but response is lost; same-ID replay after restart with NHTSA/model disabled | Exact stored status/body/time, unchanged row counts, zero external calls. |
| Abruptly terminate subprocess during NHTSA wait after admission commit | Fully stop sole process, restart on same temporary file: interrupted turn/user retained, previous safety reply/choices intact, no automatic lookup rerun. Repeat recovery safely. |
| Abruptly terminate after safety completion commit | Committed text/evidence/context survives and replays without external calls. |

Use synchronization gates and bounded deadlock guards, not scheduling sleeps. Tests own and close async lifespan, HTTP clients, temporary DB engines, tasks, and subprocesses in `finally`. Block live model/NHTSA traffic by default. Use real SQLite files and fresh sessions to inspect commits; an in-memory DB or application recreation alone does not prove crash recovery.

Measure one boundary-size parse and multiple concurrent gated lookups for responsiveness, recording fixture sizes and observations. Assert deterministic call/query limits in CI; do not turn noisy latency thresholds into correctness assertions or claim production throughput from four turn permits.

Exit: deterministic integration/recovery and static checks pass, meaningful partial-failure and abrupt-stop evidence recorded, no relaxed assertions or swallowed programming errors.

### D. Container acceptance, optional live smoke, and handoff

Prerequisite: A–C; only end-to-end live Grok verification needs runtime model credentials.

1. Run available checks below from repository root. Confirm Docker Desktop readiness before Compose. Rebuild the verification image for the runtime dependency change; use its isolated tests, never development storage.
2. Extend the step-two disposable container acceptance harness: import `docs/context/inventory/data.csv` for `mia-motors`, choose AA-1001 (2022 RAV4 FWD), run both safety questions with deterministic NHTSA/model fakes, recreate the container retaining its isolated volume, then continue and replay. Verify the real import, scoped identity, text/evidence persistence, and no second external call on replay. Record the harness's exact command once implemented; no such runnable chat harness exists today.
3. Add a separate opt-in live check using the same selected inventory identity. First verify NHTSA discovery/detail and recall data through the real service without Grok; then use configured Grok through HTTP for search → selection → both safety questions → follow-up. Compare IDs/facts with returned data, not fixed counts/prose. Record date, model/package versions and sanitized outcomes. A missing key blocks only the live Grok check; live NHTSA outage is documented independently. Do not put live checks in normal pytest/CI.
4. Update README and `docs/architecture.md`: actual module ownership, API conversation examples, safety status distinctions, year/make/model versus VIN scope, variant choices, unrated/partial data, incomplete warning-field coverage, truncation/freshness, limits, no retries/cache, and baseline persistence/interruption behavior. Remove obsolete blanket statements that safety lookup is unavailable. Update roadmap status only on verified implementation evidence; add links to test/live evidence here.
5. Review scoped diff for ignored error branches, fabricated facts, ordinal ambiguity, extra DB writes, resource leaks, hidden retries, secrets, and unrelated changes. Leave CI creation/submission packaging to step four.

Existing commands, working directory `C:\Users\shane\Documents\Apps\LlmChatBot`:

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

Focused new-test commands become runnable only after those files exist; the existing full pytest command already discovers them. The container harness must use an explicitly separate project/volume/port and fake external configuration. Stop the prior process before replacement. Do not remove the development volume or print expanded secret-bearing Compose configuration. Follow step-two private runtime-key handling; do not read `.env`, inspect process environments, or ask for keys in chat.

Exit: local and locked-container checks pass, disposable-volume safety conversation survives recreation, README demonstrates both capabilities, and live results or exact external gaps are recorded separately. No new product decision is required to implement this plan after step two.

## Planning validation and implementation checklist

Review revisions: resolved [Step 3 review](step-3-plan-review.md) findings with current-message descriptor resolution, durable presentation actions, one composable safety answer, refreshed source observations, and corresponding acceptance cases. These are plan changes; application implementation and acceptance verification remain pending.

Planning inspected the roadmap, step-two plan, baseline, current inventory/lifespan/dependency/test boundaries, preserved CSV, and selected backend architecture/backend/persistence/chat/NHTSA/verification guidance. Current official endpoints were checked with direct read-only HTTPS requests. No application feature, dependency change, database write, application test run, or live model call was performed.

- [x] Step-two prerequisites implemented and names reconciled.
- [x] A: bounded typed recall path through durable HTTP conversation.
- [x] B: crash matching, ratings, and restart-safe variant clarification.
- [x] C: partial failures, grounding, resource limits, and abrupt recovery verified.
- [x] D: container acceptance, docs, scoped review, and live-check evidence/gaps recorded.

Implementation completed 2026-09-10: user authorized the complete plan. Existing step-two modules chat/grounded.py, chat/selection.py and chat/history.py were extended directly. Final locked container verification passed all 132 tests, Ruff, and strict mypy. Live Grok remains an explicitly recorded external validation gap.

Implementation reconciliation: transport parsing is in safety/parsing.py; existing chat/grounded.py owns tool wrappers and structured outputs. Source probes and execution evidence are in [step-three evidence](step-3-implementation-evidence.md). Historical planning statements above describe the pre-implementation state.
