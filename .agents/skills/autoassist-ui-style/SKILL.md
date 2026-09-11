---
name: autoassist-ui-style
description: Apply or review AutoAssist's visual system for chat layouts, colors, typography, spacing, components, and visible states. Use for UI styling or visual design changes; transport-only and backend-only work do not need this guidance.
---

# AutoAssist UI style

Give AutoAssist a consistent, calm, professional appearance using the project's graphite-and-teal direction. This is a specialist selected by the plan/develop/review orchestrators or explicitly invoked. Preserve the requested phase: planning produces decisions, development changes the authorized UI, and review reports evidence without unsolicited fixes. User-requested visual changes can revise this direction; no extra approval or special invocation is required.

## Read the concrete reference

For visual work, read [visual-system.md](references/visual-system.md) and the relevant declarations in [tokens.css](../../../frontend/src/styles/tokens.css). Open [style-reference.html](assets/style-reference.html) when choosing or assessing appearance. It is a local visual specimen, not an implemented chatbot or inventory source. Read [research](references/research.md) only when revisiting the approach or upstream constraints.

Inspect existing application styles and affected components first. Reuse their established token-backed rules and semantic component variants instead of adding parallel buttons, bubbles, spacing conventions, or helper classes. Match both meaning and interaction state, not just a screenshot. A narrow spacing fix needs no full redesign.

## Keep decisions in one place

- Use semantic color roles such as surface, text, action, focus, and warning. Reference CSS custom properties rather than scattering new hex values. Use the shared spacing/type/radius scales; allow an exceptional value only for a concrete layout need and record its reason near the rule.
- The canonical editable token stylesheet is `frontend/src/styles/tokens.css`, linked above. The frontend and this specimen share that file. Keep one editable token source, not an asset copy and application copy that drift. Do not introduce token compilation or a JSON exchange format unless an actual second consumer needs it.
- Keep plain CSS and the accepted React/assistant-ui stack. Adapt existing primitives and public styling hooks through scoped application classes. Check installed APIs; do not assume a tutorial's Tailwind, shadcn theme, or default action set is part of this project. Do not change runtime or API behavior to reproduce the specimen.
- This skill owns appearance and visual state mapping. [Frontend](../autoassist-frontend/SKILL.md) owns interactions/runtime integration, [frontend architecture](../autoassist-frontend-architecture/SKILL.md) owns component/state boundaries, and [frontend verification](../autoassist-frontend-verification/SKILL.md) owns test structure. Load those only when relevant. The [shared baseline](../../../docs/stack-baseline.md) remains authoritative for chat lifecycle and capabilities.

## Make visual decisions observable

Plan the affected component and states against the reference: empty, populated, pending, rejected, failed/interrupted, and partial/unavailable data only where the change touches them. Do not substitute an attractive happy-path mockup for usable failure states, or add controls whose backend semantics do not exist. Product text explains user outcomes; implementation metadata belongs in diagnostics, not UI chrome.

During development, inspect the rendered affected flow at narrow and desktop widths, with long content and keyboard focus. Verify computed foreground/background contrast, control boundaries, readable text, reflow, and unoccluded controls; a matching color name or passing type check is insufficient. Honor reduced motion. Never hide clipping with page-level overflow suppression. Avoid full-page restyling outside scope.

Compare the result to the actual reference for hierarchy, density, surfaces, and state meaning, rather than demanding pixel identity across platforms. Fix observed inconsistencies and report what was visually inspected versus structurally checked. Review findings need a concrete location, affected state, consequence, and proportionate correction; personal taste is an optional suggestion. Update the reference and token source together when an authorized design decision changes.
