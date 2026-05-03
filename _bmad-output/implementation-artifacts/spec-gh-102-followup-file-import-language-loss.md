---
title: 'gh-102 followup: SessionImportTab honors `session.mainLanguage` (Canary file-import fix)'
type: 'bugfix'
created: '2026-04-30'
status: 'done'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-canary-picker-language-loss.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-81-canary-forced-english.md'
baseline_commit: '727c71532a169a43fc3b50374f841ff4a58d8800'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Issue #102 was reopened on v1.3.4. The reporter's log shows the failure path is `POST /api/transcribe/import → _run_file_import → engine.transcribe_audio → canary_backend.transcribe()` raising `ValueError: Canary requires an explicit source language; received None`. The original gh-102 fix only patched the WebSocket live-recording leg in `SessionView.tsx`. `SessionImportTab.handleFiles` (~L220) never read or plumbed the persisted `session.mainLanguage` — it called `addFiles(...)` with diarization/timestamps/parallel/multitrack and nothing else, so the form-data POST omitted `language` entirely. With Canary as the active main transcriber, the gh-81 fail-loud guard then fired with the cryptic toast the reporter screenshotted.

**Approach:** Plumb `session.mainLanguage` (and translation-target keys when Canary bidi is active) from the persisted config through `SessionImportTab.handleFiles` into the `addFiles` options. Mirror the live-recording guard pattern from the original gh-102 fix at `SessionView.handleStartRecording`: refuse to enqueue with a clear `toast.error` (same wording, same channel) when the active model lacks auto-detect and `resolveLanguage` returns `undefined`. Reuse the same `useLanguages` hook and `resolveLanguage` shape `SessionView` already uses — single source of truth for display→code resolution.

## Boundaries & Constraints

**Always:**
- The Source Language selection persisted at `session.mainLanguage` is the single source of truth for the Session-tab manual file import. Selecting "Spanish" in `SessionView` and then dropping a file into the Session Import tab MUST resolve to `language="es"` in the form-data POST.
- Refusal toasts at the import entry point use the **same wording and channel** (`sonner` / `toast.error`) as the existing live-recording guard in `SessionView.handleStartRecording`. Users see consistent messaging across the live and import surfaces.
- The Canary backend `ValueError` (canary_backend.py:79) and the gh-81 contract remain unchanged — they are the last line of defense for non-dashboard clients and must not be loosened.
- Whisper's auto-detect path is preserved bit-for-bit: `Auto Detect` selection on a Whisper backend means `addFiles` is called with `options.language=undefined` and the form-data POST omits the `language` field. No regression on the auto-detect happy path.
- Translation parity: when the user has Canary bidi active (English source + a translation target via the same picker), the import POST carries `translation_enabled=true` and `translation_target_language=<code>` — same shape `SessionView.handleStartRecording` already produces for live recording.

**Ask First:**
- *(none — both prior open questions resolved on 2026-04-30: single picker key for all import surfaces; folder-watch pause-while-loading is the design for the deferred carve-out, not this spec.)*

