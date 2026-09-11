# Demo video script — 2026-09-11

Outcome: a 60–90 second browser recording demonstrates the live OpenAI-powered chat flow using
the imported assignment inventory, selected-vehicle context, and NHTSA safety data. The final
short GIF should show the safety reply and the context follow-up; it need not show the full wait.

Prerequisites: Docker Compose is running, `http://localhost:5173` is open, the imported
dealership contains `AA-1001`, and the configured chat connection is `primary-openai` using
`gpt-5.6-luna`. Start a new conversation immediately before recording so no prior selection or
message history appears.

1. Send: `Show me 2022 Toyota SUVs under $30,000.`
   Expect two matching RAV4s, including stock `AA-1001` (2022 RAV4 LE, $26,335, FWD) and
   `AA-1041` (2022 RAV4 XLE, $27,563, AWD). This demonstrates combined inventory retrieval.
2. Send: `Select stock AA-1001.`
   Expect the assistant to confirm the 2022 Toyota RAV4 LE selection. This establishes durable
   selected-vehicle context.
3. Send: `What are its recalls and crash ratings? Include sources.`
   Expect a grounded NHTSA response that covers both recalls and ratings, includes source links
   and retrieval timing, and clearly labels any unavailable or partial safety data. Do not script
   a particular recall count or star rating because these are live external results.
4. Send: `How much does it cost, and what drivetrain does it have?`
   Expect `$26,335` and `FWD` without repeating the stock number. This proves the model used the
   selected vehicle and earlier conversation context rather than treating every turn as isolated.

Recovery: if a reply fails or exceeds the UI's normal wait guidance, stop the recording, begin a
fresh chat, and retry the current prompt once with a new send. Capture the visible failure only if
the video is intended to demonstrate error handling; it does not prove the successful LLM flow.

Acceptance: the recording shows four completed assistant replies, correct inventory facts for
`AA-1001`, an NHTSA answer with sources or an explicitly qualified live-data limitation, and the
final contextual price/drivetrain answer. The documented inventory facts were checked directly
against `docs/context/inventory/data.csv`; a prior isolated live OpenAI rehearsal completed this
same search, selection, safety, and price-follow-up sequence with HTTP 200 responses.
