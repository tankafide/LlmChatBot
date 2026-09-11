# AutoAssist architecture

## Backend

The implemented inventory path is deliberately small:

```text
HTTP route (`api/routes.py`)
  -> inventory use case (`inventory/service.py`)
    -> scoped SQL (`inventory/repository.py`)
      -> SQLAlchemy models/session factory (`db/`)
```

Routes own HTTP validation and response/error mapping. `InventoryService` owns each complete read
unit, including session lifetime and materialization. `InventoryRepository` accepts a session and
trusted dealership ID, applies combined parameterized filters/order/limit in SQL, and returns
immutable application records. ORM entities never cross into HTTP serialization.

The offline import path is separate from the web lifespan but reuses the same validated settings,
engine/session construction, schema initialization, dealership bootstrap, and ORM model:

```text
CLI (`inventory/import_cli.py`)
  -> bounded CSV parser + import use case (`inventory/importer.py`)
    -> dealership-scoped lookup/upsert (`inventory/import_repository.py`)
      -> one SQLAlchemy transaction (`db/`)
```

Parsing and validation complete before engine creation. The import service owns the transaction;
the repository batches existing-source lookups, mutates ORM rows inside that session, and never
commits independently. A successful return follows commit. Existing `(dealership_id, source_id)`
rows retain UUIDs, absent rows are not deleted, and failures roll back the batch.

FastAPI runs the synchronous route functions in its worker thread pool, so the complete
synchronous database unit stays off the event loop. The engine and session factory are created in
application lifespan and disposed at shutdown; OpenAPI generation therefore needs no database or
external service.

Startup loads and validates server-owned connection/dealership configuration, creates missing
tables, and bootstraps dealerships in one transaction. UUIDs and vehicles are retained across
restart. SQLite foreign keys and a five-second busy timeout are enabled on each connection. The
runtime assumes one process owns a database volume.

## Shared API boundary

- `GET /health` checks local storage with bounded reads across mapped tables. Health and inventory
  services share SQLite result-code classification for expected availability failures;
  unexpected SQL/schema errors propagate to the server's error handling and diagnostics.
- `GET /dealerships` exposes UUID, slug, and display name, but no connection or credential data.
- `GET /dealerships/{dealership_id}/vehicles` performs bounded combined search and UUID cursor
  pagination.
- `GET /dealerships/{dealership_id}/vehicles/{vehicle_id}` performs a dealership-scoped lookup.

Search returns the compact vehicle summary. The detail operation additionally returns nullable
trim, condition, mileage, exterior color, drivetrain, transmission, and fuel fields preserved by
the assignment importer.

Pydantic response models are separate from SQLAlchemy models. Unknown resources and expected
storage failures use a stable error envelope; request validation retains FastAPI's standard `422`
envelope. OpenAPI is generated from the actual application routes.

The conversation layer calls the same inventory service with an application-owned dealership
scope. NHTSA adapters are implemented. The browser consumes committed types generated
from this application's OpenAPI schema; see the frontend boundary below.

```text
async conversation route (`api/routes.py`)
  -> lifecycle service (`conversations/service.py`)
    -> short worker-thread transaction units (`conversations/store.py`)
      -> queries and mutations (`conversations/repository.py`, `db/models.py`)
    -> lifespan-owned named runner (`chat/openai.py`, `chat/gemini.py`, or `chat/grok.py`)
      -> Pydantic AI orchestration (`chat/grounded.py`)
        -> typed service adapters (`chat/tools.py`)
        -> answer validation/rendering (`chat/answers.py`)
```

`ConversationService` coordinates creation, admission, terminal replay, provider deadlines,
and failure/cancellation settlement. It contains no SQL, ORM models, or live sessions.
`ConversationStore` is the synchronous application transaction boundary: it owns sessions,
write serialization, commit/rollback, admission reconciliation, completion, and startup recovery.
`ConversationRepository` executes scoped SQL and mutates ORM rows inside the supplied session;
it never commits. ORM objects may pass between repository and store only while that session is
alive; the store returns materialized application records/outcomes to the asynchronous service.
`conversations/completion.py` owns completion invariants and response assembly;
`outcomes.py` owns terminal outcome serialization; `execution.py` owns cancellation draining
and process capacity. Startup invokes the store's recovery before accepting traffic.
The provider is called only after the user/request admission commits. No session crosses that await.
Completion atomically stores the rendered assistant message, complete new model/tool turn,
presentation order, selection, and serialized terminal response.

