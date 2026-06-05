# Tech Spec — In-place Transcript Editing with Find/Replace

| | |
|---|---|
| **Status** | Approved design — ready for implementation |
| **Date** | 2026-05-30 |
| **Branch** | `text-editor-modal` |
| **Handoff target** | BMAD Quick Dev (`bmad-quick-dev`) |
| **Author** | Brainstormed design (locked decisions below — do not re-litigate) |
| **Critical invariant** | AVOID DATA LOSS AT ALL COSTS — original transcript/segments are NEVER overwritten (see §10) |

---

## 1. Goal & Scope

Make three currently read-only transcript surfaces **editable**, each with a **find** and **find-and-replace** capability, reusing one shared editor component.

The three surfaces:

1. **Session main-result box** — the completed quick-transcription text in Session View.
2. **Live-mode box** — the live transcript in Session View (editable only after capture stops).
3. **Audio-Note transcript** — the saved, richly-structured transcript in the Audio Note view.

**In scope:** a reusable plain-text editor + find/replace, three integrations, and a minimal non-destructive backend field for the Audio-Note (the only persisted surface).

**Out of scope:** see §13.

---

## 2. Locked Decisions (from brainstorming — do not change without user sign-off)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Edit model for the structured Audio-Note view | **Hybrid edit toggle** — rich read-only view by default; an explicit Edit action swaps it for ONE flat editable text box. Editing flattens to plain text (word-level seek is intentionally given up once text is hand-corrected). |
| D2 | Persistence | **Audio-Note persists** to a new non-destructive `transcript_corrected` field (original segments kept, revertable). **Session main-result & Live edits are client-only** (they change what Copy/Download output; those surfaces are not records today). |
| D3 | Live-mode edit timing | **Only when stopped.** Read-only while `status === 'recording'`. |
| D4 | Edit trigger | **Context-appropriate:** flat boxes (Session result, Live) = click-into-text to edit; Audio-Note = explicit Edit (pencil) button (its body already uses click-a-word-to-seek, so click-to-edit would collide). |
| D5 | Find/replace feature set | **Standard:** find with live match count + next/prev + current-match highlight, replace + replace-all, case-sensitive toggle, Ctrl+F / Ctrl+H / Esc shortcuts. No regex / whole-word in MVP. |
| D6 | Editor implementation | **Plain `<textarea>` + native-selection find/replace.** No new dependencies. (Highlight-all overlay and CodeMirror were considered and rejected for MVP — see §13.) |

---

## 3. Current State (verified anchors)

### 3.1 Session main-result box — flat, ephemeral
- **File:** `dashboard/components/views/SessionView.tsx`
- **Render:** `:1673–1703`. `transcription.result.text` inside
  `<div className="selectable-text custom-scrollbar max-h-32 overflow-y-auto rounded-xl border border-white/5 bg-black/20 p-4 font-mono text-sm leading-relaxed text-slate-300">` (`:1675`), followed by a language/duration footer and Copy/Download buttons.
- **Data:** `transcription.result` is ephemeral React state from `useTranscription` (`dashboard/src/hooks/useTranscription.ts`). No save path exists. `TranscriptionResult` interface at `useTranscription.ts:22`.
- **Copy/Download handlers:** `SessionView.tsx:833` (`handleCopyTranscription`) and `:839` (`handleDownloadTranscription`), both read `transcription.result.text`.

### 3.2 Live-mode box — structured, streaming, ephemeral
- **File:** `dashboard/components/views/SessionView.tsx`
- **Render:** appears in **two layout branches** — `:2136` and `:2314` (both `ref={liveTranscriptRef}`, identical class strings). Each maps `live.sentences[]` (timestamped) and renders `live.partial` (streaming interim). **Both branches must host the editor.**
- **Data/helpers:** `live` from `useLiveMode` (`dashboard/src/hooks/useLiveMode.ts`). `live.getText()` (`:303`) already flattens sentences to text; `live.clearHistory()` exists. Copy button at `:2126`.
- **Status source:** `transcription.status` / `live.status`; `isRecording = transcription.status === 'recording'` (`SessionView.tsx:719`). Use the live status to gate read-only.

