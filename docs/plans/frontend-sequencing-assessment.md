# Frontend before step four: sequencing assessment

Date: 2026-09-10 (America/Chicago).
Scope: dependency assessment only; no implementation or adopted roadmap reorder.

The localhost frontend can be implemented before step four. It consumes the existing steps 1–3 API; its plan requires no new endpoint or database schema. Step four primarily consolidates verification, closes demonstrated defects, supplies shared automation, and prepares documentation and packaging. It is not a functional prerequisite for the browser interface.

Step-three evidence records 132 passing tests in locked Compose verification, disposable-container restart/replay acceptance, and successful live NHTSA checks. Live Grok failed with a provider error, so a working live chat demonstration remains unverified. A frontend will not resolve that provider issue. These are recorded results, not checks rerun for this assessment.

If choosing frontend first, retain its existing behavioral and browser acceptance criteria. Reuse the existing grounding fixtures and scripts/verify-chat-container.ps1 support where applicable. Implement offline OpenAPI export and frontend checks as required by the frontend plan; extend the existing Compose verification structure. The planned scripts/verify.py host wrapper and CI workflow are not present yet: coordinate their eventual integration with step four instead of creating competing automation. Step four must verify and package the final tree, including the frontend if delivered.

The tradeoff is scheduling and possible defect-driven rework, not a known architectural dependency. The roadmap deliberately prioritizes the required API submission over optional UI. Frontend-first is reasonable when a browser demonstration is the immediate priority; keep step four as the final completion gate.

Evidence inspected: product-roadmap.md, frontend-local-chat.md, frontend-plan-review.md, step-4-verification-handoff.md, step-3-implementation-evidence.md, shared stack baseline, current API route inventory, Compose verifier, and available scripts. Some older plan text still describes step three as in progress; the later implementation evidence supersedes that historical observation. No application changes or runtime verification were performed.
