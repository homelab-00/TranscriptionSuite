# UI Contract Maintainer Guide

This folder contains the canonical, machine-validated UI contract for the mockup-derived frontend.

## Handoff Index
- Start here for a path-by-path handoff map for replacement work:
  - `ui-contract/AGENT-HANDOFF.md`

## Canonical Files
- `ui-contract/transcription-suite-ui.contract.yaml`: canonical closed-set contract.
- `ui-contract/transcription-suite-ui.contract.schema.json`: schema for structural validation.
- `ui-contract/contract-baseline.json`: hash/version lock used for semver bump enforcement.
- `ui-contract/design-language.md`: qualitative design-language guidance.

## Delivery Status (Phased)
- Phase 1: Foundation contract complete.
- Phase 2: Component contracts complete (all discovered components covered).
- Phase 3: Validation + CI complete.
- Phase 4: Fixture-based tests complete.

## Required Change Workflow
Run this sequence whenever UI styling/tokens/contracts change:

1. Extract facts from source.
```bash
npm run ui:contract:extract
```

2. Rebuild canonical contract from extracted facts.
```bash
node scripts/ui-contract/build-contract.mjs
```

3. Validate contract (schema + semantic closed-set drift checks).
```bash
npm run ui:contract:validate
```

4. If contract content changed intentionally, bump `meta.spec_version` in `ui-contract/transcription-suite-ui.contract.yaml`.

5. Update baseline only after version bump and successful validation.
```bash
node scripts/ui-contract/validate-contract.mjs --update-baseline
```

6. Run fixture tests.
```bash
npm run ui:contract:test
```

## Drift Checks
- `npm run ui:contract:validate` fails on:
  - unknown utility/arbitrary class values,
  - token/global CSS mismatches,
  - missing component contract coverage,
  - contract hash changes without semver bump.
- `npm run ui:contract:diff` writes a structured drift report to `ui-contract/.generated/contract-diff.json`.

## CI Gate
GitHub Actions runs:
```bash
npm run ui:contract:validate
```
Workflow file: `.github/workflows/ui-contract.yml`.

## Notes
- Renderer UI is covered in v1; Electron shell/window-chrome constraints are intentionally out of scope.
- Generated artifacts under `ui-contract/.generated/` and temp fixtures are ignored via `.gitignore`.