### 3.3 Audio-Note transcript — richly structured, persisted
- **File:** `dashboard/components/views/AudioNoteModal.tsx`
- **Render:** `:2173–2278`. `segments.map(...)` (`:2182`) with speaker labels, per-word click-to-seek (`:2224–2246`), confidence chips, timestamps. Plain fallback `plainTranscriptText` (`:2267`) only when `!hasSegmentDetail`.
- **Flatten gap:** `plainTranscriptText` (`:632`) is `''` when `hasSegmentDetail` (diarization OR word timestamps) is true (`:630–638`). → A dedicated flatten helper is required (see §5.4).
- **Existing pattern to mirror (the Summary):** edit-toggle render at `:2136–2154` (`isSummaryEditing ? <textarea/> : <view/>`); save at `:864` (`handleSaveSummary` → `apiClient.updateRecordingSummary`); debounced 2s auto-save at `:894–906` (`handleSummaryEditChange`); exit-save at `:880` (`handleExitSummaryEdit`).
- **Persistence chain to mirror:**
  - `apiClient.updateRecordingSummary(id, summary?, model?)` — `dashboard/src/api/client.ts:612` → `this.patch('/api/notebook/recordings/${id}/summary', …)`.
  - Route `PATCH /recordings/{id}/summary` — `server/backend/api/routes/notebook.py:383` (`update_summary_patch`); body model `UpdateSummaryBody` at `:135`; PUT variant at `:360`.
  - Repo `update_recording_summary(id, summary, model)` — `server/backend/database/database.py:372` (`UPDATE recordings SET summary=?…`).
  - Recording columns list `:158`; `__init__` mapping `:280`; `to_dict` `:295`. Export list `server/backend/database/__init__.py:48`.
  - Frontend `Recording` type — `dashboard/src/api/types.ts:153` (`summary`, `summary_model`).
  - Migrations are **Alembic** revisions in `server/backend/database/migrations/versions/` (latest `016_add_webhook_deliveries.py`; template `script.py.mako`).

---

## 4. Architecture Overview

```
                ┌─────────────────────────────────────────────┐
                │            SHARED CORE (new)                 │
                │                                              │
   pure ───────▶│  findReplaceEngine.ts   (compute/replace)    │
   hook ───────▶│  useFindReplace.ts      (state + selection)  │
   ui   ───────▶│  FindReplaceTextEditor.tsx (+ Toolbar)       │
   util ───────▶│  transcriptFlatten.ts   (segments → text)    │
                └───────────────┬──────────────┬───────────────┘
                                │              │
        ┌───────────────────────┼──────────────┼────────────────────────┐
        ▼                       ▼              ▼                         ▼
  Session result          Live mode       Audio-Note edit          Audio-Note backend
  (client-only)         (client-only)     (persisted)              (new field/route)
```

The same `FindReplaceTextEditor` is used in all three places. Flat surfaces render it **always** (find/replace appears on focus); the Audio-Note mounts it **only in edit mode** (parent toggles).

---

## 5. Shared Core (new files — build TEST-FIRST)

> Placement follows the repo convention: pure logic/hooks in `dashboard/src/`, components under `dashboard/components/`.

### 5.1 `dashboard/src/services/findReplaceEngine.ts` (pure, unit-tested)

Literal substring matching (NOT regex). Non-overlapping, left-to-right.

```ts
export interface Match { start: number; end: number; }       // half-open offsets into text
export interface FindOptions { caseSensitive: boolean; }

/** All non-overlapping matches. Empty/whitespace-only query → []. */
export function computeMatches(text: string, query: string, opts: FindOptions): Match[];

/** Replace the single match at `match` with `replacement`; returns new text. */
export function replaceCurrent(text: string, match: Match, replacement: string): string;

/** Replace every match; returns { text, count }. */
export function replaceAll(text: string, query: string, replacement: string, opts: FindOptions): { text: string; count: number };
```

