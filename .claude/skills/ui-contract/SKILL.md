---
name: ui-contract
description: "Manage the UI contract system: verify, update, and fix the CSS-class contract baseline after UI changes. Use when editing dashboard components, styles, or any file linked to UI elements. Use for: ui contract check, contract validation failures, updating baseline, contract diff, CSS class audit."
---

# UI Contract

The UI contract system tracks CSS classes used across the dashboard and validates them against a known baseline. It lives entirely within `dashboard/`.

**All commands must be run from the `dashboard/` directory.**

## When to Use

- After editing any dashboard component, style, or UI-related file
- When `npm run ui:contract:check` fails
- To inspect what CSS-class changes a set of edits introduced

## Commands

| Command | What it does |
|---------|--------------|
| `npm run ui:contract:extract` | Scans source files, emits raw CSS-class facts to intermediate files |
| `npm run ui:contract:build` | Consumes extracted facts → writes `ui-contract/transcription-suite-ui.contract.yaml` |
| `npm run ui:contract:validate` | Compares contract YAML against `ui-contract/contract-baseline.json` (read-only) |
| `npm run ui:contract:test` | Runs assertion checks against the contract |
| `npm run ui:contract:check` | `validate` + `test` combined — the routine CI check (read-only) |
| `npm run ui:contract:diff` | Shows what changed between current contract and baseline |
| `node scripts/ui-contract/validate-contract.mjs --update-baseline` | Writes a new `contract-baseline.json` to match the current YAML — accepts deliberate UI changes |

## Procedure

### Verify (read-only)

Run after any UI edit to check compliance:

```bash
cd dashboard
npm run ui:contract:check
```

If this passes, no further action is needed.

### Update (when check fails)

When your UI changes intentionally alter CSS classes, run the full update sequence **in this exact order**:

```bash
cd dashboard
npm run ui:contract:extract                                        # 1. re-scan source
npm run ui:contract:build                                          # 2. rebuild contract YAML
node scripts/ui-contract/validate-contract.mjs --update-baseline   # 3. accept new state as baseline
npm run ui:contract:check                                          # 4. confirm clean
```

### Inspect changes

To see what changed between the current contract and baseline:

```bash
cd dashboard
npm run ui:contract:diff
```

## Rules

1. **Never run `ui:contract:build` without running `ui:contract:extract` first** — it regenerates the YAML with a stale/wrong version number.
2. **Never run `--update-baseline` against a YAML that was built without a fresh extract** — same reason.
3. **`ui:contract:check` is read-only** — it never fixes anything. Use the 4-step update sequence to fix failures.
4. **Steps must run in order**: extract → build → update-baseline → check.

## Recovery

If the YAML gets into a bad state, restore it and re-run from scratch:

```bash
cd dashboard
git checkout -- ui-contract/transcription-suite-ui.contract.yaml
npm run ui:contract:extract
npm run ui:contract:build
node scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```

## Decision: Fix vs Accept

If `ui:contract:check` still fails after the update workflow:

- **Unintended regression**: Edit the component causing the regression to restore the expected CSS classes, then re-run check.
- **Intentional change**: Run the 4-step update sequence to accept the new contract as baseline.

## Key Paths

| Path | Purpose |
|------|---------|
| `dashboard/ui-contract/transcription-suite-ui.contract.yaml` | Current contract (generated) |
| `dashboard/ui-contract/contract-baseline.json` | Accepted baseline (committed) |
| `dashboard/ui-contract/transcription-suite-ui.contract.schema.json` | Contract JSON schema |
| `dashboard/ui-contract/design-language.md` | Design language reference |
| `dashboard/scripts/ui-contract/` | All contract scripts |
