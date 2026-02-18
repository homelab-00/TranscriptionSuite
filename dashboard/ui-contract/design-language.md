# Design Language

Visual direction and style constraints for the TranscriptionSuite dashboard renderer.

The `transcription-suite-ui.contract.yaml` is the machine-enforced source of truth. This document provides qualitative guidance for interpreting and extending the contract. If there is a conflict, the contract governs runtime enforcement. **The original UI mockup (Tailwind v3 CDN) is the ultimate source of truth on design intent — if the contract or this document conflicts with the mockup's visual output, the mockup overrules.**

---

## Visual Direction

- Dark frosted glass with restrained contrast accents
- Apple-like translucency discipline with practical developer ergonomics
- Priority: legibility first, atmosphere second

## Color Space

- **All colors must render in sRGB.** The original mockup was built with Tailwind v3, which uses sRGB for all color operations. Tailwind v4's oklch/oklab progressive-enhancement `@supports` blocks are stripped at build time via a PostCSS plugin (`strip-oklab-supports`) to preserve the mockup's deeper, richer color rendering.
- Default palette shades are pinned to their Tailwind v3 hex values in the `@theme` block (e.g., `--color-slate-300: #cbd5e1`) to prevent oklch gamut-mapping drift.
- Opacity modifiers (e.g., `bg-black/60`) must produce simple `rgba()` output, not `color-mix(in oklab, ...)`.
- Gradient interpolation must occur in sRGB, not oklab.

## Surface Language

- Use glass surfaces (`glass-*`) as the primary panel language; avoid introducing opaque blocks
- Every elevated layer must have consistent radius and shadow logic from the contract tokens
- Portal surfaces (dropdowns, menus, modals) must stay within the approved z-index layers
- Layer depth comes from translucent surfaces, subtle borders, and controlled blur

## Color Usage

- **Cyan** (`accent-cyan`): active guidance, primary interactive elements, selection
- **Magenta** (`accent-magenta`): secondary emphasis, gradient accents
- **Orange** (`accent-orange`): warning states, tertiary emphasis
- Keep accent usage deliberate — each accent has a specific semantic role

## Scroll Indicators ("Blur Bars")

- Horizontal, absolutely-positioned gradient strips at the top/bottom of scrollable columns
- Must use `backdrop-blur-sm` with a linear-gradient mask (`black 50%` → `transparent 100%`)
- Right offset must be `right-3` (0.75rem / 12px) to align with the 8px scrollbar + padding
- Paired corner masks use the body background (`radial-gradient` cutout, `backgroundAttachment: fixed`) so they blend seamlessly with the page background

## Motion

- Reuse durations and easings from the contract's motion tokens
- Prefer opacity/translate/scale transitions over complex transform choreography
- Avoid stacking multiple blur-heavy animated layers in the same region
- Calm curves and short durations; no jumpy or elastic interactions

## Readability

- Selection color must remain high contrast (cyan on dark)
- Do not reduce body text contrast below current baseline values
- Dense text areas (logs, transcriptions) use monospace or high-legibility settings
- Scrollbar affordances and selection states are part of the identity and must remain consistent

## Anti-Patterns

- **Token sprawl**: adding ad hoc colors, shadows, radii, or blur values without contract updates
- **Arbitrary utilities**: random bracket-value classes not in the utility allowlist
- **Blur stacking**: excessive `backdrop-blur` on nested layers
- **Inconsistent borders**: drifting glass border strength across sibling components
- **Timing drift**: interaction timing outside approved motion tokens
- **oklch/oklab leakage**: any `color-mix(in oklab, ...)`, `oklch(...)`, or `in oklab` gradient interpolation reaching the browser — the sRGB enforcement must remain active
