---
title: 'Fix tray "Transcribe File..." to use priority queue with preemption'
type: 'bugfix'
created: '2026-04-03'
status: 'done'
baseline_commit: '6bfa13e'
context:
  - 'docs/project-context.md'
  - 'CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The tray right-click "Transcribe File..." action (GH #47) calls `apiClient.transcribeQuick` -- a synchronous text-only endpoint that returns 409 if any other transcription is running, then silently fails. It should instead queue the file for full transcription with highest priority.

**Approach:** Add a `addPriorityFiles` action to `importQueueStore` that prepends files to the front of the queue and preempts the currently running job (cancel + reset to pending). Rewire `SessionView`'s `onTranscribeFile` handler to use this new action instead of `transcribeQuick`.

## Boundaries & Constraints

**Always:**
- The displaced (preempted) job must restart from scratch -- no partial state is preserved
- Priority files always go to the front of the queue, ahead of all pending jobs
- The preempted job resets to `pending` and re-enters the queue (not lost, not errored)
- Use `notebook-normal` job type so results are persisted to the database

**Ask First:**
- Whether `trayManager.ts` should allow "Transcribe File..." when a job is already running (currently `enabled: isStandby` -- would need to change to allow preemption)

**Never:**
- Backend changes -- preemption is orchestrated entirely from the frontend using the existing `POST /api/transcribe/cancel` endpoint
- Breaking existing `addFiles` behavior -- `addPriorityFiles` is a new parallel action

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy: idle server | File picked, queue empty, server idle | Job prepended, processQueue starts, file transcribed normally | N/A |
| Preempt: job running | File picked while jobA is `processing` | jobA cancelled + reset to `pending`; priority job runs first; jobA restarts after | Cancel failure is best-effort; priority job still prepended |
| Preempt: queue has pending | File picked, jobA processing, jobB pending | Queue: `[priority, jobA(reset), jobB]` -- priority first, then jobA restarts, then jobB | N/A |
| Queue paused | File picked while queue is paused | Priority job prepended; queue remains paused (user must resume) | N/A |
| readLocalFile fails | Electron IPC file read throws | Job marked `error` with message; queue continues | Normal queue error handling |

</frozen-after-approval>

## Code Map

- `dashboard/src/stores/importQueueStore.ts` -- Queue store: addFiles, processQueue, pause/resume, module-level flags
- `dashboard/components/views/SessionView.tsx:603` -- `onTranscribeFile` handler (currently calls transcribeQuick)
- `dashboard/electron/trayManager.ts:431` -- "Transcribe File..." menu item (currently `enabled: isStandby`)
- `dashboard/src/hooks/useTraySync.ts:167-175` -- `isStandby` calculation that gates the menu item
- `dashboard/src/api/client.ts:371` -- `cancelTranscription()` existing method

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/stores/importQueueStore.ts` -- Add `_preemptedJobId` module-level flag and `addPriorityFiles` action that prepends jobs, sets the flag, and calls `cancelTranscription()` when a job is processing
- [x] `dashboard/src/stores/importQueueStore.ts` -- In `processQueue` catch block, check `_preemptedJobId`: if the failed job was preempted, reset it to `pending` instead of `error`
- [x] `dashboard/components/views/SessionView.tsx` -- Rewire `onTranscribeFile` to read the file path as a native string, then call `useImportQueueStore.getState().addPriorityFiles([filePath], 'notebook-normal')` instead of `transcribeQuick`
- [x] `dashboard/electron/trayManager.ts` -- Change "Transcribe File..." `enabled` from `isStandby` to `canTranscribeFile` (allow when busy, since preemption handles it)
- [x] `dashboard/src/hooks/useTraySync.ts` -- Add `canTranscribeFile` field to `setMenuState` payload so trayManager can gate independently of `isStandby`

**Acceptance Criteria:**
- Given the server is idle, when the user picks a file via the tray, then the file is queued as `notebook-normal` and transcription begins
- Given a transcription is in progress, when the user picks a file via the tray, then the running job is cancelled, the priority file transcribes first, and the displaced job restarts afterward
- Given the queue has pending jobs, when a priority file is added, then it appears before all existing pending jobs in the queue
- Given the queue is paused, when the user picks a file, then the priority file is prepended but the queue does not auto-resume

## Design Notes

The preemption mechanism uses a module-level `_preemptedJobId` sentinel rather than a store field to avoid re-render cascades. Flow:

1. `addPriorityFiles` finds the `processing` job → sets `_preemptedJobId = job.id` → calls `cancelTranscription()` → prepends new jobs
2. The server-side cancel causes the polling loop (`pollForNotebookResult`/`pollForSessionResult`) to detect "job lost" → throws
3. `processQueue` catch block sees `_preemptedJobId === jobId` → resets job to `pending` instead of `error` → clears `_preemptedJobId`
4. The while loop picks the next `pending` job (the priority file, now first in array) → processes normally
5. After the priority job completes, the reset job is next → restarts from scratch

The file path is passed as a string directly to `addPriorityFiles` -- the queue's `processNotebookJob` already handles string paths via `readLocalFile` (line 308-316), so no new file-reading logic is needed in SessionView.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npx vitest run` -- expected: all existing tests pass

**Manual checks:**
- Tray right-click → "Transcribe File..." opens file picker when server is idle AND when a job is running
- Picked file appears at front of Notebook import queue
- If a job was running, it restarts after the priority file completes

## Suggested Review Order

**Priority queue & preemption (core change)**

- New `addPriorityFiles` action: prepends jobs, cancels running job via Set-based sentinel
  [`importQueueStore.ts:465`](../../dashboard/src/stores/importQueueStore.ts#L465)

- Catch block: preempted jobs reset to `pending` instead of `error`
  [`importQueueStore.ts:394`](../../dashboard/src/stores/importQueueStore.ts#L394)

- Module-level `_preemptedJobIds` Set declaration
  [`importQueueStore.ts:153`](../../dashboard/src/stores/importQueueStore.ts#L153)

**Tray handler rewire**

- `onTranscribeFile` now routes through priority queue instead of `transcribeQuick`
  [`SessionView.tsx:604`](../../dashboard/components/views/SessionView.tsx#L604)

**Menu enablement (allows action during processing)**

- `canTranscribeFile` computed: healthy server + not mic-recording + not live
  [`useTraySync.ts:177`](../../dashboard/src/hooks/useTraySync.ts#L177)

- Tray menu uses `canTranscribeFile` instead of `isStandby`
  [`trayManager.ts:436`](../../dashboard/electron/trayManager.ts#L436)

**Type declarations**

- `TrayMenuState` interface updated with `canTranscribeFile`
  [`trayManager.ts:47`](../../dashboard/electron/trayManager.ts#L47)

- Renderer-side type declaration
  [`electron.d.ts:53`](../../dashboard/src/types/electron.d.ts#L53)

- IPC handler inline type
  [`main.ts:1572`](../../dashboard/electron/main.ts#L1572)
