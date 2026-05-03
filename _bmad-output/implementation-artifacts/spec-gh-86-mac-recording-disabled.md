---
title: 'Surface disabled-reason inline near Start Recording button (Issue #86 #1)'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: '65fc48fafa9c174ad2fdcae6b7637f28d3ca88ce'
context:
  - '{project-root}/docs/project-context.md'
  - '{project-root}/dashboard/components/views/SessionView.tsx'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When the Start Recording button in `SessionView` is disabled, the user has no inline indication of *why*. Issue #86 reporter on Mac M4Pro bare-metal Metal (`mlx-community/parakeet-tdt-0.6b-v3`) is stuck on a disabled button: mic permissions granted, inference server status reads "Running", but the button never enables. Two of the four gate variables (`mainModelDisabled` at line 1532-1534, remote-mode auth at line 1536-1543) already surface inline reasons; `!clientRunning` and `!serverConnection.ready` do not. The user is left with no actionable feedback.

**Approach:** Add a `recordingDisabledReason` derived value mirroring the existing `liveModeDisabledReason` IIFE at `SessionView.tsx:320-327`. Render it as an inline amber warning (mirroring the AlertTriangle pattern at line 1536-1543) directly above the Start Recording button when gated by `!clientRunning` or `!serverConnection.ready`. **No change to gate logic** — purely an additive UX surface.

## Boundaries & Constraints

**Always:**
- Mirror the existing `liveModeDisabledReason` IIFE shape and the line 1536-1543 inline-warning JSX (AlertTriangle + amber).
- Treat the four gate variables (`isLive`, `clientRunning`, `serverConnection.ready`, `mainModelDisabled`) as the source of truth — derive from them, not from raw hook state.
- Render the new warning ONLY when `canStartRecording === true` AND the relevant gate fires AND the case isn't already covered (`mainModelDisabled` and remote-auth keep their existing warnings).
- Cross-platform identical — no `process.platform` branching.

**Ask First:**
- Whether to also surface the existing `liveModeDisabledReason` near the Live Mode start button. Default: out of scope (Live Mode is not the reported symptom).

**Never:**
- Do NOT alter the disabled expression at line 1559 — gate logic is unchanged.
- Do NOT modify backend `/api/status` or `useServerStatus.ts` — pure renderer-side change.
- Do NOT touch the MLX log pipeline (tracked separately as `gh-86 #3` in `deferred-work.md`).
- Do NOT touch tray callbacks or handler logic — render-only.
- Do NOT use a tooltip on the disabled button — `<button disabled>` swallows pointer events unreliably; sibling-above-button matches existing convention.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Server not reachable | `clientRunning === false`, `canStartRecording === true` | Inline amber warning above Start button: `"Server is not running — start it from the Server view."` | N/A |
| Server reachable but not ready | `clientRunning === true`, `serverConnection.ready === false`, `mainModelDisabled === false` | Inline amber warning: `"Server is starting or model is loading — check the Server view for progress."` | N/A |
| Main model not selected | `mainModelDisabled === true` | EXISTING warning at line 1532-1534 fires; do NOT add a duplicate. | N/A |
| Remote mode, no auth token | `isRemoteMode && !admin.status` | EXISTING warning at line 1536-1543 fires; do NOT add a duplicate. | N/A |
| All gates clear | All four gate variables falsy | No new warning rendered; button enabled normally. | N/A |
| Multiple gates firing | e.g. `!clientRunning && mainModelDisabled` | Show ONLY `recordingDisabledReason` (the highest-priority server-state message); existing `mainModelDisabled` warning continues to render below. Priority order in derived value: clientRunning → serverConnection.ready. | N/A |
| Start button hidden | `canStartRecording === false` (Stop button shown) | New warning is NOT rendered (no gate to explain). | N/A |
| Live mode active | `isLive === true` (button hidden behind `canStartRecording === false`) | No new warning needed (covered by previous row). | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/SessionView.tsx` — add `recordingDisabledReason` derived value near the existing `liveModeDisabledReason` (line 320-327); add a new inline warning element in the `canStartRecording` branch above the Start Recording button (around line 1545, before the `<div className="flex items-center gap-2">` wrapper at the same indentation as the existing `mainModelDisabled` and remote-auth warnings).
- `dashboard/components/__tests__/SessionView.test.tsx` — extend with unit tests covering the I/O matrix. Use the existing render harness pattern.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/SessionView.tsx` -- Add `const recordingDisabledReason = (() => { if (!clientRunning) return '...'; if (!serverConnection.ready) return '...'; return ''; })();` near the existing `liveModeDisabledReason` block. Render an `AlertTriangle`-styled amber warning element inside the `canStartRecording` branch, above the Start button, gated by `recordingDisabledReason !== '' && !mainModelDisabled` -- mirrors the line 1536-1543 pattern, does not duplicate the existing `mainModelDisabled` warning.
- [x] `dashboard/components/__tests__/SessionView.test.tsx` -- Add a `describe('Start Recording disabled-reason surface', ...)` block with one test per I/O matrix row that produces a visible warning. Mock `clientRunning`, `serverConnection.ready`, `mainModelDisabled` via the existing prop/hook injection pattern in this file. Assert text content matches exactly.
- [x] After UI edits, run the UI-contract pipeline: `npm run ui:contract:extract` → `npm run ui:contract:build` → `node scripts/ui-contract/validate-contract.mjs --update-baseline` → `npm run ui:contract:check` (per `CLAUDE.md` quick reference).

