# LLM request feedback

Scope: improve the existing non-streaming UI using the existing persisted error codes; no schema change.

- Show elapsed browser wait and truthful slow-response guidance at 15 and 60 seconds. Do not infer exact provider retries, health, or tool stages from elapsed time. Keep duplicate sends locked and existing same-ID recovery.
- Explain provider timeouts and provider errors in both the status and saved message, including after reload. Distinguish browser timeout from confirmed provider failure.
- Keep presentation in ReplyProgress and shared failure copy in requestFeedback; the controller retains lifecycle ownership. Reuse current status styles and live regions, without per-second announcements.
- Verify with deterministic Playwright delayed replies, terminal errors/reload, timer reset, narrow layout and existing recovery tests; run shared isolated verification. The running frontend uses its source mount.

Limit: exact provider retry/tool progress remains unavailable in the non-streaming API. Elapsed time starts when the current browser wait begins.

Completed: shared verification passed (176 backend tests, 27 Playwright tests, Ruff/mypy, TypeScript/ESLint/Prettier, API drift and production build). Browser inspection of the user's restored failed message confirmed the specific timeout explanation and readable layout. The slow-response Playwright case verifies 15/60-second guidance, elapsed time, locked sends, completion cleanup and 320px reflow. Restarted frontend to invalidate stale Vite transforms; backend and database were unchanged. Scoped review found no lifecycle/schema changes or automatic resubmissions.
