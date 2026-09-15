# AutoAssist

![AutoAssist conversation demo](docs/assets/autoassist-demo.gif)

AutoAssist is an LLM-powered dealership chatbot. A
customer can search real dealership inventory in natural language, select a vehicle, ask contextual
follow-up questions, and retrieve NHTSA recall and crash-test information. The application exposes
that behavior through a durable HTTP API; the small React client above is a demonstration surface,
not the center of the design.

The backend is intentionally modest in infrastructure and strong in boundaries. FastAPI handles
transport, ordinary Python services own business rules, SQLAlchemy owns relational persistence,
Pydantic AI coordinates model tool use, and a narrow HTTPX adapter owns NHTSA traffic. Conversations,
request outcomes, model replay units, and vehicle selection live in PostgreSQL, so process restarts
do not erase context or cause completed requests to run twice. Database constraints and row locks
coordinate multiple backend workers without holding a transaction across model or NHTSA waits.

## Customer features and example interactions

| Feature | Example customer interaction |
| --- | --- |
| Inventory search | “Show me 2022 RAV4s under $30,000.” |
| Structured filters | “Do you have a Honda SUV under $25,000?” |
| Vehicle details | “Tell me more about stock A123.” |
| Choose from a displayed list | “What about the second one?” |
| Follow-up questions about the selected vehicle | “What color is it?” or “Does it have all-wheel drive?” |
| Recall lookup | “Does this vehicle have any recalls?” |
| Crash-test ratings | “What are its NHTSA crash ratings?” |
| Ambiguous crash-test choice | “NHTSA has multiple matching variants. Which body style applies?” |
| No-result handling | “Show me 2030 Toyota trucks under $5,000.” The assistant explains that no matching inventory was found. |
| Clarification | “Tell me about that car.” The assistant asks which vehicle the customer means when it cannot resolve a selection. |
| Lost-response recovery | After a reload or lost response, the browser can check an accepted message request again without submitting a duplicate message. |

A typical interaction is:

```text
Customer: Show me 2022 RAV4s under $30,000.
AutoAssist: Shows matching vehicles.

Customer: Tell me about the second one.
AutoAssist: Resolves that displayed vehicle and gives supported details.

Customer: Does it have recalls?
AutoAssist: Looks up NHTSA recall information for that vehicle's
year, make, and model. This is not VIN-specific recall confirmation.

Customer: What about crash ratings?
AutoAssist: Retrieves NHTSA ratings, or asks the customer to choose
when NHTSA returns ambiguous variants.
```

The customer-facing scope is inventory questions and NHTSA safety information grounded in
retrieved data. The prototype does not provide customer accounts, appointment booking, financing
applications, live model-token streaming, message editing, or automatic reruns of interrupted model
requests.

## Technology choices

| Technology | Role | Why it fits this prototype |
| --- | --- | --- |
| Python 3.13 | Backend runtime | Clear domain code, mature API/data tooling, and a good fit for a focused system that must remain easy to explain. |
| FastAPI + Uvicorn | HTTP API and application lifecycle | Typed request validation and OpenAPI come from the same schemas used by the running app. Lifespan provides one explicit place to construct and close database and network resources. |
| Pydantic v2 + pydantic-settings | API contracts and configuration | Strict validation keeps malformed requests and configuration out of the application core. Secrets are referenced by environment-variable name, not stored in source or the database. |
| SQLAlchemy 2 + PostgreSQL | Relational persistence and worker coordination | PostgreSQL provides durable shared state, portable constraints, row-level locking, and independent connection pools for multiple workers. SQLite provides fast isolated test fixtures. |
| Pydantic AI | LLM orchestration | Typed tools, structured output validation, repair requests, and model-history support let the model choose intent while the application retains control of facts and state. |
| OpenAI Responses API | Default model integration | The checked-in default uses a native tool-capable model connection. Gemini and xAI adapters demonstrate that provider choice remains server-owned configuration. |
| HTTPX | NHTSA integration | Async streaming responses, granular timeouts, connection pooling, and deterministic mock transports make the external boundary both bounded and testable. |
| pytest, Ruff, and mypy | Backend verification | Tests exercise temporary SQLite files plus a real isolated PostgreSQL coordination test and fake only external model/NHTSA services. |
| Docker Compose + uv | Reproducible execution | Locked Python dependencies, a non-root runtime image, two backend workers, and a named PostgreSQL volume make setup and restart behavior repeatable. |
| React + assistant-ui | Thin demo client | It makes the API easy to show while leaving conversation authority, validation, and persistence in the backend. |

