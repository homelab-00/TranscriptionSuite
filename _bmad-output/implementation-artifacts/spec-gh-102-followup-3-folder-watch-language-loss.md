---
title: 'gh-102 followup #3: folder-watch auto-imports honor `session.mainLanguage`'
type: 'bugfix'
created: '2026-04-30'
status: 'done'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-followup-2-notebook-upload-language-loss.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-102-followup-file-import-language-loss.md'
baseline_commit: '75418c7'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** With carve-outs #1 and #2 of gh-102 shipped (manual Session import + Notebook upload now honor `session.mainLanguage`), the third surface — **folder-watch auto-imports** — still drops the user's picker selection. `importQueueStore.ts::handleFilesDetected` (L557-610) reads only the toggle subset of `sessionConfig` / `notebookConfig` and forwards via `addFiles(..., 'session-auto' | 'notebook-auto', ...)` with no `language` field. With Canary active, every auto-detected file enqueued from the watcher still hits the gh-81 `ValueError: Canary requires an explicit source language; received None` — a delayed, opaque failure surfaced 30s later in the job log.

**Approach:** Snapshot + cache pattern (matches existing snapshot wiring). (a) Extend `SessionConfig` / `NotebookConfig` with `language?: string` (raw display name); (b) extend the existing snapshot `useEffect` in `SessionImportTab.tsx` and `NotebookView.tsx` `ImportTab` to push `mainLanguage` into the snapshot; (c) add a global `languagesCache` to the store + a parallel `useEffect` in both views that pushes `useLanguages()` results into it; (d) in `handleFilesDetected`, after the existing `watcherServerConnected` guard, resolve the snapshotted display name via the cache and **pause the entire detection batch** (no enqueue) when languages are still loading or when Canary is active and the resolve fails — using the same `toast.warning` + `appendWatchLog({ level: 'warn' })` channel the server-offline guard already uses.

## Boundaries & Constraints

**Always:**
- Reuse the existing folder-watch pause channel verbatim: `toast.warning(...)` + `appendWatchLog({ level: 'warn', message })`. Same channel as the `watcherServerConnected` guard at L561-574 — folder-watch has its own established UX pattern (warn-toast), distinct from the manual-upload `toast.error` refuse pattern. Do not switch channels.
- `session.mainLanguage` remains the **single source of truth**. The folder-watch path consumes it via the snapshot the picker already writes — no new picker UI, no folder-watch-specific config key.
- **Pause-while-loading is mandatory.** When `languagesCache.loading === true` (or the cache has not been populated yet — initial state), drop the entire detection batch with the wording `Folder Watch paused — languages still loading`. Re-resolve naturally happens on the next watcher event after the languages query resolves.
- **Pause-when-unresolvable on auto-detect-incapable backends.** When the cached active model lacks auto-detect (Canary, MLX-Canary — checked via existing `supportsAutoDetect` predicate) AND the snapshotted display name resolves to `undefined`, drop with `Folder Watch paused — Source Language required for the active model`. Whisper auto-detect path stays bit-for-bit unchanged.
- The Canary backend `ValueError` (canary_backend.py:79) and the gh-81 contract remain the last line of defense for non-dashboard clients.

