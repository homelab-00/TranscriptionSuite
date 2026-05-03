---
title: 'gh-102 followup #2: notebook upload surfaces honor `session.mainLanguage`'
type: 'bugfix'
created: '2026-04-30'
status: 'done'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-followup-file-import-language-loss.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-canary-picker-language-loss.md'
baseline_commit: '425d33c'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The gh-102-followup-1 fix (commit `425d33c`) closed the Session Import file-drop surface but left both **notebook upload entry points** still dropping the user's `session.mainLanguage`. `AddNoteModal.handleSubmit` (~L106-128) and the inline `ImportTab.handleFiles` inside `NotebookView` (line 1451) both call `useImportQueueStore.addFiles(..., 'notebook-normal', { ... })` with diarization, word-timestamps, parallel, file_created_at, and title — but no `language` and no translation fields. With Canary as the active main transcriber, every notebook upload from either surface hits the same gh-81 `ValueError: Canary requires an explicit source language; received None` that the original gh-102 reporter screenshotted.

**Approach:** Mirror the gh-102-followup-1 pattern verbatim across both notebook-upload entry points. Read `session.mainLanguage` (and `session.mainTranslate` / `session.mainBidiTarget` for translation parity) via `getConfig` on mount; resolve the display name to a code via `useLanguages(activeModel).languages`; refuse-with-toast at the top of the upload handler when the active model lacks auto-detect and `resolveLanguage` returns `undefined` — same wording and channel as `SessionImportTab.handleFiles` (lines 293–301). Plumb `language` (+ `translation_enabled` / `translation_target_language`) into the existing `addFiles` options.

## Boundaries & Constraints

**Always:**
- `session.mainLanguage` is the **single source of truth** for both Session Import AND every Notebook upload entry point (decision baked-in 2026-04-30). No notebook-specific picker key.
- Refusal toasts use the **same wording and channel** (`sonner` / `toast.error`) as `SessionImportTab.handleFiles`'s guard at lines 293–301 — wording-grep parity so future copy changes propagate via grep.
- The Canary backend `ValueError` (canary_backend.py:79) and the gh-81 contract remain unchanged — last line of defense for non-dashboard clients.
- Whisper auto-detect path preserved bit-for-bit on both notebook surfaces: `Auto Detect` selection on a Whisper backend → `addFiles` called with `options.language=undefined` → POST omits `language`.
- Translation parity with the live and Session Import surfaces: when the user has Canary bidi active (English source + a translation target via the picker in `SessionView`), the notebook-upload POST carries `translation_enabled=true` + `translation_target_language=<code>` — same envelope `SessionView.handleStartRecording` and `SessionImportTab.handleFiles` already produce.

