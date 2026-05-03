---
title: 'GH-49: Global toggle to hide timestamps from transcription output'
type: 'feature'
created: '2026-04-03'
status: 'done'
baseline_commit: 'db5ca363fdb0cdfdb50e13046ebcdebd00f7d647'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When users feed transcripts to LLMs, timestamps waste context tokens and sometimes confuse the model. There is currently no way to get speaker-labeled output without timestamps.

**Approach:** Add a global "Hide Timestamps" toggle in Settings > Client under an Output section. When enabled: live-mode wall-clock timestamps are hidden, segment-level timestamps in AudioNoteModal are hidden (including word-level hover tooltips), and file exports skip SRT/ASS subtitle files in favor of TXT-only output.

## Boundaries & Constraints

**Always:** Toggle defaults to OFF. Existing behavior is fully preserved when toggle is off. Follow existing electron-store config pattern (`output.hideTimestamps` key).

**Ask First:** If `renderTxt()` doesn't include speaker labels when diarization is active, should we add speaker-labeled plain text output? (That's a separate enhancement from timestamp removal.)

**Never:** Don't modify server/backend code. Don't change the transcription result data structure. Don't remove timestamps from underlying data — only from display and file output. Don't affect notebook calendar event times (those are event metadata, not transcript timestamps).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Toggle OFF (default) | Any transcription | Current behavior unchanged | N/A |
| Toggle ON, live mode | Live sentence arrives | Sentence displayed without wall-clock timestamp | N/A |
| Toggle ON, segment view | AudioNoteModal with segments | Segment text without time prefix; word hover tooltips omit timing | N/A |
| Toggle ON, file export | Transcription completes | Only TXT file written, SRT/ASS skipped | N/A |
| Toggle toggled mid-session | Toggle flipped OFF→ON while live | New sentences render without timestamps; existing sentences keep current display | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/config/store.ts` -- ClientConfig interface + DEFAULT_CONFIG
- `dashboard/components/views/SettingsModal.tsx` -- Client tab (renderClientTab), clientSettings state, handleSave
- `dashboard/components/views/SessionView.tsx` -- Live-mode sentence timestamps (~L1998, ~L2167)
- `dashboard/components/views/AudioNoteModal.tsx` -- Segment timestamps (formatRecSecs at ~L1422), word-level hover (~L1440)
- `dashboard/src/stores/importQueueStore.ts` -- File export calls renderSrt/renderAss/renderTxt (~L282)
- `dashboard/src/hooks/useSessionImportQueue.ts` -- Session import file export (~L206)

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/config/store.ts` -- Add `output: { hideTimestamps: boolean }` to ClientConfig and DEFAULT_CONFIG (default: false)
- [x] `dashboard/components/views/SettingsModal.tsx` -- Add "Hide timestamps" AppleSwitch in Client tab under new "Output" section; wire state, config load, and save
- [x] `dashboard/components/views/SessionView.tsx` -- Read `output.hideTimestamps` config; conditionally hide wall-clock timestamps on live sentences (both inline and popped-out views)
- [x] `dashboard/components/views/AudioNoteModal.tsx` -- Read config; conditionally hide formatRecSecs prefix and word-level hover timing
- [x] `dashboard/src/stores/importQueueStore.ts` -- Read config; skip renderSrt/renderAss file writes when toggle is on
- [x] `dashboard/src/hooks/useSessionImportQueue.ts` -- Same: skip SRT/ASS file writes when toggle is on

**Acceptance Criteria:**
- Given toggle is OFF, when transcription runs, then all timestamps display and files export as before
- Given toggle is ON, when live mode runs, then sentences appear without wall-clock timestamps
- Given toggle is ON, when viewing segments in AudioNoteModal, then no timestamps are shown
- Given toggle is ON, when file export runs, then only TXT is written (no SRT/ASS)
- Given toggle is ON then OFF in settings, when next transcription runs, then timestamps return

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npm run build` -- expected: clean build

**Manual checks:**
- Toggle visible in Settings > Client under Output section
- Live mode hides/shows timestamps based on toggle
- AudioNoteModal hides/shows segment timestamps based on toggle
- File export skips SRT/ASS when toggle is on

## Suggested Review Order

**Config & persistence**

- New `output.hideTimestamps` key added to interface and defaults
  [`store.ts:67`](../../dashboard/src/config/store.ts#L67)

- Electron-store default ensures key exists on fresh installs
  [`main.ts:418`](../../dashboard/electron/main.ts#L418)

**Settings UI**

- Toggle wired: state init, config load, save, and AppleSwitch render
  [`SettingsModal.tsx:160`](../../dashboard/components/views/SettingsModal.tsx#L160)

**Live mode display**

- Inline view: wall-clock timestamps conditionally hidden
  [`SessionView.tsx:2003`](../../dashboard/components/views/SessionView.tsx#L2003)

- Popped-out view: same pattern for pop-out window
  [`SessionView.tsx:2178`](../../dashboard/components/views/SessionView.tsx#L2178)

**Segment display (AudioNoteModal)**

- Segment start time, word hover, and seek tooltip conditionally hidden
  [`AudioNoteModal.tsx:1431`](../../dashboard/components/views/AudioNoteModal.tsx#L1431)

**File export**

- Unified queue: forces TXT output when toggle is on
  [`importQueueStore.ts:279`](../../dashboard/src/stores/importQueueStore.ts#L279)

- Legacy hook: same override for session import queue
  [`useSessionImportQueue.ts:199`](../../dashboard/src/hooks/useSessionImportQueue.ts#L199)
