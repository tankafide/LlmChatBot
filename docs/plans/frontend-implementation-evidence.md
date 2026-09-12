# Localhost frontend implementation

Started 2026-09-10 (America/Chicago). Implements frontend-local-chat.md.

- A: React/strict TypeScript/Vite/assistant-ui scaffold, generated API boundary,
  offline schema exporter and loopback Docker proxy. Verify locked static checks,
  deterministic generation/drift and real proxy discovery.
- B: One local conversation controller, bounded history upserts, same-ID recovery,
  terminal precedence and explicit missing-conversation recovery. Verify outgoing
  identities and visible states with deterministic Playwright API fixtures.
- C: Move canonical style tokens, accessible chat screen, real-backend browser
  restart smoke reusing container_acceptance_app and assignment CSV. Extend the
  shared verification path; inspect mobile/desktop layouts and update docs.

Backend application modules are outside this change. Existing working-tree changes
are preserved, including concurrent provider/configuration work.

## Delivered

- Locked React 19.2.4, assistant-ui 0.15.18 ExternalStoreRuntime, strict TypeScript,
  Vite 6.4.3, typed ESLint, Prettier, openapi-typescript and Playwright. Node 22.13.1
  and npm 10.9.2 in Docker; npm installation reported zero audit vulnerabilities.
- Real offline OpenAPI exporter; consumed-field guards and explicit HTTP error
  decoding. Browser read/write deadlines 15/135 seconds, proxy 120/125 seconds,
  backend turn budget 60 seconds. Runtime/package APIs were checked against the
  installed declarations and official upstream documentation.
- One local controller owns admitted-message upserts, draft/pending identity,
  storage, lazy creation and bounded reconciliation. Terminal status precedence
  includes status-only changes. New chat clears pointer/identity without deleting
  history; missing-conversation recovery preserves editable text. Read/write
  results are guarded by view generation. Serial actions and disabled controls
  prevent overlapping submissions and active-view changes during unresolved work.
- Plain text rendering, multiline/IME keyboard behavior, status announcements,
  focus outlines, bottom-follow only when already there, graphite/teal styling.
  Canonical tokens moved into the application; style references updated.
- Non-root frontend Compose service on loopback 5173 with container-owned modules.
  Combined isolated `verify` image, cross-platform `scripts/verify.py`, and CI using
  the same entry point. Backend application/schema files were not changed for UI.

## Observed verification

- `python scripts/verify.py` through uv on the host: exit 0. Docker readiness,
  Compose validation and locked image build passed. Backend Ruff/format/mypy passed;
  **146 backend tests passed** (one upstream Starlette/AnyIO deprecation warning).
  Frontend typecheck, typed lint, format, fresh-schema comparison and build passed;
  **25 Playwright checks passed**. Build reports upstream `use client` directives
  ignored by the client-only Vite bundle; these are not runtime errors.
- Browser recovery tests capture outgoing request IDs/text for duplicate submission,
  transport retry, busy/in-progress/conflict, failed/timeout/interrupted/new attempt,
  restored pending completion, malformed success, validation, internal error,
  lost creation, storage failure and New chat. History tests include page failure,
  nonadvancing cursors and 1,101 messages across bounded actions. Terminal response
  status wins over deliberately stale in-progress history at the same sequence.
- Real API browser smoke imports the assignment CSV into temporary SQLite, searches,
  selects AA-1001, gets price/recalls/crash choices, stops the actual backend process,
  starts a sole replacement on the retained database, reloads identical messages,
  selects NHTSA variant 202 and continues with grounded price. External model/NHTSA
  fakes are reused from existing backend acceptance support. A tiny browser support
  subclass enables stable stock selection; test configuration is isolated from
  concurrently changing development provider settings.
- Offline schema generation twice is identical with database/network connection
  functions disabled. An altered temporary schema fails drift with nonzero status
  without modifying the committed types. The first shared run also propagated a
  browser-smoke failure as exit 1, proving failures are not hidden by the wrapper.
- Agent inspected Chromium screenshots at 320×720 and 1440×900, both long-message
  recovery fixtures and the actual Docker-served empty screen. No horizontal page
  overflow; long URLs/script text wrap safely. Keyboard-only navigation, focus,
  IME, newline/send, preserved reading position and 200% font reflow passed.
  Computed token contrast passed 4.5:1 for used text pairs and 3:1 for input borders.
  A mobile Send wrap and old-failure retry affordance were corrected during review.
- Final focused Docker rerun mounted the latest frontend source/tests into the
  verifier: typecheck, lint, format and all 25 browser checks passed again, including
  successful deliberate retry and removal of the obsolete retry action.
- `docker compose up --build -d backend frontend`: exit 0, healthy backend;
  `/api/dealerships` through the actual browser proxy displayed Mia Motors.
  Frontend `id` reports uid/gid 1000 (`node`); browser page errors were empty.
  No development-database message was created by the browser inspection.

## Live boundary and limitations

The separate existing `compose.safety-live.yaml` smoke ran on 2026-09-10 at about
23:51 America/Chicago (2026-09-11 04:51 UTC). Live NHTSA returned recall evidence and
crash variant 16640. The configured provider's first inventory turn returned
HTTP 502 `provider_error` (sanitized ModelHTTPError/ClientError). Its process exits
0 even when reporting that outcome, so this is **not** a passing live-model demo.
Provider account/model diagnostics remain outside this frontend slice. No provider
credentials were printed or placed in the frontend.

Chromium automation and visual/keyboard inspection are not a complete screen-reader
or cross-browser certification. Full transcript projection is retained in memory;
each history action is bounded to ten pages, but very large histories are not
virtualized. Multi-tab coordination, hosting and the controls excluded by the plan
remain omitted. Failed browser storage limits reload recovery; the browser retains a creation ID across response
loss and reload so retries return the same conversation. Step-four packaging/handoff remains separate.
