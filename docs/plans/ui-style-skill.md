# Consistent chatbot UI style

Status: complete and ready for use. User delegated the visual direction and skill design on 2026-09-10 and requested no further testing.

## Decision and scope

Add `autoassist-ui-style` as a focused specialist, following the existing explicit-only specialist routing policy. The initial catalog deliberately omitted a styling skill; this request supersedes that omission. Existing frontend guidance covers behavior/accessibility but does not define a reusable visual system.

Use a small semantic CSS token set, component/state rules, and a self-contained visual reference. Choose a light reading surface, graphite navigation, and restrained deep-teal actions with a system font stack. Keep plain CSS and assistant-ui; no UI-kit dependency, theme generator, hosted service, or application scaffolding.

## Steps and exit criteria

1. Read current primary design-token, chatbot, assistant-ui, and accessibility documentation. Record which guidance is adopted and which appearance decisions are project choices.
2. Author skill, invocation metadata, focused visual-system/research references, and token/reference assets. Integrate selective routing into all three orchestrators and frontend/verification. Keep one editable token source and preserve API/state ownership.
3. Validate skill metadata and links. Render the reference at desktop/mobile widths; verify overflow, focus/targets, text/control contrast, long content, and reduced-motion behavior where relevant. Inspect screenshots and correct observed problems. Record the scope of evidence without claiming the unbuilt application's UI is verified.

## Completion

Created autoassist-ui-style with explicit-only specialist metadata, visual-system and research references, canonical CSS tokens, and a browser-viewable specimen. Integrated all three orchestrators plus frontend/verification guidance. Structural validation passed. Completed checks covered 320/390/1440px layouts, long content, 200% text enlargement, keyboard focus, control sizes, reduced motion, forced-color indicators, and 18 token contrast pairings. Desktop/mobile screenshots were inspected. Independent review found no blocking instruction or routing defects. The specimen demonstrates appearance, not working chat behavior or full accessibility conformance. No further evaluation is required for this authoring task.
