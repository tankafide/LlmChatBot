# AutoAssist project context

## Goal and required scope
Build a clear, working prototype of an LLM-powered dealership chatbot exposed through an HTTP API (text messages in, text replies out).
- Search inventory in a relational database by a useful combination of make, model, year, price, and body type.
- Answer follow-up questions about a specific vehicle using inventory data and conversation context.
- Integrate NHTSA safety information: both recalls and crash-test ratings.
- Persist every conversation and message in PostgreSQL; conversation state must survive server restarts. Database constraints and row locks coordinate workers; startup and scoped submissions recover only stale requests.
- Include a README with setup/run instructions, configuration, API examples, design decisions, testing, and known omissions.

Favor a small, complete system that is easy to explain and defend. The source inventory is stored at `docs/context/inventory/data.csv`; inspect and import that file rather than inventing project data.

## Prototype workflow
- Keep implementation plans and meaningful plan changes in `docs/plans/`; keep plans short and current.
- Breaking changes are welcome. Update the plan, code, and affected tests together. Do not preserve obsolete behavior just to satisfy old tests.
- No compatibility workarounds, legacy paths, or database versioning/migration framework. Document how to recreate the development database when its schema changes; ordinary server restarts must still preserve state.
- Add fallbacks only as explicit design decisions for expected failure scenarios. Distinguish missing safety data from a verified absence of recalls or safety concerns.
- Validate the changed behavior with focused, meaningful tests; fix or update affected tests before finishing.

## Docker Desktop workflow
- Use Docker Desktop installed on this Windows machine with Docker Compose. The Docker context name `desktop-linux` is Docker Desktop's internal engine name, not a separate Docker or Linux installation requirement.
- Start Docker Desktop through its supported CLI: `docker desktop start --detach --timeout 120`. Do not launch `Docker Desktop.exe` directly with `Start-Process` or assume a system-wide installation path.
- Confirm readiness with `docker info` before running Compose. If startup fails, inspect Docker Desktop logs and runtime state; do not factory-reset or delete images, volumes, or application data without explicit authorization.

## Implemented commands
- Start local storage: `docker compose up -d database`.
- Run locally: `uv run --project backend uvicorn autoassist.main:app --host 127.0.0.1 --port 8000 --workers 2`.
- Import locally with the server stopped: `uv run --project backend autoassist-import-inventory --file docs/context/inventory/data.csv --dealership mia-motors --server-stopped`.
- Run in Docker: `docker compose up --build -d backend frontend`, then open `http://localhost:5173`; stop without deleting data using `docker compose down`.
- Shared verification: `python scripts/verify.py` builds and runs the isolated Compose verifier for both backend and frontend.
- Focused local verification: `uv run --project backend ruff check backend`, `uv run --project backend ruff format --check backend`, `uv run --project backend mypy backend/src`, and `uv run --project backend pytest backend/tests -q`.
- Never run checks against the development database volume. Schema changes require explicit development database recreation; ordinary startup preserves it.

## Code showcase quality
- Write clean, readable, well-architected code with clear names, small cohesive components, and explicit dependencies. Use design patterns when they simplify a real problem; avoid speculative abstractions.
- Separate HTTP handling, conversation/application logic, database access, and LLM/NHTSA integrations. Keep domain behavior testable without live external services.
- Ground vehicle and safety claims in retrieved data. Validate inputs and handle expected external-service failures clearly. Keep secrets in environment configuration and out of Git and logs.
- Keep context and documentation focused. Record significant tradeoffs and omissions in the README, and finish each task with a simple summary of notable changes and validation.