**Never:**
- Do not introduce a new language picker UI inside `SessionImportTab`. The user's source of truth is the picker in `SessionView`; this spec only plumbs that selection through, it does not add a duplicate UI.
- Do not lift `mainLanguage` into a Zustand store as part of this fix. Reading `getConfig('session.mainLanguage')` mirrors how `SessionView` already loads the persisted value.
- Do not silently default to `language="en"` on Canary when the picker is unresolved — that re-introduces the gh-81 footgun.
- Do not touch `AddNoteModal`, `importQueueStore.handleFilesDetected` (folder watch), or the backend route layer in this spec — those are tracked as gh-102-followup carve-outs in `deferred-work.md` and ship in separate PRs.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| Canary + Source Language = Spanish, drop file in Session Import | `session.mainLanguage="Spanish"`, activeModel=`nvidia/canary-1b-v2`, languages list resolved | `addFiles` enqueues with `options.language="es"`; POST `/api/transcribe/import` form-data carries `language=es`; transcription succeeds | N/A |
| Canary + Source Language = Auto Detect (or empty / unresolvable), drop file in | `session.mainLanguage="Auto Detect"`, Canary active | `addFiles` is NOT called; `toast.error` shown (same wording as `handleStartRecording` guard); queue unchanged | Surfaced via existing `sonner` channel |
| Canary + bidi translation active (English source, target = French), drop file in | `mainTranslate` true OR `mainBidiTarget="French"`, English picker | `addFiles` enqueues with `language="en"`, `translation_enabled=true`, `translation_target_language="fr"` | N/A |
| Whisper + Source Language = Auto Detect, drop file in | `session.mainLanguage="Auto Detect"`, Whisper active | `addFiles` enqueues with `options.language=undefined`; POST omits `language`; Whisper auto-detects | N/A |
| Languages still loading when user drops file | `useLanguages.loading=true`, Canary active, Spanish persisted | Refuse-with-toast same as unresolved case, with "loading languages — try again" wording (mirrors `handleStartRecording`'s loading branch) | Existing toast channel |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/SessionImportTab.tsx` — root cause. `handleFiles` (~L220-250) currently passes only diarization/word-timestamps/parallel/multitrack into `addFiles`. Add: `mainLanguage` state mirrored from `getConfig('session.mainLanguage')` (mirror SessionView's load pattern at `SessionView.tsx:393-412`); `mainTranslate` / `mainBidiTarget` similarly mirrored if not already exposed elsewhere; a `resolveLanguage` callback against `useLanguages(activeModel).languages` (line 104 already imports the hook); the same refuse-with-toast guard pattern from `SessionView.tsx:705-715`. On the happy path, pass `language: resolvedLang`, `translation_enabled`, `translation_target_language` into the existing `addFiles` options object.
- `dashboard/components/views/SessionView.tsx` — verification only. Confirm `session.mainLanguage` is already persisted on every `setMainLanguage` (via `setConfig` at `SessionView.tsx:476-477` — gh-102 spec already wired this). Same check for `session.mainTranslate` / `session.mainBidiTarget` — only add `setConfig` writes if any are missing. Likely zero changes here; flag and add if a gap is found during step-03.
- `dashboard/components/__tests__/SessionImportTab.canary-language.test.tsx` (new) — covers the four behaviorally distinct I/O Matrix rows. Reuses the established `useLanguages` mock pattern from `SessionView.canary-language.test.tsx` (`getConfig`/`setConfig` async mocks; `useLanguages` returning a fixed NEMO list; toast.error spy). Each test asserts on the `addFiles` mock argument shape (called or not, with what `options.language`).

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/SessionImportTab.tsx` — read `session.mainLanguage` (+ `session.mainTranslate` / `session.mainBidiTarget` for translation parity) from config via `getConfig` on mount and on relevant config-change events; resolve to code via `useLanguages(activeModel).languages`; add the refuse-with-toast guard mirroring `SessionView.handleStartRecording`'s wording and channel; plumb `language` (+ `translation_enabled` / `translation_target_language`) into the existing `addFiles` options object in `handleFiles`.
- [x] `dashboard/components/views/SessionView.tsx` — verification only: confirm all three keys (`session.mainLanguage`, `session.mainTranslate`, `session.mainBidiTarget`) are already persisted on every change. Add `setConfig` writes only if any gap is found. *(Gap found: `session.mainTranslate` and `session.mainBidiTarget` were not persisted; wrapped `setMainTranslate` / `setMainBidiTarget` setters with `setConfig` writes and added matching hydrate reads in the mount-time load. `session.mainLanguage` was already persisted via `handleMainLanguageChange`.)*
- [x] `dashboard/components/__tests__/SessionImportTab.canary-language.test.tsx` (new) — five tests covering the I/O Matrix rows (Canary+Spanish happy path; Canary+Auto Detect refuse; Canary+bidi translation; Whisper+Auto Detect happy path; Canary+languages-loading refuse with loading wording).
- [x] `dashboard/components/__tests__/SessionView.canary-language.test.tsx` — sanity-only: re-run after the SessionImportTab change. The existing live-recording assertions must stay green (no regression to `handleStartRecording` / `handleLiveToggle`).

## Spec Change Log

### 2026-04-30 step-04 patches (iteration 1, no bad_spec/intent_gap)

- **Patch:** `dashboard/components/views/SessionView.tsx:514` — replaced `setMainTranslate(false)` with `setMainTranslateRaw(false)` inside the `if (!canTranslate)` reset effect, with a comment explaining the rationale. Triggering finding: edge-case hunter #1+#2 (HIGH). The step-03 implementation correctly wrapped `setMainTranslate` and `setMainBidiTarget` in persisting `useCallback`s for user-initiated changes (UI onChange at lines 1547/1555) — but the existing reset effect at line 514, which fires on model swaps to non-translation backends (Parakeet, Whisper turbo, .en, distil-large-v3), unconditionally called the new wrapper. Result: every model swap through a non-translation backend silently wrote `mainTranslate=false` to disk, clobbering the user's saved preference. Using the raw setter inside the reset effect keeps model-driven resets in-memory only; persistence remains correctly tied to user-initiated callbacks. The same pattern is already used by the hydration block at line 442 (`setMainTranslateRaw(savedMainTranslate)`) so this is a consistency fix, not a new pattern. `setMainBidiTarget` does not have an analogous auto-reset effect (only the UI onChange at line 1547 calls it), so no parallel patch is needed there.
- **Reject:** "Hydration race in SessionImportTab" (blind #1+#2, edge-case #3+#5). The `handleFiles` toast guard's branch order already prefers the `languagesLoading` message over the `mainLanguage` truthy branch, so the only reachable confusing-toast scenario requires a user dropping a file within the ~5ms `Promise.all([getConfig...])` hydration window of mounting the import tab. Drag-and-drop is human-scale (>>1s); the race is essentially unreachable. Drop in favor of the simpler implementation. If a future programmatic-enqueue path lands (e.g. file-picker auto-upload), revisit and add a `hydrated` flag.
- **Reject:** "Translation parity desync — SessionImportTab is read-only for `mainTranslate`/`mainBidiTarget`" (blind #3). This is the intended design; the comment at SessionImportTab.tsx:38 enforces it and the spec's `Never` block bars adding a duplicate picker UI. No action.
- **Reject:** "Stale bidi target → silent English fallback" (blind #4) — pre-existing in SessionView.tsx:745, faithfully replicated per spec's translation-parity invariant. Not introduced by this diff.
- **Reject:** "`setConfig` `.catch(() => {})` swallows persistence errors" (blind #5+#6) — consistent with the pre-existing pattern at SessionView.tsx:477 (`session.mainLanguage`). A codebase-wide cleanup is out of scope here.
- **Reject:** "Whisper + translate=true + Auto Detect omits `language` from POST" (edge #4) — pre-existing live-mode behavior at SessionView.tsx:744-745, faithfully replicated per spec. Backend currently allows it; future tightening is speculative.
- **Reject:** "MLX Canary parity — `isCanaryModel` returns false for MLX-Canary variants" (edge #6) — pre-existing in `modelCapabilities.ts`, this diff only propagates it. Edge-case hunter explicitly flagged as pre-existing. Not this story's problem.
- **Reject:** Test fragility nits (blind #9, #10, #11): module-level mock state, `.cursor-pointer` selector, `Promise.resolve()` await pattern. Tests pass; concerns are theoretical without a current symptom.
- **Reject:** Cosmetic / future-suggestion findings (blind #7, #8, #12; edge none): `useCallback` dep audit (blind itself confirmed deps are correct), XSS-shape (sonner is text-only), suggestion to add a hydration regression test (suggestion, not a finding).


**Acceptance Criteria:**
- Given Canary is the active main transcriber and `session.mainLanguage="Spanish"`, when the user drops an audio file into the Session Import area, then `apiClient.importAndTranscribe` is invoked with `options.language="es"` and no error toast is shown.
- Given Canary is active and `session.mainLanguage` is `"Auto Detect"` or empty/unresolvable, when the user drops a file in, then `addFiles` is NOT called and a `toast.error` appears whose wording matches the existing live-recording guard.
- Given Canary is active with bidi translation enabled (English source, target = French), when the user drops a file in, then `addFiles` is called with `language="en"`, `translation_enabled=true`, `translation_target_language="fr"`.
- Given Whisper is active and `session.mainLanguage="Auto Detect"`, when the user drops a file in, then `addFiles` is called with `options.language=undefined` (POST omits the `language` field; Whisper auto-detects).
- Given the languages query is still loading when the user drops a file in (Canary active), then the refuse-with-toast path fires using the "loading languages" wording from the existing live-mode guard.

## Verification

**Commands:**
- `cd dashboard && npm run test -- SessionImportTab.canary-language` — new tests pass.
- `cd dashboard && npm run test -- SessionView.canary-language` — gh-102 live-recording tests stay green.
- `cd dashboard && npm run typecheck` — no type errors.
- `cd dashboard && npm run ui:contract:check` — no contract drift (no class-name changes expected).

**Manual checks:**
- Reproduce the issue-#102 scenario: select `nvidia/canary-1b-v2` as main transcriber, set Source Language to `Spanish`, switch to the Session Import tab, drag-drop a Spanish audio file → transcript appears in Spanish, no error toast.
- Same model + `Auto Detect` selected → drop a file → see refuse toast with the exact same wording as the live-recording guard, queue unchanged.
- Switch to Whisper + `Auto Detect` → drop a file → transcribes normally (regression check).
- Live recording on Canary still works with Spanish source (regression check on the prior gh-102 fix).

## Suggested Review Order

**Source-of-truth plumbing (start here — this is the design intent)**

- Persisted single-picker config keys mirrored from SessionView's `mainLanguage` load pattern; one source of truth for live and import paths.
  [`SessionImportTab.tsx:60`](../../dashboard/components/views/SessionImportTab.tsx#L60)

- Display→code resolver mirrors `SessionView.resolveLanguage` so both surfaces use identical lookup semantics.
  [`SessionImportTab.tsx:99`](../../dashboard/components/views/SessionImportTab.tsx#L99)

**Refuse-with-toast guard (verbatim wording from live recording)**

- Guard refuses to enqueue when Canary cannot resolve a source language; wording is byte-identical to `handleStartRecording`.
  [`SessionImportTab.tsx:111`](../../dashboard/components/views/SessionImportTab.tsx#L111)

- Translation envelope mirrors `SessionView.handleStartRecording`'s `mainTranslateActive` / `mainTranslateTarget` shape — Canary bidi parity.
  [`SessionImportTab.tsx:128`](../../dashboard/components/views/SessionImportTab.tsx#L128)

- Plumbed `language` + translation fields land on the existing `addFiles` options object.
  [`SessionImportTab.tsx:158`](../../dashboard/components/views/SessionImportTab.tsx#L158)

**Persistence wiring (gap-fill in SessionView)**

- New persisting wrappers for `setMainTranslate` / `setMainBidiTarget` so the import surface can read what live writes.
  [`SessionView.tsx:380`](../../dashboard/components/views/SessionView.tsx#L380)

- Hydrate uses `setMainTranslateRaw` / `setMainBidiTargetRaw` to avoid a write-on-read loop.
  [`SessionView.tsx:442`](../../dashboard/components/views/SessionView.tsx#L442)

- **step-04 patch:** model-driven reset uses the raw setter so swaps to non-translation backends don't clobber the user's saved preference.
  [`SessionView.tsx:514`](../../dashboard/components/views/SessionView.tsx#L514)

**Tests (supporting)**

- New file pins the five I/O Matrix rows; mock pattern reused from `SessionView.canary-language.test.tsx`.
  [`SessionImportTab.canary-language.test.tsx:1`](../../dashboard/components/__tests__/SessionImportTab.canary-language.test.tsx#L1)

- gh-102 live-recording assertions stay green — regression baseline.
  [`SessionView.canary-language.test.tsx:258`](../../dashboard/components/__tests__/SessionView.canary-language.test.tsx#L258)
