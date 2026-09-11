# AutoAssist product implementation roadmap

Created: 2026-09-10 (America/Chicago).
Status: high-level guide; steps 1 and 2 are implemented and deterministically verified.

## Outcome and scope

Deliver AutoAssist: an HTTP chatbot that searches dealership inventory, answers vehicle follow-ups, retrieves NHTSA recalls and crash-test ratings, and preserves conversations and messages across restarts. Finish with reproducible setup, meaningful tests, and reviewer-friendly documentation.

Use four large implementation chunks, in order. Create a focused sub-plan in `docs/plans/` when starting each chunk, linked back here; keep technical contracts and exact commands in those sub-plans. Include tests and documentation with each chunk. Prioritize required API behavior over optional UI and polish.

## Shared decisions

- Retain the [accepted stack and request lifecycle](../stack-baseline.md): FastAPI, PostgreSQL/SQLAlchemy, Pydantic AI, HTTPX, and Docker Compose, with two backend workers sharing a PostgreSQL service and its persistent volume.
- Support multiple dealerships in the initial data model. Inventory and conversations belong to a dealership; messages and selected vehicles inherit that scope. Every inventory, vehicle-detail, conversation, and history operation enforces that scope in application/database access. The model cannot choose or override it. Test with two dealerships to catch cross-dealership leakage. Local dealership selection is not production authentication or authorization.
- Support a configurable collection of named LLM connections, without a hardcoded single connection or arbitrary fixed count. Each connection identifies its provider, model, and server-side credential reference. A dealership chooses a configured default, and a conversation records its connection selection so follow-ups remain consistent. Validate connection references before accepting conversations; do not expose secrets or allow arbitrary provider URLs/credentials in chat requests.
- Start with one xAI/Grok connection. Reuse Pydantic AI's provider boundary and a small configuration/resolution layer; additional connections can reuse a provider, while a new provider may need integration work and verification. This does not require simultaneous calls to several models, automatic failover, runtime connection administration, or unlimited concurrent work.
- Preserve all admitted conversation messages and the context needed for follow-ups in PostgreSQL. Follow the baseline's retry, failure, and interruption behavior; never claim durable success before commit. Keep external calls outside database transactions and bound model/tool work.
- The original inventory is preserved at `docs/context/inventory/data.csv`. Clearly labeled synthetic fixtures may support independent tests but cannot substitute for that assignment data in importer verification.

## 1. Working foundation and dealership inventory

Implementation sub-plan: [Step 1: foundation and inventory](step-1-foundation-inventory.md).

**Outcome:** A runnable API backed by persistent, dealership-scoped relational data and searchable assignment inventory.

Set up the backend, configuration, Docker workflow, database, and initial verification entry point. Establish dealership ownership and named LLM connection configuration. Inspect the preserved attachment, implement a validated import with documented repeat-import behavior, and support combined make, model, year, price, and body-type filters plus specific-vehicle lookup. Keep HTTP, application logic, database access, and integrations separate.

**Dependency:** The target configured dealership slug must be supplied explicitly when running the importer because the CSV has no dealership column.

**Exit:** A clean build starts the API; the real attachment imports successfully; combined filters and vehicle details return correct dealership-scoped records; invalid imports do not leave partial data; records survive container recreation. Focused temporary-database tests verify filtering and isolation. README contains working setup/import/reset instructions.

## 2. Complete conversational inventory API with Grok

Implementation sub-plan: [Step 2: conversational inventory API](step-2-conversational-inventory.md).

**Outcome:** Text requests produce grounded inventory replies and coherent vehicle follow-ups, with durable conversation history.

Implement conversation creation, message submission, and history retrieval. Connect the initial Grok configuration through Pydantic AI and typed inventory tools. Resolve each conversation's dealership and LLM connection on the server. Persist user messages, replies, selected-vehicle context, and model history according to the accepted lifecycle. Handle ambiguous references, no matches, invalid input, provider failures, retries, and interrupted requests clearly.

