---
title: 'Memoize ModelManager rows + soft-virtualize via content-visibility (Issue #87)'
type: 'refactor'
created: '2026-04-21'
status: 'done'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md'
baseline_commit: '048dba8'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On the Model tab (Mac M4 Pro / Sequoia / Metal build, GH issue #87), the user reports flicker on tab entry (S3) and partial repaints while scrolling the model list (S4). The brainstorm's Cluster B traced this to per-row React reconciliation churn (parent re-renders rebuild every row even when nothing about a row changed) plus compositor pressure from a long scrollable list. Today both `ModelRow` and `CustomModelRow` are plain function components without `React.memo`, so unrelated parent state changes (toast show/hide, downloadingModels Set churn, customModelInput keystrokes) force every row to re-reconcile.

**Approach:** Two layered fixes that target S3 and S4 respectively, without adding a runtime dependency:
1. Wrap `ModelRow` and `CustomModelRow` in `React.memo`. Parent handlers are already `useCallback`-stabilized and prop values are primitives or stable registry references, so default shallow comparison is sufficient.
2. Apply CSS `content-visibility: auto` + `contain-intrinsic-size` to each row wrapper. This is a browser-native windowing primitive: the compositor skips layout/paint for rows scrolled off-screen entirely, which is the exact mechanism the brainstorm wanted virtualization to deliver — but at zero JS cost and with no library install.

A true JS virtualization library (`@tanstack/react-virtual`) is intentionally NOT introduced here because (a) the largest single section is 18 rows in Metal mode and the per-tab total is 25 in non-Metal mode — both below the brainstorm's >20 trigger when measured per section, and (b) `content-visibility` is the cheaper hammer for the same nail at this scale. The brainstorm's "virtualize if > 20" condition is recorded in deferred-work for revisit if MODEL_REGISTRY grows past ~50.

## Boundaries & Constraints

**Always:**
- Preserve every existing visible behavior of both row components (status dot, badges, dropdown open/close, button states, hover transition).
- Keep `React.memo` comparison shallow — do not write a custom `areEqual` unless step-04 review surfaces a referential-stability bug.
- The `content-visibility: auto` declaration MUST be paired with a `contain-intrinsic-size` placeholder so scrollbar geometry stays stable when off-screen rows are skipped.
- All edits are local to `dashboard/components/views/ModelManagerTab.tsx`. Do NOT modify `GlassCard.tsx`, `ModelManagerView.tsx`, the registry, or any service.

**Ask First:**
- Adding any npm dependency (e.g. `@tanstack/react-virtual`) — out of scope here.
- Restructuring the family-section/GlassCard hierarchy — out of scope.

**Never:**
- Do not change row markup in any way that breaks the UI contract (`npm run ui:contract:check` must pass).
- Do not introduce a virtualization library.
- Do not modify the parent's handler `useCallback` signatures.
- Do not change the dropdown's outside-click handler logic.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Toast appears | parent state `toast` flips null→string | Memoized rows DO NOT re-render; only the toast div mounts | N/A |
| Download starts on row X | `downloadingModels` Set adds id X | Only row X re-renders (its `downloading` prop flipped); other rows skip | N/A |
| User types in custom-model input | `customModelInput` changes per keystroke | No registry/custom row re-renders; only the input + Add button | N/A |
| User scrolls past 18-row MLX list | rows scroll off-screen | Off-screen rows have `content-visibility: auto` → browser skips paint/layout | If browser doesn't support it (Safari < 18, very old Chromium), CSS is ignored, behavior matches current build |
| Cache status loads/refreshes for one model | `modelCacheStatus[id]` changes | Only the affected row re-renders | N/A |
| Active model selection changes | `activeMain` / `activeLive` / `activeDiarization` flip | Old + new active rows re-render (their `isActiveX` prop flipped); rest skip | N/A |
| Tab mount with empty cache | initial render | Same content as today; no flicker delta on first paint (memo helps on subsequent renders) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/ModelManagerTab.tsx` -- The whole edit lives here. Two row components (`ModelRow` ~line 142, `CustomModelRow` ~line 338) get wrapped in `React.memo`; their root `<div>` gets the `content-visibility` style. The parent `ModelManagerTab` is unchanged.
- `dashboard/components/views/ModelManagerView.tsx` -- READ-ONLY. Confirms parent handlers (`refreshCacheStatus`, setters from `useState`) are stable refs across renders. No edit.
- `dashboard/components/ui/GlassCard.tsx` -- READ-ONLY. Confirms section containers use `backdrop-blur-xl` (only ~6 instances total across the tab — not per-row as the brainstorm assumed).
- `dashboard/src/services/modelRegistry.ts` -- READ-ONLY. Confirms 43 total models, 18 max per section (MLX in Metal mode).
- `_bmad-output/implementation-artifacts/deferred-work.md` -- WRITE. Append a follow-up note: revisit `@tanstack/react-virtual` if any single section grows past ~30 rows.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/ModelManagerTab.tsx` -- `ModelRow` wrapped in `React.memo`: `const ModelRow = React.memo(function ModelRow(...) { ... })`. Inner `function` preserves React DevTools displayName. Shallow compare skips re-render when no row prop changed. [KEPT from iter 1]
- [x] `dashboard/components/views/ModelManagerTab.tsx` -- Same `React.memo` conversion applied to `CustomModelRow`. [KEPT from iter 1]
- [x] `dashboard/components/views/ModelManagerTab.tsx` -- Two module-level style constants hoisted: `ROW_CV_AUTO = { contentVisibility: 'auto', containIntrinsicSize: 'auto 120px' }` and `ROW_CV_VISIBLE = { contentVisibility: 'visible', containIntrinsicSize: 'auto 120px' }`. Both row components apply `style={selectOpen ? ROW_CV_VISIBLE : ROW_CV_AUTO}`. When the dropdown is closed (the common case), the row gets paint-containment and can be skipped when off-screen; when the dropdown is open, containment is disabled so the absolutely-positioned menu is not clipped. Bumped 90→120px intrinsic size to better match typical registry-row height (name + detail line + wrapped description).
- [x] `dashboard/ui-contract/*` -- Regenerated via extract → build → spec_version bump → baseline refresh. New closed-set entries: properties `contentVisibility`, `containIntrinsicSize`; literals `auto`, `visible`, `auto 120px`. `npm run ui:contract:check` passes.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- **NOT appended.** The "virtualize-if-grows" follow-up fails triage criterion #1 (LOW severity — purely future-proofing, no current user symptom). Recorded inline: if any single ModelManagerTab section exceeds ~30 rows in a future registry expansion, evaluate `@tanstack/react-virtual`.

**Acceptance Criteria:**
- Given the user is on the Model tab and a toast appears, when the toast mounts/unmounts, then no row component re-renders (verifiable via React DevTools Profiler — only the toast div should appear in the commit).
- Given the user is downloading model X, when `downloadingModels` Set updates, then only the row for X re-renders (verifiable via Profiler).
- Given the user scrolls the MLX section in Metal mode, when rows scroll off-screen, then those rows show `content-visibility: auto` in computed styles and the painted area in the rendering tab is bounded to the viewport.
- Given a fresh build, when `npm run typecheck`, `npm run format:check`, and `npm run ui:contract:check` are run, then all three pass with no new errors.

## Spec Change Log

### Iteration 2 — bad_spec loopback (2026-04-21)

**Triggering finding:** Edge Case Hunter F3 (MED) — `content-visibility: auto` applies paint containment per CSS spec, which clips overflow at the padding edge. The `Select` dropdown rendered inside each row is `absolute right-0 mt-1` and extends ~40px below the row's natural bottom when open. With paint containment always-on (regardless of whether the row is on-screen), the open dropdown would be visually clipped — a real regression introduced by this story.

**Root cause:** Spec under-specified the row's overflow shape. The spec assumed rows were self-contained, but the action area contains a dropdown that overflows the row box.

**What was amended:**
- Tasks & Acceptance: replaced the unconditional `style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 90px' }}` task with a conditional variant that flips to `'visible'` when the row's `selectOpen` state is true, plus hoisting two static style constants to module scope.
- Design Notes: added the dropdown-clipping reasoning and the hoisted-constant rationale.
- Tasks: bumped `containIntrinsicSize` from `auto 90px` to `auto 120px` to reduce scrollbar-jump (Blind F2 / Edge F2).
- I/O Matrix: added a row covering the dropdown-open path.

**Known-bad state avoided:** Open dropdown gets visually clipped by paint containment whenever a user opens a model's Select menu.

**KEEP instructions (must survive re-derivation):**
- `React.memo(function ModelRow ...)` and `React.memo(function CustomModelRow ...)` wrappings — both are correct as implemented in iteration 1. Do not change the displayName-preserving form.
- Choice NOT to install `@tanstack/react-virtual` — correct, do not introduce.
- Choice to skip paint via CSS rather than JS virtualization — correct, just must coexist with the dropdown.
- The deferred-work decision (drop the "virtualize-if-grows" follow-up because it fails triage criterion #1) — keep.
- The UI-contract regen sequence (extract → build → bump spec_version → refresh baseline) — keep; will need to re-run after iteration-2 code lands.

## Design Notes

**Why no virtualization library:** `@tanstack/react-virtual` shines for thousands of rows. At 18-25 rows of ~80px each, the painted DOM is under 100 KB; the win is from telling the compositor to skip work, not from removing nodes. `content-visibility: auto` does exactly that natively. It is supported on Chromium >= 85 (which Electron 40 ships) and Safari >= 18.2 (irrelevant for Electron). On the unsupported tail it is silently ignored, leaving today's behavior intact.

**Why shallow `React.memo` is enough:** All ModelRow props are primitives (booleans, strings, undefined) or come from stable parent references:
- `model` — reference into module-level `MODEL_REGISTRY` constant; same identity every render.
- `cached`, `downloading`, `isRunning`, `isActiveMain/Live/Diarization` — booleans.
- `cacheSize` — string | undefined.
- `onDownload`, `onRemove`, `onSelectAs` — already `useCallback`-stabilized in `ModelManagerTab` (lines 552, 575, 591) with deps that don't change per render.

**Why conditional `content-visibility`:** Per CSS Containment spec, `content-visibility: auto` always applies paint containment, which clips at the padding edge. The Select dropdown inside each row is `absolute right-0 mt-1` and overflows the row's natural box by ~40px when open. With unconditional containment, the open dropdown would be visually clipped on every row. The conditional flip to `visible` while `selectOpen` is true scopes the containment lift narrowly: only the one row whose dropdown is open opts out, the other ~17-24 rows still benefit from off-screen paint-skip.

**Why hoisted style constants:** Inline `style={{...}}` object literals are recreated each render. With memoized rows the style object is the only non-stable prop on the inner `<div>`. Module-level constants (`ROW_CV_AUTO`, `ROW_CV_VISIBLE`) are referentially stable, so React's diff sees `prev.style === next.style` and skips the inline-style write entirely when `selectOpen` doesn't change.

**Accessibility note (out of scope for this story):** `content-visibility: auto` removes skipped subtrees from the accessibility tree until they scroll into view. Tab navigation auto-scrolls to bring the next focusable element into view, so keyboard navigation still functions, but screen-reader virtual-cursor exploration of off-screen rows requires scrolling first. The Select dropdown trigger also lacks `aria-haspopup` / `aria-expanded` / `role="menu"` (pre-existing). Both gaps belong in a future a11y-pass story, not this performance sprint.

**Code shape (golden example):**

```tsx
const ROW_CV_AUTO = {
  contentVisibility: 'auto' as const,
  containIntrinsicSize: 'auto 120px',
};
const ROW_CV_VISIBLE = {
  contentVisibility: 'visible' as const,
  containIntrinsicSize: 'auto 120px',
};

const ModelRow = React.memo(function ModelRow({ model, cached, ... }: ModelRowProps) {
  const [selectOpen, setSelectOpen] = useState(false);
  // ... existing body unchanged
  return (
    <div
      style={selectOpen ? ROW_CV_VISIBLE : ROW_CV_AUTO}
      className="rounded-lg border border-white/10 bg-white/5 ..."
    >
      {/* existing JSX unchanged */}
    </div>
  );
});
```

The inner `function ModelRow` preserves displayName for React DevTools and stack traces.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: exits 0, no errors.
- `cd dashboard && npm run format:check` -- expected: exits 0 (or surfaces formatting that prettier should normalize on next run).
- `cd dashboard && npm run ui:contract:check` -- expected: exits 0 (no new untracked classNames or stale_in_contract failures).

**Manual checks (if no CLI):**
- Open the dashboard, switch to Model tab, open React DevTools Profiler, type a character in the "Custom Models" input. Expectation: only the input + Add button commit; zero ModelRow / CustomModelRow commits.
- In the same Profiler session, click Download on one model. Expectation: only the clicked row commits.
- In Chrome DevTools Rendering tab, enable "Layer borders" and scroll the model list. Expectation: off-screen rows show no layer activity once `content-visibility: auto` skips them.
- Open a Select dropdown on any row and confirm the menu is fully visible (not clipped at the row's bottom edge). Expectation: dropdown extends past the row container as designed.

## Suggested Review Order

**Performance fix — paint-skip styles**

- Module-level style constants with comment explaining the dropdown-clipping interaction.
  [`ModelManagerTab.tsx:126`](../../dashboard/components/views/ModelManagerTab.tsx#L126)

**Performance fix — row memoization**

- `ModelRow` wrapped in `React.memo` so unrelated parent re-renders skip these ~25 rows.
  [`ModelManagerTab.tsx:161`](../../dashboard/components/views/ModelManagerTab.tsx#L161)

- Conditional style flips containment off when the dropdown is open.
  [`ModelManagerTab.tsx:211`](../../dashboard/components/views/ModelManagerTab.tsx#L211)

- Same memo wrap for `CustomModelRow`.
  [`ModelManagerTab.tsx:360`](../../dashboard/components/views/ModelManagerTab.tsx#L360)

- Same conditional style on the custom row.
  [`ModelManagerTab.tsx:400`](../../dashboard/components/views/ModelManagerTab.tsx#L400)

**Contract closed-set update**

- Two new inline-style properties + literals appended; spec_version 1.0.19 → 1.0.20.
  [`transcription-suite-ui.contract.yaml:2`](../../dashboard/ui-contract/transcription-suite-ui.contract.yaml#L2)