## How the backend is organized

The code follows the direction of one request instead of organizing everything around a framework:

```text
HTTP routes and schemas
    ↓
Conversation / inventory application services
    ↓
Repositories and short SQLAlchemy transaction units
    ↓
PostgreSQL

Conversation service
    ↓
Pydantic AI runner → typed inventory and safety tools
                         ↓
                  Inventory service / NHTSA client
```

The important modules are:

- `backend/src/autoassist/app.py` — composition root and lifespan ownership. It loads configuration,
  creates the engine and external clients, constructs named model runners, recovers interrupted
  work, and closes everything on shutdown. Importing the module performs no I/O.
- `backend/src/autoassist/api/` — HTTP validation, response schemas, status codes, and translation
  between application records and public JSON. Routes do not contain SQL or model prompts.
- `backend/src/autoassist/inventory/` — CSV parsing/import, combined inventory filtering, detail
  lookup, and immutable records. The importer and web API share storage rules without sharing a
  long-lived session.
- `backend/src/autoassist/conversations/` — request admission, idempotency, persistence, paging,
  completion, failure settlement, cancellation, and startup recovery.
- `backend/src/autoassist/chat/` — provider adapters, bounded model execution, typed tool wrappers,
  structured answers, evidence validation, deterministic rendering, context selection, and budgets.
- `backend/src/autoassist/integrations/nhtsa.py` and `backend/src/autoassist/safety/` — bounded NHTSA
  HTTP calls, strict parsing, conservative vehicle matching, variant clarification, and presentation.
- `backend/src/autoassist/db/` — SQLAlchemy models, engine/session construction, schema checks, and
  dealership bootstrap.

For the fuller ownership map, see [`docs/architecture.md`](docs/architecture.md).

## Request lifecycle and durability

Every message submission includes a client-generated `request_id`. That ID is the durable identity
of one intentional attempt, not merely a tracing value.

1. The conversation service validates dealership and conversation scope.
2. A short transaction atomically inserts the request and user message and claims the conversation.
3. After that commit, a service-owned task takes execution ownership and POST returns `202 Accepted`.
   The transaction and session close before the backend waits on the model or NHTSA.
4. The model can call typed tools, but those tools receive the trusted dealership scope from the
   application. They cannot submit SQL or replace that scope.
5. The application validates the model's structured answer against evidence returned in this turn.
6. A deterministic renderer—not the model—writes inventory prices, specifications, recall facts,
   ratings, source links, and limitations into the public reply.
7. One completion transaction stores the assistant message, complete model/tool replay unit,
   selected vehicle, displayed choices, and exact terminal response. Status reads then expose that outcome.

This produces useful failure semantics:

| Situation | Observable result |
| --- | --- |
| Same ID and text while active | `202` with the existing request identity; no second provider run. |
| Same ID and text after completion | The exact stored status/body is replayed; the provider and NHTSA are not called again. |
| Same ID with different text | `409 request_id_conflict`; no message is appended. |
| Another request while the conversation is active | `409 conversation_busy`; the rejected request is not persisted as chat history. |
| Provider failure or timeout after admission | The user message remains, a sanitized terminal failure is stored, and no fictional assistant message is created. |
| Worker stops after admission but before completion | Other workers leave the fresh request alone. After its renewable database lease expires, startup, a scoped submission/status read, or the background sweep marks it interrupted and releases the claim; external work is never silently rerun. |
| Completion committed but the response was lost | Retrying the same ID returns the stored success without duplicating messages. |

