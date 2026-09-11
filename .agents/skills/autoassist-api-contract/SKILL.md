---
name: autoassist-api-contract
description: Design, implement, or review AutoAssist public HTTP schemas, error contracts, OpenAPI generation, and generated frontend type compatibility. Use when the API boundary or its consumers change.
---

# AutoAssist API contract

Read [AGENTS.md](../../../AGENTS.md) and the [shared baseline](../../../docs/stack-baseline.md), especially its API contract and chat lifecycle, before making contract decisions. This specialist supports the requested planning, development, or review phase; loading it does not authorize implementation or spawn agents. Keep the lifecycle table authoritative rather than copying it here.

## Own the public boundary

- Inspect existing schemas, routes, exception handlers, generated files, adapter callers, and generation/check configuration before changing them. During planning, identify affected operations, success/error bodies, consumers, and verification. During implementation, change these together. During review, trace actual response branches, not just type declarations.
- Public Pydantic schemas belong to the application and remain separate from ORM entities, Pydantic AI replay serialization, and assistant-ui message formats. Expose only fields the client needs; history represents persisted application messages and request states. Browser history never supplies authoritative tool results.
- Declare required versus optional and nullable fields intentionally, with bounded text/collection inputs and stable enum values where behavior depends on them. Preserve wire representations in generated types; transformations such as parsing dates belong in the adapter. Do not hide input/output schema differences by forcing them into one frontend interface.
- Use the baseline's request ID scope, payload comparison, admission, replay, and status/error mappings. A transport retry preserves ID and payload; a fresh ID means a deliberate new submission. Describe these semantics in API examples, including a terminal failure replay and busy response. Do not equate a disconnect with cancellation or terminal retry with another provider attempt.
- Declare all implemented success and error responses in OpenAPI, including validation and exception-handler paths. Use machine-readable error codes aligned with the lifecycle, sanitized messages, and an explicit body shape. Do not silently change FastAPI's 422 envelope without updating its handler, schema, tests, and consumers together. Error-response documentation alone does not validate a directly returned response. Match actual media types and serialization, including stored terminal response replay; do not leak provider exceptions or database details.

## Generate from the real application

- FastAPI routes and public schemas are the source for OpenAPI; openapi-typescript is the locked frontend development dependency generating the committed type file. Import generated operation/component types in the native-fetch adapter; avoid handwritten duplicate payload interfaces or edits to generated output. A narrow alias into generated types is fine.
- Make local schema export instantiate the same route/schema configuration and call the application's OpenAPI generation without starting the server or its lifespan. Construct live clients and validate serving credentials at runtime startup, not schema-import time. Schema export must need neither provider credentials nor LLM/NHTSA calls, database writes, or the development volume. Do not invent a reduced fake schema app that can drift from real routes.
- Use installed, lockfile-resolved tools in the accepted Docker/Compose workflow. Keep schema references local and generation deterministic; avoid timestamps or environment-dependent fields. Record the actual export/generation commands and output paths when implemented; no application scaffold or executable project commands exist merely because this skill does.
- The shared verification entry point must export fresh OpenAPI, regenerate types, and fail on missing/stale committed output. A temporary-output comparison avoids rewriting developer files; compare with the same formatting rules used for generation. Never check only an old schema snapshot. Run twice to establish stable output, and verify a deliberate schema change produces drift failure in an isolated test before regeneration.

## Prove compatibility

Use the backend and frontend verification guidance for affected checks. Exercise real HTTP serialization with injected external fakes: representative success, invalid input, each affected error code, and replayed terminal responses must match documented bodies/statuses. Compile the adapter against regenerated types and exercise its success/error branches, including request ID preservation and displayed request state. Type generation alone does not prove either HTTP behavior or adapter correctness.

Generated TypeScript types have no runtime validation. Treat parsed JSON as untrusted at the adapter boundary; use proportionate runtime checks for consumed fields and a clear malformed-response path. Do not claim that a cast validates a body or add a second manually maintained schema system by default. Test malformed JSON/unexpected shapes when this boundary changes.

Update API examples and the shared API-boundary section in `docs/architecture.md` when implemented, coordinating with architecture owners. Report observed generation, drift, HTTP, and adapter checks separately from pending work. Optional [research notes](references/research.md) explain the upstream mechanisms behind these project decisions.
