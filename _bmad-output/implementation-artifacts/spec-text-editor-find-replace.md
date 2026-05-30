---
title: 'In-place transcript editing with find/replace'
type: 'feature'
created: '2026-05-30'
status: 'done'
baseline_commit: '710ea59f17546d82973491677b7c8f0d26244077'
context:
  - '{project-root}/docs/superpowers/specs/2026-05-30-text-editor-find-replace-design.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Three transcript surfaces (Session main-result, Live-mode box, Audio-Note transcript) are read-only with no way to correct STT errors or search within long text.

**Approach:** Build ONE reusable plain-`<textarea>` editor + find/replace core (pure engine, hook, component), then integrate it into all three surfaces. Session-result and Live edits are client-only (drive Copy/Download); Audio-Note edits persist non-destructively to a NEW additive `transcript_corrected` DB column (original segments never touched, revertable). Locked decisions D1–D6 in the design doc are authoritative.

## Boundaries & Constraints

**Always:**
- DATA-LOSS INVARIANT: original `segments`/word-timestamps are NEVER overwritten. `transcript_corrected` is additive; Revert sets it NULL and restores the rich view.
- New DB column via forward-only Alembic migration mirroring the current HEAD (`016`) exactly: `upgrade()` uses `_revision_metadata()` + `op.get_bind()` + `ALTER TABLE recordings ADD COLUMN transcript_corrected TEXT`; `downgrade()` RAISES the forward-only `RuntimeError` (do NOT hand-write a real downgrade).
- Audio-Note autosave mirrors the Summary chain: debounced 2s, silent-fail-and-retry-on-next-keystroke, update local recording state on success.
- After any CSS-class change, run the UI-contract update sequence then `npm run ui:contract:check` from `dashboard/`.
- New files build TEST-FIRST (Vitest co-location for FE; pytest direct-call pattern for routes). Target ≥80% on new code.
- `uv` only (never `pip`); backend tests use the **build venv** (`../../build/.venv/bin/pytest`).

**Ask First:**
- Adding any new npm dependency (design locks plain `<textarea>`, no CodeMirror/regex).
- Changing the persistence model (e.g. persisting Session/Live edits, or making the column non-additive).
- Any change touching the original `segments` storage or word-timestamp data.

**Never:**
- No regex / whole-word / highlight-all-overlay / rich-text in MVP (see design §13).
- No speaker-label prefixes in flattened Audio-Note text.
- No new dependencies.

## I/O & Edge-Case Matrix

Applies to `findReplaceEngine` (literal, non-overlapping, left-to-right) and `flattenSegmentsToText`.

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Empty/whitespace query | text="abc", query="" or "   " | `computeMatches` → `[]`; replaces are no-ops | N/A |
| Case-insensitive find | "Foo foo", "foo", `{caseSensitive:false}` | 2 matches; replacement preserves surrounding original casing | N/A |
| Case-sensitive find | "Foo foo", "foo", `{caseSensitive:true}` | 1 match (offset of lowercase only) | N/A |
| Overlapping substring | "aaaa", "aa" | 2 non-overlapping matches [0,2],[2,4] | N/A |
| replaceAll count | "a a a", "a"→"b" | `{text:"b b b", count:3}` | N/A |
| replaceCurrent | text + one Match | returns new string, original unchanged (immutable) | N/A |
| Flatten diarized/word-ts segments | segments with speaker/words | newline-joined per-segment text, trimmed, blank segments dropped, NO speaker prefix | N/A |
| Flatten empty/blank | `[]` or all-blank | `""` | N/A |

</frozen-after-approval>

## Code Map

Anchors below were re-verified against live code (line numbers current as of planning).

