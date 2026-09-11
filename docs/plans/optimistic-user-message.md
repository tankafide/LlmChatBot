# Optimistic user message — 2026-09-11

Outcome: sending immediately places the submitted text in the normal user-message treatment rather
than a separate submission banner. The pending reply progress remains in the existing status area.

Implementation: `ChatScreen.tsx` renders unresolved text only while no server-owned user message
with the same request ID exists. A successful response replaces that projection with the persisted
message by stable request identity, so the transcript never shows two copies. While delivery is
unresolved or rejected, the controller's existing recovery notice appears inline beneath the same
user bubble and remains a polite status; the global notice does not duplicate it. No API, storage,
or request-lifecycle behavior changes.

Verification: delay a deterministic response and assert one normal user bubble appears immediately,
with no legacy pending banner. Complete it and assert one persisted user message plus the assistant
reply. Exercise an unaccepted/server-busy and an uncertain-transport result and assert the existing
recovery text is inline under the user bubble. Re-run responsive, keyboard-focus, static frontend,
and full browser checks.
