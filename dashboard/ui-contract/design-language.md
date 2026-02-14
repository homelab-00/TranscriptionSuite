# Design Language

Visual direction and style constraints for the TranscriptionSuite dashboard renderer.

The `transcription-suite-ui.contract.yaml` is the machine-enforced source of truth. This document provides qualitative guidance for interpreting and extending the contract. If there is a conflict, the contract governs runtime enforcement.

---

## Visual Direction

- Dark frosted glass with restrained contrast accents
- Apple-like translucency discipline with practical developer ergonomics
- Priority: legibility first, atmosphere second

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