**Never:**
- Do not introduce a language picker UI inside the folder-watch settings surface. The persisted picker in `SessionView` is the user's source of truth.
- Do not silently default to `language="en"` on Canary when unresolved — re-introduces the gh-81 footgun.
- Do not touch the backend route layer (`/api/transcribe/import`, `/api/notebook/transcribe/upload`) — that is gh-102-followup carve-out #3, deferred separately.
- Do not modify the upload-handler refuse-with-toast paths in `AddNoteModal` / `NotebookView.ImportTab.handleFiles` / `SessionImportTab.handleFiles` — those shipped in carve-outs #1 and gh-102-followup-1.
- Do not call `apiClient.getLanguages()` directly from the store. The cache is populated by `useLanguages()` consumers via the snapshot pattern only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| Canary active, `session.mainLanguage="Spanish"`, languages loaded, watched folder receives file | Canary active, `cache.loading=false`, snapshot has `language="Spanish"` | `addFiles(files, 'session-auto', { ..., language: 'es' })` — file enqueued with code | N/A |
| Canary active, `session.mainLanguage="Auto Detect"` (or empty, or unresolvable display name), watched folder receives file | Canary active, `cache.loading=false`, snapshot resolves to `undefined` | `addFiles` is NOT called; `appendWatchLog({ level: 'warn', message: 'Folder Watch paused — Source Language required for the active model' })`; `toast.warning` with same wording | sonner |
| Canary active, `session.mainLanguage="Spanish"`, languages still loading at watcher firing | Canary active, `cache.loading=true` | `addFiles` is NOT called; `appendWatchLog({ level: 'warn', message: 'Folder Watch paused — languages still loading' })`; `toast.warning` with same wording | sonner |
| Whisper active, `session.mainLanguage="Auto Detect"`, watched folder receives file | Whisper active, snapshot has `language="Auto Detect"` | `addFiles(files, 'session-auto', { ..., language: undefined })` — POST omits `language`; Whisper auto-detects | N/A |
| Whisper active, `session.mainLanguage="Spanish"`, watched folder receives file | Whisper active, snapshot has `language="Spanish"` | `addFiles(files, 'session-auto', { ..., language: 'es' })` | N/A |
| Notebook variant of the watcher: same five scenarios for `'notebook-auto'` enqueue, reading `notebookConfig.language` and writing to the same `addFiles` notebook envelope | Same as above per `payload.type === 'notebook'` | Same outcomes — folder-watch paths must stay symmetric session/notebook | sonner on pause cases |

</frozen-after-approval>

## Code Map

- `dashboard/src/stores/importQueueStore.ts` — root cause. (a) Extend `SessionConfig` (L43-51) and `NotebookConfig` (L53-58) with `language?: string` (raw display name; optional because folder-watch may fire before any snapshot lands). (b) Add a top-level `languagesCache: { model: string | null; languages: Array<{ code: string; name: string }>; loading: boolean }` field with initial `{ model: null, languages: [], loading: true }`. (c) Add `setLanguagesCache(payload)` action. (d) In `handleFilesDetected` (L557-610), after the existing `watcherServerConnected` early-return at L561-574, insert the resolve+pause block: read `state.languagesCache`, read snapshot's `language` display name, resolve via name-match (mirror `SessionImportTab.tsx::resolveLanguage` at L270-277), and pause-with-warn-toast on the two failure conditions. Plumb the resolved code into the existing `addFiles` calls at L586 (notebook) and L596 (session) as `language`.

- `dashboard/components/views/SessionImportTab.tsx` — extend the existing snapshot `useEffect` at L215-234 to include `language: mainLanguage` in the `updateSessionConfig` call (and add `mainLanguage` to its deps array). Add a parallel `useEffect` (idiomatic spot: just below the existing one) that calls `setLanguagesCache({ model: activeModel, languages, loading: languagesLoading })` whenever any of those three change. `activeModel`, `languages`, `languagesLoading` are already in scope from the carve-out #1 wiring.

- `dashboard/components/views/NotebookView.tsx` — same pattern inside the inline `ImportTab` component (L1302-1480). Extend the snapshot effect at L1483-1489 to include `language: mainLanguage` in the `updateNotebookConfig` call. Add a parallel `setLanguagesCache` effect. `useLanguages(activeModel)` already wired in this `ImportTab` post-carve-out-#1.

