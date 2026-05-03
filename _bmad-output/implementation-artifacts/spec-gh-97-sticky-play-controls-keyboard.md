---
title: 'GH #97 — Always-visible Play Controls + keyboard shortcuts in AudioNoteModal'
type: 'feature'
created: '2026-05-02'
status: 'in-review'
baseline_commit: '2251728e7d20cef0c0902d0a3f12fb09de2eba4f'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When the user opens an audio note in the Notebook (`AudioNoteModal`) and presses play, the per-word highlighter auto-scrolls the active word to the vertical center of the scroll container (`useWordHighlighter.ts:65`). Because the Audio Player Card lives **inside** that same scroll container (`AudioNoteModal.tsx:1700–1771`), it scrolls out of view within seconds — the user can no longer see the play / pause / rewind / forward / scrubber controls until they scroll back up. Issue #97 also asks for keyboard play/pause and skip controls so playback can be steered without reaching for the mouse.

**Approach:** Lift the Audio Player Card out of the scrollable body and render it as a `flex-none` sibling between the modal header and the scroll container — so it is always visible regardless of transcript scroll position. Add a single document `keydown` listener (mounted while `isOpen === true`) that maps `Space` and `K` to play/pause, `J` to seek `-10s`, and `L` to seek `+10s`, reusing the existing `handlePlayPause` and `handleSeek` callbacks. Suppress the shortcuts when focus is in any text input (input / textarea / contentEditable) to avoid hijacking the rename / chat / summary editors.

## Boundaries & Constraints

**Always:**
- Reuse existing handlers `handlePlayPause` (`AudioNoteModal.tsx:928`) and `handleSeek(delta)` (`:942`). Do not add new playback logic.
- The Audio Player Card markup at `AudioNoteModal.tsx:1700–1771` is moved verbatim — same Tailwind classes, same `AudioVisualizer`, same `<audio>` element, same `audioRef`. No visual redesign.
- The lifted card sits between the header (`flex h-20 flex-none …`) and the scrollable body (`transcriptContainerRef` / `custom-scrollbar flex-1 overflow-y-auto`). It must be `flex-none` so it never shrinks the scroll area's flex budget unpredictably.
- The scroll container (`transcriptContainerRef`) keeps its identity, ref, and overflow behavior — `useWordHighlighter` continues to scroll within the same DOM node it scrolls today.
- Keyboard shortcuts honour standard "no-hijack" rules: no fire when `event.target` is `INPUT`, `TEXTAREA`, or `[contenteditable=""|"true"]`; no fire when any of `ctrlKey`/`metaKey`/`altKey` is held (so OS-level shortcuts like `Cmd+L`, `Ctrl+J` keep working). `Space` is matched by `event.code === 'Space'` (key-layout-stable); `K`/`J`/`L` by `event.key.toLowerCase()`.
- `event.preventDefault()` only fires when the shortcut actually executes — never on no-op paths, so unrelated keys propagate untouched.
- Listener attaches on `document` and is cleaned up in the effect return; it is gated on `isOpen` and the same `note.recordingId != null` guard the existing player buttons use (no shortcut should fire when there is no audio loaded).

**Ask First:**
- Adding a sentence-level skip (e.g. `Shift+J/L` jumps to previous/next segment boundary) — out of scope unless requested.
- Adding the optional `M` marker action from the issue's "(M – Place Marker)" wishlist line — defer to a separate issue (needs UI for placement, persistence, search). Not implemented here.
- Any restructure of the LM Assistant sidebar layout that the player lift might brush against — sidebar lives in the right pane (`AudioNoteModal.tsx:1554` left section, sidebar separate). The lift only touches the left pane.

