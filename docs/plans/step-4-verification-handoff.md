# Step 4: Assignment verification and handoff

Created: 2026-09-10 (America/Chicago).
Status: detailed implementation plan; implementation and acceptance checks pending.
Parent: [Product roadmap, step 4](product-roadmap.md#4-assignment-verification-and-handoff).
Prerequisites: verified [step 2](step-2-conversational-inventory.md) and [step 3](step-3-nhtsa-safety.md), building on [step 1](step-1-foundation-inventory.md).

## Outcome and scope

Deliver a reproducible API submission: a fresh source extraction builds from lockfiles, imports the assignment CSV, demonstrates a grounded conversation including both safety capabilities, preserves it across container recreation, and passes deterministic failure/recovery checks. Supply one complete host verification command orchestrating container checks, a GitHub Actions workflow using it, accurate setup and API documentation, concise walkthrough notes, and a verified source ZIP with a checksum.

This step integrates acceptance evidence and closes demonstrated defects in required behavior. It does not add a frontend, authentication, provider administration, deployment, a migration framework, automatic interrupted-run resumption, or new product features. Do not upload/send the submission or publish a release as part of packaging. Planning ends with this document; application implementation is not part of the current request.

Use the [shared baseline](../stack-baseline.md#chat-request-lifecycle) as the authoritative request lifecycle and session-ownership specification. Reuse steps 2–3's budgets, safety distinctions, and tools; do not redesign those contracts during handoff.

## Repository evidence and resolved decisions

- At inspection, inventory implementation and tests exist. Chat implementation is in progress under `backend/src/autoassist/chat/` and `conversations/`, with conversation routes/schemas in the existing `api/routes.py` and `api/schemas.py`. `app.py` already accepts an injected runner factory. These are observed code, not a claim that chat passes acceptance.
- No NHTSA implementation, `.github/workflows/`, `scripts/`, or chat/container acceptance harness was present in the inspected tree. Earlier plans' descriptions of source state are historical; reconcile against the completed preceding steps before implementation.
- Existing tests cover real-file inventory import, rollback, an importer subprocess kill, scope, query counts, and inventory responsiveness. Reuse `backend/tests/conftest.py`, `test_inventory_import.py`, `test_configuration_and_storage.py`, and `test_responsiveness.py`. An importer crash test does not establish conversation crash recovery.
- The actual first CSV row is AA-1001: 2022 Toyota RAV4 LE, SUV, $26,335, 15,819 miles, FWD, Automatic, Gasoline. The existing real-file test expects 127 rows. Use this row for the final demonstration, resolving its generated vehicle UUID at runtime.
- `compose.yaml` already has a `verify` service invoking Ruff lint/format, strict mypy, and pytest, using `/tmp` database storage and selective read-only mounts. It does not mount the development volume. Extend this entry point instead of replacing it with separate local and CI check lists.
- `Dockerfile` pins Python 3.13.7 and uv 0.8.13, installs from `backend/uv.lock`, runs as UID 10001, and starts one Uvicorn worker. Reuse this image and storage ownership. The current verifier can reuse a stale image unless explicitly rebuilt after lock changes; final documented invocation must include `--build`.
- README and architecture notes still describe an inventory-only application. Finish them from verified final behavior. Do not copy old test counts or turn planned features into passing claims.
- The workspace contains substantial uncommitted/untracked work. Preserve it. Package an explicit allowlist from the current filesystem snapshot, including intended untracked deliverables; `git archive HEAD` would omit them. No automatic commit, reset, or cleanup of unrelated work.

Proposed paths below are new unless already supplied by steps 2–3. Reuse equivalent delivered harnesses rather than creating competing copies. No new runtime dependency or application schema change is expected solely for step 4.

## A. Establish the final acceptance inventory

Prerequisites: steps 2–3 delivered far enough to exercise their HTTP paths; inspection can begin earlier.

1. Re-read their final evidence, actual route/schema definitions, runner/NHTSA injection seams, lifecycle units, test fixtures, Docker settings, and lockfile. Record exact present paths in `docs/verification.md`. Make a requirement-to-test table with test node IDs, evidence boundary, last command/result, and outstanding gap. Mark unimplemented prerequisite behavior explicitly; do not silently substitute a fake business service for it.
2. Map the existing tests to the scenarios in phases B/C. Add only missing behavioral coverage or strengthen insufficient assertions. Keep failures attached to the owning implementation and plan: inventory defects to step 1, request/grounding defects to step 2, safety defects to step 3. A required failure remains a step-4 blocker until fixed and rechecked.
3. Establish test isolation in shared fixtures: temporary file-backed SQLite with the application engine configuration; two dealerships and two named model connections; fake credential values only. Deny live model and NHTSA calls by default using provider-library test controls where available plus rejecting external transports/factories. Allow only test-controlled loopback HTTP in process tests. Patch and restore environment values without reading or printing local secrets.
4. Add or extend `backend/tests/test_assignment_flow.py` and shared fake support under `backend/tests/support/`. Use a scripted Pydantic AI model at the external model boundary to invoke the real tools, matching, evidence validation, and renderer. NHTSA uses injected HTTPX transport payloads. A runner stub is useful for low-level lifecycle tests but is insufficient for the final grounding flow.
5. Confirm OpenAPI can be generated from the real `create_app()` without lifespan, credentials, storage writes, or external traffic. Compare actual HTTP success/error envelopes with declared schemas. Do not introduce TypeScript generation before the optional frontend exists.

Exit: every assignment requirement has a concrete test owner and expected result; prerequisites and fake boundaries are explicit. The deterministic tests fail immediately if they attempt live provider access. No implementation completion is inferred from file presence.

## B. Prove the full assignment flow through HTTP

Prerequisites: working inventory/chat/safety paths and phase A's external fakes.

Implement one synchronous, standard-library-only scenario module at `scripts/assignment_scenario.py`. It must not import pytest, HTTPX, application models, or test fixtures, implement chat decisions, or persist application state. Its HTTP boundary is a callable `request(method, relative_path, json_body=None)` returning `(status_code, decoded_json)` using ordinary Python JSON values. Include query strings in the relative path. Return non-2xx responses normally for assertions; transport failures, timeouts, and invalid JSON fail the scenario. The adapter owns base URLs, JSON encoding/decoding, and bounded request timeouts; it must not silently retry submissions.

Use two thin adapters: the integration test wraps a context-managed FastAPI `TestClient` (which runs the real ASGI application and lifespan), while the host harness uses `urllib.request`, decoding `HTTPError` bodies through the same response path. Keep Pydantic AI/HTTPX fakes and the application launcher in separate `backend/tests/support/` modules loaded only in the test/container environment. Mount `/app/scripts/` in the verifier and explicitly add that directory to the integration test's import path; in a checkout resolve the sibling root `scripts/` directory from the test file. Do not require an installed application package on the host.

Split the scenario into `before_restart(request, expected_vehicle)` and `after_restart(request, state)`. The caller parses the original CSV into plain expected facts. The first stage performs the pre-restart HTTP actions below and returns JSON-serializable state containing discovered dealership/conversation/vehicle IDs, submitted request IDs and exact text, terminal status/bodies, and the fully paged history snapshot. The second stage compares preserved history and replays a completed submission, then issues a fresh follow-up. This state is test evidence, not replacement conversation storage.

The caller exclusively owns import/reimport, app or container startup, readiness, fake configuration, stop/wait/recreation, and cleanup. For integration it closes the first TestClient lifespan before creating a new app/client on the same database; for TCP it waits for container exit before replacement and supplies a new adapter for the discovered port. Configure the restarted external fakes to reject replay-time calls and permit only the later fresh follow-up; no HTTP fault-control endpoint is added. Database-only assertions (selected state and complete model replay units) and fake call-count assertions belong to the surrounding test/support harness, not the portable HTTP driver.

| Ordered action / setup | Expected HTTP, durable state, and evidence |
| --- | --- |
| On a fresh temporary database, run the real offline import CLI with the original CSV and explicit `mia-motors` slug, before server startup | Successful committed import of 127 rows; no source edits. Reimport while stopped yields unchanged records and stable UUIDs. Reuse existing complete mapping assertions. |
| Start app; request health and dealerships | Health succeeds using local storage only; discover UUIDs by slug. No hardcoded UUID, live model call, or automatic inventory overwrite. |
| Search with make Toyota, model RAV4, body type SUV, year min/max 2022, price min/max 26335.00 | AA-1001 appears with matching facts; all five filter dimensions combine. Assert details against the parsed source row, and test a contradictory filter yields an empty list. |
| Create a conversation with `{}`; submit a search request with a fresh UUID and natural-language filters | 201 creation followed by committed 200 reply grounded in real scoped tool results. Count one admitted user and one actual assistant per successful request; verify complete tool-call/result replay unit. |
| Select AA-1001 explicitly, then ask its mileage and drivetrain without repeating its identity | Reply has 15,819 miles and FWD; committed selected vehicle is its UUID. An earlier list search alone must not silently select its first item. |
| Ask recalls, then crash-test ratings | Each reply identifies the selected stock vehicle and reports synthetic upstream facts with source/time and required limitations. Use compatible FWD discovery/detail fixtures; fake data must be labeled in evidence. Validate facts/statuses, not exact model prose. |
| Ask for both with one upstream branch failing; also exercise successful zero recalls and unrated/partial ratings | Useful branch remains present; unavailable differs from verified empty and unrated. Completed explanatory replies are 200; no fabricated safety assurance or omitted failed branch. Detailed permutations remain in step-3 tests. |
| Save history and terminal bodies, stop/recreate app on the same file, then load all history pages | IDs, ordering, messages, request status, selected vehicle, successful replay, and original safety timestamps persist. No duplicated or missing page entries. |
| Retry an earlier completed ID/text while model and NHTSA fakes reject any call | Exact stored JSON status/body; unchanged message counts and zero external calls. JSON equality is required; transport header/whitespace equality is not. |
| Submit a fresh follow-up after restart | Uses persisted selected inventory identity and completed-turn context; new reply commits normally. Failed/interrupted turns never become replayed model input. |

Drive ambiguous inventory ordinal and crash-variant clarification/restart through existing step-2/3 tests rather than lengthening the happy-path demo. Verify ordinal references resolve the displayed list, and safety choices cannot cross vehicle/dealership boundaries. Compare exact committed outcomes on idempotent replay even though fresh generated wording is not fixed.

Exit: the single assignment scenario passes on real temporary SQLite and real HTTP handlers, with scripted external calls. `docs/verification.md` names the source fixture, fake model/transport boundary, test node, and observed outcome. It does not claim live service integration.

## C. Close isolation, failure, and durability gaps

Prerequisites: prior lifecycle and safety suites. Extend their files instead of cloning their implementations. Reuse synchronization events/barriers and test-only injection hooks; never expose fault-control endpoints or fake modes on the ordinary runtime API.

For each row, assert both public outcome and rows read through fresh SQLite sessions. Count model runs and NHTSA calls. Use bounded waits as deadlock guards, not sleeps to arrange races.

| Scenario / controlled fault | Required observable result and recovery |
| --- | --- |
| Two dealerships, including identical stock numbers in labeled synthetic fixtures; swap conversation, vehicle, history, and replay identifiers | Uniform scoped 404/no details where applicable, no unauthorized messages/selection, no wrong-vehicle NHTSA call. Model/tool arguments cannot override trusted dealership identity. |
| Two connection names with distinguishable fakes; change dealership default after conversation creation | Existing conversation uses stored identity; new conversation uses new default. Removing/changing a stored connection rejects new admission with `connection_unavailable`, while history and terminal replay still work without external calls. Missing keys do not break inventory/health. |
| Invalid/unknown input, same-ID same-text race, different-ID active race, same-ID changed text | Baseline 422/404/409 distinctions; rejected requests append nothing. Same accepted identity produces at most one user/reply pair and one model run; terminal replay takes precedence over busy/capacity/connection checks. |
| Model failure, deadline, malformed/unrepairable output, tools/context/output budgets | Sanitized specified 502/504 outcome, admitted user retained, no invented assistant or partial selection; same ID replays failure; a fresh ID can deliberately try again. Assert cumulative attempts including SDK retries. |
| Paused external call, paused DB worker unit, concurrent tools/other conversation | No session/transaction spans external await; each database unit owns/closes its session in its worker thread; health/event loop and unrelated conversation progress. Enforce four active-turn capacity and existing bounds without claiming production throughput. |
| Fault during admission before commit | No partial request/user/claim after rollback, no external execution; transient storage outcome is sanitized. Recover storage and resubmit original ID when no durable admission exists. |
| Fault after assistant insert but before completion commit, or completion commit failure | Prior committed selection/history preserved; no partial assistant/replay/terminal success. Reconcile uncertain outcome by durable request identity. Settle failure if possible; otherwise leave active state for startup recovery. Never return 200 without confirmed committed completion. |
| Actual commit succeeds but response is discarded; cancellation races completion | Stored completed outcome wins; same-ID retry returns it without rerun. Await outstanding database work before interruption settlement. Keep disconnect and observed server cancellation distinct. |
| Storage unavailable or recovery commit fails during startup | No readiness/traffic, no empty replacement database or in-memory success. Restore access and repeat exclusive startup safely; committed data remains. |
| Oversized history/results and increased row counts | Existing SQL filtering/order/limits and bounded/batched query counts hold through serialization. Preserve all stored history while bounding complete model turns; no split tool pair. Record measurements separately from deterministic assertions. |

Add abrupt-stop coverage to the existing/proposed conversation recovery harness:

1. Start the sole child process on a temporary SQLite file, complete a baseline inventory and safety turn, and record committed identities/text/presentation.
2. In a new request gate immediately after confirmed admission commit while external work is pending. Signal readiness to the parent via IPC or an atomic test marker. Force-kill the child (not graceful terminate on Linux), wait for its exit, and only then start its replacement on the intact file.
3. Before readiness, recovery must settle the new request as interrupted, retain its single user message, preserve baseline reply/selection/safety choices, and release the claim. Same ID returns stored 409 `request_interrupted`; zero automatic provider/NHTSA reruns. A new ID completes normally.
4. Repeat with a gate after confirmed completion commit but before response delivery. After forced death, the request remains completed and replays exactly. A pre-commit completion fault must instead leave no partial assistant/evidence.
5. Restart again to prove recovery is repeatable. In `finally`, release gates, stop/join tasks/processes, close clients/engines, and remove only the owned temporary artifacts. A parent failure must not orphan a worker against the database.

Exit: all mapped invariants pass, including real process death. Record graceful recreation, abrupt process recovery, and container volume preservation as separate evidence. Application-object recreation alone cannot satisfy this phase.

## D. Finish the shared verifier and container acceptance

Prerequisites: phases B/C; Docker Desktop ready on Windows. Reuse any harness delivered by steps 2–3.

1. Add standard-library host `scripts/verify.py` as the single complete verification entry point. Resolve the repository root from the script location, run subprocess argument arrays with that working directory, confirm Docker/Compose readiness, and validate Compose quietly. Run `docker compose --profile verify run --build --rm verify` first, then invoke `scripts/verify_containers.py` using `sys.executable`. Stop on either failure and return a nonzero exit; report success only after both phases pass. The inner Compose command remains available for focused checks. Neither inner phase calls the wrapper, and packaging/extraction is not invoked by the wrapper, avoiding recursion. Move the Compose command list to a small `backend/scripts/verify.py` only if needed for structured results, preserving its failure status and `/app` working directory. Mount `backend/scripts/` read-only at `/app/checks/` and root `scripts/` at `/app/scripts/`, and include both in lint coverage. Resolve test-support script paths explicitly for checkout versus `/app` layout; packaging unit tests construct their own temporary source tree rather than assuming the verifier contains a full checkout. Do not put Docker orchestration inside pytest or mount the Docker socket into the verifier.
2. Ensure the inner Compose verifier runs lint, formatting, strict application typing, and all deterministic unit/API/process tests, including the assignment scenario. The complete host wrapper additionally requires container acceptance. Keep development `/data` absent from verifier mounts. Verify lock consistency, and rebuild before final acceptance. Bind-mounted source cannot substitute for testing the actual built runtime image.
3. Add a host-side standard-library `scripts/verify_containers.py` plus standalone `compose.acceptance.yaml` if no equivalent exists. Use a unique `autoassist-acceptance-<random>` project, project-scoped named test volume, and dynamically assigned localhost port. The standalone file must have no development `env_file`, volume, fixed container name, or implicit use of host credentials. Pass a temporary nonsecret config with two fake connections and dummy credential values.
4. Build the normal image from the repository root. Run its real importer with the CSV mounted read-only while no server owns the test volume. Start its normal application factory through a test-only launcher mounted from test support that injects the scripted model/NHTSA transport. Application modules and dependencies must come from the built image, not host source mounts. Test hooks never enter the runtime image or become a production environment flag.
5. Resolve the published port from Compose, poll `/health` with a bounded deadline, and fail promptly if the service exits. Execute phase B's `before_restart` using the urllib adapter. Stop the original container and wait for exit; recreate it preserving the test volume, rediscover the port, and run `after_restart` with the returned state and a new adapter. The host harness owns all lifecycle operations. Run a forced container-kill case gated after admission as in phase C, proving the actual Docker/volume boundary. Do not start two workers against one volume.
6. On success or failure, collect sanitized results and remove only resources whose exact IDs and Compose project labels match this run. Capture failure diagnostics without inspecting environments or expanded secret-bearing config. Ordinary runtime shutdown stays `docker compose down`; any volume deletion is restricted to verified disposable acceptance resources. Never use global prune.
7. Prove failures propagate through `python scripts/verify.py`: run an intentionally failing pytest case in an isolated copy and require a nonzero host exit without starting container acceptance; remove that fixture afterward. With the inner verifier passing, make the acceptance server fail readiness in an isolated run and require the complete wrapper to fail and the harness to clean up. No permanent always-failing test or production fault switch.

New command, runnable only after this phase exists, from repository root:

```powershell
python scripts/verify.py
```

The script uses standard-library host Python 3.13 and Docker CLI; backend dependency tools stay in the image. On Windows it may be invoked with `py -3.13` where `python` is not on PATH. Document this host-Python prerequisite for acceptance tooling separately from Docker-only application setup. Bound each subprocess and readiness wait; emit progress and a final nonzero result on failure. Permit build network access, but no real model/NHTSA access in deterministic execution.

Exit: a clean locked image, actual published HTTP API, writable UID-10001 volume, graceful recreation, abrupt container recovery, and failure exit propagation all have recorded evidence. The development database is untouched.

## E. Add GitHub Actions using the same checks

Prerequisite: shared verifier and host container harness work locally.

1. Create `.github/workflows/verify.yml` for `push`, `pull_request`, and `workflow_dispatch`, with `contents: read`, no service secrets, and a bounded job timeout (initially 20 minutes). Use an Ubuntu runner with Docker/Compose and host Python 3.13. Resolve maintained checkout/setup-python/upload-artifact releases from their official repositories during implementation, pin full commit SHAs, and comment the release versions. No guessed SHA or unpinned action tag.
2. Checkout, provision host Python, then run the exact complete command `python scripts/verify.py`; the wrapper owns readiness/configuration checks, the inner Compose verifier, and container acceptance in that order. Do not duplicate these invocations in workflow steps. Do not call the Windows Desktop startup command on Linux or create a separate CI-only pytest selection.
3. Preserve default failure propagation; no `continue-on-error` on required checks. Let the harness own cleanup even on failure, and add a final narrowly scoped cleanup only if needed for interrupted jobs. Upload only explicitly sanitized reports when available, with a short retention (7 days); no databases, full environment dumps, credentials, raw chat/provider logs, or user prompt history.
4. Validate YAML and referenced commands locally. If this work is already pushed through an authorized workflow, record an actual run link and status; otherwise record CI configuration/local equivalent verified, remote execution pending. Creating the workflow does not authorize pushing or publishing the repository.

Docker documents that one-off Compose runs propagate the container command's exit status and support `--build`; retain that behavior in wrappers. GitHub documents workflow permissions and artifact storage. Sources: [Compose run](https://docs.docker.com/reference/cli/docker/compose/run/), [Compose FAQ](https://docs.docker.com/compose/support-and-feedback/faq/), [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [workflow artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data).

Exit: the workflow references the same passing local checks, has no live-service dependency, and required failures fail the job. Report remote CI evidence separately from local execution.

## F. Complete documentation and the walkthrough

Prerequisites: final implemented contract and phase B–E results. Draft alongside earlier phases; finalize after checks.

1. Rewrite `README.md` around the delivered API. Cover prerequisites, locked local/Docker setup, server-owned connection configuration and secret environment references, dealership discovery, explicit stopped-server real CSV import, health/docs URLs, and ordinary stop/restart. Preserve explicit schema recreation as a separate destructive operation; do not include reset in the happy path. Explain missing/placeholder connection behavior and stored connection identity across configuration changes.
2. Make PowerShell examples executable: use `Invoke-RestMethod`, hashtables and `ConvertTo-Json` for bodies; discover UUIDs and assign `request_id` once per intentional submission. Demonstrate creation, combined chat search, stock selection, follow-up, recalls, ratings, history paging, preserved-ID replay, terminal failure versus new attempt, and continued conversation after restart. Match real request bounds, response schemas, money strings, and error envelopes. Keep a compact API operation/status table instead of embedding every full payload.
3. Update `docs/architecture.md` with actual final module paths and one sequence diagram: scoped admission commit → external tools/model with no open transaction → atomic completion commit → response; show failure/recovery ownership. Explain deterministic rendering/evidence, library-specific replay boundary, selected vehicle and displayed-choice persistence, lifespan-owned clients, named connections, thread/session ownership, and one-worker SQLite capacity. Keep it concise enough to walk through.
4. Record limitations accurately: local dealership scope is not authentication; NHTSA year/make/model data is not VIN recall applicability or repair status; ratings need compatible variants, may be partial/unrated, and are not safety guarantees. Include source freshness/truncation, unsupported safety categories, request bounds, creation's lack of idempotency, no automatic interrupted-run resumption, loss of uncommitted provider output, no multi-worker/HA/backup guarantee, and the optional frontend's omission. Remove only obsolete pending-feature statements.
5. Add `docs/demo.md` as a 30–60 minute walkthrough outline: 5 minutes setup/scope, 10 API demo, 10 code/data boundaries, 10 safety/grounding, 10 durability/tests, remaining discussion. Link exact test nodes and source files. Include a short deterministic demo route and a separately labeled live route; do not portray scripted responses as live model intelligence.
6. Use `docs/verification.md` for dated command/results, source snapshot identifier, runtime/package versions, requirement coverage, fake-versus-live boundaries, container/process evidence, and actual gaps. No hardcoded passing test count until execution. Keep verbose temporary logs out of the source ZIP.
7. Reuse steps 2–3's optional live smoke procedure on isolated storage with credentials supplied privately at runtime. Verify direct live NHTSA separately, then Grok-driven search → selection → both safety questions → follow-up. Record date/model/version, returned inventory identity, source facts and categorized outcome; allow changing recall counts/ratings. Missing key, service outage, or account/model access blocks that live check only and must be stated plainly. Do not inspect `.env` or ask for credentials in chat. Do not add live tests to CI.

Exit: run the documented clean setup and HTTP examples against the completed app; examples resolve real IDs and expected outcomes. All delivered features and omissions agree with code/OpenAPI/evidence. A reviewer can distinguish deterministic correctness, container execution, and live-service validation.

## G. Build and validate the submission ZIP

Prerequisites: required deterministic checks pass and documentation reflects results. Live gaps may remain only when explicitly recorded; required application failures cannot be relabeled as live gaps.

1. Implement standard-library `scripts/package_submission.py` with `--output <zip-path>`. Resolve the repository root relative to the script, independent of working directory or Git metadata. Create a single top-level `AutoAssist/` archive directory with portable relative paths. Write to a temporary sibling and rename only after validation; refuse an existing output rather than silently replacing it. Failure leaves no apparently complete ZIP.
2. Use explicit include roots/files: `README.md`, `AGENTS.md`, `.env.example`, `.gitignore`, `.dockerignore`, `Dockerfile`, `compose.yaml`, `compose.acceptance.yaml`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/src/`, `backend/tests/`, `backend/scripts/` if created, `config/dealerships.json`, `scripts/`, `.github/workflows/`, `docs/architecture.md`, `docs/stack-baseline.md`, `docs/demo.md`, `docs/verification.md`, `docs/context/inventory/`, and relevant `docs/plans/` Markdown. Include `.agents/skills/` because project instructions/plans reference it. Missing required files fail packaging; only deliberately conditional paths may be absent.
3. Independently reject secret/local/generated paths inside allowed roots: `.env` and non-example variants, keys/certificates, all SQLite databases and sidecars, `.git`, virtual environments, `node_modules`, Python caches, build/dist/output folders, logs, coverage output, ZIPs, and `prompt history/`. Reject symlinks/reparse-point files or directories and resolved paths outside the root; reject absolute/traversal/case-colliding archive names. Keep this filtering active even for Git-tracked files. `.dockerignore` is not a submission manifest.
4. Check allowed text/config for obvious credential assignments/private-key blocks without printing values; report filenames/categories. This is an additional check, not a proof that arbitrary secrets cannot exist. Manually review `.env.example`, packaged config, and chosen docs for placeholder-only credentials. Document AI assistance concisely; prompt history is not required as submission evidence.
5. Sort archive members and compute SHA-256. Emit adjacent manifest/checksum files listing member paths and source-content hashes plus build date/source revision when available and an explicit dirty-worktree indication. Do not imply a Git commit captures uncommitted contents. Validate member CRCs and required members before completing output. Tests use synthetic secrets/DB/cache/reparse/traversal cases and missing required files to prove filtering and failure behavior; no actual secret needed.
6. Extract the ZIP into a new temporary directory outside the checkout, verify member hashes, and run `python scripts/verify.py` from the extracted `AutoAssist/` root, covering both inner verification and container acceptance. There must be no dependency on `.git`, original absolute paths, ignored local files, development `.env`, or undeclared host dependencies; host Python 3.13 and Docker/Compose remain prerequisites. Confirm the preserved CSV hash equals the repository source. Follow README setup using a fresh isolated acceptance volume; do not run its normal development project against the user's volume.
7. On a packaging/extraction failure, fix the manifest/docs/source issue and rebuild/recheck the affected artifact. Save final verification results outside the tested archive with its exact SHA-256; do not modify an archive after testing it. If documentation inside must change, regenerate and rerun extraction checks so evidence identifies the delivered bytes. Final local handoff includes ZIP, checksum, concise evidence and any live/remote-CI gap. Do not send it to Mia Labs automatically.

Proposed commands, only runnable after implementation, from repository root:

```powershell
python scripts/package_submission.py --output dist/AutoAssist-source.zip
```

Add `dist/` to `.dockerignore` as well as its existing Git exclusion so local submission artifacts do not expand image build context. The package script creates the output directory and reports absolute output paths. Add its meaningful packaging tests to the shared pytest discovery and its code to Ruff coverage; no additional runtime package is required.

Exit: the exact ZIP delivered passes CRC/member/hash checks and clean-extraction verification, includes the original CSV and lockfile, and excludes secrets, local state, and dependencies. The final checksum/evidence refers to the delivered bytes.

## Execution commands and final completion gate

Existing focused checks and Docker preparation, working directory `C:\Users\shane\Documents\Apps\LlmChatBot` (the inner Compose check alone does not establish full acceptance):

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

After phase D is implemented, the single complete verification command for local handoff, README instructions, CI, and clean-extraction acceptance is:

```powershell
python scripts/verify.py
```

On Windows, `py -3.13 scripts/verify.py` is equivalent when needed. This command is planned, not currently runnable. Extend lint targets for newly added host scripts in the inner Compose command and document the corresponding local invocation. Frozen builds may require network access to package/image registries; deterministic tests require no provider keys or live safety endpoints. If Docker startup fails, inspect supported Desktop logs/runtime state; do not reset or delete application data.

- [ ] A: current prerequisite implementation reconciled; requirement-to-test map complete.
- [ ] B: real import and complete grounded HTTP flow pass with external fakes.
- [ ] C: scope/routing/failure/commit/replay/cancellation and abrupt process checks pass.
- [ ] D: shared verifier and disposable container recreation/kill checks pass; failures propagate.
- [ ] E: workflow uses identical checks; actual remote execution status reported honestly.
- [ ] F: setup/examples, architecture, demo, omissions, and dated evidence agree with code.
- [ ] G: final source ZIP passes clean-extraction checks and has a verified checksum.
- [ ] Scoped final diff review finds no unresolved required defects, secret leakage, or unrelated edits; update roadmap status only with implementation evidence.

Planning validation: inspected roadmap/baseline, prior plans, current routes/app/provider seam, manifests/container configuration, test inventory and CSV, and backend-verification/Docker/persistence/API-contract guidance. Checked current official Compose and GitHub workflow documentation. No application code, dependencies, development database, tests, containers, remote workflow, live model call, or submission ZIP was changed/run for this planning request. The only new deliverables are this plan, its roadmap link, and the required prompt log. No additional product decision is needed; live credentials and a remote workflow run are external evidence dependencies only.

Review revision: resolved the two execution-contract findings in [the plan review](step-4-plan-review.md). The planned host wrapper owns complete verification across local, CI, and extracted-source runs; the portable scenario has explicit adapters, stage state, and caller-owned lifecycle. Reviewed these references for consistency; no scripts were implemented or acceptance checks run for this revision.


Frontend implementation coordination (2026-09-10): `scripts/verify.py`,
`Dockerfile.verify`, and `.github/workflows/verify.yaml` now provide the shared
Docker verification entry point, including frontend checks and browser restart
acceptance. Reuse/extend these during step four; packaging and handoff remain in
that step's scope. Do not add another host wrapper or CI check list.
