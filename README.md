# AutoAssist

AutoAssist is an LLM-powered dealership chatbot prototype for the Mia Labs take-home
interview. It exposes a durable, dealership-scoped inventory and conversational HTTP API backed
by OpenAI by default, with optional Gemini and Grok connections. Selected-vehicle safety questions retrieve NHTSA recalls and crash ratings, with
attributed evidence and restart-safe variant clarification.

## What works

- FastAPI application factory with no import-time database or provider calls.
- File-backed SQLite storage through synchronous SQLAlchemy 2 sessions.
- Atomic bootstrap of configured dealerships with stable persisted UUIDs.
- Any number of named OpenAI/Google/xAI connection definitions, with one default per dealership.
- Combined make, model, body type, year, and price filtering.
- Bounded UUID cursor pagination and dealership-scoped vehicle detail lookup.
- Bounded, validated CSV import with atomic dealership-scoped upserts and stable vehicle UUIDs.
- Imported trim, condition, mileage, color, drivetrain, transmission, and fuel on vehicle details.
- Explicit `404`, `422`, and sanitized storage `503` responses documented in OpenAPI.
- Durable conversations, messages, selected vehicle context, and terminal request replay.
- Idempotent request IDs with distinct in-progress, conflict, busy, and interrupted outcomes.
- Native OpenAI Responses, Google, and xAI/Pydantic AI integrations with typed inventory tools and application-rendered facts.
- Grounded search, exact stock lookup, numbered-list follow-ups, and bounded whole-turn replay.
- Startup recovery for interrupted requests and a four-turn process-wide capacity limit.
- Docker runtime with one non-root worker and a named data volume.
- Localhost React chat with durable-history restoration and explicit request recovery.
- Locked dependencies and focused Ruff, strict mypy, and pytest checks.

The assignment inventory is preserved at `docs/context/inventory/data.csv`, with its provenance,
schema, and import mapping documented in `docs/context/inventory/README.md`. A fresh database still
starts with no vehicles until the explicit offline import is run. Synthetic records exist only
inside isolated tests.

## Prerequisites

- Docker Desktop on Windows with Docker Compose v2+, or
- Python 3.13 and uv 0.8.13 for local development.