**Never:**
- Don't change `useWordHighlighter.ts` — auto-scroll behaviour is unaffected and out of scope.
- Don't add a "mini-player" or duplicate compact bar — there is one player, always visible.
- Don't bind shortcuts to `keyup` (Space-on-keyup interacts badly with focused buttons firing click on Space). Use `keydown`.
- Don't move the AI Summary or Transcript blocks out of the scroll container; only the Audio Player Card is lifted.
- Don't introduce a global Zustand/Context handler — the listener is local to `AudioNoteModal`'s lifecycle.
- Don't add `tabIndex` / `autoFocus` to the modal root just to capture keys — the document-level listener already covers all focus states except text inputs (which we explicitly skip).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| User opens modal, scrolls transcript down | Player is visible | Player remains visible at top of left pane; transcript scrolls underneath in the body container | N/A |
| Word highlighter auto-scrolls during playback | `isPlaying === true` | Active word centers in scroll container; player card stays put outside that container | N/A |
| User presses `Space` with focus on modal background | Modal open, no input focused | Toggles play/pause via `handlePlayPause`; `preventDefault` consumes the key (no page scroll) | If `audioRef.current` is null, callback no-ops |
| User presses `K` | Modal open, no input focused | Toggles play/pause | Same as `Space` |
| User presses `J` | Modal open, no input focused | Calls `handleSeek(-10)` — clamped to `[0, duration]` by existing handler | N/A |
| User presses `L` | Modal open, no input focused | Calls `handleSeek(+10)` — clamped by existing handler | N/A |
| User presses `Space` while typing in title-rename input | `event.target` is `INPUT` | Shortcut does NOT fire; default behaviour (insert space) preserved | N/A |
| User presses `J` while typing in chat / summary editor | `event.target` is `TEXTAREA` or `contentEditable` | Shortcut does NOT fire | N/A |
| User holds `Ctrl+L` (browser address bar) | Modifier present | Shortcut does NOT fire; OS/browser handles the chord | N/A |
| User presses `K` while modal is closed | `isOpen === false` | Listener is not attached; no-op | N/A |
| Modal opens but `note.recordingId == null` | No recording | Shortcuts no-op (same gate as the player buttons today) | N/A |
| User clicks a word to seek, then presses `Space` | Focus may be on the clicked `<span>` | Shortcut still fires (span isn't an input); play resumes from the new position | N/A |
| Modal closes via `X` or `Escape` | `isOpen` flips to false | Effect cleanup removes the document listener | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/AudioNoteModal.tsx` — only file touched.
  - **Move**: Audio Player Card block at lines ~1700–1771 (the `<div className="group relative overflow-hidden rounded-2xl …">` containing the `<audio>` element, `AudioVisualizer`, time counter, Rewind / Play / Forward buttons, and seek bar). Cut from inside the `transcriptContainerRef` div and paste as a sibling between the header (`</div>` closing line ~1693) and the scroll container (`<div ref={transcriptContainerRef} …>` at line ~1696).
  - **Wrapper**: wrap the lifted card in `<div className="flex-none px-8 pt-8 select-none">` so the existing `p-8` whitespace rhythm is preserved (the scroll container retains its own `p-8`; visually the gap stays the same since the lifted card supplies its own padding via `p-6`).
  - **Scroll container adjustment**: change `space-y-8` to keep the same vertical spacing among the *remaining* children (AI Summary + Transcript). The first child (AI Summary) needs no manual top spacing because the container's `p-8` covers it.
  - **New effect**: add a `useEffect` after the existing audio-handler block (~line 992) that, when `isOpen && note?.recordingId != null`, attaches a document `keydown` listener implementing the matrix above. Effect deps: `[isOpen, note?.recordingId, isPlaying]` — `isPlaying` is captured indirectly via the existing handlers, but listing it makes intent explicit (the handler always reads the latest via closure since the handler is recreated each render via the inline arrow; alternative is to use `useCallback` + ref). Implementation note: read `audioRef.current` inside the handler so we always operate on the live element, never a stale closure value.
- `dashboard/src/hooks/useWordHighlighter.ts` — read-only reference; not modified.
- `dashboard/ui-contract/transcription-suite-ui.contract.yaml` — no class additions are planned, but the wrapper `flex-none px-8 pt-8 select-none` is a new combination on a new element. Run the full contract pipeline (`extract` → `build` → `validate --update-baseline` → `check`) per `CLAUDE.md`. If new keys appear in the diff, accept them; if a class lookup goes stale (because the player card moves DOM positions), re-baseline.

## Tasks

**Execution:**
- [ ] `dashboard/components/views/AudioNoteModal.tsx` — Lift the Audio Player Card out of the scroll container into a `flex-none` wrapper between header and scroll body. Same markup, no visual redesign.
- [ ] `dashboard/components/views/AudioNoteModal.tsx` — Add `useEffect` that registers a document `keydown` listener while `isOpen && note?.recordingId != null`. Map `Space`/`K` → `handlePlayPause()`, `J` → `handleSeek(-10)`, `L` → `handleSeek(+10)`. Skip when target is `INPUT`/`TEXTAREA`/contentEditable, or any of Ctrl/Meta/Alt is held. `preventDefault` only on actual matches.
- [ ] `dashboard/`: run `npm run ui:contract:extract` → `npm run ui:contract:build` → `node scripts/ui-contract/validate-contract.mjs --update-baseline` → `npm run ui:contract:check`.
- [ ] `dashboard/`: run `npm run typecheck` — must pass.
- [ ] Manual smoke: open the dev server, open a note with word timestamps, hit Play. Confirm the player card stays visible while the active word centers in the transcript. Confirm `Space`, `K`, `J`, `L` work; confirm typing in the title-rename and chat inputs does not trigger them.

**Acceptance Criteria:**
- **AC1**: When the AudioNoteModal is open and the user scrolls or auto-scrolls the transcript body, the Audio Player Card (visualizer + time counter + Rewind / Play / Forward buttons + seek bar) remains fully visible at the top of the modal's left pane at all times.
- **AC2**: **Given** the modal is open with a loaded recording **When** the user presses `Space` or `K` with no text input focused **Then** playback toggles between play and pause, and the page does not scroll.
- **AC3**: **Given** the modal is open with a loaded recording **When** the user presses `J` (or `L`) with no text input focused **Then** the audio current time decreases (or increases) by 10 seconds, clamped to `[0, duration]`.
- **AC4**: **Given** the user is focused in any text input or textarea inside the modal (rename title input, summary editor, chat input, AI sidebar inputs) **When** the user presses `Space`, `K`, `J`, or `L` **Then** the shortcut does NOT fire and the keystroke is consumed by the input as normal text.
- **AC5**: **Given** any of `Ctrl`, `Meta`, or `Alt` is held **When** the user presses `K`, `J`, or `L` **Then** the shortcut does NOT fire (browser/OS chord wins).
- **AC6**: **Given** the modal is closed **When** the user presses `Space`/`K`/`J`/`L` anywhere on the page **Then** nothing related to AudioNoteModal happens (listener detached).
- **AC7**: The Word Highlighter (`useWordHighlighter`) continues to scroll the active word within the transcript area — no regression to the existing per-word centering behaviour.
- **AC8**: `npm run typecheck` from `dashboard/` passes; UI contract baseline is regenerated and `npm run ui:contract:check` passes.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — expected: exit 0.
- `cd dashboard && npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` — expected: final `check` exits 0.

**Manual checks (dev server):**
- Open the Electron dashboard dev server, navigate to **Notebook**, click an existing audio note with diarized + word-timestamped transcript.
- Click Play. Confirm the player card never scrolls out of view as the active word auto-centers.
- With nothing focused, press `Space` → pauses. Press `K` → resumes. Press `J` → counter jumps back ~10s. Press `L` → jumps forward ~10s.
- Open the rename input via the "..." menu (GH #96 dropdown). Press `Space` while typing → a literal space is inserted, audio does NOT toggle.
- Hit `Escape` to close any open dialog, then close the modal. Press `Space` → no audio side effects.

## Risks & Mitigations

- **Risk**: The lifted card increases the left pane's chrome height (~280 px) at the expense of the scrollable body. **Mitigation**: the scroll container is `flex-1` — it shrinks gracefully, and the player card was already taking the same vertical space at the top of the scroll. Net loss is only the auto-hide-on-scroll behaviour, which is exactly what the user asked us to remove.
- **Risk**: `Space` key fires the click handler of an in-focus button (e.g. the Play button itself), causing a double-toggle. **Mitigation**: the handler calls `event.preventDefault()` whenever it matches; this stops the synthetic click on the focused button. Buttons inside the player are reachable by Tab but the keydown handler runs first because it's on `document` (capture phase optional). If a Space-double-fire is observed on a specific button, add `event.stopPropagation()` to the matched branch.
- **Risk**: The `<audio>` element was previously inside the scroll body; some browsers detach `MediaElementSource` when the element is moved in the DOM. **Mitigation**: `mediaSourceCreatedRef.current` guards the `createMediaElementSource` call to once-per-element; moving the element in markup is a render swap, but React re-uses the same DOM node because we keep the same JSX position relative to its parent (just a different parent — React will unmount + remount the `<audio>`, and `audioRef` will point to a fresh node). To keep the Web Audio pipeline intact, the `<audio>` element MUST move with the lifted card (it already lives inside that card at line 1703). After the move, on the first `loadedmetadata`, the analyser pipeline rebuilds — verified by the existing `try / catch` around `createMediaElementSource`.

## Out of Scope

- The `M` marker feature with searchable notes (issue mentions it as a wishlist with 🙏). Tracked separately.
- Sentence-level skip (`Shift+J/L`) — current ask is parity with the existing 10s buttons.
- Touch / swipe gestures.
- Showing the shortcuts in any UI tooltip or help modal (button `title` attributes are already present for Rewind/Forward).
- Changes to `SessionView.tsx` live-mode playback (no auto-scroll there; out of scope).
- Backend or API changes — this is dashboard-only.
