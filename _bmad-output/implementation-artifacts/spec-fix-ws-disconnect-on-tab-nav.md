---
title: 'Fix transcription loss on tab navigation'
type: 'bugfix'
created: '2026-03-31'
status: 'done'
baseline_commit: 'a00e59b'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Navigating away from the Session tab while a recording is in progress or being transcribed unmounts `SessionView`, which triggers `useTranscription`'s cleanup effect. That cleanup unconditionally calls `socketRef.current?.disconnect()` and sets `pollCancelledRef.current = true`, killing both the WebSocket and the poll-for-result fallback. The transcription completes on the server but the result never reaches the client.

**Approach:** Keep `SessionView` always mounted in `App.tsx` — hide it with CSS (`display: none`) when another view is active. This preserves the `useTranscription` hook lifecycle (socket, refs, state) across tab switches without any architectural redesign. As a safety net, make the cleanup effect in `useTranscription` skip disconnect when status is `recording` or `processing`.

## Boundaries & Constraints

**Always:**
- SessionView must remain mounted for the entire app lifetime once rendered
- Other views (Notebook, Server, ModelManager, Downloads, Logs) keep their current unmount-on-switch behavior — no change
- The existing ErrorBoundary around SessionView must be preserved
- The fade-in animation on view switch should still apply to the *visible* view

**Ask First:**
- If the always-mounted SessionView causes observable performance issues (memory, re-renders)

**Never:**
- Do not lift useTranscription state into a Zustand store or App-level context (too large a change for this fix)
- Do not add a navigation-blocking modal/dialog — this would be annoying UX
- Do not change the server-side WebSocket handling

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Navigate away during recording | User clicks Notebook tab while status=recording | Session tab hides, recording continues, audio still captured | N/A |
| Navigate away during processing | User clicks Logs tab while status=processing | Session tab hides, transcription completes normally, result received | N/A |
| Navigate back after completion | User returns to Session tab after result arrived | Transcription result is visible, status=complete | N/A |
| Navigate away while idle | User switches tabs with no active transcription | Normal tab switch behavior, no change from current | N/A |
| App unmount (window close) | Electron window closes during processing | Cleanup fires, socket disconnects — server has durability (Wave 1) | Result persisted server-side |

</frozen-after-approval>

## Code Map

- `dashboard/App.tsx:580-648` -- `renderView()` switch statement that unmounts views on tab change
- `dashboard/src/hooks/useTranscription.ts:102-108` -- cleanup effect that unconditionally disconnects
- `dashboard/components/views/SessionView.tsx` -- component that hosts useTranscription

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/App.tsx` -- Replace `renderView()` switch: always render SessionView (hidden via `display:none` when not active), keep switch for other views -- prevents unmount during active transcription
- [x] `dashboard/src/hooks/useTranscription.ts` -- Guard cleanup effect: only disconnect and cancel polling when status is idle/complete/error, skip when recording/processing -- safety net if SessionView ever unmounts during active work

**Acceptance Criteria:**
- Given a recording is in progress, when the user clicks a different sidebar tab, then the recording continues and audio is still captured
- Given a transcription is processing, when the user navigates to Logs and back, then the transcription result is displayed when complete
- Given no active transcription, when the user switches tabs, then behavior is unchanged from current

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npm run build` -- expected: successful build

**Manual checks:**
- Start a recording, switch to Logs tab, switch back — recording should still be active
- Start a recording, stop it, switch to Downloads tab while processing, switch back — result should appear

## Suggested Review Order

- SessionView rendered persistently, hidden via `display:none` when inactive
  [`App.tsx:651`](../../dashboard/App.tsx#L651)

- Other views still mount/unmount normally via switch
  [`App.tsx:580`](../../dashboard/App.tsx#L580)

- Cleanup effect guarded: skips disconnect when recording or processing
  [`useTranscription.ts:103`](../../dashboard/src/hooks/useTranscription.ts#L103)
