---
title: 'GH-87 — Split blur/idle into two independent toggles + opaque panels when blur off'
type: 'feature'
created: '2026-06-01'
status: 'done'
baseline_commit: '5c7d86c10bb956bc0b6d1704d546cf0a61073ff1'
context:
  - '{project-root}/docs/project-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/gh-87-blur-tier-audit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Appearance settings expose one combined "Low idle usage" switch that disables blur AND freezes idle animations together, so the user cannot keep blur while stopping idle animations (or vice-versa). Separately, when blur is turned off, panels that rely on `backdrop-blur` over a translucent background (e.g. the Settings modal, `bg-glass-surface` = `rgba(0,0,0,0.4)`) become see-through and the content behind bleeds through.

**Approach:** (a) Split the combined switch into two independent toggles — keep "Blur effects" as-is, and convert the second into "Idle animations" (default ON; OFF only freezes the idle visualizer waves and no longer touches blur). (b) When blur is off, give blur-dependent panels an opaque `slate-800` (#1e293b) background via a single shared `blur-panel` marker class + one CSS rule.

## Boundaries & Constraints

**Always:**
- The two toggles are fully independent: "Blur effects" controls only `backdrop-filter`; "Idle animations" controls only the idle-wave animations. Default both ON; attributes applied only when the user disables.
- Reuse `var(--color-slate-800)` for the opaque fill (no new literals); opaque rule fires only under `:root[data-blur-effects='off']`.
- Preserve the boot-before-paint synchronous localStorage probe (`index.tsx`) and the modal live-preview + close-revert pattern (`SettingsModal`).
- Migrate any existing `ui.lowIdleUsageEnabled` choice (see I/O matrix).

**Ask First:**
- Applying `blur-panel` beyond the panel set in Tasks (scrims, toasts, menus/popovers, small buttons) — HALT if tempted.

**Never:**
- Do NOT make modal scrims opaque — they stay translucent dims; `blur-panel` goes on panel roots only.
- Do NOT change blur radii / `blur_depth_budgets` or execute any audit demotion (out of scope).
- Do NOT reintroduce coupling between the idle toggle and `backdrop-filter`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh user / never opted in | no `lowIdleUsageEnabled`, or `false` | Idle animations ON (no `data-idle-animations` attr); blur unchanged | n/a |
| Toggle Idle animations OFF | user flips switch off | `data-idle-animations='off'` set; idle waves freeze; blur NOT affected | n/a |
| Toggle Blur effects OFF | user flips switch off | `data-blur-effects='off'`; blur-dependent panels show opaque slate-800 bg | n/a |
| Migrate legacy ON | `ts-config:ui.lowIdleUsageEnabled` = `true` | `idleAnimationsEnabled`→false (waves frozen) AND `blurEffectsEnabled`→false (blur stays off); old key removed | malformed/throwing storage → no migration, no throw |
| Boot before paint, idle off | new key `false` in localStorage | `data-idle-animations='off'` applied pre-paint | never throws; default ON |
| Boot before paint, idle on/absent | new key `true`/missing | no attribute (animations play) | never throws |

</frozen-after-approval>

## Code Map

- `dashboard/src/index.css` — L119-130: `data-low-idle-usage='on'` rules (rename + decouple from blur); add `:root[data-blur-effects='off'] .blur-panel{}` rule.
- `dashboard/src/utils/lowIdleUsageBoot.ts` → rename `idleAnimationsBoot.ts` — flip polarity (default ON), new key, new attribute.
- `dashboard/src/utils/__tests__/lowIdleUsageBoot.test.ts` → rename `idleAnimationsBoot.test.ts` — flip expectations.
- `dashboard/src/utils/migrateLegacyAppearanceConfig.ts` — NEW: one-time legacy `lowIdleUsageEnabled` → split-keys migration.
- `dashboard/index.tsx` — L6,16-19: swap boot import; run migration before probes; rename install call.
- `dashboard/components/views/SettingsModal.tsx` — Appearance section (L936-953), ref (L207), load (L390-409), save (L543,565-578): relabel toggle, rename state/ref/keys, default ON, new attribute.
- `dashboard/src/config/store.ts` — L80-86,149: rename `lowIdleUsageEnabled`→`idleAnimationsEnabled` (default true).
- `dashboard/electron/main.ts` — L488: default `ui.idleAnimationsEnabled: true`; remove old key default.
- Panel roots needing `blur-panel` (per blur-tier-audit T1 table + persistent panels) — see Tasks.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/utils/idleAnimationsBoot.ts` (rename from lowIdleUsageBoot.ts) -- export `IDLE_ANIMATIONS_STORAGE_KEY='ts-config:ui.idleAnimationsEnabled'`, `readPersistedIdleAnimations()` (default `true`), `applyIdleAnimationsBoot()` setting `data-idle-animations='off'` only when stored value is `false` -- decouples idle from blur, inverts polarity.
- [x] `dashboard/src/utils/migrateLegacyAppearanceConfig.ts` (NEW) -- localStorage-synchronous: if old `ts-config:ui.lowIdleUsageEnabled` present and new idle key absent, write `idleAnimationsEnabled=!old`, and if old was `true` write `blurEffectsEnabled=false`; remove old key; fire-and-forget mirror to electron-store via `electronAPI.config.set`; wrap in try/catch -- preserves a migrated user's blur-off + frozen-waves state.
- [x] `dashboard/index.tsx` -- call `migrateLegacyAppearanceConfig()` first, then `applyBlurEffectsBoot()`, `applyIdleAnimationsBoot()`, `installIdleVisibilityGate()` -- migration must run before the synchronous probes.
- [x] `dashboard/src/index.css` -- replace the `:root[data-low-idle-usage='on']` block with `:root[data-idle-animations='off'] .idle-wave-*{animation:none!important}` (DROP the `backdrop-filter:none` lines); keep `data-doc-hidden` gate; ADD `:root[data-blur-effects='off'] .blur-panel{background-color:var(--color-slate-800)!important;background-image:none!important}` -- decouples idle from blur; opaque panel fallback.
- [x] `dashboard/components/views/SettingsModal.tsx` -- rename state `lowIdleUsageEnabled`→`idleAnimationsEnabled` (default `true`) + ref `savedLowIdleUsageRef`→`savedIdleAnimationsRef` (seed from `readPersistedIdleAnimations`); relabel toggle "Idle animations" / description "Stop the idle audio-visualizer animations to cut idle CPU/GPU. Recommended on laptops and Apple Silicon Macs."; toggle is `checked={idleAnimationsEnabled}`, onChange sets `data-idle-animations='off'` when OFF / removes it when ON; update load (`cfg['ui.idleAnimationsEnabled'] ?? true`), save entry `['ui.idleAnimationsEnabled', ...]`, localStorage mirror key, and close-revert branch -- independent idle toggle, default ON.
- [x] `dashboard/src/config/store.ts` -- rename `ui.lowIdleUsageEnabled`→`ui.idleAnimationsEnabled` in interface + `DEFAULT_CONFIG` (default `true`); update doc comment -- config schema parity.
- [x] `dashboard/electron/main.ts` -- replace `'ui.lowIdleUsageEnabled': false` default with `'ui.idleAnimationsEnabled': true` -- electron-store default parity.
- [x] `dashboard/src/utils/__tests__/idleAnimationsBoot.test.ts` (rename) + NEW `migrateLegacyAppearanceConfig.test.ts` -- cover the I/O matrix: default ON, attr-when-false, never-throws, and the legacy-ON migration mapping.
- [x] Add `blur-panel` class to each panel root in the audit's "Modal & dialog panels — KEEP (T1)" table (App.tsx ×4, SettingsModal, AudioNoteModal ×3, AddNoteModal, AboutModal, BugReportModal, StarPopupModal, GpuDiagnosticModal, UpdateModal, ServerView ×2, useConfirm, DedupPromptModal, DeleteRecordingDialog) PLUS `GlassCard.tsx:18`, `Sidebar.tsx:234`, `NotebookView.tsx:808`, `SessionView.tsx:1331` -- the blur-dependent panels; NEVER scrims/toasts/menus/small surfaces.
- [x] UI contract -- from `dashboard/`: `npm run ui:contract:extract` → `npm run ui:contract:build` → `node scripts/ui-contract/validate-contract.mjs --update-baseline` → `npm run ui:contract:check` -- new `blur-panel` token + removed label text.

**Acceptance Criteria:**
- Given blur ON + idle animations OFF, when the app is idle, then panels stay frosted/blurred and the visualizer waves are frozen.
- Given idle animations ON + blur OFF, when a modal opens over content, then the waves animate and the panel shows an opaque slate-800 background (no bleed-through, matching Image 3's fix).
- Given a user who had the old "Low idle usage" ON, when they upgrade and launch, then blur is off and idle waves are frozen, with no flash-of-blur on the first painted frame.
- Given blur OFF, when any listed modal is open, then its full-screen scrim remains a translucent dim (NOT opaque).

## Design Notes

`background-image:none` flattens gradient panels (GlassCard `from-glass-200 to-glass-100`, the `from-white/5 to-black/20` modals) to solid slate-800. Inner translucent layers (`bg-black/20` scroll areas, `bg-white/5` headers) compose fine over the now-opaque root, so only the outermost panel needs the marker. A class marker (not a utility-keyed CSS selector) is required because scrims and panels share the same `bg-black/40–60` values — a utility-keyed rule would wrongly solidify scrims.

## Verification

**Commands:**
- `cd dashboard && nvm use && npx vitest run src/utils/__tests__/idleAnimationsBoot.test.ts src/utils/migrateLegacyAppearanceConfig.test.ts` -- expected: all green (Node 22 per gotcha).
- `cd dashboard && npm run typecheck` -- expected: no errors (no lingering `lowIdleUsage` references).
- `cd dashboard && npm run ui:contract:check` -- expected: pass after baseline update.
- `cd dashboard && rg -n "lowIdleUsage|data-low-idle-usage" components src electron index.tsx` -- expected: no matches (full rename).

**Manual checks:**
- Toggle Blur effects off with a modal open → panel is solid slate-800, scrim still see-through dim.
- Toggle each switch independently → confirm blur and wave-animation states change independently.

## Suggested Review Order

**Toggle split — user-facing semantics (entry point)**

- Start here: the two independent toggles; idle polarity flips to match blur (ON = no attribute).
  [`SettingsModal.tsx:954`](../../dashboard/components/views/SettingsModal.tsx#L954)
- New config key persisted on Save (replaces `ui.lowIdleUsageEnabled`).
  [`SettingsModal.tsx:545`](../../dashboard/components/views/SettingsModal.tsx#L545)

**CSS — decoupling + opaque-panel fix**

- The whole of part (b): opaque slate-800 fill for `.blur-panel` only when blur is off.
  [`index.css:119`](../../dashboard/src/index.css#L119)
- Idle rule now freezes waves only — no longer touches `backdrop-filter` (kept intact above at L101).
  [`index.css:133`](../../dashboard/src/index.css#L133)

**Boot + migration — pre-paint correctness**

- Migration runs before the boot probes so the first frame after upgrade is already correct.
  [`index.tsx:14`](../../dashboard/index.tsx#L14)
- Legacy `lowIdleUsageEnabled` → split keys; ON preserves blur-off + frozen-waves; idempotent.
  [`migrateLegacyAppearanceConfig.ts:33`](../../dashboard/src/utils/migrateLegacyAppearanceConfig.ts#L33)
- Boot probe: default ON, attribute applied only on literal `false` (mirrors blur).
  [`idleAnimationsBoot.ts:58`](../../dashboard/src/utils/idleAnimationsBoot.ts#L58)

**Config schema defaults**

- Renderer default ON.
  [`store.ts:149`](../../dashboard/src/config/store.ts#L149)
- electron-store default ON.
  [`main.ts:489`](../../dashboard/electron/main.ts#L489)

**Peripherals — panel markers & tests**

- Representative `blur-panel` marker (applied to all 22 modal panels + GlassCard/Sidebar/Notebook/Session).
  [`GlassCard.tsx:18`](../../dashboard/components/ui/GlassCard.tsx#L18)
- Boot-probe polarity + state-mirror invariant tests.
  [`idleAnimationsBoot.test.ts:1`](../../dashboard/src/utils/__tests__/idleAnimationsBoot.test.ts#L1)
- Migration matrix tests (legacy true/false/missing/corrupt, idempotency, electron-store mirror).
  [`migrateLegacyAppearanceConfig.test.ts:1`](../../dashboard/src/utils/__tests__/migrateLegacyAppearanceConfig.test.ts#L1)
