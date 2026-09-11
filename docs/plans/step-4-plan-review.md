# Step 4 plan review

Reviewed: 2026-09-10 (America/Chicago).
Scope: pasted Step 4 plan, compared with the current repository and accepted baseline. Review only; no application implementation or test execution.

## Verdict

Sound acceptance design, but make the execution-contract clarifications below before implementing the full handoff. Phase A can begin now. Full execution depends on verified steps 2 and 3; current source has conversational inventory but no NHTSA implementation. File presence is not passing evidence.

## Findings and recommended revisions

1. **One complete verification entry point (phase D/E and final commands).** The shared Compose command runs static/unit/API/process checks, while a second host command separately runs required container acceptance. This leaves the advertised shared command incomplete and conflicts with the baseline's one-entry-point intent. Keep the Compose verifier as an inner command and make a standard-library host wrapper run it followed by container acceptance, propagating either failure. Use that complete wrapper in CI, clean-extraction validation, and final acceptance documentation. Do not call the wrapper recursively from its container phase. Retain the inner command for focused checks.

2. **Define the reusable scenario's host dependency and restart boundary (phase B/D).** A driver accepting an unspecified HTTP client/base URL does not settle how one implementation runs under asynchronous ASGI tests and standard-library-only host Python. Accidental imports of HTTPX, pytest, application models, or test conftest code would break the documented host prerequisite. Specify a synchronous standard-library-only scenario module with a small JSON request callback, adapt it to the existing FastAPI TestClient for integration and urllib for host TCP execution, and keep provider fakes in separate container-side support. Divide it into before-restart and after-restart functions with explicit returned state; the caller owns server/container lifecycle. This is a small clarification, not a new abstraction framework. Correct G6's 'no ... host dependencies' wording to 'no undeclared host dependencies'; Python 3.13 and Docker remain required.

3. **Bound handoff scope explicitly (A/C/G).** The plan already says to reuse existing tests, which is appropriate. Enforce that by making A's coverage map determine new work: an existing test that proves an invariant satisfies that row. Retain one full assignment flow and the required process/container durability evidence. Treat packaging enhancements beyond an explicit safe manifest, hashes, and extraction verification as lower priority if the take-home time budget is still binding. The package-security test matrix and repeated harness fault exercises constitute additional tooling work, not merely running acceptance. This is a scope recommendation rather than a functional defect.

## Existing dependency, not a new plan defect

The absence of NHTSA code blocks B's complete flow and later acceptance, as the plan already acknowledges. Reconcile completed step-2/3 APIs and injection seams in A before finalizing harness implementation. Do not redesign their lifecycle during handoff.

## Strengths to preserve

- Fakes sit at external model/HTTP boundaries while real grounding and persistence execute.
- Committed terminal replay, interrupted requests, and actual process death are distinguished.
- Disposable volumes protect development state.
- Live-provider and remote-CI evidence are separate from deterministic acceptance.
- The delivered archive's exact bytes are validated after extraction.

## Evidence and limits

Read the full pasted plan, planning/backend-verification/Docker skill guidance, baseline, roadmap, current Compose/Dockerfile/manifests, application runner seam, representative recovery tests, source/test inventory, and Git status. No tests, containers, live providers, or remote workflows ran. The original implementation plan is unchanged; this review and the required prompt log are the only files created for this request.

## Resolution

Findings 1 and 2 are resolved in the implementation plan: phases B/D define the standard-library scenario, TestClient/urllib adapters, restart state, and lifecycle ownership; phases D/E/G and the final gate consistently use the planned complete wrapper. Finding 3 remains a scope recommendation; this revision does not change that scope. This records plan readiness, not executed implementation evidence.

