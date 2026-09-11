# Live manual browser testing — 2026-09-11

Follow-up: regression tests, selection correction, and bounded Google 503/504 recovery are
recorded in [fix evidence](../plans/manual-test-fixes.md). The original findings below describe
the pre-fix session; the final browser rerun passed the original search/detail/reload/safety flow.

## Outcome

Tested 11 live chat submissions across three conversations, plus browser input, recovery, reload, and layout scenarios. Five submissions completed; six failed with persisted `provider_error` (HTTP 502). One completed response exposed a context defect. This is an exploratory sample, not a statistical failure-rate estimate.

Environment: existing http://localhost:5173 UI and Docker Compose backend, Mia Motors, configured Google `gemini-3.1-flash-lite`. Real UI submissions and live providers; CSV facts checked against `docs/context/inventory/data.csv`. No application fixes, configuration changes, server restarts, or database resets. Existing automated suites were not run in this manual-testing task.

## Findings ordered by impact

### 1. Live provider failures prevent a reliable demo (high)

Six of eleven submitted messages ended with HTTP 502 / `provider_error`: both explicit-stock safety attempts in conversation 1, a combined inventory search in conversation 1, explicit selection in conversation 2, and safety plus the adversarial prompt in conversation 3. All three explicit safety attempts failed, including one as the first message in a brand-new conversation. Successful inventory and no-match turns show the app is not completely unavailable.

Observed logs include `Chat provider failure: type=ModelHTTPError cause_type=ServerError`. The exact upstream cause remains undiagnosed; this does not establish an NHTSA outage or incorrect credentials. Relevant boundary: `backend/src/autoassist/chat/budget.py:46-59`; provider construction: `backend/src/autoassist/chat/gemini.py:26-43`. Next correction should start with sanitized upstream status/category and correlation diagnostics, then verify the configured model/request path with these exact prompts. Do not mask the problem by fabricating successful replies.

### 2. A resolved detail response does not necessarily retain vehicle selection (medium)

Reproduction, conversation 1:
1. Send `Show me Toyota SUVs under $35,000.`
2. Send `Tell me more about the third one. What is its mileage, drivetrain, and price?`
3. Correct reply identifies AA-1001, 15,819 miles, FWD, $26,335.
4. Reload; both turns restore.
5. Send `What recalls and crash-test ratings does it have?`
6. Reply: `Please specify a stock number or a number from the latest vehicle list.`

Public history reports `selected_vehicle_id: null`. This is a backend state invariant gap, not evidence that browser reload deletes state. At `backend/src/autoassist/chat/grounded.py:492-496`, detail validation checks which vehicle is described but does not require that vehicle to become the retained selection. The answer selection defaults to keep. Require or derive the resolved detail selection before successful completion and cover the next pronoun follow-up. A real restart test should follow a fix in isolated storage.

## Manual scenario results

| Scenario | Observed result |
| --- | --- |
| Initially unavailable conversation | New chat recovered composer; prior conversation absence not diagnosed |
| Toyota SUVs under $35,000 | Exactly six CSV matches, correct prices/specifications; first reply approximately 29 seconds |
| Numbered detail reference | Correct third result AA-1001, requested facts correct |
| Repeated Enter while submitting | One admitted user message and one reply, no duplicate |
| Busy controls | Send and New chat disabled during active submission |
| Reload completed transcript | Both turns restored in order, no duplicates |
| Pronoun safety follow-up | Context defect above |
| Explicit safety request and deliberate retry | Both failed with provider_error |
| Try again | Exact failed text restored and focused; no automatic submission |
| Deliberate resend | Distinct request identity; prior failed message retained |
| Reload during request | Admitted in-progress message restored with Check reply |
| Check reply during/after request | In-progress notice then terminal error replay; no extra admitted duplicate |
| Failed-message rendering | No fabricated assistant response; failed status persisted |
| Combined make/model/year/body/price filters | Failed in conversation 1; succeeded in fresh conversation 2, exactly AA-1001 |
| New chat | Cleared displayed transcript and browser pointer; earlier history still readable through API |
| Whitespace-only Enter | Ignored, Send disabled |
| Shift+Enter | Newline inserted without submission; multiline query later succeeded |
| Explicit stock selection | Provider error, selection success unverified |
| No-match Ferrari SUV under $5,000 | Correct no-match reply, no invented inventory |
| 4,000-character boundary | Extra typed character blocked; counter stayed 4,000; test draft cleared unsent |
| 390 x 844 mobile layout | Long text wraps, composer/Send reachable; temporary viewport override reset |
| Fresh-conversation safety | Provider error; previous history is not the sole cause |
| HTML-like user text | Script text displayed literally in pending and saved message, no observed execution |
| Instruction to invent price/no recalls | Provider error with no fabricated reply; successful model resistance unverified |

## Evidence

Saved public API transcripts (only these test conversations):
- `2026-09-11-manual-conversation-1.json`: `1a5164c4-3da4-445a-bdfd-a1f7cebb4c9a`
- `2026-09-11-manual-conversation-2.json`: `07dcbeca-f911-4c74-93fb-ef920879130c`
- `2026-09-11-manual-conversation-3.json`: `025a7bf6-be09-475f-967b-960bc5994d70`

Dealership: `2b64c0b5-0548-4d8e-88a4-9739b3be9dfd`.

## Remaining coverage

No successful end-to-end safety result, crash variant disambiguation, recall-empty/unavailable distinction, server restart durability, injected network outage, cross-tab concurrency, screen reader/IME, or long-history pagination was verified in this pass. Source reading and a small script-text rendering check do not constitute a security audit. Provider failures should be resolved before extending conversational coverage. The test conversations remain saved; application source was not changed.