PostgreSQL is the source of truth for the transcript and model replay context. Failed and interrupted
user messages remain visible to the customer but are excluded from future model input. Public
history can grow and page independently; model context retains only bounded, complete turns so a
tool call is never separated from its result.

## Grounding instead of trusting generated facts

The LLM is useful for interpreting language and choosing tools, but it is not treated as a database.
Inventory tools accept typed filters and execute parameterized, dealership-scoped SQL. The model's
final structure contains intent, evidence IDs and requested fields. The application supplies
prices and safety values and derives selection from the validated answer and user reference.

The application then checks that every referenced vehicle or safety result came from current tool
evidence. Lists may use only the final search result set. Exact stock numbers and displayed ordinals
are resolved by application code. A successful detail or safety response retains its resolved vehicle as the
conversation selection, allowing a later question such as “What are its recalls?” to work after a
restart.

The prompt includes refreshed current vehicle evidence for selected/list follow-ups, avoiding
extra model-directed stock lookups. Tool descriptions and output schemas specify prerequisites
and stopping conditions: a missing stock or unresolved safety subject asks for clarification;
`no_match` requires an empty filtered search. Model-authored selection state is not accepted.

This split keeps the probabilistic part narrow: the model can misunderstand a request and ask for
clarification, but it cannot make an invented price valid by putting it in fluent prose.

## NHTSA safety behavior

Recall and crash-rating lookups begin with the selected inventory record. The integration uses the
vehicle's year, make, model, body type, and drivetrain conservatively; it does not guess across a
known conflict. When NHTSA returns multiple compatible crash-test variants, AutoAssist presents up
to five choices and persists them so the customer can answer with an NHTSA ID after a restart.

Safety results retain their important distinctions:

- zero returned recalls is a verified empty result, not a network failure;
- unavailable data is labeled unavailable rather than presented as safe;
- crash categories can be available, partial, explicitly unrated, incomplete, ambiguous, absent,
  or unavailable;
- one safety branch can still be useful when the other branch fails;
- invalid star values never become zero-star ratings;
- source URLs and UTC retrieval/attempt times are rendered with the answer.

NHTSA responses are streamed and size-bounded. Per-request and cumulative deadlines, a three-GET
limit, record/variant caps, and evidence-size limits prevent an upstream service or model-directed
tool loop from creating unbounded work.

## Inventory import and query behavior

The source inventory is committed at
[`docs/context/inventory/data.csv`](docs/context/inventory/data.csv). A fresh database intentionally
contains no inventory until this file is imported while the server is stopped.

The parser validates the entire CSV before opening storage. One transaction then inserts new stock
IDs, updates changed records, leaves identical and absent records untouched, and preserves existing
vehicle UUIDs. A parse, lock, write, or commit failure leaves no partial batch. Re-running the same
file is the recovery procedure after an uncertain import outcome.

Inventory queries combine make, model, body type, year range, and price range with `AND`. Text filters
are trimmed and case-insensitive; ranges are inclusive. Filtering, ordering, cursor paging, and
limits happen in SQL. Every query requires a trusted dealership ID, including detail lookups.

## Run the project with Docker

Prerequisites are Docker Desktop and Docker Compose v2. Create a local `.env` from the example and
set the credential referenced by the default connection (`OPENAI_API_KEY` in the checked-in config).
No provider key is needed for health, inventory, or reading already stored terminal outcomes.

From the repository root:

```powershell
docker desktop start --detach --timeout 120
docker info
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose build backend frontend
docker compose up -d database
docker compose stop backend
$inventoryCsv = (Resolve-Path docs/context/inventory/data.csv).Path
docker compose run --rm --no-deps -v "${inventoryCsv}:/tmp/inventory.csv:ro" backend autoassist-import-inventory --file /tmp/inventory.csv --dealership mia-motors --server-stopped
docker compose up -d backend frontend
python scripts/check-setup.py
```

