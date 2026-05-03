---
title: 'Folder Watch loses Diarization and other transcribe toggles'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: 'c7b5867c65c2e42d6ce7af85e1cc308f8dda6500'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When a user enables the Diarization toggle (or Parallel Diarization, Word Timestamps, Multitrack) in the Sessions or Notebook import tabs, files that are auto-imported via Folder Watch ignore those toggles and fall back to backend defaults — diarization silently fails, word timestamps may flip, and multitrack mode is dropped. The UI suggests the toggle is "on" but the watch-folder path uses `enable_diarization=False`. Reported on Issue #93 (Apple Silicon M1 Max, v1.3.3) but reproducible on every platform.

**Approach:** Extend the existing `sessionConfig` zustand bridge to also carry the four import toggles, add a parallel `notebookConfig` for the Notebook tab, sync both from their UI tabs via the existing `useEffect`/`updateXxxConfig` pattern, and have `handleFilesDetected` read from those configs (applying the existing `multitrack ? false : diarization` derivation) when calling `addFiles` for `session-auto` and `notebook-auto` jobs.

## Boundaries & Constraints

**Always:**
- Preserve the manual-import derivation rules: `enable_diarization = multitrack ? false : diarization` (sessions only), `parallel_diarization` only sent when diarization is on, `enable_word_timestamps = supportsExplicitWordTimestampToggle ? wordTimestamps : true`.
- Auto-watch jobs MUST send the same option payload shape as their manual counterparts so the backend cannot tell them apart from option metadata alone.
- Toggles remain ephemeral (UI-state lifetime) — do not persist them to electron-store. Defaults match the existing local `useState` initial values.
- Backend route signature, default values, and persistence behavior stay unchanged.

**Ask First:**
- If the Notebook tab's import sub-component cannot reliably mount the sync `useEffect` (e.g., conditional rendering), surface the constraint instead of inventing alternative state plumbing.

**Never:**
- Do not change the Folder Watch tech spec's "active toggle is ephemeral on mount" rule (`useSessionWatcher.ts:25`).
- Do not introduce a new config namespace, IPC channel, or backend field — this is a frontend-only state-bridge fix.
- Do not change the diarization fallback chain in `server/backend/core/diarization_engine.py` or any STT backend.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Session watch, diarization ON | User toggled Diarization=on in SessionImportTab; file dropped into watch folder | `addFiles(..., 'session-auto', { enable_diarization: true, enable_word_timestamps: true, parallel_diarization: <parallelDefault> })`; backend returns diarized result | N/A |
| Session watch, multitrack ON | Multitrack=on, Diarization toggle (irrelevant per UI rule) | `enable_diarization: false, multitrack: true` — same rule as manual | N/A |
| Session watch, diarization OFF, timestamps OFF | Both toggles off | `enable_diarization: false, enable_word_timestamps: false` | N/A |
| Notebook watch, diarization ON | Notebook tab Diarization=on; file dropped into notebook watch folder | `addFiles([path], 'notebook-auto', { file_created_at, enable_diarization: true, enable_word_timestamps: true, parallel_diarization: <parallelDefault> })` | N/A |
| Notebook tab never mounted this session | User starts app, opens only Sessions tab, then notebook watch fires | `notebookConfig` defaults apply (`diarization: true`, `wordTimestamps: true`, `parallelDiarization: false`) — matches the UI default the user would have seen | N/A |
| `supportsExplicitWordTimestampToggle === false` (e.g. VibeVoice ASR) | UI forces wordTimestamps=true | Auto-path also sends `enable_word_timestamps: true` regardless of stored value | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/stores/importQueueStore.ts` — extend `SessionConfig`, add `NotebookConfig` + `updateNotebookConfig`, update `handleFilesDetected` to source options from configs.
- `dashboard/components/views/SessionImportTab.tsx` — extend the existing `updateSessionConfig` `useEffect` (line 162-165) to also push `diarization`, `wordTimestamps`, `parallelDiarization`, `multitrack`.
- `dashboard/components/views/NotebookView.tsx` — in the import sub-component (around line 1397-1418, the one with `handleFiles` for `notebook-normal`), add a `useEffect` that calls `updateNotebookConfig` whenever the local `diarization`/`wordTimestamps`/`parallelDiarization` change.
- `dashboard/src/stores/__tests__/importQueueStore.test.ts` _(new or existing — check first)_ — verify `handleFilesDetected` reads from config and produces the expected option payload for both `session-auto` and `notebook-auto`.
- `dashboard/src/api/types.ts` — reference only; no changes expected.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/stores/importQueueStore.ts` — Extend `SessionConfig` with `enableDiarization: boolean`, `enableWordTimestamps: boolean`, `parallelDiarization: boolean`, `multitrack: boolean`. Add `NotebookConfig` interface and a `notebookConfig` store slot with matching toggle fields (no `multitrack`). Add `updateNotebookConfig` action. Update default state with the same initial values the UIs use (`enableDiarization: true`, `enableWordTimestamps: true`, `parallelDiarization: false`, `multitrack: false`). Rewrite `handleFilesDetected` so the `session-auto` branch derives `{ enable_diarization: multitrack ? false : enableDiarization, enable_word_timestamps: enableWordTimestamps, parallel_diarization: (enableDiarization && !multitrack) ? parallelDiarization : undefined, multitrack: multitrack || undefined }` from `sessionConfig`, and the `notebook-auto` branch merges `{ file_created_at, enable_diarization: enableDiarization, enable_word_timestamps: enableWordTimestamps, parallel_diarization: enableDiarization ? parallelDiarization : undefined }` from `notebookConfig`. Rationale: single source of truth for the derivation rule; auto-jobs now match manual-job payload shape.
- [x] `dashboard/components/views/SessionImportTab.tsx` — Extend the existing `updateSessionConfig` `useEffect` (line 162-165) to also push `enableDiarization: diarization`, `enableWordTimestamps: wordTimestamps`, `parallelDiarization`, `multitrack`. Update its dependency array. Rationale: sync UI state to store so `handleFilesDetected` sees the user's current selection.
- [x] `dashboard/components/views/NotebookView.tsx` — In the notebook import sub-component (the one declaring `useState(true)` for diarization at line 1397), add `const updateNotebookConfig = useImportQueueStore((s) => s.updateNotebookConfig);` and a `useEffect` that calls `updateNotebookConfig({ enableDiarization: diarization, enableWordTimestamps: wordTimestamps, parallelDiarization })` when those values change. Rationale: same sync bridge for the notebook side.
- [x] `dashboard/src/stores/__tests__/importQueueStore.test.ts` — Add unit tests covering the I/O matrix scenarios above (session ON/OFF/multitrack, notebook ON/OFF, defaults when notebook tab never mounted). Use a `vi.fn()` spy on `addFiles` to assert the produced options. If the file does not exist, create it next to other store tests under `dashboard/src/stores/`.