**Acceptance Criteria:**
- Given the Start Recording button is visible (`canStartRecording === true`) and `clientRunning === false`, when `SessionView` renders, then an amber warning above the button reads exactly `"Server is not running — start it from the Server view."`.
- Given the button is visible, `clientRunning === true`, `serverConnection.ready === false`, and `mainModelDisabled === false`, when rendered, then the warning reads exactly `"Server is starting or model is loading — check the Server view for progress."`.
- Given `mainModelDisabled === true`, when rendered, then the existing "Main model not selected." warning is the only model-related message shown — the new `recordingDisabledReason` element does NOT render.
- Given all four gate variables are falsy, when rendered, then no `recordingDisabledReason` warning element exists in the DOM and the Start button is enabled.
- Given the Stop button is shown (`canStartRecording === false`), when rendered, then no `recordingDisabledReason` warning element exists.
- `npm run typecheck` passes from `dashboard/`.
- `npm test -- SessionView` passes (Vitest, jsdom).
- `npm run ui:contract:check` passes from `dashboard/` (after the full extract→build→validate→check pipeline).

## Design Notes

**Why mirror `liveModeDisabledReason`, don't refactor.** The existing IIFE pattern at line 320-327 is the closest precedent. Two co-located derivations are easier to spot and unify later than one helper used once.

**Why a sibling element, not a tooltip.** `<button disabled>` swallows pointer events unreliably across Linux Wayland and historical macOS — tooltips would be invisible exactly where the user needs them. The existing warnings at lines 1532 and 1536 already use the sibling-above-button convention.

**Why two distinct messages.** `!clientRunning` and `!serverConnection.ready` have different remedies (start the server vs wait for model load); conflating them would lose actionable info.

## Verification

**Commands** (run from `dashboard/`):
- `npm run typecheck` -- expected: 0 errors.
- `npx vitest run components/__tests__/SessionView.test.tsx` -- expected: all tests pass, including the new `Start Recording disabled-reason surface` block.
- `npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` -- expected: contract check passes.

Bill has no Apple Silicon to validate the Mac path manually; the Vitest assertions are the primary verification surface. The Issue #86 reporter (or any user reproducing the gate) confirms the new surface visually after release.

## Suggested Review Order

- Derived value: mirrors the `liveModeDisabledReason` IIFE shape directly above it.
  [`SessionView.tsx:328`](../../dashboard/components/views/SessionView.tsx#L328)

- Render block: sibling-above-button warning with two suppressors (`canStartRecording` to skip during Stop, `!gpu_error` so the red GPU warning owns crash surfaces).
  [`SessionView.tsx:1557`](../../dashboard/components/views/SessionView.tsx#L1557)

- Mock infrastructure: `isModelDisabled` becomes a `vi.fn()` so per-test overrides work via `vi.mocked()`.
  [`SessionView.test.tsx:152`](../../dashboard/components/__tests__/SessionView.test.tsx#L152)

- Test block: 7 cases covering both message variants, gate-suppression paths, and the review-cycle multi-gate / GPU-error edges.
  [`SessionView.test.tsx:303`](../../dashboard/components/__tests__/SessionView.test.tsx#L303)