- `dashboard/src/stores/__tests__/importQueueStore.test.ts` — extend the existing `handleFilesDetected` test block (L309-437). Add five tests covering the I/O Matrix rows (one per scenario, session and notebook each get coverage; share fixtures where the row is symmetric). Pre-seed the snapshot via `setSessionConfig` / `setNotebookConfig` and the languages cache via the new `setLanguagesCache` action.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/stores/importQueueStore.ts` — extend `SessionConfig` / `NotebookConfig` with `language?: string`; add `languagesCache` state + `setLanguagesCache` action; insert resolve+pause logic in `handleFilesDetected` after the `watcherServerConnected` guard; plumb resolved code into both `addFiles` calls.
- [x] `dashboard/components/views/SessionImportTab.tsx` — extend the L215 snapshot effect to include `language: mainLanguage`; add a parallel `setLanguagesCache` effect.
- [x] `dashboard/components/views/NotebookView.tsx` — same pattern in the inline `ImportTab` snapshot effect (L1483) and add the parallel `setLanguagesCache` effect.
- [x] `dashboard/src/stores/__tests__/importQueueStore.test.ts` — add five tests covering the I/O Matrix rows; verify `appendWatchLog` entries and `toast.warning` calls in pause cases; assert `addFiles` argument shape in success cases. (Note: actual path is `dashboard/src/stores/importQueueStore.test.ts` — no `__tests__` subdir.)

**Acceptance Criteria:**
- Given Canary is active, `session.mainLanguage="Spanish"`, languages cache is populated, when the watcher emits a file detection event, then `addFiles` is called once with `options.language="es"`.
- Given Canary is active and the snapshotted language resolves to `undefined` (Auto Detect / empty / drift), when the watcher fires, then `addFiles` is NOT called and `appendWatchLog` records exactly `Folder Watch paused — Source Language required for the active model` at `level: 'warn'`, with a matching `toast.warning`.
- Given Canary is active and `languagesCache.loading === true` when the watcher fires, then `addFiles` is NOT called and `appendWatchLog` records exactly `Folder Watch paused — languages still loading` at `level: 'warn'`, with a matching `toast.warning`.
- Given Whisper is active and `session.mainLanguage="Auto Detect"`, when the watcher fires, then `addFiles` is called with `options.language=undefined` (POST omits `language`).
- The notebook-auto path mirrors all four behaviors when `payload.type === 'notebook'`, reading from `notebookConfig.language` instead of `sessionConfig.language`.
- Existing `importQueueStore.test.ts::handleFilesDetected` tests stay green.
- Carve-out #1 + gh-102-followup-1 test suites stay green: `AddNoteModal.canary-language.test.tsx`, `NotebookView.canary-language.test.tsx`, `SessionImportTab.canary-language.test.tsx`, `SessionView.canary-language.test.tsx`.

## Spec Change Log

### 2026-04-30 step-04 patches (iteration 1, no bad_spec/intent_gap)

- **Patch:** `dashboard/src/stores/importQueueStore.ts` — refined the loading-pause guard from `cache.loading || cache.languages.length === 0` to `cache.loading || cache.model === null`. Triggering finding: blind#1 + blind#2 + edge#2 + edge#4 (HIGH). The `length === 0` branch conflated three distinct states ("loading", "cache not yet populated by any view", "loaded but empty") and emitted the wrong toast wording in the third. Switching the guard to model-identity isolates "cache not yet populated" cleanly. The `loaded-but-empty` case now falls through to the explicit-required guard where Canary still pauses (with the more accurate "Source Language required" wording) and Whisper proceeds with auto-detect — both correct. No spec-text change required (the spec sketch in Design Notes is illustrative; the `Always:` invariants in the frozen block read on intent, not exact predicate shape).

- **Patch:** `dashboard/src/stores/importQueueStore.test.ts` — moved sonner mock-clearing to the outer `beforeEach`; replaced per-test `await import('sonner') + (toast.warning as any).mockClear()` with a top-level `import { toast }` plus `vi.mocked(...).mockClear()` calls in the suite-level `beforeEach`. Triggering finding: edge#7 (MED). The pre-existing `watcherServerConnected` test emits `toast.warning`, and the call-count would otherwise leak into the new gh-102 #3 describe's `toHaveBeenCalledWith` assertions. Suite-level clearing eliminates the cross-describe contamination risk and removes the `as any` cast (edge#12).

- **Patch:** `dashboard/src/stores/importQueueStore.test.ts` — added three notebook-variant tests: notebook + Canary + Spanish loading → pause; notebook + Whisper + Auto Detect → enqueue with `language=undefined`; notebook + Whisper + Spanish → enqueue with `language='es'`. Triggering finding: auditor#1 (LOW). The implementation is type-agnostic (the resolve+pause runs before the type branch), but I/O Matrix row 6 explicitly says "the same five scenarios for `'notebook-auto'` enqueue" and AC#5 says "the notebook-auto path mirrors all four behaviors". 11 total tests in the gh-102 #3 describe block (5 session + 6 notebook with the new ones).

- **Patch:** `dashboard/src/stores/importQueueStore.test.ts::resetStore` — changed the default `languagesCache.model` from `null` to `'large-v3'` (Whisper). Required by the model-identity refinement above: with `model: null`, the new guard would incorrectly pause every pre-existing `handleFilesDetected` test. The Whisper default produces `requiresExplicit=false` so all pre-existing tests fall through unchanged.

- **Reject:** "Cold-start race — files dropped, no retry/buffer" (edge#1, edge#6, HIGH). Pre-existing pattern. The existing `watcherServerConnected: false` guard at L599-605 already drops detection events with the same `toast.warning + appendWatchLog` channel and no retry buffer. This diff faithfully mirrors that pattern; adding a buffered-replay mechanism would be a cross-cutting enhancement to both the new pause cases and the pre-existing offline-server case, out of scope for this carve-out. CLAUDE.md "AVOID DATA LOSS AT ALL COSTS" applies to transcription **results**, not detection events — the user's source files remain on disk untouched, and the watcher fires again on the next file event.

- **Reject:** "Model-switch stale-cache window" (edge#3, edge#9, HIGH). Pre-existing race pattern. The handler reads `state.sessionConfig`/`state.notebookConfig` which can also be inconsistent with the active backend during model switches (e.g., diarization toggle mid-switch). Window is 1 React frame (~16ms); folder-watch events are at human-time scale (file drops have at-least-seconds gaps). Same shape as the toggle-snapshot inconsistency the existing tests already accept.

- **Reject:** "TOCTOU between cache snapshot and addFiles" (blind#4, MED). `handleFilesDetected` is fully synchronous between the snapshot read and `addFiles` call. The cache cannot mutate mid-function. Concern is theoretical and only manifests if the function is ever made async.

- **Reject:** "Multiple consumers race — last-write-wins" (blind#5, edge#5, MED). Both `SessionImportTab` and `NotebookView ImportTab` call `useLanguages` with the same `activeModel` source (`useAdminStatus`), so React Query dedupes the underlying fetch and both writes carry the same payload — idempotent. No serialization needed.

- **Reject:** "`language: undefined` written explicitly into addFiles options" (blind#7, MED). The existing manual-upload paths (`SessionImportTab.handleFiles`, `AddNoteModal.handleSubmit`, `NotebookView.ImportTab.handleFiles`) already pass `options.language = undefined` for Whisper auto-detect. `apiClient.importAndTranscribe` / `uploadAndTranscribe` skip the field when undefined (faithfully replicated pre-existing behavior).

- **Reject:** "Test-reset overrides languagesCache, may regress pre-existing toMatchObject expectations" (blind#6, MED). Verified empirically — all 1025 tests pass after the patches. Pre-existing `toMatchObject` calls don't enumerate `language`, so `options.language: undefined` doesn't break the partial match.

- **Reject:** "Sonner `await import('sonner')` in beforeEach may resolve a different mock reference" (blind#8, MED). Vitest's `vi.mock` is hoisted at module-load time, and dynamic `import()` returns the cached module — same mock reference. Made moot anyway by the patch above moving to a top-level static import.

- **Reject:** "`setLanguagesCache: vi.fn()` in component tests hides regressions" (edge#8, MED). The component tests cover the manual-upload flow, not the folder-watch flow. The `setLanguagesCache` effect is incidental to those tests; its correctness is covered by direct store-level tests in `importQueueStore.test.ts`. Adding component-level assertions for the effect would couple unrelated test scopes.

- **Reject:** Stylistic / cosmetic concerns (blind#9 cfg unused beyond `.language`; blind#10 `mainLanguage` stability — primitive `useState<string>`; blind#11 file_created_at test; blind#12 `setLanguagesCache` full-replace vs `Partial<>` API inconsistency — full-replace is intentional, the cache is a unit; edge#10 resetStore documentation; edge#11 `isPaused` not checked — pre-existing). Tests pass; concerns are theoretical without current symptoms.

- **Reject:** Display-name drift on model swap (blind#3, MED). When the user switches active model, the persisted `session.mainLanguage` may not exist in the new model's language list. The implementation correctly pauses with "Source Language required" — the wording is mildly inaccurate ("name not in new list" vs literal "required") but the user response is identical (pick a language from the picker). Cross-surface harmonization would belong in a separate spec.

## Design Notes

**Why a store-level languages cache (not direct `apiClient.getLanguages()` in the store):** The `useLanguages` hook already deduplicates fetches via React Query (cache key `['languages', backendType]`). Calling the API directly from the store would create a parallel fetch path with its own race conditions, error states, and refresh policy. The snapshot pattern keeps the hook as the single source of truth and the store as a passive consumer of its results.

**Why pause-while-loading instead of "queue and resolve later":** A queued-but-paused file would conflict with the existing `addFiles` lifecycle (the queue UI immediately shows the file as "pending"). Re-deriving language at dequeue time would re-introduce the same async race. Pausing the detection batch entirely is conservative and clear — the watcher will fire again on the next file event after languages resolve, and the user gets a single visible warning entry.

**Why both views push the same languages cache:** `useLanguages` is keyed per-backend-type. Both `SessionImportTab` and `NotebookView.ImportTab` call it with the same `activeModel`, so React Query dedupes and they receive the same data. Either view's `setLanguagesCache` write produces an idempotent result. If neither view is mounted (cold start, folder-watch fires before user navigates), the cache stays at initial `{ loading: true }` and the watcher pauses — the safe default.

**Sample resolve+pause sketch (for reference, not prescriptive):**

```typescript
// inside handleFilesDetected, after the watcherServerConnected guard:
const { languagesCache, sessionConfig, notebookConfig } = useImportQueueStore.getState();
const cfg = payload.type === 'session' ? sessionConfig : notebookConfig;
const isAuto = cfg.language === 'Auto Detect' || !cfg.language;
const resolvedCode = isAuto ? undefined : languagesCache.languages.find(l => l.name === cfg.language)?.code;
const requiresExplicit = languagesCache.model ? !supportsAutoDetect(languagesCache.model) : false;

