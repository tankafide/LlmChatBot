---
name: autoassist-docker
description: Guide AutoAssist Dockerfiles, Compose, locked dependency builds, persistent storage, networking, readiness, shutdown, and container verification. Use when explicitly requested or selected by a project orchestrator for container-related work.
---

# AutoAssist Docker

Read [AGENTS.md](../../../AGENTS.md) and the [shared stack baseline](../../../docs/stack-baseline.md), including its shared PostgreSQL storage and chat lifecycle requirements. Inspect existing Compose files, Dockerfiles, ignore files, manifests, lockfiles, settings, and verification scripts before choosing commands. The baseline records accepted decisions; files establish what is implemented. `tech-stack` remains an explicit-only decision workflow, not an automatic prerequisite.

Use this guidance within the requested phase: planning specifies concrete files, behavior, and evidence; development implements and verifies the authorized slice; review reports defects and coverage gaps without unsolicited fixes. Do not scaffold an application just to demonstrate this skill. Do not add production hosting, orchestration platforms, or extra services without a concrete requirement.

## Build and runtime boundaries

- Use Docker Desktop on this Windows machine with Docker Compose, backend first and a frontend development service when the UI exists. Start it through the supported CLI with `docker desktop start --detach --timeout 120`, then confirm readiness with `docker info`. Do not launch `Docker Desktop.exe` directly or assume a system-wide install path. The context name `desktop-linux` is internal to Docker Desktop and does not require a separate Linux installation. Inspect actual failures instead of claiming a build ran.
- Pin compatible runtime/base-image and uv versions during scaffolding. Install Python from committed `uv.lock` with lock consistency enforced, and frontend dependencies with `npm ci` from `package-lock.json`. Resolve legitimate lock changes deliberately; do not conceal drift with an install that rewrites locks during verification. Include development dependencies in check images even if a runtime image omits them.
- Keep build contexts narrow and `.dockerignore` effective at the actual context root. Exclude credentials, local databases, host `.venv`, and `node_modules`. Supply application secrets at runtime, never through image layers or frontend public configuration. Avoid printing expanded Compose configuration containing secret values; use quiet validation when appropriate.
- Copy dependency manifests/locks before frequently changing source when useful for caching. Keep Python virtual environments and Node modules inside their containers. A broad source bind mount can hide image-installed dependencies; use selective source mounts or an explicit container dependency location. Account for stale dependency volumes after lock changes without deleting the PostgreSQL data volume.

## Storage, process, and connectivity invariants

- Mount PostgreSQL data on its named volume and keep backend credentials runtime-only. Run the app as a non-root user. The database container owns volume permissions and readiness.
- Multiple backend workers or stateless instances may share PostgreSQL. Serialize schema/bootstrap with the database startup lock, protect fresh active requests, and recover only stale work. Startup must validate storage before admitting requests; no reset, reseed-overwrite, or in-memory fallback on failure.
- Use signal-forwarding execution (exec-form entrypoint or an explicit `exec` in a wrapper). Align the server's bounded drain and Compose `stop_grace_period` so normal shutdown can finish cleanup before forced termination. Abrupt termination must still recover according to the shared lifecycle; graceful shutdown is not the durability guarantee.
- Bind servers inside containers to `0.0.0.0`; publish development ports on host localhost. Compose service DNS is for containers. Browser requests use a browser-reachable address, preferably relative API URLs through the frontend development proxy to the backend service.
- Treat running and ready as different states. Health checks use an existing local endpoint that reflects service/storage readiness and does not call LLM/NHTSA. Ensure the probe executable exists in the image; when startup ordering matters, use health-conditioned dependencies rather than arbitrary sleeps.

## Observable completion

For affected implementation, validate Compose, build from locks, and exercise the actual service through its published API. Use the project's one cross-platform verification entry point and the same entry point in CI; add checks there rather than creating competing automation. Propagate container/check exit codes to the caller and prove an intentional failing check returns failure. Never run tests against the development PostgreSQL volume.

For persistence/shutdown changes, use a disposable PostgreSQL test service or separately named test volume: write a conversation, recreate the backend/database container, and confirm messages and terminal replay survive. Include an abrupt-stop/in-progress stale-recovery case with backend-verification. Distinguish application-object recreation evidence from process/container restart evidence. Coordinate with persistence/backend-verification on persisted outcomes and frontend/frontend-verification on browser connectivity.

Document verified commands and outcomes, unresolved tool limitations, runtime versions, normal stop/restart, and the separate explicit development database reset. Ordinary shutdown must not use `down -v` or volume pruning. The guarantee assumes the data volume survives; volume deletion/disk loss, backup systems, high availability, and automatic interrupted-run resumption remain outside scope.

Read [research notes](references/research.md) only when revisiting these Docker/dependency decisions or checking upstream semantics.
