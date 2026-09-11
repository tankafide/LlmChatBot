---
name: autoassist-frontend
description: Implement or assess AutoAssist React chat UI behavior, assistant-ui adaptation, history restoration, accessible layout, and request states. Use explicitly or as frontend guidance selected by an orchestrator.
---

# AutoAssist frontend

Read [the shared baseline](../../../docs/stack-baseline.md), especially its chat lifecycle, and inspect the existing frontend and API contract before choosing an implementation path. These are planned requirements until scaffolded; frontend implementation follows the required working API slice. Planning defines affected states and acceptance evidence; development implements and verifies them; review reports concrete defects without unsolicited fixes.

Use React, strict TypeScript, Vite, assistant-ui, plain CSS, native fetch, and local component state. Read [frontend architecture](../autoassist-frontend-architecture/SKILL.md) when changing boundaries or state owners, [API contract](../autoassist-api-contract/SKILL.md) for schema changes, and [frontend verification](../autoassist-frontend-verification/SKILL.md) early for affected acceptance checks. Do not load unrelated specialists or create subagents automatically.

## Runtime and transport

- Begin with LocalRuntime and a custom backend adapter; use ExternalStoreRuntime if application-owned message state demonstrably simplifies synchronization. Check installed package APIs before wiring capabilities. Tutorial defaults for branches, edits, regeneration, cancellation, hosted services, Next.js, or client-side tools are not project requirements.
- Send the current submission with application conversation/request identifiers through the API adapter. Backend history and selected-vehicle state remain authoritative; do not post the runtime's entire transcript as trusted model/tool history or make browser snapshots the persistence contract.
- Consume generated OpenAPI request/response types in the fetch adapter. Keep assistant-ui conversion at its boundary and HTTP/error handling out of presentation components. Generated types do not validate JSON at runtime: handle malformed or unexpected responses explicitly without asserting them into a success shape.
- Check HTTP status as well as network rejection; fetch resolves on HTTP errors. Map documented error codes into user-visible states, including non-JSON gateway errors. Use browser-reachable API URLs, preferably the development proxy; never embed credentials or Compose-only hostnames in browser requests.

## Conversation behavior

- Follow the [canonical lifecycle](../../../docs/stack-baseline.md#chat-request-lifecycle), rather than designing a second retry protocol. Create a conversation before its first submission. Allocate an ID once per intentional submission and retain its exact payload through transport retries and unresolved outcomes. A disconnected request is not proof of cancellation or failure; recover with the same ID. A deliberate new attempt after a terminal failure uses a new ID.
- Prevent repeated local sends while busy, including keyboard paths. Distinguish an unaccepted busy submission from an admitted in-progress message; preserve the pending text/ID as appropriate. Do not treat every 409 as the same retryable condition or automatically resubmit terminal failures. Any polling/retry loop needs a bound and explicit unresolved-state UI.
- Restore server history before allowing a continuation. Separate history loading, empty history, history failure, ready, submitting, uncertain transport outcome, and persisted failed/interrupted states. Show only actual assistant replies. If optimistic rendering is used, reconcile by stable identifiers so rejection, retry, or reload cannot duplicate messages or imply admission that never occurred.
- Initiate sends in event handlers, not mount effects. Clean up history reads and ignore stale results when switching conversations; a late response must not overwrite the newly selected conversation. Derive display state where possible rather than synchronize redundant state with effects. Browser reload must restore the conversation from backend history; any locally retained recovery token is a hint, not authoritative history.
- Expose edit, regenerate, cancel, branch, attachment, or feedback controls only when their end-to-end behavior exists. In particular, aborting fetch alone does not implement cancellation. Remove unsupported default assistant-ui controls instead of wiring no-op callbacks that advertise a capability.

## Usable, accessible presentation

For visual design or styling changes, read [UI style](../autoassist-ui-style/SKILL.md) for the canonical tokens, component treatments, and visual reference. Appearance belongs there; this skill retains runtime and interaction ownership. Transport-only changes do not need style guidance.

Keep vehicle and safety text faithful to API data, including unavailable versus verified empty safety results. Render untrusted text safely; do not insert model HTML directly. If rich text is introduced, define supported rendering and safe link handling deliberately.

Use semantic controls with accessible names, visible keyboard focus, associated composer labels, and status/error text that does not rely on color alone. Give the transcript an accessible name and appropriate log/live-region behavior; avoid announcing restored history or the same response repeatedly. Preserve focus during replies and loading. Keyboard submission must respect multiline input and IME composition. Keep long vehicle names, URLs, errors, and message text readable at narrow widths and browser zoom; the composer and retry actions must remain reachable without clipping or horizontal page scrolling. Respect users reading earlier messages instead of forcing every update to scroll to the bottom.

## Evidence before completion

During planning, name observable cases and existing commands, or the checks to add if none exist. During implementation, run available type/lint/format and generated-type drift checks plus focused adapter/interaction checks. Use browser tools to exercise send/reply, reload restoration, a lost-response same-ID retry, busy rejection, failed/interrupted history, and only supported controls as relevant to the change. Verify keyboard focus and narrow/desktop layouts yourself; coordinate test structure with frontend-verification. Use deterministic API data for UI failures and a local backend with external fakes for selected integrated flows. Report observed results and unavailable coverage accurately; do not select a new test runner or claim browser checks passed merely because the skill exists.

Optional background: [research and rationale](references/research.md), consulted when revisiting runtime, transport, or accessibility decisions.
