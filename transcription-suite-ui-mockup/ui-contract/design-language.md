# Transcription Suite Design Language (v1)

## Intent
- Visual direction: dark frosted glass with restrained contrast accents.
- Primary inspiration: Apple-like translucency discipline with practical developer ergonomics.
- Priority: legibility first, atmosphere second.

## Core Principles
- Layer depth through translucent surfaces, subtle borders, and controlled blur.
- Keep accent usage deliberate: cyan for active guidance, magenta/orange for secondary emphasis.
- Preserve calm motion curves and short durations; avoid jumpy or elastic interactions.
- Keep text readable against all gradients and translucent panels.

## Composition Rules
- Use glass surfaces (`glass-*`) as the main panel language; avoid introducing random opaque blocks.
- Every elevated layer should have consistent radius and shadow logic from the contract.
- Portal surfaces (dropdowns, menus, modals) must stay within the approved z-index layers.
- Scroll affordances and selection states are part of the identity and must remain consistent.

## Motion Rules
- Reuse approved durations/easings from the canonical contract.
- Prefer opacity/translate/scale transitions over heavy transform choreography.
- Avoid stacking multiple blur-heavy animated layers in the same region.

## Accessibility and Readability
- Selection color must remain high contrast.
- Do not reduce body text contrast below current baseline values.
- Keep dense text areas in mono or high-legibility settings where currently used.

## Anti-Patterns
- Token sprawl: adding ad hoc colors, shadows, radii, or blur values.
- Random arbitrary utility values without contract updates.
- Excessive backdrop blur on nested layers.
- Inconsistent glass border strength across sibling components.
- Drifting interaction timing outside approved motion tokens.

## Governance
- `ui-contract/transcription-suite-ui.contract.yaml` is the machine-enforced source of truth.
- This document is qualitative guidance; if there is a conflict, the contract governs runtime enforcement.
- Any intentional style-system change must update the contract and bump `meta.spec_version`.