**Dependency:** Chunk 1's data/API foundation; a configured Grok model and server-side API key for live verification. Confirm current provider integration details when writing this sub-plan; no concrete SDK compatibility is assumed here.

**Exit:** A search followed by a specific-vehicle question works through HTTP and remains coherent after restart. Deterministic tests cover two dealerships and multiple named connections, routing, follow-ups, ambiguity, durable success/failure, duplicate-request replay, and interruption recovery. A separate live Grok smoke conversation validates actual credentials/model/tool integration when available. README documents API examples and configuration.

## 3. NHTSA safety answers in the same conversation

Implementation sub-plan: [Step 3: NHTSA safety answers](step-3-nhtsa-safety.md).

Status: implemented and deterministically verified; live NHTSA passed. Live Grok verification encountered an upstream provider error. See [evidence](step-3-implementation-evidence.md).

**Outcome:** The user can ask about recalls and crash-test ratings for a selected inventory vehicle.

Add NHTSA lookup services and thin chat tools for both capabilities. Resolve vehicle identity from inventory and conversation context; clarify ambiguous crash-test variants. Keep successful empty recalls, unavailable service, missing/unrated ratings, and partial results distinct. Attribute safety answers to the retrieved data and avoid unsupported safety assurances.

**Dependency:** Chunk 2's grounded chat and selected-vehicle context.

**Exit:** HTTP conversations answer both recall and rating questions for the intended vehicle. Deterministic integration tests cover valid results, empty recalls, ambiguous matching, partial/unrated results, malformed responses, and timeouts without fabricated claims. Useful results remain available when the other safety lookup fails. README explains safety limitations.

## 4. Assignment verification and handoff

Implementation sub-plan: [Step 4: assignment verification and handoff](step-4-verification-handoff.md).

**Outcome:** A complete, reproducible submission that is easy to demonstrate and explain.

Run the full assignment flow from a clean setup: import, combined search, follow-up, both safety questions, restart, and continued conversation. Complete focused checks for tenant isolation, connection routing, persistence, failure behavior, and abrupt interruption recovery, using isolated storage and external fakes. Finish the shared Docker verification command and CI workflow, README, concise architecture notes, API examples, omissions, and source ZIP excluding secrets, local databases, and generated dependencies.

**Dependency:** Chunks 1–3.

**Exit:** Required behavior passes repeatable checks; clean setup and restart behavior are demonstrated; any live-service validation gaps are explicitly recorded; the README and submission ZIP allow another developer to run and review the project.

## Optional follow-on

Implementation sub-plan: [Localhost chat frontend](frontend-local-chat.md). The localhost frontend and deterministic browser/restart acceptance are implemented; see [evidence](frontend-implementation-evidence.md). A separate live-model smoke returned provider_error and is not a passing live demonstration.

The accepted React/assistant-ui frontend is a separate follow-on after the required API submission works. It is not needed to satisfy the assignment scope recorded in AGENTS.md. Defer production hosting, dealership accounts/authentication, connection-management UI, multiple-worker scaling, automatic provider failover, and interrupted-run resumption. Multiple dealerships and named connections remain required design foundations within this roadmap.

## Inputs still needed

- A configured dealership slug selected explicitly when importing `docs/context/inventory/data.csv` in chunk 1.
- Grok credentials supplied through local environment configuration and a model choice, before the live check in chunk 2. Never put the API key in the plan, Git, or chat history.
- Any assignment instructions beyond the requirements already recorded in AGENTS.md, if they exist. No further product decisions are needed to use this roadmap.

Validation: checked coverage against AGENTS.md and the shared baseline. Steps 1 and 2 have focused
local, locked Linux, and disposable-volume container acceptance evidence in their implementation
sub-plans. Step 2's live Grok smoke remains pending account access; steps 3–4 remain future work.