- `dashboard/src/services/findReplaceEngine.ts` (+`.test.ts`) -- **NEW** pure match/replace
- `dashboard/src/services/transcriptFlatten.ts` (+`.test.ts`) -- **NEW** `flattenSegmentsToText(segments: TranscriptionSegment[])`; segment type at `dashboard/src/api/types.ts:88` (`{text,start,end,speaker?,words?}`)
- `dashboard/src/hooks/useFindReplace.ts` (+`.test.ts`) -- **NEW** state + drives `textarea.setSelectionRange`
- `dashboard/components/editor/FindReplaceTextEditor.tsx` (+`FindReplaceToolbar.tsx`, +`.test.tsx`) -- **NEW** reusable editor; dir does not exist yet
- `dashboard/components/views/SessionView.tsx` -- result render `:1675-1676` (className `:1675`), copy `:832`, download `:838`, live branches `:2136`+`:2313` (ref `liveTranscriptRef`, identical class), live copy `:2122-2133`/`:2298-2309`, `isRecording` `:719`, `isLive` `:332`; `live` arrives as a **prop** (`LiveModeState`), `transcription` from `useTranscription()` `:163`
- `dashboard/src/hooks/useLiveMode.ts` -- `getText()` `:303`, `clearHistory()` `:297`, `LiveStatus` union `:13` (no `'recording'` value), `LiveSentence{text,timestamp}` `:21`
- `dashboard/src/hooks/useTranscription.ts` -- `TranscriptionResult` `:22` (`text`, `words`, `language?`, `duration?`); `result` state `:66`
- `dashboard/components/views/AudioNoteModal.tsx` -- Transcript section `:2173-2278` (segments.map `:2182`, word-seek `:2224-2246`, sticky header `:2174-2179`, plain fallback `:2267`); `hasSegmentDetail` `:630`, `plainTranscriptText` `:632`; Summary pattern to MIRROR: state `:460-466` (`summaryText`,`isSummaryEditing`,`summaryEditText`,`isSummarySaving`,`summaryEditRef`,`summarySaveTimerRef`), `handleSaveSummary` `:864`, `handleExitSummaryEdit` `:880`, `handleSummaryEditChange` `:894`, toggle render `:2136-2154`; `recording`+`recordingId` from `useRecording(note.recordingId)` `:551`, `recordingId` `:565`
- `dashboard/src/api/client.ts` -- `updateRecordingSummary` `:612`, private `patch<T>` `:243`, prefix `/api/notebook/recordings`
- `dashboard/src/api/types.ts` -- `Recording` interface `:143-165`, `summary` `:153`
- `server/backend/api/routes/notebook.py` -- `SummaryUpdate` model `:134`, repo imports `:41-55`, `update_summary_put` `:360`, `update_summary_patch` `:384` (returns `{"status":"updated","id",...}`)
- `server/backend/database/database.py` -- recordings column set `:147-161`, `Recording.__init__` `:270-282`, `to_dict` `:284-298`, `update_recording_summary` `:372-386`
- `server/backend/database/__init__.py` -- `__all__` export list (`update_recording_summary` `:48`)
- `server/backend/database/migrations/versions/` -- HEAD = `016_add_webhook_deliveries.py` (`revision="016"`); mirror its forward-only structure for new `017`

## Tasks & Acceptance

**Execution (build in phase order P1→P4; each phase independently shippable):**

P1 — Shared core (TEST-FIRST):
- [x] `dashboard/src/services/findReplaceEngine.ts` + test -- implement `computeMatches`/`replaceCurrent`/`replaceAll` per I/O matrix; immutable, literal substring, non-overlapping
- [x] `dashboard/src/services/transcriptFlatten.ts` + test -- `flattenSegmentsToText` per matrix; reuse `TranscriptionSegment` type
- [x] `dashboard/src/hooks/useFindReplace.ts` + test -- wrap engine; recompute + clamp `currentIndex` on value/query/caseSensitive change; wrap-around next/prev; drive selection + scroll-into-view
- [x] `dashboard/components/editor/FindReplaceToolbar.tsx` -- floating single search-icon → compact find bar (input, `n/total`, ↑/↓, `Aa`, ✕); chevron expands replace row (input, Replace, Replace-all)
- [x] `dashboard/components/editor/FindReplaceTextEditor.tsx` + test -- props per design §5.3; `relative` container; `readOnly` renders display-only block; control visible on focus or (`enableFindReplace && !readOnly`); shortcuts scoped to container with `preventDefault` (Ctrl/Cmd+F find, Ctrl/Cmd+H replace, Esc close, Enter/Shift+Enter next/prev in find input, Enter in replace input = replace current); auto-grow height in edit mode

P2 — Session main-result (client-only):
- [x] `dashboard/components/views/SessionView.tsx` -- add `editedResultText` state seeded from `transcription.result?.text`, reset via `useEffect` on text change; replace text node `:1676` with `FindReplaceTextEditor` (preserve `selectable-text custom-scrollbar … bg-black/20` look via `className`, pass `textClassName="font-mono text-sm leading-relaxed text-slate-300"`, expand `max-h-32` when editing); keep footer + copy/download row; point `handleCopyTranscription`/`handleDownloadTranscription` at `editedResultText` (fallback `result.text`)