Edge rules: empty query ⇒ no matches and no-op replaces; case-insensitive compares lowercased copies but preserves original casing in output.

### 5.2 `dashboard/src/hooks/useFindReplace.ts` (state, unit-tested)

Wraps the engine; owns query/replacement/options/current index and drives the textarea selection.

```ts
interface UseFindReplaceArgs {
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  value: string;                       // current editor text
  onChange: (next: string) => void;    // commit replaces
}
interface UseFindReplaceState {
  isOpen: boolean; mode: 'find' | 'replace';
  query: string; replacement: string; caseSensitive: boolean;
  matchCount: number; currentIndex: number;          // 0-based; UI shows currentIndex+1 / matchCount
  open(mode: 'find' | 'replace'): void; close(): void;
  setQuery(q: string): void; setReplacement(r: string): void; toggleCaseSensitive(): void;
  next(): void; prev(): void;                          // wrap-around
  replaceCurrentMatch(): void; replaceAllMatches(): void;
}
```

Behavior: recompute matches when `value`/`query`/`caseSensitive` change (clamp `currentIndex`). `next/prev` and `replaceCurrentMatch` call `textarea.setSelectionRange(start, end)` and scroll the match into view. **Note (D6 caveat):** while focus is in the find input, the current match shows in the browser's *inactive-selection* color — acceptable for MVP; highlight-all is a future enhancement (§13).

### 5.3 `dashboard/components/editor/FindReplaceTextEditor.tsx` (+ `FindReplaceToolbar.tsx`)

The reusable editable surface.

```ts
interface FindReplaceTextEditorProps {
  value: string;
  onChange: (next: string) => void;
  readOnly?: boolean;            // true = display only (e.g. Live while recording)
  autoFocus?: boolean;           // Audio-Note edit entry focuses immediately
  placeholder?: string;
  className?: string;            // container styling (each box passes its own)
  textClassName?: string;       // textarea typography (e.g. 'font-mono text-sm leading-relaxed text-slate-300')
  enableFindReplace?: boolean;  // default true
  ariaLabel?: string;
}
```

- Container is `relative`; the textarea fills it. When `readOnly`, render the existing read-only block styling (no editing affordances).
- **Floating control (top-right, inside the box):** a single search-icon button (honors "don't need two separate icons"). Click → compact find bar (input + count `n/total` + ↑/↓ + case-sensitive toggle + ✕). A chevron expands it to the replace row (replacement input + Replace + Replace-all). This is `FindReplaceToolbar.tsx`, driven by `useFindReplace`.
- **Visibility:** the control appears when the editor is focused (flat boxes) or whenever `enableFindReplace && !readOnly` and the editor is mounted in edit mode (Audio-Note).
- **Shortcuts** (scoped to the editor container; `preventDefault` so Electron's native find doesn't hijack): **Ctrl/Cmd+F** open find · **Ctrl/Cmd+H** open replace · **Esc** close (return focus to textarea) · **Enter / Shift+Enter** next/prev while focus in the find input · **Enter** in the replace input = replace current.
- Auto-grow height in edit mode (the Session box is `max-h-32` — expand to a workable min-height when editing).

### 5.4 `dashboard/src/services/transcriptFlatten.ts` (pure, unit-tested)

```ts
// Reuse the existing segment type that AudioNoteModal already consumes
// (grep the segment shape used at AudioNoteModal.tsx:557 `transcription?.segments`).
/** Flatten segments to editable plain text. Newline-joined per segment, trimmed, blanks dropped. No speaker prefixes in MVP. */
export function flattenSegmentsToText(segments: Segment[]): string;
```

---

## 6. Find/Replace UX Summary