The default OpenAI adapter uses Pydantic AI's native Responses API model with an explicitly owned
`AsyncOpenAI` client. Requests have a 30-second client timeout and SDK retries are disabled so they
cannot multiply the shared six-request/60-second turn budgets. The runner closes the client during
application shutdown. Provider/model identity remains server-owned named configuration.

The Gemini adapter uses a Google schema transformer to express array bounds as
descriptions on the wire; Gemini rejects the nested `maxItems` constraints with 400.
Application Pydantic validation still enforces the original bounded answer schema.
The Gemini model adapter retries HTTP 503/504 generation failures, up to three attempts
within the enclosing turn deadline. It does not repeat tools or whole conversation turns;
the SDK itself still makes one attempt. Other HTTP/transport errors remain terminal. Short
numeric Retry-After delays are honored and longer/unparseable delays are not retried in-turn.
An upstream HTTP 504 remains a timeout when retries are exhausted.

Conversation rows pin server-owned connection/provider/model identity. SQLite uniqueness enforces
request identity and one active request per conversation. Application scope checks additionally
ensure selected vehicles belong to the conversation's dealership. Full public history is ordered
by a conversation-local sequence; bounded model replay uses only completed whole turns, while
failed and interrupted user messages remain visible to clients.

The model can request repository-backed evidence and return only typed intent, vehicle IDs, field
names, and a selection action. Application validation rejects unknown evidence IDs and extra
factual values, then a deterministic renderer supplies identity, money, specifications, null
handling, displayed ordering, and evidence-based safety rendering.
`chat/answers.py` holds the typed answer schema, evidence policy, and inventory renderer.
Its validation errors become Pydantic AI repair requests only in the runner adapter.
List answers must reference the latest search result set, even when older evidence remains
available for follow-up resolution. Multiple searches use the final result set, not their union.
`chat/context.py` owns per-turn evidence and tool budgets; `chat/tools.py` adapts typed model
calls to the existing inventory/safety services. The runner owns model-history serialization,
agent execution, and staging the final replay/selection result, rather than SQL or rendering rules.
For a validated detail answer, application reference resolution also determines the retained
selection; model defaults cannot leave the next pronoun without a subject. Selection, reply,
and replay still commit together through the existing completion transaction.

## NHTSA safety ownership

`integrations/nhtsa.py` owns fixed HTTPS requests, streamed response bounds, deadlines, and
sanitized transport errors. `safety/parsing.py` validates endpoint casing/counts, every identity
and campaign, star categories, and detail IDs. `safety/records.py` validates application evidence
and presentation invariants. `safety/matching.py` conservatively matches variants and parses
whole-message choices. `safety/service.py` composes independent results with per-run reuse.
Duplicate descriptions remain ambiguous until an explicit ID or unambiguous ordinal is given.
Safety tools and selection validation share reference resolution: explicit stock references
retain priority, and pending NHTSA ordinals cannot select from an older inventory list.

`chat/tools.py` implements the two sequential safety tools registered by the runner. Each refetches
scoped inventory in a complete worker-thread unit before network work. Output validation requires
current evidence for every produced/requested branch; `safety/rendering.py` emits bounded facts,
urgency, provenance, and uncertainty. The model cannot supply safety values or source URLs.

`safety/history.py` folds choices over the same chronological retained suffix as model replay.
The runner derives keep/clear/set from final selection and rendered evidence. Completion validates
presentation identity against the selected vehicle inside the existing transaction. Replay byte
accounting includes metadata and public text. No new table, independent tool write, second request
lifecycle, or startup reset exists. Safety receives the shared outer deadline; HTTPX context
managers close responses on cancellation, and existing completion-thread draining still applies.

`chat/selection.py` resolves stock/list references before validating detail and selection IDs.
`chat/history.py` selects the same whole-turn byte/count suffix for repository presentation metadata
and model replay. Selected identity remains independent of trimmed lists.
`chat/budget.py` wraps each non-streaming model request and counts its full serialized application
envelope, including schemas and repair/tool messages; the native xAI channel additionally bounds
the final protobuf message size. Budget failures follow normal terminal provider-error settlement.