P3 — Live mode (client-only, only when stopped):
- [x] `dashboard/components/views/SessionView.tsx` -- extract duplicated live body (`:2136` & `:2313`) into a shared `LiveTranscriptView` sub-component so both branches get the editor without duplication; while `isLive` (active: not `idle`/`error`) keep streaming `live.sentences`+`live.partial` read-only; when stopped (`!isLive`) AND content exists render `FindReplaceTextEditor` seeded from `editedLiveText` (init from `live.getText()`), reset seed on new live session; live Copy reads `editedLiveText` when present

P4 — Audio-Note (persisted, non-destructive) — FE + BE:
- [x] `server/backend/database/migrations/versions/017_add_recording_transcript_corrected.py` -- **NEW**; copy HEAD `016` structure; `revision="017"`, `down_revision="016"`; `upgrade()` adds `transcript_corrected TEXT`; `downgrade()` raises forward-only `RuntimeError`
- [x] `server/backend/database/database.py` -- add `"transcript_corrected"` to column set; `self.transcript_corrected = data.get("transcript_corrected")` in `__init__`; emit in `to_dict`; add `update_recording_corrected_transcript(recording_id: int, transcript: str | None) -> bool` mirroring `update_recording_summary` (`UPDATE recordings SET transcript_corrected = ? WHERE id = ?`, store `None` when falsy)
- [x] `server/backend/database/__init__.py` -- add `update_recording_corrected_transcript` to `__all__`
- [x] `server/backend/api/routes/notebook.py` -- add `TranscriptUpdate{transcript: str | None = None}` model (mirror `SummaryUpdate`); import new repo fn; add `PATCH /recordings/{recording_id}/transcript` mirroring `update_summary_patch`, returning `{"status":"updated","id":recording_id,"transcript_corrected": body.transcript or None}`, raise 500 on failure
- [x] `dashboard/src/api/types.ts` -- add `transcript_corrected: string | null` to `Recording`
- [x] `dashboard/src/api/client.ts` -- add `updateRecordingCorrectedTranscript(id, transcript?)` mirroring `updateRecordingSummary` → `patch('/api/notebook/recordings/${id}/transcript', { transcript })`
- [x] `dashboard/components/views/AudioNoteModal.tsx` -- add transcript-edit state (`transcriptDraft`, `isTranscriptEditing`, `isTranscriptSaving`, timer ref) + handlers mirroring Summary (`handleSaveCorrectedTranscript`, `handleTranscriptEditChange` debounced 2s, `handleExitTranscriptEdit`, `handleRevertTranscript`); `correctedTranscript = recording?.transcript_corrected`; add Edit pencil to sticky header `:2176` + "Edited · Revert" affordance when `hasCorrected`; read-mode: `hasCorrected`→flat selectable block, else existing rich `segments.map`; edit-mode: `FindReplaceTextEditor autoFocus` seeded from `correctedTranscript ?? flattenSegmentsToText(segments)`
- [x] `server/backend/tests/` -- **NEW** pytest: repo `update_recording_corrected_transcript` set+clear; route via direct-call pattern; `to_dict` includes field

**Acceptance Criteria:**
- Given a completed Session transcription, when I click into the result box and edit text, then Copy and Download reflect my edits; starting a new transcription resets the box.
- Given live capture is active, when I try to edit the live box, then it is read-only; after I stop, the box becomes editable with find/replace in BOTH layout branches and Copy reflects edits.
- Given an Audio-Note, when I click the Edit pencil, edit, and wait 2s, then `transcript_corrected` is autosaved; reopening the note shows corrected text; clicking Revert restores the rich segment view and the DB column is NULL.
- Given any corrected Audio-Note, when I inspect the DB, then original `segments`/word-timestamps are intact throughout (additive column only).
- Given the editor is focused, when I press Ctrl+F/Ctrl+H, then the find/replace control opens and Electron's native find does not hijack; Esc closes and returns focus to the textarea.

## Spec Change Log

## Design Notes

**Three corrections to the literal design doc (verified against live code):**
1. Pydantic model is `SummaryUpdate` (not `UpdateSummaryBody`); existing PATCH returns `"status":"updated"`. New model `TranscriptUpdate`; mirror the `"updated"` shape, not the doc's `"ok"`.
2. Migrations are **forward-only**: `downgrade()` raises `RuntimeError("forward-only migration — see NFR22; restore from backup if a roll-back is required.")`. Mirror HEAD `016` (with `_revision_metadata()` + `conn = op.get_bind(); conn.execute(text(...))`), NOT a hand-written reversible downgrade.
3. `LiveStatus` has NO `'recording'` value (`idle|connecting|starting|listening|processing|error`). Implement D3 as editable only when stopped: `const liveEditable = !isLive && hasContent` where `isLive = live.status !== 'idle' && live.status !== 'error'` (existing `:332`).

