---
title: 'Low idle usage toggle (GH-124 Part C / Issue 87)'
type: 'feature'
created: '2026-05-31'
baseline_commit: '2d5d618'
status: 'done'
context:
  - '{project-root}/.claude/skills/ui-contract/SKILL.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** macOS idle (reported M4 Max / macOS 15) burns ~44% CPU / ~13.5% GPU on the Sessions tab with nothing running (Issue 87, resurfaced as GH-124 Part C). The dominant idle cost is the Chromium backdrop-blur compositor; the shipped per-effect "Blur effects" toggle defaults ON and is buried, so most users get no relief.

**Approach:** Add ONE discoverable, cross-platform (no arch gating) "Low idle usage" toggle that, when ON, disables backdrop blur (the dominant lever per the RCA residual-cost table) and freezes the idle AudioVisualizer waves; plus an always-on hygiene fix pausing those waves while the window is hidden. Clone the proven `data-blur-effects` plumbing into a parallel `data-low-idle-usage` attribute. The new toggle wins over the Blur-effects toggle by CSS precedence; both toggles stay.

## Boundaries & Constraints

**Always:**
- Clone the Blur-effects pattern exactly: SettingsModal `AppleSwitch` → live-preview DOM write → `savedXRef` revert-on-close → `handleSave` dual-write (electron-store + `ts-config:` localStorage mirror) → synchronous boot-before-paint applier.
- Platform-agnostic — no `process.platform`/arch branches. Toggle OFF (the default) = current behavior byte-for-byte on every platform.
- In dashboard source comments write `GH-124` / `issue 87` — never `#124` (3+ digits after `#` parse as a hex color in the UI-contract scanner); avoid apostrophes inside `//` comments.

**Ask First:**
- If the Blur-effects plumbing has structurally diverged from the Code Map (renamed/removed functions, restructured save path) — line shifts are fine — HALT and reconcile before cloning.
- If `ui:contract:check` reports NEW class-token or blur-budget violations (it should not — see Design Notes) — HALT and run the full extract→build→validate --update-baseline→check sequence; never silently rebaseline.

**Never:** Revert `a129877` (idle SVG keyframes — compositor-only, not dominant). Touch polling intervals (out of scope; tracked in deferred-work). Remove/alter the existing Blur-effects toggle. Add new `backdrop-blur-*` class sites or change Vite `base`. Use per-frame JS for the gate (a single `visibilitychange` listener toggling a CSS attribute only).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| First run | no low-idle key in storage | `data-low-idle-usage` NOT set; blur on, waves animate | default OFF |
| Boot, stored true | `ts-config:ui.lowIdleUsageEnabled`=`true` | `data-low-idle-usage='on'` set before first paint; blur off, waves frozen | n/a |
| Corrupt/throwing storage | bad JSON or `getItem` throws | attribute NOT set; no throw | swallow → default OFF |
| Modal closed via X after toggling | toggled, not saved | attribute reverts to last-saved via `savedLowIdleUsageRef` | n/a |
| Toggle ON + Blur effects re-enabled | both controls active | blur stays OFF (low-idle wins via `!important`) | documented precedence |
| Window hidden | `document.visibilityState==='hidden'` | `data-doc-hidden='true'`; idle waves `animation-play-state: paused` | n/a |

</frozen-after-approval>

## Code Map

