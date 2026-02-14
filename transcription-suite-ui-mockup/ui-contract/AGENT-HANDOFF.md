# Frontend Replacement Handoff Guide

This document is for the agent that will integrate/replace the frontend in a larger app.

## 1) Fast File Map (What / Where)

| Purpose | File(s) |
|---|---|
| Canonical UI contract (authoritative) | `ui-contract/transcription-suite-ui.contract.yaml` |
| Contract schema (machine validation) | `ui-contract/transcription-suite-ui.contract.schema.json` |
| Design language (qualitative style intent) | `ui-contract/design-language.md` |
| Contract workflow/how to maintain | `ui-contract/README.md` |
| Handoff index (this file) | `ui-contract/AGENT-HANDOFF.md` |
| Contract version/hash baseline (semver enforcement) | `ui-contract/contract-baseline.json` |
| Source extraction script | `scripts/ui-contract/extract-facts.mjs` |
| Contract build/regeneration script | `scripts/ui-contract/build-contract.mjs` |
| Contract validator (schema + semantic drift + semver checks) | `scripts/ui-contract/validate-contract.mjs` |
| Drift diff report generator | `scripts/ui-contract/diff-contract.mjs` |
| Contract tests (fixtures + scenarios) | `scripts/ui-contract/test-contract.mjs` |
| Shared extraction/compare utilities | `scripts/ui-contract/shared.mjs` |
| CI gate config | `.github/workflows/ui-contract.yml` |
| NPM command wiring | `package.json` |

## 2) Frontend Code Surface (Current Mockup)

Top-level app shell:
- `App.tsx`
- `index.tsx`
- `index.html` (Tailwind CDN config + global CSS behavior definitions)

Primary UI components:
- `components/Sidebar.tsx`
- `components/AudioVisualizer.tsx`
- `components/ui/Button.tsx`
- `components/ui/GlassCard.tsx`
- `components/ui/AppleSwitch.tsx`
- `components/ui/CustomSelect.tsx`
- `components/ui/StatusLight.tsx`
- `components/ui/LogTerminal.tsx`

View-level components:
- `components/views/SessionView.tsx`
- `components/views/NotebookView.tsx`
- `components/views/ServerView.tsx`
- `components/views/SettingsModal.tsx`
- `components/views/AboutModal.tsx`
- `components/views/AudioNoteModal.tsx`
- `components/views/AddNoteModal.tsx`
- `components/views/FullscreenVisualizer.tsx`

Shared type enums:
- `types.ts`

## 3) Contract Meaning (How to Read `transcription-suite-ui.contract.yaml`)

- `meta`: contract identity and enforcement mode.
  - `spec_version`: semver contract version.
  - `contract_mode: closed_set`: unknown style values are disallowed.
  - `source_scope: mockup_repo`: baseline source context.
  - `validation_method: static_source_scan`: extraction compares source text/classes/styles.

- `foundation.tailwind`: canonical Tailwind extension values (dark mode, fonts, glass/accent scales, custom blur scale).

- `foundation.tokens`: frozen token registries used by validator.
  - colors, blur levels, shadow levels, motion, radii, z-index levels, spacing/size arbitrary values, status mappings.

- `global_behaviors`: canonical global CSS behavior and policy.
  - Includes `body`, selection styling, selectable text override, custom scrollbar blocks, portal layering policy.

- `utility_allowlist`: full allowed class universe.
  - `exact_classes`: normal utility classes.
  - `arbitrary_classes`: bracket-value classes (e.g. `shadow-[...]`, `z-[9999]`).

- `inline_style_allowlist`: allowed inline style properties/literals and animation-related literals.

- `component_contracts`: per-component constraints.
  - For each component: `required_tokens`, `allowed_variants`, `structural_invariants`, `behavior_rules`, `state_rules`.
  - Includes local helper components (e.g. `TimeSection`, `CalendarTab`, `SearchTab`, `NoteActionMenu`, etc.).

- `validation_policy`: required enforcement behavior (all currently `error`).

## 4) Commands the Agent Should Use

Extract facts from current source:
```bash
npm run ui:contract:extract
```

Regenerate contract from extracted facts:
```bash
node scripts/ui-contract/build-contract.mjs
```

Validate contract + drift + semver policy:
```bash
npm run ui:contract:validate
```

Generate detailed mismatch report:
```bash
npm run ui:contract:diff
```

Run fixture-based contract tests:
```bash
npm run ui:contract:test
```

If contract changed intentionally and `spec_version` was bumped, update baseline:
```bash
node scripts/ui-contract/validate-contract.mjs --update-baseline
```

## 5) Expected Enforcement Behavior

Validation fails when:
- a new utility/arbitrary class appears that is not in allowlists,
- token lists drift (colors/shadows/motion/radii/z-index/etc.),
- global CSS blocks differ from contract,
- discovered components are missing in `component_contracts`,
- contract content changes but `meta.spec_version` is not bumped.

## 6) Integration Notes for Replacement Work

- Treat `ui-contract/transcription-suite-ui.contract.yaml` as the single source of truth for renderer styling.
- Preserve all global CSS behavior from `index.html` unless intentionally versioning contract changes.
- When transplanting UI into another repo, copy both:
  - `ui-contract/`
  - `scripts/ui-contract/`
- Keep npm scripts and CI gate intact so drift is blocked automatically.

## 7) CI Reference

Workflow file:
- `.github/workflows/ui-contract.yml`

Gate command:
```bash
npm run ui:contract:validate
```

## 8) If the Agent Only Needs “Where Is X?”

- Schema: `ui-contract/transcription-suite-ui.contract.schema.json`
- Canonical contract: `ui-contract/transcription-suite-ui.contract.yaml`
- Design doc: `ui-contract/design-language.md`
- Maintenance workflow: `ui-contract/README.md`
- Handoff map: `ui-contract/AGENT-HANDOFF.md`
- Validation script: `scripts/ui-contract/validate-contract.mjs`
- Diff script: `scripts/ui-contract/diff-contract.mjs`
- Extraction script: `scripts/ui-contract/extract-facts.mjs`
- Build script: `scripts/ui-contract/build-contract.mjs`
- Tests: `scripts/ui-contract/test-contract.mjs`
- CI gate: `.github/workflows/ui-contract.yml`
