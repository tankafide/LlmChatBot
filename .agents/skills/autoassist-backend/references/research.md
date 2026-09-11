# Backend research

Reviewed 2026-09-10 (America/Chicago). Primary documentation informs framework mechanics; project-specific durability and ownership rules come from the [approved baseline](../../../../docs/stack-baseline.md), not upstream framework guarantees. No application exists yet, so these are guidance and acceptance criteria rather than verified runtime behavior.

| Source | Agent failure prevented and resulting rule |
| --- | --- |
| [FastAPI concurrency](https://fastapi.tiangolo.com/async/) | Framework-managed synchronous endpoints/dependencies are dispatched differently from ordinary helpers. Calling a blocking helper inside async code does not offload it; trace the entire database unit and verify event-loop responsiveness. |
| [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) | Lifespan owns setup and cleanup around serving. Put pooled resources and readiness recovery there; avoid mixing lifespan with deprecated startup/shutdown handlers and avoid import-time I/O. Recovery semantics themselves are project decisions. |
| [Pydantic settings](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/) | Typed settings validate configuration from configured sources. Validate essential runtime settings before writes, inject tests' settings, and avoid silently replacing missing secrets or persistent paths with unsafe defaults. |
| [HTTPX async support](https://www.python-httpx.org/async/) | Repeated client creation defeats connection pooling. Reuse an injected AsyncClient within its application lifespan and await closure. |
| [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/) and [resource limits](https://www.python-httpx.org/advanced/resource-limits/) | Connection caps and phase timeouts address different limits. Bound both; neither alone limits total LLM-turn duration or the number of waiting tasks. |
| [FastAPI errors](https://fastapi.tiangolo.com/tutorial/handling-errors/) | Custom exception handlers can implement consistent boundary mapping, but response-validation failures are server defects. Do not leak validation internals or classify every validation exception as bad client input. |

The approved baseline adds non-streaming request replay, thread-local complete database units, exclusive startup recovery, one worker per SQLite volume, and completion only after commit. The skill links that source rather than duplicating its lifecycle table. Architecture, persistence, API contracts, and verification retain their respective detailed ownership.