Admission owns a shielded task through cancellation, drains its worker, and interrupts only a turn
it admitted. Internal admission IDs permit fresh-session reconciliation after uncertain commit
acknowledgements. Completion likewise drains its worker before cancellation settlement, preserving
committed-completion precedence. Capacity is released only after this cleanup finishes.

## Frontend and generated API boundary

Readiness hardening: `initialize_schema` checks required existing columns and named
index definitions before `create_all` or bootstrap writes. It never alters an
incompatible table. `check_storage` selects all mapped columns across application
tables, rather than only a vehicle ID. `scripts/check-setup.py` separately verifies
that the selected dealership has queryable inventory. The browser smoke exercises
empty-before-import and ready-after-import states on its isolated backend.

Provider exception conversion lives around `BudgetedModel.wrapped.request`, where
no inventory tool executes. `PydanticChatRunner` translates model-output/budget
exhaustion, while local tool exceptions reach the conversation service. It owns
terminal failure settlement, category-specific responses, replay, and claim release.
Known tool storage errors settle as storage failures when commit succeeds; uncertain
commits keep existing recovery semantics. Partial app startup closes constructed
runners even before a conversation service takes ownership.

`frontend/src/chat/useConversation.ts` is the sole React-local controller. A synchronous current
state reference prevents same-event duplicate submission; React renders snapshots. View generation
checks reject old read/write results. No write is triggered by mounting. The controller owns lazy
creation, exact request identity, draft/pending separation, storage warnings, bounded history loading,
terminal outcome precedence, and explicit missing-conversation recovery. Stable message IDs are
upserted and sorted by sequence; terminal statuses cannot be downgraded by stale in-progress rows.
Check reply rereads from the unresolved user sequence minus one (or zero), including status-only
changes with no new assistant row. An incomplete reconciliation keeps sending disabled.

`src/api/client.ts` consumes `src/api/generated.ts`, validates consumed fields at runtime, checks
HTTP status and error codes, and bounds native-fetch deadlines. `scripts/export-openapi.py` uses the
real app without lifespan. Locked openapi-typescript generation and temporary comparison run in
shared verification; an isolated altered-schema test proves drift fails without modifying source.

`src/chat/runtime.tsx` projects actual server messages through assistant-ui ExternalStoreRuntime;
only `onNew` is supplied. `ChatScreen.tsx` renders primitives with a controlled multiline composer
and one request-identity-scoped optimistic user projection. The projection uses the normal user
message treatment, disappears as soon as a matching server-owned message exists, and keeps
unaccepted or uncertain recovery text inline without becoming authoritative history. There is no
second transcript store, global store, hosted chat service, or browser history upload. Unsupported
runtime actions have no UI controls. The canonical visual tokens live in
`frontend/src/styles/tokens.css`; the style skill and specimen link there.
The screen tracks scroll intent separately from message state: a submitted reply is positioned at
its beginning only when the reader was following current content, while manual history reading is
preserved behind an explicit jump control. Newly submitted assistant text gets a presentation-only,
220–700ms reveal after the complete response arrives; restored history and reduced-motion views
render immediately. This does not change the non-streaming transport or persisted message text.

Vite strips `/api` and proxies to the server-owned target. Compose publishes the non-root frontend
only on loopback port 5173 and leaves dependencies in the image. `Dockerfile.verify` is a separate
combined check image used by the existing Compose `verify` service; `scripts/verify.py` and CI use
the same check sequence. Chromium's real-backend smoke reuses the existing safety scripted model
and acceptance runner with stable stock-number selection, isolated configuration, assignment CSV,
and temporary SQLite. It stops the backend before restarting against that database. Development
configuration and database storage are never used by the browser smoke.

ReplyProgress owns only the current mounted browser-wait timer and cleans it up on completion. Its stage messages are elapsed-time guidance, not backend telemetry; per-second updates are outside the live region. requestFeedback shares sanitized error-code explanations between the controller notice and persisted message rendering. Existing API error codes supply the cause without a schema change.
