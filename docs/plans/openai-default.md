# OpenAI default provider

Add native Pydantic AI OpenAI Responses support to the existing named-runner factory and make
`gpt-5.6-luna` the default connection for both dealerships. Preserve the Gemini and Grok named
connections so persisted conversations retain their pinned provider identity.

- Add the locked OpenAI provider dependency and a lifespan-owned runner with a 30-second request
  timeout and no hidden SDK retries; retain the shared turn, tool, output, and replay budgets.
- Accept `openai` in runtime configuration, dispatch it through the existing factory boundary,
  and configure `primary-openai` as the default without changing the public API or database schema.
- Add the `OPENAI_API_KEY` setting to `.env` and a blank checked-in `.env.example` placeholder;
  never copy a credential value into tracked files.
- Verify default dispatch, missing-key behavior, Responses API structured tool output, request
  bounds, cleanup, and the existing backend static/test suite. Update README and architecture.

Success is a startup-ready application when `OPENAI_API_KEY` is present, chat-unavailable behavior
when it is absent, and no live provider call in deterministic tests. A real-key live chat remains a
separate optional check after the user supplies the credential.

Completed: native Responses runner, OpenAI default dispatch, environment configuration,
locked dependency, and documentation/architecture updates. Verification passed with 179 backend
tests, Ruff lint/format, strict mypy, frozen dependency sync, Compose validation, and a clean backend
image build. Live API verification remains intentionally outside CI.

Live verification follow-up (2026-09-11, America/Chicago): a direct Responses request asserted the
configured `primary-openai` connection, `openai` provider, and exact `gpt-5.6-luna` model. OpenAI's
completed response also reported `gpt-5.6-luna`. The isolated application smoke then completed all
four turns with HTTP 200: 2022 Toyota RAV4 search, stock AA-1001 selection, combined NHTSA
recall/crash evidence, and a contextual price follow-up. It used the assignment CSV and a temporary
SQLite database; the development database was untouched and the credential was not printed.
