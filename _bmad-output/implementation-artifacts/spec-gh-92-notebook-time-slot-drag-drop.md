---
title: 'GH #92 — Drag & drop audio files directly onto a Notebook time slot'
type: 'feature'
created: '2026-05-02'
status: 'done'
baseline_commit: 'f189ae48d08005190c95ffc283c1f8c7a6d4d847'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Today users must click a Notebook time-slot's "+" button, wait for `AddNoteModal` to open, then drag files into the modal. Issue #92 asks to drop files **directly onto a time slot** in the timeline, collapsing the two-step flow into one.

**Approach:** Add per-hour drag/drop handlers to the morning/afternoon timeline slots in `NotebookView`. On a valid audio drop the existing `AddNoteModal` opens with `initialTime`/`initialDate`/`initialFiles` already populated, so the user only confirms options and clicks "Create Note".

## Boundaries & Constraints

**Always:**
- Reuse the existing `AddNoteModal` import path (`useImportQueueStore.addFiles('notebook-normal', …)`) — do **not** introduce a parallel upload path.
- Honor the persisted Source Language / translation picker exactly as `AddNoteModal` already does (gh-102 followup #2 hydration logic must not be bypassed).
- Filter dropped files to the same audio extensions the existing browse/file input accepts: `.mp3,.wav,.m4a,.flac,.ogg,.webm,.opus`.
- Show a clear hover state on the targeted hour row (cyan dashed border + tinted bg) consistent with other drop zones in the codebase.
- `e.preventDefault()` + `e.stopPropagation()` on the per-slot drop so the event never bubbles to the broader page or the calendar grid.
- The Add-Note "+" button keeps working (click flow unchanged).

**Ask First:**
- Anything that changes the upload contract, the import-queue payload shape, or the `notebook-normal` job kind.
- Allowing non-audio file drops (current scope: audio only).

**Never:**
- Don't auto-submit on drop. The user must still review/confirm in the modal so they can adjust title, diarization, timestamps, etc.
- Don't change `ImportTab`'s drop zone, `useNotebookWatcher`, or the watch-folder logic.
- Don't add backend changes — this is dashboard-only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Single audio file dropped on hour 14 of selected day | `.mp3` dragged onto 14:00 row | Modal opens with `initialTime=14`, `initialDate=<selectedDay>`, `initialFiles=[file]`, title pre-filled from filename | N/A |
| Multiple audio files dropped on a slot | 3 audio files on 09:00 row | Modal opens with all 3 in `initialFiles`; selectedFiles list shows 3 entries | N/A |
| Mixed audio + non-audio dropped | 2 `.mp3` + 1 `.txt` on 11:00 | Modal opens with the 2 audio files only | Toast warns "1 non-audio file ignored" |
| All non-audio dropped | `.txt` only on 11:00 | Modal does **not** open | Toast: "No audio files in drop. Supports MP3, WAV, M4A, FLAC, OGG, WebM, Opus." |
| Drop on hour row with existing events | Audio dropped on a row that already has notes | Same behavior as empty row — modal opens for that hour | N/A |
| Drag without dropping (cancel) | DragLeave or Esc | Hover state clears; no modal opens | N/A |
| Drop while modal already open | User drops while another modal session is in flight | New drop replaces preloaded files (same as opening fresh) | N/A — last drop wins |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/NotebookView.tsx` — `TimeSection` (per-hour rows, lines ~606–877) and `CalendarTab` (wires `onAddNote` to `NotebookView` parent, lines ~903–1180); also the parent `NotebookView` modal state (lines ~67–196). Add per-hour drop handlers + new `onDropFilesAtSlot(hour, dateKey, files)` callback chain.
- `dashboard/components/views/AddNoteModal.tsx` — Add `initialFiles?: File[]` prop; seed `selectedFiles` from it on `isOpen` transition; reset on close.
- `dashboard/components/__tests__/NotebookView.test.tsx` — Existing render test; extend with a per-hour drop scenario.
- `dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx` — Pattern reference for testing `AddNoteModal`.
- `dashboard/src/stores/importQueueStore.ts` — No changes; existing `addFiles(files, 'notebook-normal', opts)` handles the rest.

## Tasks & Acceptance

**Execution:**
- [ ] `dashboard/components/views/AddNoteModal.tsx` -- Add `initialFiles?: File[]` prop; on `isOpen → true`, if `initialFiles?.length` seed `selectedFiles` and default the title from the first file's name; clear on close. Keep existing time-based default title as fallback when no files preloaded.
- [ ] `dashboard/components/views/NotebookView.tsx` -- In `TimeSection`, add per-hour `onDragEnter/Over/Leave/Drop` handlers and a `dragOverHour: number | null` state. Highlight the target row with a cyan tint while dragging. On drop, filter to audio MIME/extension and call new prop `onDropFilesAtSlot(hour, audioFiles)`. Wire `CalendarTab` to bridge `(hour) => onDropFilesAtSlot(hour, addNoteDateKey, files)`. In `NotebookView`, add `selectedInitialFiles` state; `handleDropFilesAtSlot` sets time/date/files and opens the modal.
- [ ] `dashboard/components/views/NotebookView.tsx` -- Add a small helper `filterAudioFiles(files: FileList | File[]): { audio: File[]; rejectedCount: number }` near the top of the file (or a `utils/notebookDrop.ts` module — agent's call based on cleanliness). Reuse the same allow-list as `AddNoteModal`'s `<input accept>`.
- [ ] `dashboard/components/__tests__/NotebookView.test.tsx` -- Add a test that simulates a `drop` event on an hour slot and asserts the modal opens with the file preloaded (or that `addFiles` is queued via the store after clicking "Create Note"). Mock `useImportQueueStore.getState().addFiles` and `useCalendar`.
- [ ] `dashboard/components/__tests__/AddNoteModal.canary-language.test.tsx` (or new sibling test) -- Add coverage for the new `initialFiles` prop: open modal with one preloaded file, assert it appears in the selected list and the title defaults to the filename.

**Acceptance Criteria:**
- Given the user is on the Notebook Calendar tab with a day selected, when they drop one or more audio files onto the 14:00 row, then `AddNoteModal` opens with the time set to "14:00 - 15:00", the date set to the selected day, and the files appearing in the selected files list.
- Given the user drops a mix of audio and non-audio files, when the drop completes, then only the audio files appear in the modal and a toast informs them how many non-audio were ignored.
- Given the user drops only non-audio files, when the drop completes, then the modal does **not** open and a toast explains the supported formats.
- Given the user drags but never drops (cancels), when they leave the row, then the highlight clears and no modal opens.
- Given the existing "+" Add-Note button, when clicked, then the modal still opens with no preloaded files (backwards-compatible).
- `npm run typecheck` passes; `npm run ui:contract:check` passes after the contract baseline is updated; `npm test` passes for `dashboard/`.

## Design Notes

The cleanest seam is to keep the entire upload pipeline (queue, language hydration, translation gating, file_created_at envelope) inside `AddNoteModal` and treat the new feature as a **shortcut into the same modal**. Any duplication of that envelope risks divergence from the gh-102 followup #2 fixes that converged all import surfaces on a single picker.

Visual idiom: copy the existing pattern from the import-tab drop zone (`isDragOver ? 'border-accent-cyan bg-accent-cyan/10 scale-[1.02]'`) but scale it down for an inline row — a soft cyan border + subtle bg tint is enough; do not scale the row.

Bubble suppression: the per-hour drop must `stopPropagation` — the calendar grid currently has no drop handler, but importing-tab's drop zone is in a different tab so no conflict. Still, defensive `stopPropagation` future-proofs against added parents.

`AddNoteModal` already resets `selectedFiles` to `[]` on the `isOpen → true` effect (lines 262–304). The new `initialFiles` seeding must run **after** that reset (or replace it) so files survive the open transition. Simplest implementation: when `initialTime` is undefined-or-defined and `initialFiles?.length`, set `selectedFiles = initialFiles` instead of `[]` and prefer the file-derived title over the time-derived one.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: 0 errors
- `cd dashboard && npm test` -- expected: all suites pass
- `cd dashboard && npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` -- expected: contract check passes after baseline regenerated

**Manual checks:**
- Run the dev server, open the Audio Notebook → Calendar tab, select a day, drag any `.mp3` from the desktop onto the 10:00 row of the Morning section. The modal opens with title pre-filled, the file in the list, and the time band reads "10:00 - 11:00". Click "Create Note" and verify the import-queue toast appears.
- Repeat with a non-audio file (e.g., a `.txt`) — verify no modal opens and a toast explains the supported formats.
- Repeat with the existing "+" button — verify modal still opens empty.

## Suggested Review Order

**Entry point — drop handler design**

- Per-hour drop handlers in TimeSection: gates on `'Files'` type, sets `dropEffect='copy'`, and forwards `FileList` up.
  [`NotebookView.tsx:812`](../../dashboard/components/views/NotebookView.tsx#L812)

**Audio filtering and toast surface**

- Allow-list constant kept in lockstep with `AddNoteModal`'s `<input accept>`.
  [`NotebookView.tsx:66`](../../dashboard/components/views/NotebookView.tsx#L66)

- `CalendarTab::handleDropAtHour` filters non-audio, toasts warnings, and forwards to parent.
  [`NotebookView.tsx:1120`](../../dashboard/components/views/NotebookView.tsx#L1120)

**Parent state plumbing**

- `handleDropFilesAtSlot` sets time/date/files and opens the modal — symmetric counterpart to `handleAddNote`.
  [`NotebookView.tsx:115`](../../dashboard/components/views/NotebookView.tsx#L115)

- `handleAddModalClose` clears `selectedInitialFiles` so the next "+" click never sees stale drop files.
  [`NotebookView.tsx:124`](../../dashboard/components/views/NotebookView.tsx#L124)

- TimeSection drop wiring: Morning + Afternoon both bridge through `handleDropAtHour`.
  [`NotebookView.tsx:1264`](../../dashboard/components/views/NotebookView.tsx#L1264)

**Modal seeding (the "open with files preloaded" half)**

- `initialFiles` prop, intentionally optional so the "+" click flow stays empty.
  [`AddNoteModal.tsx:24`](../../dashboard/components/views/AddNoteModal.tsx#L24)

- Open-effect seeds `selectedFiles` and prefers file-stem title on the `isOpen → true` transition.
  [`AddNoteModal.tsx:273`](../../dashboard/components/views/AddNoteModal.tsx#L273)

- Deps array is `[isOpen]` only — the eslint-disable explains why omitting `initialFiles` is intentional (review patch from blind/edge hunters).
  [`AddNoteModal.tsx:314`](../../dashboard/components/views/AddNoteModal.tsx#L314)

**Test coverage**

- Notebook drop scenarios: single audio, mixed, all-non-audio.
  [`NotebookView.test.tsx:191`](../../dashboard/components/__tests__/NotebookView.test.tsx#L191)

- Modal seeding regression + click-flow fallback for empty case.
  [`AddNoteModal.initialFiles.test.tsx:75`](../../dashboard/components/__tests__/AddNoteModal.initialFiles.test.tsx#L75)