**Never:**
- Do not introduce a new language picker UI inside `AddNoteModal` or `NotebookView`'s ImportTab. The persisted picker in `SessionView` is the user's source of truth; this spec only plumbs that selection through.
- Do not silently default to `language="en"` on Canary when unresolved — re-introduces the gh-81 footgun.
- Do not lift `mainLanguage` into a Zustand store. Keep reading via `getConfig('session.mainLanguage')` — same pattern `SessionImportTab` already uses.
- Do not touch `importQueueStore.handleFilesDetected` (folder watch), `SessionConfig`/`NotebookConfig` types, or the backend route layer — those are gh-102-followup carve-outs #2 and #3, deferred separately in `deferred-work.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| Canary + `mainLanguage="Spanish"`, drop file in AddNoteModal OR NotebookView ImportTab | Canary active, languages resolved | `addFiles` enqueues with `options.language="es"`; POST `/api/notebook/transcribe/upload` carries `language=es`; transcription succeeds | N/A |
| Canary + `mainLanguage="Auto Detect"` (or empty / unresolvable), drop in either notebook surface | Canary active | `addFiles` is NOT called; `toast.error` shown matching `SessionImportTab.handleFiles` guard wording verbatim | sonner |
| Canary bidi (English source + `mainBidiTarget="French"`), drop in either notebook surface | Canary active | `addFiles` enqueues with `language="en"`, `translation_enabled=true`, `translation_target_language="fr"` | N/A |
| Whisper + `mainLanguage="Auto Detect"`, drop in either notebook surface | Whisper active | `addFiles` enqueues with `options.language=undefined`; POST omits `language`; Whisper auto-detects | N/A |
| Languages still loading when user uploads | `useLanguages.loading=true`, Canary active, Spanish persisted | Refuse-with-toast same as unresolved case, with "loading languages" wording (mirrors `SessionImportTab.handleFiles` loading branch) | sonner |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/AddNoteModal.tsx` — root cause #1. `handleSubmit` (~L106-128) currently passes only diarization/word-timestamps/parallel/file_created_at/title into `addFiles`. Add: `useLanguages(activeModel)` + `useAdminStatus()` imports; `mainLanguage`/`mainTranslate`/`mainBidiTarget` state hydrated from `getConfig` on mount (mirror `SessionImportTab.tsx:163–183`); `resolveLanguage` callback against `useLanguages(activeModel).languages` (mirror `SessionImportTab.tsx:270–277`); refuse-with-toast guard at the top of `handleSubmit` (mirror `SessionImportTab.tsx:291–301` — three branches: loading / unresolvable display name / no selection); plumb `language` (+ `translation_enabled` / `translation_target_language`) into the existing `addFiles` options object.

- `dashboard/components/views/NotebookView.tsx` — root cause #2. The inline `ImportTab` (lines 1302–1480) has the same drop at `handleFiles` (line 1451). Apply the same pattern there. The parent `NotebookView` already calls `useLanguages(activeModel)` at line 113 — but call `useLanguages` inside `ImportTab` directly (local consumption, simpler diff than prop-drilling). The hydrate `useEffect` and `resolveLanguage` callback also live inside `ImportTab`.

- `dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx` (new) — covers the five I/O Matrix rows. Reuse the `useLanguages`/`getConfig`/`useAdminStatus`/toast.error mock pattern from `SessionImportTab.canary-language.test.tsx`. Each test asserts on the `addFiles` mock argument shape (called or not, with what `options.language` / `translation_*`).

- `dashboard/components/__tests__/NotebookView.canary-language.test.tsx` (new) — same five-row coverage for `NotebookView`'s ImportTab. May share a small fixture file with the AddNoteModal test if helpful.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/AddNoteModal.tsx` — add the four imports (`useLanguages`, `useAdminStatus`, `getConfig`, `supportsAutoDetect`/`isCanaryModel`/`supportsTranslation` from `modelCapabilities`), the three state vars + hydrate `useEffect`, `resolveLanguage` callback, refuse-with-toast guard at the top of `handleSubmit`, and plumb `language` + translation fields into `addFiles` options.
- [x] `dashboard/components/views/NotebookView.tsx` — same pattern inside the inline `ImportTab` component (handleFiles guard + `addFiles` plumbing).
- [x] `dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx` (new) — five tests covering the I/O Matrix rows.
- [x] `dashboard/components/__tests__/NotebookView.canary-language.test.tsx` (new) — five tests with the same coverage for the NotebookView ImportTab.

**Acceptance Criteria:**
- Given Canary is the active main transcriber and `session.mainLanguage="Spanish"`, when the user uploads a file via AddNoteModal OR NotebookView ImportTab, then `apiClient.uploadAndTranscribe` is invoked with `options.language="es"` and no error toast is shown.
- Given Canary is active and `session.mainLanguage` is `"Auto Detect"` or empty/unresolvable, when the user uploads via either notebook surface, then `addFiles` is NOT called and a `toast.error` appears whose wording matches the `SessionImportTab.handleFiles` guard verbatim.
- Given Canary is active with bidi translation enabled (English source, target = French), when the user uploads via either notebook surface, then `addFiles` is called with `language="en"`, `translation_enabled=true`, `translation_target_language="fr"`.
- Given Whisper is active and `session.mainLanguage="Auto Detect"`, when the user uploads via either notebook surface, then `addFiles` is called with `options.language=undefined` (POST omits `language`; Whisper auto-detects).
- Given the languages query is still loading when the user uploads (Canary active), then the refuse-with-toast path fires using the "loading languages" wording from the existing `SessionImportTab.handleFiles` loading branch.
- All gh-102-followup-1 tests stay green (`SessionImportTab.canary-language.test.tsx` and `SessionView.canary-language.test.tsx` — no regression in the live recording or session-import surfaces).

## Spec Change Log

### 2026-04-30 step-04 patches (iteration 1, no bad_spec/intent_gap)

- **Patch:** `dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx` and `NotebookView.canary-language.test.tsx` — replaced loose `toMatch(/source language required/i)` + `toMatch(/not a valid source language|no source language/i)` + `toMatch(/loading languages/i)` regex assertions with strict `toBe(...)` equality against the verbatim `SessionImportTab.handleFiles` (lines 293–301) toast title and description strings. Triggering finding: acceptance auditor #1 + #2 (LOW). The spec's `Always:` block requires "wording-grep parity so future copy changes propagate via grep"; loose regexes silently allowed copy drift between the three guard sites (AddNoteModal / NotebookView.ImportTab / SessionImportTab.handleFiles). Strict equality now enforces the invariant — a future copy edit at any one site fails tests until propagated to the other two. Tests still pass (10/10).