**D6 caveat (accepted for MVP):** current match shows in the browser's inactive-selection color while focus is in the find input — highlight-all overlay is out of scope (design §13).

## Verification

**Commands:**
- `cd dashboard && npx vitest run src/services/findReplaceEngine.test.ts src/services/transcriptFlatten.test.ts src/hooks/useFindReplace.test.ts components/editor/FindReplaceTextEditor.test.tsx` -- expected: all green
- `cd dashboard && npm run typecheck` -- expected: no errors
- `cd dashboard && npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` -- expected: contract check passes (new editor classes added to baseline)
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short -k "transcript_corrected or notebook"` -- expected: new repo+route tests green
- `cd server/backend && ../../build/.venv/bin/alembic upgrade head` (or app startup) -- expected: migration `017` applies, `transcript_corrected` column present

**Manual checks:**
- Session result + Live (after stop) + Audio-Note all show the floating search icon and support find/replace; Audio-Note Revert restores the word-clickable rich view; original audio/segments untouched.

## Suggested Review Order

**Shared core — start here (defines the whole feature)**

- Pure literal match/replace engine — the semantics everything else builds on.
  [`findReplaceEngine.ts:30`](../../dashboard/src/services/findReplaceEngine.ts#L30)

- Replace-then-advance: anchors past the inserted text so a superstring replacement still makes progress (review finding E2).
  [`useFindReplace.ts:147`](../../dashboard/src/hooks/useFindReplace.ts#L147)

- Selection sync bails when the textarea is focused — live highlight without yanking the typist's caret.
  [`useFindReplace.ts:113`](../../dashboard/src/hooks/useFindReplace.ts#L113)

- Reusable editor; container `onKeyDown` intercepts Ctrl/Cmd+F/H so Electron's native find can't hijack.
  [`FindReplaceTextEditor.tsx:74`](../../dashboard/components/editor/FindReplaceTextEditor.tsx#L74)

**Audio-Note persistence — the only durable surface (data-loss invariant)**

- Edit entry stores a seed ref; a correction persists only when the draft diverges from it (review finding E1 — no-op edits don't degrade the rich view).
  [`AudioNoteModal.tsx:955`](../../dashboard/components/views/AudioNoteModal.tsx#L955)

- Debounced 2s autosave + revert; blank → NULL; original segments never touched.
  [`AudioNoteModal.tsx:938`](../../dashboard/components/views/AudioNoteModal.tsx#L938)

- Three-way render: edit ↔ corrected-flat ↔ original rich segments.
  [`AudioNoteModal.tsx:2278`](../../dashboard/components/views/AudioNoteModal.tsx#L2278)

**Backend — additive, non-destructive schema + route**

- Forward-only migration adds the nullable `transcript_corrected` column (mirrors head 016).
  [`017_add_recording_transcript_corrected.py:44`](../../server/backend/database/migrations/versions/017_add_recording_transcript_corrected.py#L44)

- Repo update: `UPDATE ... SET transcript_corrected` only; falsy → NULL (revert).
  [`database.py:392`](../../server/backend/database/database.py#L392)

- PATCH route mirrors the summary chain; normalizes whitespace-only → NULL at the boundary (review finding E5).
  [`notebook.py:417`](../../server/backend/api/routes/notebook.py#L417)

**Session + Live integrations (client-only — no persistence per D2)**

- Session result state seeded from the result, reset on each new transcription.
  [`SessionView.tsx:172`](../../dashboard/components/views/SessionView.tsx#L172)

- Live editable only when stopped with content — the D3 gate (note: `LiveStatus` has no `'recording'` value).
  [`LiveTranscriptView.tsx:53`](../../dashboard/components/views/LiveTranscriptView.tsx#L53)

- Dirty-ref seeding: editable text reseeds from `getText()` until the user types, resets on a new session.
  [`SessionView.tsx:362`](../../dashboard/components/views/SessionView.tsx#L362)

**Supporting (flatten, API binding, tests)**

- Segments → editable plain text (no speaker prefixes; blanks dropped).
  [`transcriptFlatten.ts:15`](../../dashboard/src/services/transcriptFlatten.ts#L15)

- API client method + `Recording` type field.
  [`client.ts:624`](../../dashboard/src/api/client.ts#L624) · [`types.ts:157`](../../dashboard/src/api/types.ts#L157)

- Backend repo + route tests (set/clear/blank/404/500, `to_dict`, migration head).
  [`test_transcript_corrected.py:1`](../../server/backend/tests/test_transcript_corrected.py#L1)
