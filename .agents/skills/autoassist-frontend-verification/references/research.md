# Frontend verification research

Checked 2026-09-10 (America/Chicago). These primary sources support the testing approach; the shared baseline owns project stack and lifecycle decisions.

- [Playwright best practices](https://playwright.dev/docs/best-practices): user-facing assertions, isolated tests, controlled external responses, accessible locators, and retrying assertions reduce brittle tests. Applied as rendered outcomes rather than CSS/private-state checks, deterministic API scenarios, and no arbitrary sleeps.
- [Playwright accessibility testing](https://playwright.dev/docs/accessibility-testing): scans find only some accessibility issues and must run in the relevant interactive state. Applied as supplementary scans plus agent keyboard/focus inspection, with no blanket accessibility claim.
- [Playwright emulation](https://playwright.dev/docs/emulation): viewport and device settings support repeatable responsive checks. Applied as narrow/wide layout evidence for affected content; emulation is not evidence of every physical device.
- [Playwright TypeScript](https://playwright.dev/docs/test-typescript) and [TypeScript noEmit](https://www.typescriptlang.org/tsconfig/noEmit.html): browser-test transpilation does not perform full type checking; the compiler can check independently of generated JavaScript. Applied as a separate compiler check covering applicable source and test configurations.
- [openapi-typescript CLI](https://openapi-ts.dev/cli): accepts local/remote schemas and provides `--check` for freshness. Applied as pinned, reproducible local schema/type verification that fails on drift; inspect the installed version before choosing flags.

Project-specific decisions, not upstream prescriptions: explicit-only specialist routing; assistant-ui with a custom backend adapter; stable request identity on transport retry; backend-authoritative history; no selected component/unit runner; conditional small Playwright suite; and one shared Docker/Compose verification entry point and CI workflow. Deterministic browser fakes establish UI behavior; durable replay and backend message/provider counts require real backend evidence.