- Entry point: one floating search icon, top-right inside the editor (per user's request — single affordance, not two icons).
- Find bar: query input · `current/total` counter · prev (↑) · next (↓) · `Aa` case-sensitive toggle · close (✕).
- Replace row (expand): replacement input · Replace (current) · Replace all.
- Current match highlighted via native textarea selection + scroll-into-view.
- Keyboard per §5.3.

---

## 7. Integration A — Session main-result (client-only)

**File:** `dashboard/components/views/SessionView.tsx`

1. Add local state `editedResultText` seeded from `transcription.result.text`; reset via `useEffect` whenever `transcription.result?.text` changes (new transcription replaces edits).
2. Replace the text node at `:1675–1676` with `<FindReplaceTextEditor value={editedResultText} onChange={setEditedResultText} textClassName="font-mono text-sm leading-relaxed text-slate-300" … />`, keeping the language/duration footer (`:1677–1682`) and the Copy/Download row (`:1684–1701`). Preserve the `selectable-text custom-scrollbar … rounded-xl border … bg-black/20` look via `className`.
3. Point `handleCopyTranscription` (`:833`) and `handleDownloadTranscription` (`:839`) at `editedResultText` (fallback to `result.text`).
4. **No persistence.** Edits live only in this component instance.

**Acceptance:** click into the result box → editable + find control appears; edits flow into Copy & Download; starting a new transcription resets the box.

---

## 8. Integration B — Live mode (client-only, only when stopped)

**File:** `dashboard/components/views/SessionView.tsx`

1. **Recommended refactor:** extract the duplicated live transcript body (`:2136` and `:2314`) into a shared `LiveTranscriptView` sub-component so both layout branches get the editor with no duplication. (If skipped, apply identical changes to both branches.)
2. While `live` is actively recording → keep the current streaming render (`live.sentences` + `live.partial`), read-only.
3. When stopped and content exists → render `<FindReplaceTextEditor value={editedLiveText} onChange={setEditedLiveText} … />` seeded from `live.getText()`. Reset seed when a new live session starts.
4. The Copy button (`:2126`) reads `editedLiveText` when present.
5. **No persistence.**

**Acceptance:** cannot edit mid-capture; after stop the box is editable with find/replace; Copy reflects edits.

---

## 9. Integration C — Audio-Note (persisted, non-destructive)

### 9.1 Frontend — `dashboard/components/views/AudioNoteModal.tsx`

State & helpers (mirror the Summary block at `:864–906`):
- `transcriptDraft`, `isTranscriptEditing`, `isTranscriptSaving`, a debounce timer ref.
- `correctedTranscript = recording?.transcript_corrected ?? null`; `hasCorrected = !!correctedTranscript?.trim()`.
- `handleSaveCorrectedTranscript(text)` → `apiClient.updateRecordingCorrectedTranscript(recordingId, text || undefined)`; on success update local recording state so the UI reflects it (mirror `setSummaryText`).
- `handleTranscriptEditChange(text)` → set draft + debounced 2s autosave.
- `handleExitTranscriptEdit(save)` → flush/save, `setIsTranscriptEditing(false)`.
- `handleRevertTranscript()` → `apiClient.updateRecordingCorrectedTranscript(recordingId, undefined)` (clears field) → local state cleared → rich view returns.

Render changes in the Transcript section (`:2173–2278`):
- Add an **Edit (pencil) button** to the Transcript header (near the sticky chip `:2176`). When `hasCorrected`, also show an **"Edited · Revert"** affordance.
- **Read mode:**
  - `hasCorrected` → render `correctedTranscript` as a flat, read-only, selectable block (reuse `selectable-text whitespace-pre-wrap … text-slate-300`).
  - else → existing rich `segments.map(...)` view (unchanged).
- **Edit mode** (`isTranscriptEditing`): render `<FindReplaceTextEditor autoFocus value={transcriptDraft} onChange={handleTranscriptEditChange} … />`, seeded from `correctedTranscript ?? flattenSegmentsToText(segments)`.

### 9.2 Backend (non-destructive field + endpoint)

Mirror the Summary chain exactly:

1. **Migration** — new Alembic revision `server/backend/database/migrations/versions/017_add_recording_transcript_corrected.py` (confirm `017` is the next head before numbering; set `down_revision` to the current head `016`). **Copy the structure of an existing add-column migration** such as `014_add_recording_speaker_aliases.py` or `015_add_recording_auto_action_status.py` for upgrade/downgrade conventions (including how SQLite downgrade is handled there). Upgrade body: `op.execute(text("ALTER TABLE recordings ADD COLUMN transcript_corrected TEXT"))`.
2. **`server/backend/database/database.py`:**
   - Add `"transcript_corrected"` to the column list (`~:158`).
   - `__init__`: `self.transcript_corrected = data.get("transcript_corrected")` (`~:280`).
   - `to_dict`: `"transcript_corrected": self.transcript_corrected` (`~:295`).
   - New fn `update_recording_corrected_transcript(recording_id: int, transcript: str | None) -> bool` (mirror `:372`): `UPDATE recordings SET transcript_corrected = ? WHERE id = ?`, storing `None` when `transcript` is falsy (revert).
3. **`server/backend/database/__init__.py`:** export `update_recording_corrected_transcript` (mirror `:48`).
4. **`server/backend/api/routes/notebook.py`:**
   - Body model `UpdateTranscriptBody { transcript: str | None = None }` (mirror `UpdateSummaryBody` `:135`).
   - `PATCH /recordings/{recording_id}/transcript` (mirror `update_summary_patch` `:383`) calling the new repo fn; return `{ "status": "ok", "id": recording_id, "transcript_corrected": body.transcript or None }`; raise 500 on failure. Import the new fn at the top (mirror `:53`).
5. **`dashboard/src/api/client.ts`:** add (mirror `:612`):
   ```ts
   /** PATCH /api/notebook/recordings/:id/transcript — set or clear (revert) the corrected transcript */
   async updateRecordingCorrectedTranscript(id: number, transcript?: string):
     Promise<{ status: string; id: number; transcript_corrected: string | null }> {
     return this.patch(`/api/notebook/recordings/${id}/transcript`, { transcript });
   }
   ```
6. **`dashboard/src/api/types.ts`:** add `transcript_corrected: string | null;` to the `Recording` interface (next to `summary` `:153`).

**Acceptance:** Edit pencil swaps rich view → flat editor; edits autosave (2s) to `transcript_corrected`; reopening the note shows the corrected text; Revert restores the rich segment view; original segments/word-timestamps are intact in the DB throughout.

---

## 10. Data Safety (critical invariant)

- The original `segments` / transcript storage is **never modified**. `transcript_corrected` is an **additive** column.
- Revert = set `transcript_corrected = NULL`. The rich, word-timestamped view returns intact.
- Autosave failures fail silently and are retried on next keystroke (mirror Summary). The user's draft remains in the textarea; no completed data is discarded.

---

## 11. Testing (target ≥80% on new code)

- **Engine** `findReplaceEngine.test.ts` (Vitest): empty/whitespace query, single/multi/zero matches, case-sensitive vs insensitive, overlapping-substring safety, `replaceCurrent`, `replaceAll` count, casing preserved.
- **Flatten** `transcriptFlatten.test.ts`: diarized, word-timestamped, plain, empty segments, blank-segment dropping.
- **Hook** `useFindReplace.test.ts`: index clamping on text change, wrap-around next/prev, replace recomputes matches.
- **Component** `FindReplaceTextEditor.test.tsx` (Vitest + RTL): focus reveals control, Ctrl+F/Ctrl+H/Esc, replace-all updates value, `readOnly` blocks editing.
- **Backend** (pytest, run from `server/backend/` with the **build venv**: `../../build/.venv/bin/pytest tests/ -v --tb=short`): repo `update_recording_corrected_transcript` set + clear; route handler via the **direct-call pattern** (see CLAUDE.md "Route handler tests" + `tests/test_transcription_durability_routes.py`); `to_dict` includes the new field.
- **Frontend tests** run from `dashboard/` (Vitest).

---

## 12. Phasing & Acceptance

| Phase | Deliverable | Gate |
|-------|-------------|------|
| **P1** | Shared core (§5) + unit tests | Engine/hook/flatten green; component renders + find/replace works in isolation |
| **P2** | Session main-result integration (§7) | Click-to-edit, find/replace, Copy/Download reflect edits, reset-on-new |
| **P3** | Live-mode integration (§8) | Read-only while recording; editable after stop in BOTH layout branches; Copy reflects edits |
| **P4** | Audio-Note + backend (§9) | Migration applies; edit→autosave→reopen persists; Revert restores rich view; original data intact; pytest green |

Build P1 first; P2→P3→P4 is easy→hard. Each phase is independently shippable.

---

## 13. Out of Scope / Future Enhancements

- **Highlight-all matches** simultaneously (needs a backdrop/overlay or `contentEditable`) — MVP highlights only the current match.
- **Regex / whole-word** find (Power tier).
- **Rich text** (bold/italic) — plain text only.
- **Persisting** Session-result / Live edits as records (they stay client-only per D2).
- **Speaker-label prefixes** in the flattened Audio-Note text.
- A **"show original ↔ show edited" toggle** for the Audio-Note (Revert is the MVP path).

---

## 14. Risks & Project-Specific Gotchas (read before coding)

1. **UI contract:** any change touching CSS classes requires the update sequence then `npm run ui:contract:check` from `dashboard/` (extract → build → `validate-contract.mjs --update-baseline` → check). See `.claude/skills/ui-contract/SKILL.md` and CLAUDE.md. New editor markup adds classes — budget for this.
2. **Two live render branches** (`SessionView.tsx:2136` & `:2314`) — both must be handled; prefer the `LiveTranscriptView` extraction.
3. **Cramped main-result box** (`max-h-32`) — expand height in edit mode or editing is unusable.
4. **Electron native find** — ensure Ctrl+F is captured/prevented inside the editor so it doesn't trigger the app/browser find.
5. **`plainTranscriptText` is empty for detailed transcripts** — must use `flattenSegmentsToText` (§5.4), not the existing field, to seed the Audio-Note editor.
6. **Tooling:** use `uv`, never `pip`. Backend tests use the **build venv**, not the server venv.
7. **GitNexus:** run `gitnexus_impact` before editing `SessionView`/`AudioNoteModal` symbols and `gitnexus_detect_changes()` before committing (per CLAUDE.md).
8. **Credit sources:** if any find/replace logic is ported from an external project/SO answer, add the attribution comment per CLAUDE.md.
9. **Data-loss invariant (§10)** is non-negotiable — never overwrite original segments.

---

## 15. File Change Checklist

| File | Change |
|------|--------|
| `dashboard/src/services/findReplaceEngine.ts` | **new** — pure match/replace |
| `dashboard/src/services/findReplaceEngine.test.ts` | **new** |
| `dashboard/src/services/transcriptFlatten.ts` | **new** — segments→text |
| `dashboard/src/services/transcriptFlatten.test.ts` | **new** |
| `dashboard/src/hooks/useFindReplace.ts` | **new** — state + selection |
| `dashboard/src/hooks/useFindReplace.test.ts` | **new** |
| `dashboard/components/editor/FindReplaceTextEditor.tsx` | **new** — reusable editor |
| `dashboard/components/editor/FindReplaceToolbar.tsx` | **new** — floating control |
| `dashboard/components/editor/FindReplaceTextEditor.test.tsx` | **new** |
| `dashboard/components/views/SessionView.tsx` | edit — integrate (result `:1673`, live `:2136`/`:2314`, copy/download `:833`/`:839`) |
| `dashboard/components/views/AudioNoteModal.tsx` | edit — Edit toggle, flat editor, autosave, revert (Transcript section `:2173`) |
| `dashboard/src/api/client.ts` | edit — `updateRecordingCorrectedTranscript` |
| `dashboard/src/api/types.ts` | edit — `transcript_corrected` on `Recording` |
| `server/backend/api/routes/notebook.py` | edit — `PATCH …/transcript` + body model |
| `server/backend/database/database.py` | edit — column, `__init__`, `to_dict`, update fn |
| `server/backend/database/__init__.py` | edit — export update fn |
| `server/backend/database/migrations/versions/017_add_recording_transcript_corrected.py` | **new** — Alembic add-column |
| backend tests under `server/backend/tests/` | **new** — repo + route |

---

*End of spec.*
