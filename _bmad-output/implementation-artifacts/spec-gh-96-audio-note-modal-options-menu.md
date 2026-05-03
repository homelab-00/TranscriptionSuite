---
title: 'GH #96 — Surface Rename / Export / Delete options inside the AudioNoteModal'
type: 'feature'
created: '2026-05-02'
status: 'done'
baseline_commit: '650898e1a9912bba7eedfa8866facd3de28b14b3'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Today the only way to Rename, Export, or Delete a recording from the Notebook is via the `NoteActionMenu` kebab on the calendar tile (`NotebookView.tsx:255-503`). Once the user opens the recording's pop-up box (`AudioNoteModal`), only date editing is available — they have to close the modal and reopen the row's kebab to take any other action. Issue #96 asks for the same options (the "..." dots) inside the pop-up box.

**Approach:** Add a `MoreHorizontal` button to `AudioNoteModal`'s header (next to the existing `X` close button) that opens a dropdown with **Rename**, **Export TXT**, **Export SRT**, **Export ASS**, and **Delete**. Reuse the existing API client methods (`updateRecordingTitle`, `getExportUrl`, `deleteRecording`) and propagate `onRecordingMutated()` so the calendar refreshes. Rename uses the same modal portal pattern already used in this file for chat-session rename.

## Boundaries & Constraints

**Always:**
- Reuse existing API methods on `apiClient`: `updateRecordingTitle(id, title)`, `getExportUrl(id, format)`, `deleteRecording(id)`. Do **not** introduce new endpoints.
- The dropdown must close on outside-click (mirror the `modelDropdownOpen` pattern at `AudioNoteModal.tsx:1303-1313`).
- The Rename dialog must reuse the centered portal modal pattern already in this file (`renameDialog` at `AudioNoteModal.tsx:1347-1388`) — render via `createPortal(..., document.body)` at `z-10000` so it stacks above the modal.
- Delete must require a confirmation via `useConfirm` (already imported), close the `AudioNoteModal`, and call `onRecordingMutated()`.
- Rename success must call `onRecordingMutated()` so the calendar tile reflects the new title; the modal can stay open with the new title shown via the `useRecording` query refetch — but it is acceptable to close it for parity with the existing delete flow.
- Export must call `apiClient.getExportUrl(id, format)`; if it returns `null` (remote not configured), surface `toast.error('Remote host not configured. Open Settings → Connection.')` — same message as `NoteActionMenu`.
- Honor the project's existing icon set (`MoreHorizontal`, `Edit2`, `Download`, `Trash2`) — already imported or trivially addable from `lucide-react`.

**Ask First:**
- Any change to `NotebookView`'s existing kebab menu (the row-level menu remains as-is — this spec is additive in `AudioNoteModal` only).
- Auto-closing the modal after a successful Rename (current flow leaves it open via `useRecording` refetch — confirm with user only if the refetch is unexpectedly stale).