- `dashboard/src/utils/blurEffectsBoot.ts` -- REFERENCE pattern to clone (read-persisted + apply-before-paint).
- `dashboard/components/views/SettingsModal.tsx` -- toggle host: Appearance `Section` (~881-898), `savedBlurEffectsRef` (~198), load seed (~379-380), modal-close revert (~443-451), `handleSave` dual-write (~521, 534-541).
- `dashboard/electron/main.ts` -- electron-store defaults (~480-483).
- `dashboard/src/config/store.ts` -- `ClientConfig.ui` interface (~72-79) + defaults (~139-142).
- `dashboard/index.tsx` -- pre-paint boot calls (~5, 11).
- `dashboard/src/index.css` -- blur-off override (~91-107); `.idle-wave-{cyan,magenta,orange}` selectors (~206-222) — add new rules adjacent.
- `dashboard/components/AudioVisualizer.tsx` -- idle SVG branch renders `.idle-wave-*` (~164-216); no code change (gate is CSS+attribute).

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/utils/lowIdleUsageBoot.ts` (NEW) -- mirror `blurEffectsBoot.ts`: export `LOW_IDLE_USAGE_STORAGE_KEY='ts-config:ui.lowIdleUsageEnabled'`, `readPersistedLowIdleUsage()` (default **false**), `applyLowIdleUsageBoot()` sets `documentElement.dataset.lowIdleUsage='on'` only when stored true. Inverse default of blur, same set-only-in-non-default-state shape.
- [x] `dashboard/src/utils/idleVisibilityGate.ts` (NEW) -- export idempotent `installIdleVisibilityGate()`: one `visibilitychange` listener that sets/removes `documentElement.dataset.docHidden='true'`. No per-frame work.
- [x] `dashboard/index.tsx` -- call `applyLowIdleUsageBoot()` (before render, beside blur boot) and `installIdleVisibilityGate()`.
- [x] `dashboard/src/config/store.ts` -- add `lowIdleUsageEnabled: boolean` to `ui` interface + default `false`.
- [x] `dashboard/electron/main.ts` -- add electron-store default `'ui.lowIdleUsageEnabled': false`.
- [x] `dashboard/components/views/SettingsModal.tsx` -- add Appearance `AppleSwitch` cloning the blur toggle (live-preview write to `dataset.lowIdleUsage`, `savedLowIdleUsageRef`, load seed, modal-close revert, `handleSave` dual-write). Label "Low idle usage"; description names the CPU/GPU benefit and that it suits laptops / Apple Silicon.
- [x] `dashboard/src/index.css` -- add the `:root[data-low-idle-usage='on']` and `:root[data-doc-hidden='true']` rules (exact block in Design Notes).
- [x] `dashboard/src/utils/__tests__/lowIdleUsageBoot.test.ts` (NEW) -- mirror blur boot tests for the inverse default: absent→false/no attr, `true`→attr `on`, parse-fail/throw→default OFF.
- [x] `dashboard/src/utils/__tests__/idleVisibilityGate.test.ts` (NEW) -- dispatch `visibilitychange` with stubbed `visibilityState`; assert `data-doc-hidden` toggles and the listener installs once.

**Acceptance Criteria:**
- Given low-idle OFF (default) on any platform, when the app boots, then the UI is identical to current behavior (no `data-low-idle-usage` attribute; blur and waves unchanged).
- Given low-idle ON at idle on the Sessions tab, when inspecting DevTools, then every element computes `backdrop-filter: none` and the three `.idle-wave-*` compute `animation: none`.
- Given the new code, when `npm run typecheck` and `npm run ui:contract:check` run from `dashboard/`, then both pass with no new violations.
- Given the GPU magnitude is RCA-predicted, not freshly measured (no Mac), when shipped, then the PR/issue note states the expected reduction is the RCA "Both" row (≈85–95% idle GPU) pending reporter confirmation.

## Design Notes

**Evidence (no Mac):** RCA `brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md:766-772` — blur-off + animation-off predicts **80–95% CPU / 85–95% GPU** idle reduction ("Both" row); blur dominates, animation multiplies it. Native vibrancy (`:2067-2077`) adds a Mac-only 30–60% bonus — deferred, not the primary lever. (Handoff's "~54 blur sites" is inaccurate; RCA cites 21 files / 36 call sites.)

**Default OFF + the one decision for you:** OFF preserves the shipped design on primary-platform Linux and avoids arch-conditional defaults; discoverability comes from the clear label, not an auto-default. **Override option at checkpoint:** default-ON-on-Apple-Silicon (reintroduces platform branching — rejected here) vs OFF-everywhere (chosen).

**Visibility gate is hygiene, not the reporter's fix:** `visibilityState==='hidden'` fires only on minimize/background, NOT the reporter's "app visible" case — so it is an always-on correctness add, independent of the toggle. Blur-off is what targets the reported scenario.

**Exact CSS (existing classes only — no new tokens/blur sites → contract untouched):**
```css
:root[data-low-idle-usage='on'],
:root[data-low-idle-usage='on'] *,
:root[data-low-idle-usage='on'] *::before,
:root[data-low-idle-usage='on'] *::after {
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}
:root[data-low-idle-usage='on'] .idle-wave-cyan,
:root[data-low-idle-usage='on'] .idle-wave-magenta,
:root[data-low-idle-usage='on'] .idle-wave-orange { animation: none !important; }
:root[data-doc-hidden='true'] .idle-wave-cyan,
:root[data-doc-hidden='true'] .idle-wave-magenta,
:root[data-doc-hidden='true'] .idle-wave-orange { animation-play-state: paused !important; }
```

## Verification

**Commands** (from `dashboard/`, Node 22 — `nvm use` or v22.22.3):
- `npx vitest run src/utils/__tests__/lowIdleUsageBoot.test.ts src/utils/__tests__/idleVisibilityGate.test.ts` -- expected: all pass.
- `npm run typecheck` -- expected: no errors.
- `npm run ui:contract:check` -- expected: clean (read-only). data-* selectors, `@keyframes`, and property overrides are not class tokens — they do not trip the contract or blur-depth budget.

**Manual (no Mac):**
- DevTools: toggle ON → a `GlassCard` computes `backdrop-filter: none`, `.idle-wave-cyan` computes `animation: none`; toggle OFF → both restore live.
- Minimize/background → `:root[data-doc-hidden='true']` present, idle waves paused; restore → removed, waves resume.

## Suggested Review Order

**Design intent — the persisted-state model (start here)**

- Applies `data-low-idle-usage='on'` only when opted in; the gate for the whole feature.
  [`lowIdleUsageBoot.ts:53`](../../dashboard/src/utils/lowIdleUsageBoot.ts#L53)

- Inverse-of-blur default: returns false on every failure/missing path (mode OFF).
  [`lowIdleUsageBoot.ts:40`](../../dashboard/src/utils/lowIdleUsageBoot.ts#L40)

**The visual effect (what the attribute does)**

- Nulls backdrop blur everywhere — the dominant idle-GPU lever per the RCA.
  [`index.css:119`](../../dashboard/src/index.css#L119)

- Freezes the three idle-wave compositor animations.
  [`index.css:126`](../../dashboard/src/index.css#L126)

- Always-on hygiene: pauses idle waves while the window is hidden.
  [`index.css:131`](../../dashboard/src/index.css#L131)

**Settings UI wiring (toggle, persistence, revert)**

- The new "Low idle usage" switch with immediate live-preview DOM write.
  [`SettingsModal.tsx:946`](../../dashboard/components/views/SettingsModal.tsx#L946)

- handleSave persists to electron-store and mirrors to localStorage for pre-paint boot.
  [`SettingsModal.tsx:543`](../../dashboard/components/views/SettingsModal.tsx#L543)

- Modal-close revert restores the last-saved baseline (no-op after Save).
  [`SettingsModal.tsx:468`](../../dashboard/components/views/SettingsModal.tsx#L468)

- Rollback target ref, seeded from the same localStorage the boot probe reads.
  [`SettingsModal.tsx:207`](../../dashboard/components/views/SettingsModal.tsx#L207)

**Boot + visibility wiring**

- Pre-paint boot apply + always-on visibility-gate install, beside the blur boot.
  [`index.tsx:19`](../../dashboard/index.tsx#L19)

- Idempotent single `visibilitychange` listener toggling `data-doc-hidden`.
  [`idleVisibilityGate.ts:18`](../../dashboard/src/utils/idleVisibilityGate.ts#L18)

**Config defaults (default OFF, all platforms)**

- ClientConfig interface field + renderer default false.
  [`store.ts:86`](../../dashboard/src/config/store.ts#L86)

- electron-store default false (canonical source of truth).
  [`main.ts:488`](../../dashboard/electron/main.ts#L488)

**Tests (peripherals)**

- 16 tests: inverse-default semantics + every failure path + state-mirror invariant.
  [`lowIdleUsageBoot.test.ts:1`](../../dashboard/src/utils/__tests__/lowIdleUsageBoot.test.ts#L1)

- 5 tests: hidden/visible toggle, start-hidden, single-listener idempotency, SSR guard.
  [`idleVisibilityGate.test.ts:1`](../../dashboard/src/utils/__tests__/idleVisibilityGate.test.ts#L1)
