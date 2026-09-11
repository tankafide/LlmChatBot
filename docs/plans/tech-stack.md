# Tech stack decision

Accepted: Pydantic AI for backend LLM orchestration, assistant-ui for the React chat interface, and openapi-typescript for frontend API types generated from FastAPI's OpenAPI schema. The [shared stack baseline](../stack-baseline.md) contains the authoritative baseline and library boundaries; tech-stack remains the explicit-only decision workflow.

During implementation, connect ordinary inventory/NHTSA services through thin tools and connect assistant-ui to the FastAPI API through a custom adapter. Keep SQLite authoritative for persisted conversations and isolate library message formats from public schemas. Verify compatible package versions when scaffolding.

When scaffolding the frontend, add reproducible type generation and a schema/type drift check to the shared verification command. Use the generated types in the fetch adapter and commit the generated type file.

The initial provider is xAI/Grok. The supplied inventory is preserved at `docs/context/inventory/data.csv`; its importer remains pending. The backend foundation and inventory search API are implemented.

Accepted: async orchestration offloads complete synchronous database units to worker threads. Sessions are created, used, and closed within one unit; factories supply independent sessions to concurrent tools. Application services own short transactions; no transaction spans external-service waits. Follow the authoritative [database execution rules](../stack-baseline.md#database-execution-and-session-ownership).

Accepted: non-streaming chat uses one backend worker per SQLite volume, database-enforced admission of one active request per conversation, and client request IDs for persisted outcome replay. Provider failures preserve admitted user messages; startup marks unfinished requests interrupted without rerunning them. The [request lifecycle acceptance table](../stack-baseline.md#chat-request-lifecycle) defines responses, retries, history, and recovery. Implement its focused concurrency/failure/durability tests with the first chat persistence slice; these behaviors are not implemented yet.

Accepted: Docker Desktop on this Windows machine and Docker Compose are the standard build/run/verification workflow, replacing the earlier Docker deferral. Use a backend container with uv and the committed Python lockfile; add the frontend development container using npm and its lockfile when the UI is implemented. Start Desktop with `docker desktop start --detach --timeout 120` and verify readiness with `docker info`; `desktop-linux` is Docker Desktop's internal context name, not a separate Linux setup. Keep SQLite in a named data volume mounted by the backend; ordinary restarts, container recreation, and rebuilds must preserve conversations. Database reset is a separate explicit operation.

Dockerfiles, `.dockerignore`, Compose configuration, runtime environment examples, and concrete README setup/run/check/reset commands now exist. Keep browser URLs distinct from Compose service names, prevent host dependency mounts from hiding container dependencies, and run checks against isolated test storage. Validate configuration, clean image builds, API connectivity, and persisted state after container recreation. CI will run the shared container-based verification entry point when added.
