# AutoAssist visual system

Direction selected 2026-09-10 under the user's delegated design authority. This is the initial project direction, not an industry-mandated palette. The [token stylesheet](../../../../frontend/src/styles/tokens.css) owns exact values; the [visual reference](../assets/style-reference.html) demonstrates them. No real inventory or working chat is included.

## Character and hierarchy

Use a light reading canvas, white content surfaces, graphite navigation/chrome, and deep teal for the main action, selected item, and small brand accent. The effect should feel like a considered dealership concierge: confident, useful, and restrained. Give answers room to read. Avoid hero-sized marketing layouts inside an active conversation, decorative car photography, glass effects, neon glow, gradient text, and decorative badges that resemble factual certifications.

The main hierarchy is conversation title/context, latest exchange, then composer. On a wide screen, a compact graphite conversation rail may appear once history switching exists. On narrow screens, make that navigation accessible through a real implemented disclosure or another compact layout; do not merely hide an existing capability. The specimen rail navigates its reference sections and is not a requirement to implement a conversation sidebar now.

## Tokens, type, and geometry

- Use `--aa-*` roles from the stylesheet. Surface borders are decorative separators; input boundaries and focus use stronger tokens. Never use the quiet separator token where it is the only way to identify an interactive control.
- Use the system sans-serif stack for dependable rendering without a font service. Body and composer text default to 1rem with generous line height; small text is reserved for metadata, never the only representation of an error or action. Avoid all-caps body text, ultralight text, and shrinking input text to solve mobile layout.
- Use the 4px-based spacing scale. Prefer 16–24px inside content regions, 24–32px between exchanges, and compact but distinct label/value spacing. Keep the reading column at roughly 45–70 characters, bounded by the content-width token and available viewport. Do not force a minimum width on mobile.
- Use modest corners: small controls, slightly rounder message surfaces, and a larger composer radius. Use one understated elevation for the composer or raised shell, not shadows on every message. Icons use a consistent line weight and size; decorative icons are hidden from assistive technology, icon-only actions have accessible names.
- Controls default to at least 44px in each target dimension (a project comfort target, not the WCAG AA minimum). Focus uses an offset solid outline with a contrasting gap; never remove the native indicator without a visible replacement. Text normally reaches 4.5:1, qualifying large text 3:1, and required control/state indicators 3:1 against adjacent colors. Check actual pairings and states; token measurements alone do not establish conformance.

## Component treatments

| Element | Stable treatment |
| --- | --- |
| Assistant reply | Left aligned, open white/light surface, readable paragraphs and short lists. Use a small assistant label/mark; avoid putting every paragraph in its own card. |
| User message | Right aligned within the reading column, pale teal surface with dark text; width follows content up to a sensible bound. Identity is also conveyed by placement/label, not color alone. |
| Primary action | Deep teal with white text, darker hover/pressed roles, clear focus. One main action per region. No opacity tricks that silently weaken text contrast. |
| Secondary action / suggestion | White or quiet surface, dark label and discernible border where needed. Suggestions must correspond to supported actions; do not make decorative chips look clickable. |
| Composer | White, strong outline, comfortable padding, labeled multiline input and distinct send target. Keep helper/status text outside the editable content. Sticky positioning is optional; if used, reserve transcript space and test short viewport/keyboard occlusion. |
| Vehicle summary | Introduce only when structured API data supports it. Put vehicle identity first, price next, then a few factual label/value pairs. Use tabular numerals for prices. No fabricated vehicle images, ratings, stock counters, finance terms, or inventory records. |
| Source / safety detail | Readable source label near the relevant claim, underlined text links, separate recall and crash results. “Unavailable” is neutral or amber with explicit text, never a green check. |

## State language and appearance

| State | Visual and wording rule |
| --- | --- |
| Empty | Briefly identify the AI dealership assistant and supported tasks; use suggested prompts only when they submit through the real input path. |
| Pending | Keep admitted user content visible and display a restrained textual progress indicator such as “Looking that up…”. Do not invent percent completion or pretend a particular lookup occurred without evidence. |
| Uncertain transport outcome | Say the reply could not be confirmed; preserve the recoverable request state. Styling does not decide whether a new message should be sent. |
| Rejected/busy | Explain that this submission was not accepted; preserve the draft appropriately. Do not style it as an admitted failed message. |
| Failed/interrupted | Persistent inline error text near the affected request, with the supported recovery action. Do not rely on a disappearing toast or fabricate an assistant reply. |
| Safety unavailable/partial | Explicit status and retained useful data. Do not equate a request that completed successfully with a vehicle being safe. |
| Verified empty recalls | State only that no recalls were returned for the identified lookup. No blanket “safe” badge; follow NHTSA guidance for qualifications. |

Initial theme is light with dark chrome. Do not add dark mode, theme toggles, or extra navigation just to display a design system. Motion is optional: prefer brief color/focus transitions; avoid animated transcript entrances or persistent shimmer. Respect reduced-motion preferences and preserve readability in forced-color modes.

## Evidence for a change

Check the affected component at 320px and a desktop width, enlarged text/zoom as relevant, long vehicle names/URLs, pending/error content, keyboard focus, and reduced motion. Test actual interactions with frontend-verification when implemented. A static specimen proves appearance and layout only; it cannot prove runtime accessibility, mobile virtual-keyboard behavior, persisted history, or backend safety semantics.