**Never:**
- Don't touch the row-level `NoteActionMenu` in `NotebookView.tsx` — both menus must continue to exist and behave identically.
- Don't add a "Play Recording" item — the modal already has its own audio player UI; including it would be redundant.
- Don't rename the `chat session` `contextMenu` state or its `renameDialog` portal (still owned by the AI Assistant sidebar).
- Don't add backend changes — this is dashboard-only.
- Don't bypass `useConfirm` for Delete; never call `window.confirm` (Electron-blocked).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| User clicks "..." in modal header | Modal open, recording loaded | Dropdown opens at button anchor with 5 items: Rename, Export TXT/SRT/ASS, Delete | N/A |
| User clicks outside open dropdown | Dropdown open | Dropdown closes; no action fires | N/A |
| User clicks "Rename" | Dropdown open | Inline rename portal opens, prefilled with current title, autofocused | N/A |
| User commits Rename with new title | Title text non-empty + changed | `apiClient.updateRecordingTitle()` succeeds → `onRecordingMutated()` fires → portal closes, header reflects new title via `useRecording` | On failure: `toast.error('Failed to rename recording.')`, portal stays open |
| User commits Rename with unchanged/empty | Trimmed title is empty or same | Portal closes silently — no API call | N/A |
| User clicks "Export TXT/SRT/ASS" | `getExportUrl` returns valid URL | `window.open(url, '_blank')` triggers download; dropdown closes | If `getExportUrl` returns `null`: `toast.error('Remote host not configured. Open Settings → Connection.')` |
| User clicks "Delete" → confirms | Confirm dialog returns `true` | `apiClient.deleteRecording()` → `onRecordingMutated()` → modal closes; toast: 'Recording deleted.' | On API failure: `toast.error(message)`, modal stays open |
| User clicks "Delete" → cancels confirm | Confirm dialog returns `false` | No API call, dropdown closes | N/A |
| Modal opens with `recording === null` (still loading) | `useRecording` not resolved yet | "..." button is disabled (greyed out, no click handler) | Prevents API calls with `note.recordingId` undefined |
| Modal opens with `note.recordingId === undefined` | Note has no recordingId (rare) | "..." button hidden — there is no recording to act on | N/A |
| Sidebar (AI Assistant) is open | `isSidebarOpen === true` | "..." button still visible and functional in header | Dropdown z-index sits above sidebar overlays |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/AudioNoteModal.tsx` — primary edit site:
  - **Header row (lines ~1404–1481)**: insert `MoreHorizontal` button immediately before the existing `X` close button at line 1474; gate visibility on `note.recordingId != null`.
  - **State (near lines ~464–476)**: add `optionsMenuOpen` (`boolean`) and `recordingRenameDialog` (`{ currentTitle: string } | null`).
  - **Outside-click effect**: clone the `modelDropdownOpen` pattern at lines 1303–1313 for `optionsMenuOpen`.
  - **Handlers (near line ~1338, after `handleDateSave`)**: add `handleRecordingRenameOpen`, `handleRecordingRenameCommit`, `handleRecordingExport(format)`, `handleRecordingDelete`. Mirror error handling from `NotebookView.tsx::NoteActionMenu` (lines ~283–345).
  - **Dropdown render**: place a small absolute-positioned dropdown anchored to the new button (header is `flex` so a `relative` wrapper around the button is sufficient; no portal needed for the dropdown itself since the modal already lives inside a `z-9999` portal).
  - **Recording rename dialog portal**: add a second portal block right after the existing chat-session `renameDialog` portal (~lines 1347–1388), so it stacks above the modal. Reuse the visual styling (rounded-3xl border, glass surface).
- `dashboard/src/api/client.ts` — no edits; methods already exist (`updateRecordingTitle`:529, `getExportUrl`:590, `deleteRecording`:524).
- `dashboard/components/views/NotebookView.tsx` — no edits. The existing `NoteActionMenu` row-level kebab continues to work; behavior is unchanged.
- `dashboard/ui-contract/transcription-suite-ui.contract.yaml` — `AudioNoteModal` block at lines 1371–1401: the new dropdown adds CSS classes; after edits run the full contract pipeline (`extract` → `build` → `validate --update-baseline` → `check`).

## Tasks

1. **State and handlers** — Add `optionsMenuOpen` state, `recordingRenameDialog` state, outside-click effect, and the four handler callbacks (`handleRecordingRenameOpen`, `handleRecordingRenameCommit`, `handleRecordingExport`, `handleRecordingDelete`) in `AudioNoteModal.tsx`. Use `useCallback` consistently with neighboring handlers.
2. **Header button + dropdown** — Insert `MoreHorizontal` button before the `X` close button. Render the dropdown as a `div` absolute-positioned under the button when `optionsMenuOpen === true`. Items: Rename (Edit2), Export TXT/SRT/ASS (Download), divider, Delete (Trash2, red). Use the same Tailwind tokens as the existing chat-session contextMenu (`bg-slate-900`, `border-slate-900`, `rounded-xl`, `text-sm` items).
3. **Recording rename portal** — Add a second `createPortal(..., document.body)` block alongside the existing chat-session `renameDialog` portal. Title field bound to `renameValue` reused, but commit handler is the new `handleRecordingRenameCommit`. Header text: "Rename Recording".
4. **Wire success callbacks** — Every mutating action (rename / delete) must call `onRecordingMutated?.()` so the calendar tile updates. Delete also calls `onClose()`.
5. **Manual smoke test** — Open the dashboard dev server (`npm run dev` from `dashboard/`), open the Notebook tab, click an existing note, exercise each dropdown action.
6. **UI contract update** — Run `npm run ui:contract:extract`, `npm run ui:contract:build`, `node scripts/ui-contract/validate-contract.mjs --update-baseline`, then `npm run ui:contract:check` from `dashboard/`.
7. **Type-check** — Run `npm run typecheck` from `dashboard/`.
8. **Tests** — No existing AudioNoteModal test file; do not introduce a new test in this PR (out of scope per Bill's deferred-work triage rule). Behavior is exercised manually + via UI contract.

## Acceptance Criteria

- **AC1**: When the AudioNoteModal is open with a loaded recording, a "..." (`MoreHorizontal`) button is visible in the header to the left of the close button.
- **AC2**: **Given** the dropdown is closed **When** the user clicks the "..." button **Then** a dropdown menu appears showing "Rename", "Export TXT", "Export SRT", "Export ASS", and "Delete" (Delete styled in red, separated by a divider).
- **AC3**: **Given** the dropdown is open **When** the user clicks anywhere outside the dropdown **Then** the dropdown closes without firing any action.
- **AC4**: **Given** the user clicks "Rename" **When** the rename portal opens **Then** the input is autofocused, prefilled with the current recording title, and committing a non-empty changed title calls `apiClient.updateRecordingTitle(recordingId, newTitle)`, then fires `onRecordingMutated()`.
- **AC5**: **Given** the user commits the Rename portal with an unchanged or empty title **When** the commit fires **Then** no API request is made and the portal closes silently.
- **AC6**: **Given** the user clicks any of the three Export items **When** `getExportUrl` returns a valid URL **Then** `window.open(url, '_blank')` is called and the dropdown closes; if it returns `null`, a `toast.error('Remote host not configured. Open Settings → Connection.')` fires instead.
- **AC7**: **Given** the user clicks "Delete" **When** the confirm dialog returns `true` **Then** `apiClient.deleteRecording(recordingId)` runs, `onRecordingMutated()` fires, the AudioNoteModal closes, and a success toast appears. If the confirm returns `false`, no API call is made.
- **AC8**: The existing row-level `NoteActionMenu` in `NotebookView.tsx` is unchanged — opening it via right-click or hover-button on a calendar tile still shows Play / Rename / Export / Delete identically.
- **AC9**: `npm run typecheck` from `dashboard/` passes; the UI contract baseline is regenerated and `npm run ui:contract:check` passes.

## Risks & Mitigations

- **Risk**: Stacking-context conflicts — the dropdown could render below the modal's audio visualizer or AI sidebar. **Mitigation**: anchor the dropdown inside the same z-9999 portal as the rest of the modal; use `z-50` relative to the header.
- **Risk**: Double-rename if the user submits Enter twice quickly. **Mitigation**: add a `recordingRenameLoading` boolean to disable the commit button while the request is in flight (mirror `renameLoading` in `NoteActionMenu`).
- **Risk**: Delete confirmation modal stacks under the AudioNoteModal. **Mitigation**: `useConfirm()` already returns a `confirmDialog` that the caller renders via `createPortal(confirmDialog, document.body)` — the existing portal block at line 1346 already does this; reuse it.
- **Risk**: UI contract baseline drift if any unrelated CSS class is touched. **Mitigation**: run the four-step contract pipeline exactly as documented in `CLAUDE.md` to keep the diff scoped.

## Out of Scope

- Changes to row-level `NoteActionMenu` in `NotebookView.tsx`.
- Adding a "Play Recording" item to the modal dropdown (modal has its own player).
- Backend changes — all required endpoints already exist.
- Adding automated unit tests for `AudioNoteModal` — there are none today and adding the first one is its own scoped initiative.

### Review Findings

Three-layer review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) run on 2026-05-02. 5 patches applied, 9 deferred to `deferred-work.md`, 9 dismissed as noise/false positives.

- [x] [Review][Patch] Add `'noopener,noreferrer'` to `window.open` for export downloads [AudioNoteModal.tsx:handleRecordingExport]
- [x] [Review][Patch] Guard `handleRecordingRenameCommit` against double-Enter while a request is in flight [AudioNoteModal.tsx:handleRecordingRenameCommit]
- [x] [Review][Patch] Disable the options-menu button while `recordingLoading === true` (matches AC1 / edge-case matrix) [AudioNoteModal.tsx:options-menu trigger]
- [x] [Review][Patch] Reset `optionsMenuOpen` / `recordingRenameDialog` / `recordingRenameValue` / `recordingRenameLoading` whenever `isOpen` flips false, to avoid state leaking across modal sessions [AudioNoteModal.tsx:state-reset effect]
- [x] [Review][Patch] Replace `bg-black/80 backdrop-blur-xl` dropdown surface with `bg-slate-900 border-slate-900` to match the spec's "same tokens as the existing chat-session contextMenu" requirement (also drops blur budget back from 8 → 7) [AudioNoteModal.tsx:options-menu dropdown]
- [x] [Review][Defer] Stale-closure: delete-confirm captures `note?.recordingId` at menu-open; if parent swaps the active note mid-confirm, the wrong recording is deleted — pre-existing pattern across the file (date editor, summary, etc.).
- [x] [Review][Defer] Concurrent rename + modal close can call `setRecordingRenameLoading` on an unmounted component — no `mounted-ref` pattern is used anywhere in this file; React 18 silently drops these.
- [x] [Review][Defer] No `maxLength` / newline-strip on the rename input — same pattern as the chat-session rename dialog and `NoteActionMenu`; backend should enforce.
- [x] [Review][Defer] `window.open` returns `null` when a popup blocker activates — silent no-op; `NoteActionMenu` has the same gap.
- [x] [Review][Defer] Export does not gate on `recording.has_transcription`; user can request export of a still-processing recording and get a server 404 — same pattern as `NoteActionMenu`.
- [x] [Review][Defer] Title snapshot taken at menu-open; if `recording` resolves a moment later, the rename input still shows the stale `note.title` calendar-card label — same fallback pattern as `handleDateEditOpen`.
- [x] [Review][Defer] Dropdown lacks `aria-haspopup` / `aria-expanded` / `role="menu"` and no Escape-to-close — consistent with `modelDropdownOpen` and the chat-session contextMenu in this file. Project-wide a11y pass not in scope.
- [x] [Review][Defer] No focus trap on the dropdown — same a11y category as above.
- [x] [Review][Defer] `apiClient.deleteRecording` response `status` ignored — server has no soft-delete today; would require API change to surface.

#### Dismissed (noise / false positives)

- `z-10000` flagged as "non-standard Tailwind" — verified valid: 10+ existing usages in this codebase, supported by Tailwind v4's arbitrary numeric utilities, and the contract's `z_index_classes` allowlist explicitly includes it.
- `apiClient.getExportUrl` flagged for "could return ''" — return type is `string | null`, never `''` or `undefined`.
- `note.recordingId === 0` falsy-but-non-null inconsistency — SQLite primary keys start at 1; impossible in practice.
- Various theoretical races (outside-click handler ordering, stacking-context conflicts between `z-50` dropdown and `z-10000` confirm) — actually handled by `setTimeout(..., 0)` registration and the existing portal hierarchy.
- Empty/whitespace silent close — matches the existing chat-session and row-level rename pattern; intentional UX, not a defect.
- Two simultaneous outside-click listeners (`modelDropdownOpen` + `optionsMenuOpen`) — `e.stopPropagation()` on each panel prevents cross-fire; benign.
- Toast double-firing on delete — verified parent does not fire its own delete toast.
- Rename portal z-stacking — `z-10000` portal-to-body sits above the modal's `z-9999` portal, as designed.
- Silent no-op when `note.recordingId` falsy in handler guards — defense-in-depth on a code path the visibility gate already prevents.