No provider key is required for inventory, health, or existing history/replay reads. Creating a new
conversation requires the selected dealership connection's key. The checked-in primary model is
[`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna). Add an OpenAI
API key to `OPENAI_API_KEY` in the ignored root `.env` before starting Docker. The model supports
the Responses API, function calling, and structured outputs; OpenAI lists no free-tier access for
it, so the API account needs available credit.

## Run with Docker

From the repository root:

```powershell
docker desktop start --detach --timeout 120
docker info
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build -d backend
docker compose ps
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/dealerships
```

The API and interactive documentation are available at `http://localhost:8000` and
`http://localhost:8000/docs`. Stop normally without deleting data:

```powershell
docker compose down
```

The `autoassist-data` named volume retains the SQLite database across container and image
recreation. Do not run overlapping backend containers against this volume.

## Run locally

From the repository root:

```powershell
uv sync --project backend --frozen
uv run --project backend uvicorn autoassist.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Local defaults read `config/dealerships.json` and create `data/autoassist.db`. Settings can be
overridden with `AUTOASSIST_CONFIG_FILE` and `AUTOASSIST_DATABASE_URL`. Local runs read
process environment variables: set `OPENAI_API_KEY` in your shell before running the server.
Docker Compose loads the root `.env` automatically.

## Import the assignment inventory

Stop the API first. The required `--server-stopped` flag is an explicit acknowledgement that no
server or other importer is using the target SQLite database. Import locally from the repository
root:

```powershell
uv run --project backend autoassist-import-inventory --file docs/context/inventory/data.csv --dealership mia-motors --server-stopped
```

For Docker, stop the backend and run the importer as a one-off container against the same named
data volume, mounting only the input file read-only:

```powershell
docker compose stop backend
$inventoryCsv = (Resolve-Path docs/context/inventory/data.csv).Path
docker compose run --rm --no-deps -v "${inventoryCsv}:/tmp/inventory.csv:ro" backend autoassist-import-inventory --file /tmp/inventory.csv --dealership mia-motors --server-stopped
docker compose up -d backend
```

The importer accepts UTF-8 CSV up to 20 MiB and 50,000 data records with the exact documented
header. `stock_number`, `year`, `make`, and `model` are required. Price is optional but, when
present, must be a nonnegative whole US-dollar amount; mileage must be a nonnegative whole number.
Blank optional values remain null. The file has no dealership column, so every run requires one
configured dealership slug.

The complete file is parsed and validated before storage setup. One transaction then inserts new
source IDs, updates changed rows, leaves identical and absent rows untouched, and retains existing
vehicle UUIDs. Success prints inserted/updated/unchanged counts only after commit. Validation,
write, lock, or commit failure returns nonzero without a partial batch. After an uncertain outcome,
stop competing processes and rerun the same file; the upsert converges without creating duplicates.

## Configuration

`config/dealerships.json` is server-owned configuration. `connections` maps arbitrary names to
`provider`, `model`, and the name of an environment variable containing its credential.
Each dealership has a unique slug/name and references one configured default connection.
Connection names are trimmed; names that collide after trimming are rejected before startup
writes instead of silently selecting one definition.

Startup validates the entire file before writing. In one transaction it inserts new slugs and
updates names/default references while retaining dealership UUIDs; it never deletes absent
dealerships or inventory. Startup fails if an absent persisted dealership refers to a removed
connection. Missing credentials leave that connection chat-unavailable without breaking
inventory, health, or stored terminal replay. Set `OPENAI_API_KEY` for both default dealerships;
optional connections use `GEMINI_API_KEY`, `XAI_API_KEY`, and `SECONDARY_XAI_API_KEY` in the
ignored root `.env`.
Credential values are never stored in SQLite or returned by
the API. A conversation pins its connection name, provider, and model; changing that identity
never silently reroutes an existing conversation. Start a new conversation to use OpenAI after
switching the default; no database reset is needed. OpenAI uses the Responses API with a 30-second
SDK timeout and no SDK retries within the shared whole-turn deadline and tool/output budgets.
There is no automatic provider failover.

Gemini's wire schema describes array-size limits in field descriptions because its
API rejects the nested `maxItems` constraints in our final-answer schema. Pydantic
still enforces all array limits on returned answers; token and tool budgets also remain.

## API examples

Discover the persisted dealership UUIDs:

```powershell
curl.exe http://localhost:8000/dealerships
```

Set one returned UUID, then search. All supplied filters combine with AND; text comparison is
trimmed and case-insensitive, and numeric ranges are inclusive.

```powershell
$dealershipId = "REPLACE_WITH_RETURNED_UUID"
curl.exe "http://localhost:8000/dealerships/$dealershipId/vehicles?make=Toyota&model=Camry&body_type=Sedan&year_min=2020&year_max=2024&price_min=20000.00&price_max=35000.00&limit=20"
```

Continue a live-inventory page with the returned `next_after`, keeping filters unchanged:

```powershell
$after = "REPLACE_WITH_NEXT_AFTER"
curl.exe "http://localhost:8000/dealerships/$dealershipId/vehicles?make=Toyota&limit=20&after=$after"
```

Retrieve a vehicle returned by search:

```powershell
$vehicleId = "REPLACE_WITH_VEHICLE_UUID"
curl.exe "http://localhost:8000/dealerships/$dealershipId/vehicles/$vehicleId"
```

The detail response adds nullable `trim`, `condition`, `mileage`, `exterior_color`, `drivetrain`,
`transmission`, and `fuel` fields. Search results retain the smaller summary shape.

Prices are nullable two-decimal strings. A price or body-type filter excludes rows whose value is
unknown. Empty valid searches return `200` with an empty `items` array. Cursor pagination is
bounded and stable by UUID but is not a historical snapshot.

Create a conversation and send a message with a client-generated UUID:

```powershell
$conversation = curl.exe -sS -X POST "http://localhost:8000/dealerships/$dealershipId/conversations" -H "Content-Type: application/json" -d '{}'
$conversationId = ($conversation | ConvertFrom-Json).id
$requestId = [guid]::NewGuid().ToString()
curl.exe -X POST "http://localhost:8000/dealerships/$dealershipId/conversations/$conversationId/messages" -H "Content-Type: application/json" -d "{\"request_id\":\"$requestId\",\"text\":\"Show me Toyota sedans under 35000 dollars\"}"
```

Use a new request ID for a deliberate follow-up such as `Tell me about the second one` or
`What is the price of stock MIA123?`. Reuse the original ID and exact text only for a transport
retry: a terminal outcome is replayed from storage without another model run. Reusing an ID with
different text returns `request_id_conflict`.

Page the durable public history independently of model-context trimming:

```powershell
curl.exe "http://localhost:8000/dealerships/$dealershipId/conversations/$conversationId/messages?after_sequence=0&limit=50"
```

Admitted failed or interrupted user messages remain visible with their request state and no
fictional assistant message. A provider failure is terminal for that request ID; retrying the same
ID discovers the stored failure, while a deliberate retry uses a new ID.

## Verification

The shared container check uses temporary storage and never mounts the development volume:

```powershell
python scripts/verify.py
```

The HTTP/recreation acceptance harness imports the assignment CSV, uses a test-only injected
runner, recreates the backend while retaining a uniquely named disposable volume, verifies terminal
replay and a selected-vehicle follow-up, then removes only that disposable volume:

```powershell
.\scripts\verify-chat-container.ps1
```

Equivalent focused local checks are:

```powershell
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
uv run --project backend mypy backend/src
uv run --project backend pytest backend/tests -q
```

Tests use real temporary SQLite files. The backend suite covers configuration rollback,
foreign keys, combined filters and pagination, tenant isolation, HTTP validation/OpenAPI,
constant-query search behavior, event-loop responsiveness, the full 127-row assignment mapping,
bounded/corrupt inputs, repeat-import UUID stability, changed/absent rows, write and commit
rollback, lock contention, abrupt process termination before commit, and API preservation across
application recreation. Regression tests also cover normalized connection-name collisions,
locked-storage health/error responses and recovery, and propagation of schema defects.
Conversation coverage adds write-first admission, terminal success/failure replay, exact payload
identity, paging, tenant isolation, connection pinning, cancellation, abrupt-process recovery,
provider saturation, grounded tool exchanges, invalid factual-output repair, and relational
constraints. The shared
Linux container verifier runs the same suite. Live Grok account/model access remains an opt-in
smoke boundary and was not exercised by deterministic verification.

## Database reset and schema changes

There is deliberately no migration framework in this prototype. Ordinary startup creates missing
tables and preserves existing data. After a schema change, explicitly recreate only the intended
development database.

Startup now checks required columns and named index definitions on every existing
application table before bootstrap/recovery writes. An incompatible schema fails
with an explicit backup/recreation instruction. Health queries every mapped column,
so a table with missing detail fields cannot report healthy merely because its ID
column exists. This is validation, not automatic migration.

Step 2 adds conversation, request, and message tables. `create_all` can add those tables to the
current step-1 database, but it does not alter incompatible existing tables. Recreate a development
database whenever its schema differs from the current models; startup never performs migrations.

For Docker, first stop the service, resolve its exact Compose volume name with
`docker volume ls`, and remove only that development volume before starting again. For local use,
stop the server and delete only `data/autoassist.db` and its SQLite sidecar files. Neither normal
shutdown command performs a reset.

Prefer preserving a timestamped backup of the stopped database and its sidecars
before recreation when any conversations should be retained. Reimport the assignment
CSV before claiming that the demo is inventory-ready. Validate the running backend:

```powershell
python scripts/check-setup.py
```

This read-only operator check returns nonzero for failed health, a missing dealership,
failed inventory queries, or empty inventory. It checks `mia-motors` by default;
`--url` and `--dealership` choose another target. Health intentionally does not require
inventory rows or live provider calls. Automated browser acceptance proves this check
fails before import and passes after import in isolated storage.

## Design decisions and limits

- Errors from inventory tools retain their application/storage category. Only errors
  from the external model call and model-output/retry exhaustion become provider
  failures. A tool storage failure is saved as a failed `503 storage_unavailable`
  outcome when request storage remains writable; local code/schema bugs settle as
  `500 internal_error`. If failure settlement cannot commit, the outcome remains
  uncertain and follows the existing reconciliation/restart recovery behavior.
  Corrupt persisted model history is an internal error before any provider call;
  it is never reported as a provider outage.
- Partial startup closes provider clients already constructed when a later provider
  initialization fails. Startup failure never silently leaves those clients owned by
  an application that did not become ready.

- One Uvicorn worker owns one SQLite volume. Five-second SQLite lock waits, page size at most 100,
  four concurrent model turns with no queue, and SQL-side filtering are deterministic bounds, not
  throughput claims.
- Synchronous route functions let FastAPI run each complete database unit in a worker thread.
  Services create, materialize, and close their own sessions and return immutable records rather
  than ORM objects.
- Routes map validation/results. `ConversationService` owns asynchronous lifecycle orchestration;
  `ConversationStore` owns synchronous session/transaction units and write serialization;
  `ConversationRepository` owns SQL and ORM mutations without committing. Scoped reads and
  admission require the dealership; completion uses the already admitted request identity.
  Inventory services likewise own sessions and transactions around their repositories.
- Admission is a write-first scoped insert, so SQLite claims a request before provider work. Short
  writes are serialized in-process to avoid SQLite lock-upgrade collisions; no transaction spans a
  provider wait.
- Cancellation drains owned admission/completion threads before settling interruption or releasing
  capacity. A committed completion wins. Admission commit errors are reconciled by internal request
  identity in a fresh session, so a duplicate caller cannot interrupt another caller's turn.
- Each provider run has a 60-second outer deadline, 30-second model client/tool timeouts, at most six
  model requests and eight tool calls, 2,048 output tokens per response, 16 KiB tool results,
  64 KiB retained whole-turn history/replay units, 128 KiB per model request, and an 8,000-character
  public reply. These are deterministic resource guards, not throughput measurements.
- Input accounting serializes the complete Pydantic AI request envelope before every call, including
  instructions, schemas, settings, and accumulated tool/repair messages. The xAI gRPC client also
  caps each encoded outbound message at 128 KiB. No payload is truncated to fit.
- Inventory facts are rendered from repository records after structured output validation. The
  model chooses intent, evidence IDs, and requested fields but cannot publish its own price or
  specification values. A list may contain only IDs from the latest search result set; earlier
  searches and retained follow-up evidence cannot authorize a nonmatching list. Multiple searches
  in one turn use the last result set, not a union. This does not guarantee that a model interprets
  every natural-language filter correctly.
- Selection/details resolve exact stock tokens (for example `AA-1001`) or numbered choices
  (`the second one`, `option 2`, `#2`) against retained presentation order. Conflicting, unavailable,
  or out-of-range references require clarification. Unqualified detail follow-ups use the existing
  selection; a new search does not inherit it. This deliberately conservative reference handling
  may ask for a stock/list number for other descriptions. Presentation and replay use the same
  latest-ten-turn, 64 KiB suffix, so discarded lists cannot authorize ordinal choices.
  A successful, resolved detail answer always retains that vehicle as the selection, even if
  the model omits a selection action; the next pronoun follow-up uses the committed selection.
- Startup marks leftover `in_progress` requests `interrupted` before serving traffic. Automatic
  provider reruns, exactly-once execution, and preservation of uncommitted output are not promised.
- Local dealership IDs are routing scope, not authentication or production authorization.
- Health performs bounded reads across the mapped tables, so inaccessible storage cannot pass
  readiness merely because SQLite can evaluate a constant expression.
- SQLite busy/locked, cannot-open, I/O, full-disk, and read-only operational errors map to a
  sanitized `storage_unavailable` response using SQLite result codes. Unexpected SQL/schema
  failures propagate as server errors with diagnostics rather than being mislabeled as 503.
- The importer intentionally requires exclusive server downtime rather than coordinating live
  writes. It never deletes vehicles missing from a file; this is an upsert, not snapshot sync.
- Automated backups, multi-worker coordination, production
  authentication, conversation-creation idempotency, and automatic interrupted-run resumption
  remain pending.

See `docs/architecture.md` and `docs/plans/product-roadmap.md` for the implemented boundary and
remaining slices.

## NHTSA safety conversations

Use the existing message endpoint: `Select stock AA-1001`, then `What are its recalls and crash
ratings?`, with a new request ID for each turn. For ambiguous variants, reply with a displayed
NHTSA ID or exact description. Up to five choices are shown; a descriptor can locate another
variant, which is then presented for explicit confirmation. Fresh discovery revalidates each
choice. A choice cannot override a known model or drivetrain conflict.
Identical descriptions require a displayed ID. While NHTSA choices are pending, a bare
ordinal refers to that list; name the stock or explicitly say `first vehicle` to refer to
inventory instead. An explicit stock reference takes precedence over pending choices.

Application code renders safety facts from validated tool evidence. Both requested branches
appear even when one fails. Explanatory unavailable replies can complete with HTTP 200; outer
deadline/model failures retain 504/502 behavior. Same-ID replay returns the original dated answer
without calling either external service.

- Recalls distinguish campaigns, verified empty results, and unavailable data. Model-level
  campaigns do not establish VIN applicability or repair completion. At most five campaigns are
  displayed, urgent first, with explicit excerpts/omissions and urgency counted across all records.
- Crash results distinguish available, partial, explicitly unrated, incomplete/no-ratings,
  no matching record, ambiguous, and unavailable. Invalid values never become zero stars.
  Matching preserves semantic model suffixes and drivetrain distinctions; unknown qualifiers
  require confirmation. There are no guessed aliases or nearest-year substitutions.
- Supplemental concern/warning fields retain upstream labels; known forward-collision equipment
  is excluded. Coverage is incomplete, and missing notes do not prove no safety concerns.
  Ratings are individual results, not guarantees or rankings; inventory lacks comparison weight.
- Source links and UTC retrieval/attempt times accompany answers. There is no cross-turn cache,
  automatic retry, VIN lookup, bulk scan, or background refresh.
- One pooled HTTPX client permits eight connections/four keepalives. Connect/read/write/pool
  timeouts are 2/5/2/1 seconds; the whole request cap is seven seconds. A turn has at most three
  GETs and 20 seconds cumulative NHTSA time, reserving the final ten seconds of its outer deadline.
  Decoded responses are capped at 512 KiB, discovery at 100 variants, and recalls at 200 records.
  Recall/crash evidence fits 12/8 KiB within the existing 16 KiB tool result limit.
- Choices commit with the reply, evidence, selection, and terminal response. Every production
  turn records keep/clear/set metadata within bounded complete-turn replay. Changing or clearing
  inventory selection invalidates choices, including A to B to A. Trimming the original set
  cannot resurrect it from keep actions. No database schema change or startup reset is needed.

Deterministic acceptance uses the real CSV, fake externals, and a disposable project/volume/port:

```powershell
./scripts/verify-chat-container.ps1
```

Opt-in live NHTSA/chat check using the configured default (OpenAI), a temporary database,
and runtime Compose secrets. A failed chat step exits nonzero:

```powershell
docker compose -f compose.safety-live.yaml run --build --rm safety-live
```

For NHTSA only, append `python smoke-safety.py`. This is excluded from normal pytest/CI.
Do not read or print `.env`; Docker supplies it at runtime. See
[step-three evidence](docs/plans/step-3-implementation-evidence.md) for results and the live Grok gap.

## Localhost chat frontend

After configuring a backend chat connection and importing `docs/context/inventory/data.csv`
using the instructions above, launch the browser UI:

```powershell
docker desktop start --detach --timeout 120
docker info
docker compose up --build -d backend frontend
```

Open http://localhost:5173. The header displays the backend's Mia Motors name. Enter sends;
Shift+Enter inserts a line break; IME composition does not submit. Ask for inventory, select a
vehicle, and ask detail, recall, or crash-rating follow-ups. Responses preserve backend text,
including ambiguity choices, sources, missing data, and recall qualifications. Stop normally
with `docker compose down`; the database survives. No permissive CORS or public hosting is used.

The development image pins Node 22.13.1/npm 10.9.2, runs as `node`, installs with `npm ci`, and
keeps dependencies inside the container. Rebuild after dependency/config changes; source edits
under `frontend/src` are mounted read-only for Vite. Host development uses Node 22.x (at least
22.13.1), `npm ci --prefix frontend`, then `npm run dev --prefix frontend`, alongside the local
backend command above. Only the Vite server reads `API_PROXY_TARGET`; it defaults to
`http://127.0.0.1:8000`, while Compose uses `http://backend:8000`. Browser requests always use
`/api`. No provider credentials belong in frontend environment variables. The backend turn
budget is 60 seconds, proxy response/socket deadlines are 120/125 seconds, and browser writes
wait at most 135 seconds; reads wait 15 seconds. A write timeout has an unknown outcome.

Only the most recent conversation pointer and unresolved request ID/exact text are stored in
local storage, scoped to browser origin and dealership. SQLite owns the transcript. Reload
restores server history before sending is enabled; each action loads up to ten 100-message
pages. Continue loading handles longer conversations or failed pages without dropping earlier
messages. If a reply is unconfirmed, Check reply retries the same identity once and reconciles
history. Busy rejections preserve the unaccepted submission. Failed/interrupted admitted turns
remain visible without a fabricated reply; Try again places the text in the composer, and Send
makes a deliberate new attempt with a new ID. New chat clears only the browser pointer and
creates lazily on the next Send. A validated missing-conversation response permits New chat
recovery and retains pending text as an editable draft. A proxy/network error does not establish
that a conversation is missing. Storage warnings mean reload recovery cannot be promised.

The single shared verification command is `python scripts/verify.py` (or `python3` on Linux).
It builds and invokes `docker compose --profile verify run --rm verify`; the same command runs
in `.github/workflows/verify.yaml`. The verifier combines backend checks with frontend static,
fresh-schema drift, build, and Chromium tests, using only temporary databases and deterministic
external fakes. It never mounts the development database volume. Its image includes both locked
runtimes and Chromium; the first build downloads browser dependencies. Rebuild verification
images after source changes, as the wrapper does automatically.

Focused frontend commands (from `frontend/`):

```text
npm ci
npm run dev
npm run typecheck
npm run lint
npm run format-check
npm run build
npm run api:generate
npm run api:check
npx playwright install chromium
npm test
npm run verify
```

API generation requires the backend's uv environment and calls `create_app().openapi()` without
lifespan, credentials, network access, or database creation. `api:check` generates into temporary
storage and compares without rewriting source. Browser smoke uses ports 5173 and 18081 and
starts/stops its own backend process; stop a host Vite server before running it. API-mocked tests
prove UI recovery states; `frontend/tests/backend.spec.ts` imports all assignment rows, runs
real API/inventory/safety application code with external fakes, restarts the sole backend process
with retained SQLite, reloads the browser and continues. This is distinct from live-provider proof.

Frontend omissions: authentication, multiple-chat browsing, server streaming, cancel/edit/regenerate,
attachments, voice, rich markdown/HTML, vehicle cards, multi-tab coordination, and production
hosting. Source URLs remain safely selectable plain text. Losing an unconfirmed conversation
creation can leave an empty orphan conversation. A browser that cannot persist local storage
cannot reliably recover an unresolved submission after reload.

Completed replies open at their beginning instead of forcing the transcript to the final line.
Scrolling into older history preserves the reader's position and exposes a Jump to latest control.
Newly submitted replies use a fast, bounded client-side text reveal (at most 700ms); this cosmetic
effect starts only after the full non-streaming response arrives and is skipped for reduced motion
and restored history.

Frontend evidence is recorded in [implementation evidence](docs/plans/frontend-implementation-evidence.md).
The 2026-09-11 isolated live check completed inventory, selection, combined NHTSA recalls/ratings,
and a price follow-up, including recovery from observed 503 responses. External availability
and model output remain fallible; this is evidence of a working flow, not an uptime guarantee.
After switching providers, a second isolated live check asserted `primary-openai` and
`gpt-5.6-luna`; OpenAI's completed Responses result also reported `gpt-5.6-luna`. The full four-turn
inventory, selection, NHTSA, and price flow then completed with HTTP 200 throughout.
See [fix evidence](docs/plans/manual-test-fixes.md) for regression and verification results.
The subsequent backend responsibility refactor passed the full shared checks, but two fresh
live rehearsals timed out during selection after Gemini 503/504 responses. Direct NHTSA and
inventory search succeeded. See [current backend review](docs/reviews/2026-09-11-backend-presentation-readiness.md)
for the new module boundaries, regression evidence, and remaining live-demo limitation.

### Live-provider recovery

Manual testing reproduced Google HTTP 503 `UNAVAILABLE` caused by model demand and HTTP 504
gateway timeouts. Gemini retries these generation failures, at most three attempts, with 1s/2s
backoff; SDK retries
remain disabled. Numeric `Retry-After` up to 5s is honored; longer, date-form, or malformed
values end the attempt instead of retrying early. Other statuses and ambiguous transport
failures are not retried. Tools already executed and database writes are never rerun by this
retry loop. Six logical model requests therefore permit at most 18 generation attempts, all
inside the existing 60-second turn deadline. Cancellation stops backoff. Exhausted failures
still persist as failures and same-ID replay never calls the provider again. Logs include the
upstream HTTP status without response bodies or credentials. There is no model fallback.
An exhausted upstream HTTP 504 is classified as `provider_timeout` (HTTP 504), rather than
a generic `provider_error` (HTTP 502).

Chat feedback: a submitted message immediately appears as a normal user bubble and reconciles by
request identity when server history arrives, without creating a second authoritative transcript.
Unaccepted or uncertain delivery errors appear beneath that bubble. While awaiting a reply, the UI
shows elapsed browser wait, slow-response guidance after 15 seconds, and recovery guidance after 60
seconds. Saved failures distinguish an AI-service timeout from a provider error, including after
reload. Browser connection failures remain unconfirmed outcomes: use Check reply to recover the same
request; Try again prepares a new attempt only after a terminal failure. The non-streaming API does
not expose exact provider retries or tool progress, so the timer does not imply a processing stage
or server-health diagnosis.
