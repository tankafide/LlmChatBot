# Chat-agent research

Researched 2026-09-10 (America/Chicago). These upstream mechanisms inform implementation; the shared project baseline owns provider selection, persistence, and request semantics. Verify APIs against the installed version when scaffolding.

- [Pydantic AI agents and usage limits](https://pydantic.dev/docs/ai/core-concepts/agent/#usage-limits): request and successful-tool limits address different work. Input token accounting can occur after the response, so bounded application input and provider output settings still matter.
- [Retries](https://pydantic.dev/docs/ai/core-concepts/retries/) and [timeouts](https://pydantic.dev/docs/ai/core-concepts/timeouts/): distinguish model-correction retries from transport failures and total execution time. Project inference: budget every layer together and settle exhausted runs through the accepted lifecycle.
- [Function tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/) and [advanced tools](https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/): typed arguments support validation; concurrent calls require deliberate state ownership. Sequential tools prevent overlapping shared mutations. Successful-tool counts exclude failed executions and output tools, so that limit cannot stand alone.
- [Message history](https://pydantic.dev/docs/ai/core-concepts/message-history/): history can be serialized and supplied to later runs; processing can alter retained messages and what is considered new. Project decision: preserve complete durable history independently, trim only model input at complete-turn boundaries, and round-trip test persistence.
- [Unit testing](https://pydantic.dev/docs/ai/guides/testing/): `Agent.override`, `TestModel`, and `FunctionModel` support replacement and scripted tool exchanges; `ALLOW_MODEL_REQUESTS=False` blocks accidental live requests. Project inference: use scripted failures and inspect received history, since a generic model stub does not establish grounding quality.

No live provider was selected or called. Research does not establish application test coverage or justify adding durable execution engines, a provider abstraction framework, or an observability platform.