if (languagesCache.loading || languagesCache.languages.length === 0) {
  toast.warning('Folder Watch paused — languages still loading');
  appendWatchLog({ level: 'warn', message: 'Folder Watch paused — languages still loading' });
  return;
}
if (requiresExplicit && resolvedCode === undefined) {
  toast.warning('Folder Watch paused — Source Language required for the active model');
  appendWatchLog({ level: 'warn', message: 'Folder Watch paused — Source Language required for the active model' });
  return;
}
// then plumb resolvedCode into addFiles options
```

## Verification

**Commands:**
- `cd dashboard && npm run test -- importQueueStore` — new tests pass; existing tests stay green.
- `cd dashboard && npm run test -- SessionImportTab.canary-language` — regression baseline (gh-102-followup-1).
- `cd dashboard && npm run test -- NotebookView.canary-language` — regression baseline (carve-out #1).
- `cd dashboard && npm run test -- AddNoteModal.canary-language` — regression baseline (carve-out #1).
- `cd dashboard && npm run test -- SessionView.canary-language` — live-recording regression baseline (gh-102).
- `cd dashboard && npm run typecheck` — no type errors.
- `cd dashboard && npm run ui:contract:check` — no class-name changes expected.

**Manual checks:**
- Set up folder watch on a directory; select `nvidia/canary-1b-v2` as main transcriber; set Source Language to `Spanish`; drop a Spanish audio file into the watched directory → file enqueues with explicit Spanish, transcript appears in Spanish, no warn-toast.
- Same model + Source Language `Auto Detect` → drop a file → file does NOT enqueue, watch log shows `Folder Watch paused — Source Language required for the active model` warn entry, toast warning visible.
- Reload the dashboard (cold-start cache miss); within the first ~500ms (before `useLanguages` resolves), drop a file → file does NOT enqueue, watch log shows `Folder Watch paused — languages still loading` warn entry. After languages resolve, drop another file → enqueues normally.
- Switch to Whisper + `Auto Detect` → drop a file → enqueues with no language; transcribes normally (regression check).
- Notebook-mode folder watch (if configured): repeat the Canary + Spanish + Auto Detect cases via the notebook watcher path → same behaviors.

## Suggested Review Order

**Pause-and-cache contract (start here — design intent)**

- Heart of the diff. Resolves persisted display name → code, pauses on `loading || model === null` then on Canary-with-no-resolve, plumbs `resolvedCode` into both `addFiles` calls.
  [`importQueueStore.ts:614`](../../dashboard/src/stores/importQueueStore.ts#L614)

- Step-04 patch — model-identity guard replaces the original `length === 0` check; cleaner cold-start semantics, false-positive empty-list case falls through to the explicit-required guard correctly.
  [`importQueueStore.ts:630`](../../dashboard/src/stores/importQueueStore.ts#L630)

**Type extensions + cache state**

- `language?: string` added to `SessionConfig` and `NotebookConfig` — optional so folder-watch may fire before any snapshot lands.
  [`importQueueStore.ts:54`](../../dashboard/src/stores/importQueueStore.ts#L54)

- New `LanguagesCacheState` — full-replace shape, populated by hook consumers; initial state `{ model: null, languages: [], loading: true }` so the cold-start path naturally pauses.
  [`importQueueStore.ts:67`](../../dashboard/src/stores/importQueueStore.ts#L67)

- `setLanguagesCache` action — single-write surface for the cache.
  [`importQueueStore.ts:568`](../../dashboard/src/stores/importQueueStore.ts#L568)

**Snapshot consumers (the React → store bridge)**

- SessionImportTab: extends existing `updateSessionConfig` snapshot effect to include `mainLanguage`, plus a parallel `setLanguagesCache` effect — same pattern, two writes.
  [`SessionImportTab.tsx:240`](../../dashboard/components/views/SessionImportTab.tsx#L240)

- NotebookView ImportTab: byte-identical pattern inside the inline component; React Query dedupes the underlying `useLanguages` fetch so writes are idempotent.
  [`NotebookView.tsx:1494`](../../dashboard/components/views/NotebookView.tsx#L1494)

**Tests (I/O matrix coverage)**

- Eleven new tests pin the I/O matrix — five session, six notebook (3 happy/loading + 3 step-04 patch additions for notebook Whisper/loading symmetry).
  [`importQueueStore.test.ts:482`](../../dashboard/src/stores/importQueueStore.test.ts#L482)

- Step-04 patch — moves sonner mock-clearing to the suite-level `beforeEach` so toast call-counts can't bleed between describe blocks; replaces `(toast.warning as any).mockClear()` with `vi.mocked(...).mockClear()`.
  [`importQueueStore.test.ts:108`](../../dashboard/src/stores/importQueueStore.test.ts#L108)

**Mock parity (supporting)**

- Component-test mocks of `useImportQueueStore` updated to include `setLanguagesCache: vi.fn()` so the new view-side effects don't blow up at render time.
  [`SessionImportTab.canary-language.test.tsx:114`](../../dashboard/components/__tests__/SessionImportTab.canary-language.test.tsx#L114)

- Same parity addition for the notebook-side test files.
  [`NotebookView.canary-language.test.tsx:130`](../../dashboard/components/__tests__/NotebookView.canary-language.test.tsx#L130)

- And for the broader NotebookView test that mounts the inline ImportTab.
  [`NotebookView.test.tsx:81`](../../dashboard/components/__tests__/NotebookView.test.tsx#L81)