Open the demo at [http://localhost:5173](http://localhost:5173), the API at
[http://localhost:8000](http://localhost:8000), and generated API documentation at
[http://localhost:8000/docs](http://localhost:8000/docs).

Stop normally without deleting data:

```powershell
docker compose down
```

The `autoassist-postgres` named volume contains PostgreSQL data. Ordinary backend, database-container,
or image recreation preserves it. The backend runs two Uvicorn workers against that shared store.

## Run the backend locally

Prerequisites are Python 3.13, uv 0.8.13, and the Compose PostgreSQL service. From the repository
root:

```powershell
uv sync --project backend --frozen
$env:OPENAI_API_KEY = "YOUR_LOCAL_KEY"
docker compose up -d database
uv run --project backend autoassist-import-inventory --file docs/context/inventory/data.csv --dealership mia-motors --server-stopped
uv run --project backend uvicorn autoassist.main:app --host 127.0.0.1 --port 8000 --workers 2
```

Local defaults use `config/dealerships.json` and PostgreSQL on `127.0.0.1:5432`. Override them with
`AUTOASSIST_CONFIG_FILE` and `AUTOASSIST_DATABASE_URL`. The example credentials are development-only.

## Walk through the HTTP API

The examples use PowerShell objects so JSON quoting stays readable. First discover the persisted
dealership UUID rather than hardcoding one:

```powershell
$dealerships = Invoke-RestMethod http://localhost:8000/dealerships
$dealership = $dealerships.items | Where-Object slug -eq "mia-motors"
$dealershipId = $dealership.id
```

Run a five-dimension combined query. Source row `AA-1001` is a 2022 Toyota RAV4 SUV priced
at `$26,335.00`.

```powershell
$vehicles = Invoke-RestMethod "http://localhost:8000/dealerships/$dealershipId/vehicles?make=Toyota&model=RAV4&body_type=SUV&year_min=2022&year_max=2022&price_min=26335.00&price_max=26335.00"
$vehicles.items
$vehicleId = $vehicles.items[0].id
Invoke-RestMethod "http://localhost:8000/dealerships/$dealershipId/vehicles/$vehicleId"
```

Create a conversation. Retain the creation ID for retries after a lost response:

```powershell
$creationId = [guid]::NewGuid().ToString()
$conversation = Invoke-RestMethod -Method Post `
  "http://localhost:8000/dealerships/$dealershipId/conversations" `
  -ContentType "application/json" -Body (@{ creation_id = $creationId } | ConvertTo-Json)
$conversationId = $conversation.id
$messagesUrl = "http://localhost:8000/dealerships/$dealershipId/conversations/$conversationId/messages"
```

Submit a natural-language inventory search. Keep the ID and exact text for uncertain admission
recovery. POST returns `202` after the user message is committed; poll the request resource:

```powershell
$searchId = [guid]::NewGuid().ToString()
$searchText = "Show me Toyota RAV4 SUVs from 2022 under 30000 dollars"
$searchBody = @{ request_id = $searchId; text = $searchText } | ConvertTo-Json
$accepted = Invoke-RestMethod -Method Post $messagesUrl `
  -ContentType "application/json" -Body $searchBody
$statusUrl = $messagesUrl.Replace('/messages', "/requests/$searchId")
for ($attempt = 0; $attempt -lt 20; $attempt++) {
  $state = Invoke-RestMethod $statusUrl -TimeoutSec 15
  if ($state.status -ne 'in_progress') { break }
  Start-Sleep -Seconds 5
}
if ($state.status -eq 'completed') { $state.outcome.assistant_message.text }
elseif ($state.status -eq 'in_progress') { 'Still running: check the same status URL later.' }
else { $state.outcome.error }
```

Use a fresh request ID for each intentional follow-up, such as `Select stock AA-1001`,
`What are its mileage and drivetrain?`, or `What recalls and crash-test ratings does it have?`.
Wait for the current request to reach terminal status before submitting the next one.
Status GET returns `200` for all known states. A terminal failure has `status: "failed"` and
`outcome: { "error": { "code": "provider_timeout", "message": "The chat provider timed out." } }`,
for example. Reposting that exact ID/text returns the stored `504` error without rerunning it.

Read durable history in pages:

```powershell
$history = Invoke-RestMethod "$messagesUrl`?after_sequence=0&limit=50"
$history.items | Select-Object sequence, role, text, request_status, error_code
```

If admission is uncertain after a lost response, submit the same ID and exact text. An active
request returns `202`; a terminal request returns its stored HTTP status/body without repeating
model or NHTSA work. If admission never committed, this submits the request:

```powershell
$replayed = Invoke-RestMethod -Method Post $messagesUrl `
  -ContentType "application/json" -Body $searchBody
```

To demonstrate restart continuity, run `docker compose restart backend`, request history again, and
send a fresh follow-up such as `What is its price?`. The transcript and selected vehicle remain in
PostgreSQL.

### API surface

| Method and path | Purpose | Main outcomes |
| --- | --- | --- |
| `GET /health` | Local storage readiness | `200`, or sanitized storage `503` |
| `GET /dealerships` | Discover stable dealership IDs | `200`, `503` |
| `GET /dealerships/{id}/vehicles` | Combined filtered inventory search | `200`, `404`, `422`, `503` |
| `GET /dealerships/{id}/vehicles/{vehicle_id}` | Scoped vehicle details | `200`, `404`, `422`, `503` |
| `POST /dealerships/{id}/conversations` | Create or replay by dealership-scoped `creation_id` | `201`, `404`, `422`, `503` |
| `POST /dealerships/{id}/conversations/{id}/messages` | Admit or replay one request | `202`, `200`, `404`, `409`, `422`, `500`, `502`, `503`, `504` |
| `GET /dealerships/{id}/conversations/{id}/requests/{request_id}` | Read durable active or terminal status | `200`, `404`, `422`, `503` |
| `GET /dealerships/{id}/conversations/{id}/messages` | Page authoritative public history | `200`, `404`, `422`, `503` |

### Request status and recovery

Every status response includes `conversation_id`, `request_id`, and `status`. Status responses
use `Cache-Control: no-store` and are scoped to the dealership and conversation.

| Status | GET HTTP status | Contents |
| --- | --- | --- |
| `in_progress` | `200` | Identity and status, with no `outcome`. |
| `completed` | `200` | `outcome` contains the committed submission response, including both messages and selected vehicle ID. |
| `failed` | `200` | `outcome.error` contains the stored sanitized code and message. |
| `interrupted` | `200` | `outcome.error` describes interruption; the admitted user message remains in history. |

Inspect the body to distinguish turn success from failure. Unknown or incorrectly scoped resources
return `404`, unavailable storage returns `503`, and invalid path values return `422`. Status reads
recover expired leases within the requested scope without invoking the provider.

After confirmed admission, check the result with GET. If a status response is lost, check the same
resource again. Reusing an ID with different text returns `409 request_id_conflict`; submitting a
different request while the conversation is active returns `409 conversation_busy`. Use a fresh
request ID for an intentional turn after completion, failure, or interruption. **Check reply** retains
the original identity while the result remains unresolved.

## Configuration

[`config/dealerships.json`](config/dealerships.json) is server-owned. Each named connection contains
`provider`, `model`, and `api_key_env`; dealerships reference one default connection. Credential
values stay in the process environment and are never written to the database or returned by the
API.

Startup validates the whole file before database writes. A conversation pins its connection name,
provider, and model, so a configuration change cannot silently reroute existing history. Missing
credentials leave that connection unavailable for new work without breaking health, inventory,
history, or terminal replay. There is no automatic provider failover.

The default OpenAI client has a 30-second SDK timeout and disables SDK retries inside the shared
60-second turn deadline. Each turn is further bounded to six model requests, eight tool calls,
2,048 output tokens per model response, 16 KiB tool results, 64 KiB retained model history, 128 KiB
model request envelopes, and an 8,000-character public reply. Four conversations may run model work
at once per worker; the development container therefore permits up to eight active turns across its
two workers. There is no global queue or cross-instance admission cap.

## Verification

Run the focused backend checks from the repository root:

```powershell
uv run --project backend ruff check backend scripts
uv run --project backend ruff format --check backend scripts
uv run --project backend mypy backend/src
uv run --project backend pytest backend/tests -q
```

Most tests use real temporary, file-backed SQLite databases for speed. The shared Docker verifier
also runs isolated PostgreSQL tests for admission, terminal settlement, completion racing recovery
in both lock orders, concurrent schema/bootstrap startup, and abrupt worker termination with
fresh-request protection and stale recovery. Index-predicate validation and connection-failure
HTTP responses have regression coverage. Model and NHTSA fakes sit at external boundaries while real HTTP routes,
application services, repositories, transactions, grounding, rendering, and recovery behavior
execute. Coverage includes the complete source CSV import,
combined filters, dealership isolation, contextual selection, both safety branches, malformed and
unavailable upstream data, idempotent terminal replay, concurrency, cancellation, commit faults,
application recreation, and abrupt process termination.

For the locked Linux check image plus the small frontend demonstration checks:

```powershell
python scripts/verify.py
```

GitHub Actions runs this same verification on every push. Pull requests do not
trigger a separate run.

Optional live checks are deliberately separate from deterministic tests because provider and NHTSA
availability can change:

```powershell
docker compose -f compose.safety-live.yaml run --build --rm safety-live
```

## Model evaluation and operational events

The [evaluation guide](evaluations/README.md) describes the 20 labeled conversations,
automatic checks, human-review rubric, and report limits. The [interface improvement results](evaluations/interface-results.md)
record repeated live runs with the same model and unchanged labels. Validate without provider calls,
or opt in to a billed run against temporary CSV inventory and controlled NHTSA fixtures:

```powershell
uv run --project backend autoassist-evaluate
uv run --env-file .env --project backend autoassist-evaluate --live
```

Reports in `evaluation-results/report.json` include tool/filter accuracy, selection and
safety outcomes, latency, and model-call counts. Strict tool choice flags unnecessary calls
separately from functional checks; pending human reviews never count as passed. Bounded validation
feedback in local reports helps explain output failures without changing operational log privacy.

`autoassist.events` emits JSON to stderr at INFO level: admission, model request duration,
NHTSA operation duration/category, execution duration and terminal HTTP outcome,
model/proposed-tool counts, lease renewals, and recovery counts. Conversation and request
IDs correlate events. No prompts, secrets, vehicle records, exception messages, or provider
payloads are logged. Replay makes zero model calls and emits no execution event. Execution duration starts after
admission and includes context loading, provider work, persistence, and cleanup;
model duration includes integration retries. Use `docker compose logs backend` to inspect events.
No metrics collector or tracing server is required. Local evaluation reports intentionally
retain labeled inputs and outputs for review, separately from production logs.

## Database recreation after schema changes

This prototype deliberately has no migration framework. Ordinary startup creates missing tables
and preserves compatible data; it never resets inventory or conversations. Existing tables are
checked for required columns and indexes, including exact supported index predicates, before
bootstrap or recovery writes.

After a schema change, stop the backend and recreate only the intended development database. Back up
anything needed, run `docker compose down`, resolve the exact Compose volume with
`docker volume ls`, verify that it is this project's `autoassist-postgres` development volume, and
remove only that volume. Start `database`, then reimport the source CSV. Normal
`docker compose down` must not use `--volumes`.

## Deliberate limits

- Dealership IDs provide data routing and isolation, not authentication or production authorization.
- PostgreSQL coordinates multiple workers and permits multiple stateless backend instances, but
  the development Compose file exposes one two-worker backend. A production load balancer,
  authentication, database high availability, backups, and disaster recovery remain out of scope.
- NHTSA model-level data does not establish VIN-specific recall applicability, repair completion,
  or a safety guarantee. Inventory does not contain VINs or comparison weight.
- NHTSA data may be partial, unrated, stale, unavailable, or ambiguous. There is no background
  refresh, cross-turn safety cache, bulk scan, or nearest-year guessing.
- Creation retries reuse a client-generated `creation_id`, unique within the dealership. The
  original conversation and pinned connection are returned even if provider credentials change.
  Browser storage retains unconfirmed creation IDs across reloads; unavailable browser storage
  limits recovery to the current page session.
- Interrupted model work is not automatically resumed. PostgreSQL TIMESTAMPTZ leases use
  `clock_timestamp()`: admission grants 120 seconds and the owning turn renews every 20 seconds.
  Each worker sweeps at most 100 expired requests every 30 seconds with `FOR UPDATE SKIP LOCKED`;
  startup and scoped submissions also recover expired work. Backlogs and locked rows can delay
  recovery. Renewal cannot revive expired/terminal work. Expiry makes work eligible for recovery,
  not automatic provider cancellation; completion can win before recovery locks the row.
  Database partitions can prevent renewal. A deliberate new attempt needs a new request ID.
- Uncommitted provider output can be lost. Exactly-once external execution is not promised; durable
  terminal replay prevents completed application requests from being repeated.
- The UI is a localhost demonstration: no authentication, streaming, attachments, voice,
  edit/regenerate, multi-chat browser, or production hosting. Those omissions do not weaken the
  backend's persisted conversation contract.

## What I would discuss in a walkthrough

The most useful code-review path is:

1. Start at `app.py` to see explicit dependency and resource ownership.
2. Follow a message route into `ConversationService`, then through admission and completion in
   `ConversationStore`.
3. Inspect the SQLAlchemy constraints that enforce request identity and one active request.
4. Follow `PydanticChatRunner` through typed tools, evidence validation, and deterministic rendering.
5. Trace one NHTSA request through transport bounds, parsing, matching, and safety presentation.
6. Finish in the recovery and HTTP integration tests, including the real PostgreSQL cross-worker
   admission and terminal-write race.

That route shows the core design claim: the backend lets an LLM interpret conversation, but keeps
scope, facts, transactions, durable state, error meaning, and recovery under ordinary application
control.

AI-assisted development was used throughout the project. The resulting behavior is documented and
tested at the system boundaries rather than relying on generated-code volume as evidence of
correctness.

### Async request ownership and browser recovery

Accepted work belongs to the conversation service, not the POST coroutine. Tracked tasks hold
one of four execution slots per worker, renew database leases, and settle completion/failure with
the existing atomic writes. Shutdown stops admission, drains for 20 seconds, then cancels and
joins remaining work before closing provider clients. Database writes already running in threads
finish before cancellation settlement; a committed completion wins. Process death still requires
lease expiry and recovery, with no automatic provider rerun. This is not a durable job queue.

The browser restores server history and polls a confirmed active request after reload. It makes
at most 20 status reads per polling cycle, backing off from 0.5 to 5 seconds, with a 15-second
HTTP timeout. A failed read or exhausted cycle leaves Check reply available. Confirmed requests
use status reads; uncertain/unaccepted submissions retry POST with the exact original ID/text.
Terminal messages merge by stable ID, stale view results are ignored, and no assistant message or
provider/tool progress is fabricated. Status reads load one scoped request, not its transcript,
and disable caching. This API change needs no database recreation.
