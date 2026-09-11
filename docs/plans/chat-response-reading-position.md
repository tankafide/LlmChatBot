# Chat response reading position — 2026-09-11

Outcome: after a user sends a message, the transcript presents the beginning of the assistant
reply in the usable reading area rather than pinning the final line above the composer. The user
can always opt into following the newest content and is never forcibly pulled away while reading
history.

Observed implementation: `frontend/src/chat/ChatScreen.tsx` uses one `follow` flag and sets the
transcript scroll position to `scrollHeight` after every message or pending-state change while that
flag is true. Because this is a non-streaming API, the complete potentially long reply is appended
at once; that rule therefore leaves its tail, rather than its start, visible. The composer is
already outside the scrollable transcript and remains reachable.

## Focused frontend slice

1. Replace the single bottom-follow action in `ChatScreen.tsx` with explicit scroll intent. When a
   newly admitted user message is rendered from the current submission, position that message near
   the upper third of the transcript so the pending state and the beginning of the reply have room
   below it. When the corresponding completed assistant message arrives, align its heading/start
   to a comfortable reading position; do not scroll to the end of a long answer. Use message IDs
   and a ref rather than DOM text matching, and retain existing conversation/version guards.
2. Preserve user agency: automatic positioning applies only while the user was at the latest
   content before the event. Scrolling away disables it. When a reply arrives below the current
   reading position, show an accessible `Jump to latest` control rather than moving the viewport;
   activating it scrolls the current reply start into view. Keep keyboard focus in the textarea
   after submission; scrolling must not steal focus.
3. Keep the transcript a labeled, polite chat log/region and preserve the existing separate status
   messages. The live region should announce completion/status tersely, not re-announce a large
   generated reply on every layout change. The browser must not hide clipping with global overflow
   rules or reduce the composer’s reachable height.
4. Give newly completed assistant text a fast client-side reveal after the non-streaming response
   arrives. Bound the entire effect to well under one second regardless of reply length, expose no
   fake server progress, and render the complete text immediately when the user prefers reduced
   motion. Restored history must not replay the effect.

Expected behavior: a short reply can remain comfortably visible in full; a long reply begins under
the selected user message/assistant label, and readers manually scrolling earlier history retain
their place. A click on `Jump to latest` gives a predictable return path. No backend, API schema,
database, or message-persistence change is needed. The reveal is presentation-only and completes
in at most 700ms, so it does not turn the completed HTTP response into simulated streaming.

Verification to add: use deterministic Playwright replies with a response taller than the
transcript. Assert that after send/completion the assistant start is visible and its final line is
not the only visible content; assert textarea focus remains. Scroll away before a new response and
assert the viewport position remains stable plus the jump control is exposed; activate it and
assert the latest assistant start becomes visible. Assert a newly submitted reply enters and
completes the bounded reveal while restored history is immediately complete; verify reduced motion
bypasses the effect. Re-run the existing 320px/200% text-size tests for no horizontal overflow,
composer reachability, visible focus, and long-content reflow. Run
`npm run verify` from `frontend`, then `python scripts/verify.py` from the repository root for the
shared isolated check.

Evidence: WAI-ARIA identifies chat as a live-region use case and advises authors not to scroll an
element with focus off-screen without user intervention. The proposed behavior leaves focus in the
composer, uses a polite status announcement, and offers an explicit navigation control instead of
forced scrolling. Browser automation was unavailable during this planning inspection, so the
specific currently observed symptom is corroborated by source tracing; the implementation must
perform the stated desktop and narrow-layout browser inspection.