- **Reject:** "Stale `addFiles` closure in NotebookView ImportTab" (blind #1). False alarm: `addFiles` IS in the `handleFiles` `useCallback` dep array (it was already there before this diff and remains in place). AddNoteModal uses `useImportQueueStore.getState().addFiles(...)` so no dep needed.

- **Reject:** "`resolveLanguage(mainBidiTarget) ?? 'en'` silently fabricates an English target" (blind #2). Pre-existing pattern at SessionImportTab.tsx:312, faithfully replicated per the spec's translation-parity invariant. The behavior is well-defined: when bidi target is unresolvable, the en→en degenerate translate is preferred over silently dropping the user's translation intent. Cross-surface harmonization (if needed) is a separate concern.

- **Reject:** "Hydrate race — submit before useEffect resolves" (blind #3 / edge #2). Equivalent concern was rejected in the gh-102-followup-1 spec change log iteration 1 ("drag-and-drop is human-scale (>>1s); race is essentially unreachable"). Same logic applies: AddNoteModal mount → user drags file (human-scale) → user clicks submit, and NotebookView.ImportTab mount → user drag-drop. The synchronous `Promise.all([getConfig...])` typically resolves in <5ms; the user-action time scale makes the window effectively unreachable. If a future programmatic-submit path lands (e.g. shortcut-driven), revisit with a `hydrated` flag.

- **Reject:** "`useLanguages` schema mismatch — may not expose `loading`" (blind #4). Unfounded: `dashboard/src/hooks/useLanguages.ts:80–87` returns `loading: data === undefined`. Acceptance auditor independently verified the hook contract.

- **Reject:** "Hydrate `useEffect` deps `[]`" (blind #5). Faithfully replicated SessionImportTab.tsx:163–183 pattern. Mount-and-done semantic — the modal/tab opens, hydrates once, and stays consistent until close. Config changes from SessionView while a notebook surface is open are an unreachable path (the user can't be in two views simultaneously in this single-window app).

- **Reject:** "`isCanaryMainBidi` checks display name vs code" (blind #6 / edge #5). Pre-existing pattern (SessionImportTab.tsx:129). Per the gh-102-followup-1 spec, `session.mainLanguage` is documented as a display name, written by `SessionView.handleMainLanguageChange` from the picker which produces display names by construction. No drift possible without external mutation.

- **Reject:** "Translation envelope drift between SessionView and SessionImportTab" (edge #1). Drift exists between live-recording (SessionView) and import surfaces (SessionImportTab + new notebook surfaces), but is NOT introduced by this diff — this diff faithfully mirrors SessionImportTab. Cross-surface harmonization with SessionView is an out-of-scope concern.

- **Reject:** "`notebook-auto` (folder watch) bypasses new language plumbing" (edge #3). Exactly the deferred carve-out #2 (folder-watch). Spec's `Never:` block explicitly bars touching `importQueueStore.handleFilesDetected`. Tracked at `deferred-work.md` as `gh-102-followup carve-out #2`.

- **Reject:** "`mainBidiTarget = 'Off'` literal sentinel ambiguity" (edge #4). Pre-existing pattern at SessionImportTab.tsx:309. The picker UI in SessionView produces only finite known values; degenerate string drift is not reachable.

- **Reject:** "MLX-Parakeet bypass via `supportsAutoDetect`" (edge #6). Pre-existing modelCapabilities behavior; not introduced or exacerbated. The spec's scope is limited to plumbing `session.mainLanguage` into existing surfaces, not auditing the auto-detect predicate.

- **Reject:** "Test ordering / portal render leak" (edge #8). Tests pass (10/10). The render-leak risk is theoretical without a current symptom; vitest's default per-file isolation contains it within this file. `document.body.innerHTML = ''` in beforeEach is a defense-in-depth.

- **Reject:** Test fragility nits (blind #7, #11, #12; edge #9, #10): mock selector path, microtask-flush hack, regex-based DOM finders, Whisper-with-translate-on coverage gap. Tests pass; concerns are theoretical without current symptoms. Coverage gaps not in I/O matrix are out-of-spec scope.

- **Reject:** Cosmetic / pre-existing findings (blind #9, #10; edge #7 self-withdrawn; auditor #3, #4): activeModel derivation duplication, Whisper-translate-on path, "empty string" sub-branch (functionally unreachable — hydrate guard skips empty strings, no setter writes empty), Auto-Detect-vs-stale-display-name distinction (academic; both converge on the same descriptive branch via `supportsAutoDetect(canary)=false + truthy mainLanguage`).

## Verification

**Commands:**
- `cd dashboard && npm run test -- AddNoteModal.canary-language` — new tests pass.
- `cd dashboard && npm run test -- NotebookView.canary-language` — new tests pass.
- `cd dashboard && npm run test -- SessionImportTab.canary-language` — gh-102-followup-1 tests stay green.
- `cd dashboard && npm run test -- SessionView.canary-language` — gh-102 live-recording tests stay green.
- `cd dashboard && npm run typecheck` — no type errors.
- `cd dashboard && npm run ui:contract:check` — no contract drift expected (no class-name changes).

**Manual checks:**
- Reproduce the issue-#102 notebook flow: select `nvidia/canary-1b-v2` as main transcriber, set Source Language to `Spanish` in `SessionView`, open `AddNoteModal` (e.g. via the calendar +-button), drop a Spanish audio file → transcript appears in Spanish, no error toast.
- Same model + `Auto Detect` selected → drop a file in `AddNoteModal` → see refuse toast with the exact same wording as `SessionImportTab.handleFiles`'s guard, queue unchanged.
- Repeat both checks via `NotebookView`'s inline ImportTab drag-drop area.
- Switch to Whisper + `Auto Detect` → drop a file in either notebook surface → transcribes normally (regression check).
- Live recording on Canary + Spanish source still works (regression check on the prior gh-102 fix).

## Suggested Review Order

**Mirror pattern (start here — design intent)**

- The canonical guard pattern from gh-102-followup-1 that this diff mirrors verbatim across both notebook surfaces.
  [`SessionImportTab.tsx:291`](../../dashboard/components/views/SessionImportTab.tsx#L291)

**Source-of-truth plumbing (no duplicate UI, single picker key)**

- AddNoteModal hydrate effect — reads persisted `session.mainLanguage` / `mainTranslate` / `mainBidiTarget` on mount; the SessionView picker remains the user's source of truth.
  [`AddNoteModal.tsx:110`](../../dashboard/components/views/AddNoteModal.tsx#L110)

- NotebookView ImportTab parallel hydrate — re-derives `activeModel` from the existing `adminStatus` prop to avoid prop-drilling the model name.
  [`NotebookView.tsx:1434`](../../dashboard/components/views/NotebookView.tsx#L1434)

**Refuse-with-toast guard (verbatim wording-grep parity with SessionImportTab)**

- AddNoteModal guard at the top of `handleSubmit` — refuses to enqueue and surfaces the same `sonner` toast as the live and import surfaces.
  [`AddNoteModal.tsx:178`](../../dashboard/components/views/AddNoteModal.tsx#L178)

- NotebookView ImportTab guard at the top of `handleFiles` — byte-identical wording.
  [`NotebookView.tsx:1514`](../../dashboard/components/views/NotebookView.tsx#L1514)

**Translation envelope plumbing**

- AddNoteModal `addFiles` call now carries `language` + `translation_enabled` + `translation_target_language`.
  [`AddNoteModal.tsx:220`](../../dashboard/components/views/AddNoteModal.tsx#L220)

- NotebookView ImportTab parallel — same envelope shape SessionImportTab and live recording produce.
  [`NotebookView.tsx:1541`](../../dashboard/components/views/NotebookView.tsx#L1541)

**Tests (supporting)**

- New AddNoteModal file pins the five I/O Matrix rows; mock pattern mirrors `SessionImportTab.canary-language.test.tsx`.
  [`AddNoteModal.canary-language.test.tsx:1`](../../dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx#L1)

- New NotebookView file — same coverage for the inline `ImportTab`.
  [`NotebookView.canary-language.test.tsx:1`](../../dashboard/components/__tests__/NotebookView.canary-language.test.tsx#L1)

- **step-04 patch:** strict-equality wording assertion enforces the spec's "wording-grep parity" Always: invariant — any future copy drift between the three guard sites fails tests.
  [`AddNoteModal.canary-language.test.tsx:233`](../../dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx#L233)

- **step-04 patch:** parallel strict-equality assertion in NotebookView tests.
  [`NotebookView.canary-language.test.tsx:325`](../../dashboard/components/__tests__/NotebookView.canary-language.test.tsx#L325)

- gh-102-followup-1 tests stay green — regression baseline.
  [`SessionImportTab.canary-language.test.tsx:1`](../../dashboard/components/__tests__/SessionImportTab.canary-language.test.tsx#L1)