**Acceptance Criteria:**
- Given the user toggled Diarization ON in SessionImportTab, when a file is dropped into the active session watch folder, then the resulting `notebook_jobs` row (and the response from `/api/transcribe/import`) shows `enable_diarization=true` and the transcript contains speaker labels.
- Given the user toggled Diarization ON in the Notebook import tab, when a file is dropped into the active notebook watch folder, then the recording row in the notebook DB has `has_diarization=true` and the UI's "Diarized" tag (`NotebookView.tsx:893`) is shown for that recording.
- Given Multitrack is ON in SessionImportTab, when a file is dropped into the session watch folder, then the auto job sends `multitrack: true` and `enable_diarization: false`, matching manual-import behavior.
- Given the Notebook tab has not been mounted in this session, when the notebook watch fires, then `notebookConfig` defaults apply (`enable_diarization: true`) — i.e. the same outcome the user would get if they had opened the tab without changing toggles.
- Given the active model has `supportsExplicitWordTimestampToggle === false`, when an auto-watch job fires, then `enable_word_timestamps: true` is sent regardless of the stored value (parity with the manual path's existing override).

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — expected: passes (no new type errors).
- `cd dashboard && npm test -- importQueueStore` — expected: new auto-job option-passing tests pass.
- `cd dashboard && npm run ui:contract:check` — expected: no UI-contract drift (no className changes in this fix).

**Manual checks:**
- With server running and a `whisper-large-v3` model loaded, set Sessions watch path, enable Diarization toggle, drop a multi-speaker WAV into the watch folder; the resulting SRT/ASS file in the output dir contains `[SPEAKER_XX]` markers.
- Repeat for Notebook watch path; the new notebook entry appears with the "Diarized" tag in the recording list.
- Toggle Multitrack on the session tab, drop a multi-track WAV; verify the multitrack split pipeline runs (per existing `Multitrack` flow, not the diarization pipeline).

## Suggested Review Order

**Bug fix entry point**

- The actual fix — `handleFilesDetected` now sources options from per-tab configs and applies the same `multitrack ? false : enableDiarization` derivation as the manual paths.
  [`importQueueStore.ts:557`](../../dashboard/src/stores/importQueueStore.ts#L557)

**State bridge — types and defaults**

- New toggle fields added to `SessionConfig`; mirrored as a new `NotebookConfig`.
  [`importQueueStore.ts:47`](../../dashboard/src/stores/importQueueStore.ts#L47)

- Default values match the UI's `useState` initial values so the AC4 cold-start case (notebook tab never mounted) still produces `enable_diarization: true`.
  [`importQueueStore.ts:427`](../../dashboard/src/stores/importQueueStore.ts#L427)

- New `updateNotebookConfig` action — parallel to existing `updateSessionConfig`.
  [`importQueueStore.ts:531`](../../dashboard/src/stores/importQueueStore.ts#L531)

**UI sync — local state → store**

- SessionImportTab pushes toggles into `sessionConfig` (extends the existing `outputDir`/`diarizedFormat` sync).
  [`SessionImportTab.tsx:162`](../../dashboard/components/views/SessionImportTab.tsx#L162)

- NotebookView pushes toggles into `notebookConfig` (new bridge).
  [`NotebookView.tsx:1421`](../../dashboard/components/views/NotebookView.tsx#L1421)

**Tests**

- New `handleFilesDetected` suite covering all I/O matrix rows (session ON/OFF/multitrack, notebook ON/OFF, defaults, server-disconnected guard).
  [`importQueueStore.test.ts:302`](../../dashboard/src/stores/importQueueStore.test.ts#L302)

- NotebookView test mock extended with `updateNotebookConfig` so the new sync `useEffect` doesn't crash on render.
  [`NotebookView.test.tsx:80`](../../dashboard/components/__tests__/NotebookView.test.tsx#L80)
