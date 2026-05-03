---
title: 'Cancel Button Visible During Recording (not just Processing)'
type: 'feature'
created: '2026-04-04'
status: 'done'
baseline_commit: 'ff63f02'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Cancel button in the Main Transcription area only appears during the "Processing" phase. During recording, users must right-click the system tray icon to cancel — there is no in-app cancel affordance until after they press Stop.

**Approach:** Show the existing Cancel button from the moment recording starts, through both recording and processing phases. Fix the cancel handler to work correctly in both states (audio loopback cleanup + unconditional reset).

## Boundaries & Constraints

**Always:**
- Cancel must clean up audio loopback (same as Stop Recording does) when invoked during recording
- `transcription.reset()` must always execute — even if the server cancel API call fails
- The Cancel button must use the same `variant="secondary"` styling and X icon it already has

**Ask First:**
- If the cancel handler behavior should differ between recording and processing beyond what's specified here

**Never:**
- Do not change the Processing indicator button behavior or its label transitions
- Do not change the server-side cancel endpoint
- Do not touch tray menu cancel logic — it already works correctly

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cancel during recording | User clicks Cancel while status=recording | Audio capture stops, loopback removed, state resets to idle | N/A |
| Cancel during processing | User clicks Cancel while status=processing | API cancel fires, state resets to idle | If API call fails, reset still runs |
| Cancel during connecting | User clicks Cancel while status=connecting | State resets to idle, socket disconnected | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/SessionView.tsx:635` -- `_isRecording` defined but unused; rename to `isRecording`
- `dashboard/components/views/SessionView.tsx:1494` -- Cancel button visibility gate; currently `isProcessing`, needs expansion
- `dashboard/components/views/SessionView.tsx:706-713` -- `handleCancelProcessing` handler; needs `finally` for reset + loopback cleanup
- `dashboard/src/hooks/useTranscription.ts:361-373` -- `reset()` already stops capture + disconnects socket (no changes needed)

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/SessionView.tsx:635` -- Rename `_isRecording` to `isRecording` -- already defined, just unused
- [x] `dashboard/components/views/SessionView.tsx:1494` -- Change visibility condition from `{isProcessing && (` to `{(isConnecting || isRecording || isProcessing) && (` -- show Cancel during connecting, recording, and processing phases
- [x] `dashboard/components/views/SessionView.tsx:706-713` -- Refactor `handleCancelProcessing`: (1) move `transcription.reset()` to a `finally` block so it always runs even if the API call throws, (2) add audio loopback cleanup (same `removeMonitorLoopback`/`disableSystemAudioLoopback` logic from `handleStopRecording`) so cancelling during recording doesn't leak system audio routing. Add `isLinux` to the dependency array.

**Acceptance Criteria:**
- Given the user presses Start Recording, when the recording controls appear, then a Cancel button is visible next to the Stop Recording button
- Given the user presses Stop Recording and processing begins, then the Cancel button remains visible next to the Processing indicator
- Given the user clicks Cancel during recording, when audio is being captured, then capture stops, audio loopback is cleaned up, and state resets to idle
- Given the user clicks Cancel during processing and the server cancel API fails, then `transcription.reset()` still executes and state returns to idle

## Spec Change Log

- **2026-04-04 (review iteration 1):** Acceptance auditor found the Tasks section omitted `isConnecting` from the visibility gate, despite the frozen I/O matrix requiring "Cancel during connecting" support. Amended Task #2 to use `(isConnecting || isRecording || isProcessing)`. KEEP: the `finally` block structure and loopback cleanup pattern from Task #3.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors

**Manual checks:**
- Start recording → Cancel button visible next to Stop Recording
- Press Stop → Cancel button remains visible next to Processing indicator
- Click Cancel during recording → returns to idle state, no audio leaks
- Click Cancel during processing → returns to idle state

## Suggested Review Order

- Visibility gate widened to cover connecting + recording + processing states
  [`SessionView.tsx:1497`](../../dashboard/components/views/SessionView.tsx#L1497)

- `_isRecording` renamed to `isRecording` — now consumed by the visibility gate above
  [`SessionView.tsx:635`](../../dashboard/components/views/SessionView.tsx#L635)

- Cancel handler hardened: `reset()` in `finally`, loopback cleanup mirrors `handleStopRecording`
  [`SessionView.tsx:706`](../../dashboard/components/views/SessionView.tsx#L706)
