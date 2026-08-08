# Design: Salvage-aware busy popup + salvage progress notification

Date: 2026-08-08
Status: Approved (pending user review of this document)

## Problem

When audio sent to the server is dropped (client OOM/crash, or the user cancelled the
main transcription while recording or processing), the server transcribes it anyway
("salvage", GH-239 / PR #278). This is a conscious decision. Two UX gaps remain:

1. While a salvage is running, starting a new recording is rejected with a generic
   inline error: `Server busy - {active_user} is active`
   (`dashboard/src/hooks/useTranscription.ts:364`). The user has no way to know a
   salvage is the cause, nor a way to drop it and proceed.
2. The salvage's progress is invisible. Its `processing_progress` WS messages go to
   the dead socket and are silently dropped (`server/backend/api/routes/websocket.py`,
   `send_message()` early-returns `False` on a non-connected socket).

## Decisions made during brainstorming

- **Drop flow: automatic restart.** After the user confirms dropping the salvage, the
  dashboard cancels it, waits for the job slot to free, and starts the new recording
  automatically. No second Record press.
- **Popup scope: any salvage, only salvage.** The popup appears for any in-progress
  salvage regardless of which client's recording it was (the text names the owner).
  If the server is busy with a normal active job of another client, the current
  generic busy error is kept - we do not want to invite cancelling another device's
  live session.
- **Architecture: job_tracker salvage flag + `/api/status` polling** (Approach A).
  Rejected: push via `emit_event` JSONL (Electron-host-only file; silently dead in
  remote-server mode) and a new general job-events WS/SSE channel (right long-term,
  far larger scope - YAGNI here).

## Key facts the design rests on (verified in code)

- The salvage holds the single `TranscriptionJobTracker` slot until it finishes.
  `finalize_interrupted_recording()` (`websocket.py:906-979`) runs before `cleanup()`,
  and `cleanup()` -> `_release_job()` -> `job_tracker.end_job()` frees the slot.
- `POST /api/transcribe/cancel` (`transcription.py:615-641`) reaches an in-progress
  salvage: disconnect-based cancellation is muted during salvage but explicit
  `job_tracker.is_cancelled()` is not (`websocket.py:503-506`).
- Only whisper.cpp aborts compute mid-flight (sidecar transport polls
  `cancellation_check` every 0.25s). Every other backend (faster-whisper, whisper(x),
  NeMo Parakeet/Canary, MLX variants, SenseVoice, VibeVoice) runs to completion inside
  an unkillable executor thread; cancellation is observed only after the backend call
  returns (`engine.py:973-984`) and decides whether the finished result is persisted
  (`completed`) or discarded (`failed`). Practical effect: after a drop, the slot
  frees within seconds up to roughly the remaining compute time (typically well under
  a minute), which the auto-restart flow simply waits out.
- No data loss on drop: the WAV is written to `durability.recordings_dir` before the
  transcription call and before any `await` (`websocket.py:391-429`). A cancelled
  salvage ends `status='failed'` with `audio_path` intact -> retryable via
  `POST /api/transcribe/retry/{job_id}`. A whisper.cpp cancel with >=1 finished chunk
  ends `completed` + `partial=true` -> also retryable.
- `GET /api/status` is public (`api/main.py:186`) and already returns
  `job_tracker.get_status()` = `{is_busy, active_user, active_job_id, progress:
  {current, total, phase}, ...}` - progress is already tracked server-side during a
  salvage (same `process_transcription()` path); nothing reads it today.
- The notification center (`dashboard/src/stores/notificationsStore.ts`) supports
  upsert-by-`id` with a 0-100 `progress` bar - same pattern as docker/model download
  notifications (`useNotificationBridge.ts:109-155`).

## Design

### 1. Backend: salvage flag on the job tracker

`server/backend/core/model_manager.py`, `TranscriptionJobTracker`:

- New field `_salvage_info: dict | None` holding `{job_id, client_name, started_at}`.
- New method `mark_salvage(job_id)` (under `self._lock`; no-op if `job_id` does not
  match `_active_job_id`). Called from `finalize_interrupted_recording()` right before
  `await self.process_transcription()` (`websocket.py:~968`).
- Cleared in `end_job()` (which every teardown path reaches via `cleanup()` ->
  `_release_job()`), and defensively in `try_start_job()` on successful acquisition.
- `get_status()` gains `"salvage": {"active": bool, "job_id": str, "client_name": str}
  | None`. Automatically exposed via `GET /api/status` and `GET /api/admin/status`.
- The junk-job guard (buffered audio below `durability.min_salvage_seconds`) never
  sets the flag - no salvage runs in that path.

### 2. Backend: `session_busy` payload + honest cancel message

- `handle_client_message()` busy rejection (`websocket.py:1031-1043`): payload becomes
  `{"active_user": ..., "is_salvage": bool, "salvage_job_id": str | None}` (additive,
  backwards compatible).
- In `process_transcription()`'s cancelled branch, when `self._salvage_reason` is set,
  persist `"Salvage cancelled by user - audio saved for retry"` instead of the
  hardcoded `"Cancelled: client disconnected"`. Status remains `'failed'`,
  `audio_path` intact, `/retry/{job_id}` eligibility unchanged.

### 3. Dashboard: structured busy state in `useTranscription`

`dashboard/src/hooks/useTranscription.ts`, case `'session_busy'`:

- New state field `busyInfo: {activeUser: string, isSalvage: boolean,
  salvageJobId: string | null} | null`, cleared on `reset()`/`start()`.
- `is_salvage === false` (or field absent - old server): current behavior, generic
  error string, status `'error'`.
- `is_salvage === true`: set `busyInfo`, return status to `'idle'` (not `'error'`),
  disconnect the socket as today. `'idle'` avoids flashing the red error box and keeps
  `canStartRecording` semantics intact (`SessionView.tsx:865-868`).

### 4. Dashboard: popup and drop flow (SessionView)

- Reuse `useConfirm()` (`dashboard/src/hooks/useConfirm.tsx`; same usage pattern as
  `AudioNoteModal.tsx:961`). Trigger: `busyInfo?.isSalvage` becomes non-null after a
  start attempt.
- Copy (UI is English): title "Recovery in progress"; message "The server is still
  transcribing an interrupted recording (from {user}). Stop it and start your new
  recording? The interrupted audio is saved and can be retried later."; confirm label
  "Stop and record".
- On confirm:
  1. `POST /api/transcribe/cancel` via a new `apiClient.cancelTranscription()` method
     (add if absent).
  2. Show an inline "Stopping salvage..." indicator (not the red error box).
  3. Poll `GET /api/status` every 1s until `is_busy === false`, timeout 120s.
  4. Re-run the full `handleStartRecording()` path - it re-validates and
     rebuilds the start options from current component state, so the restart
     behaves exactly like a fresh Record press.
- On decline: stay `'idle'`, no error shown; the progress notification (section 5)
  keeps informing about the salvage.
- Race handled: if the salvage finishes on its own before the cancel lands, the cancel
  returns `success: false` ("No transcription job is currently running") - treat as
  "already free" and go straight to the start step.

### 5. Dashboard: salvage progress notification

- New hook `useSalvageProgress` mounted once at the app root (next to
  `useNotificationBridge` in `App.tsx`), backed by a small zustand `salvageStore`
  (nudge API + `lastCompletedAt`).
- Polling `GET /api/status`: idle checks on mount, on window focus, and every 15s;
  fast polling every 2s while `salvage.active` is true. Immediate-check nudges from
  `useTranscription`: on `session_busy` with `is_salvage`, and on unexpected socket
  close during recording/processing (the same-session OOM/cancel case).
- Notification upsert: `notify({id: 'salvage-' + jobId, category: 'transcription',
  title: 'Recovering interrupted recording', detail: '<owner> - <phase>', status:
  'active', progress: Math.round(current / total * 100)})`. `current`/`total` are
  audio-seconds from the job tracker progress.
- Terminal transitions when the salvage ends (flag gone / `is_busy` false):
  - Dropped by the user: the SessionView drop flow calls
    `salvageStore.markDropRequested(jobId)` before sending the cancel; the monitor
    then renders `status: 'complete'`, detail "Stopped - recording saved, retry
    available" without querying job outcome.
  - Completed and job is ours: presence in `GET /api/transcribe/recent` confirms
    completion -> `status: 'complete'`, detail "Transcript recovered - available in
    Main Transcription". The monitor must NOT call `GET /api/transcribe/result/{id}`
    for this check: a 200 response marks the job delivered as a side effect, which
    would remove it from the recovery banner.
  - Absent from `/recent` and no drop was requested: call
    `GET /api/transcribe/result/{job_id}`; a 410 means failed and carries
    `error_message` (no delivered side effect on 410) -> `status: 'error'` with that
    message.
  - Another client's salvage (`/recent` is client-scoped and the result endpoint
    403s for us): generic `status: 'complete'`, detail "Recovery finished".
- `salvageStore.lastCompletedAt` is watched by `SessionView` to call
  `refreshRecoveryJobs()` immediately, so the recovery banner appears without waiting
  for the next window-focus refresh.

### 6. Scope boundaries

- Popup only on the Main Transcription record path. HTTP entry points (`/import`,
  `/quick`, OpenAI-compatible, retry) keep their 409/429 responses.
- Live Mode is untouched - it has its own session gate (`live.py:632-642`) and never
  passes through `job_tracker`.
- The existing 15-minute same-session recovery poll in `useTranscription` stays as is;
  the notification complements it.

### 7. Error handling

- Cancel request fails -> surface the error, abort the auto-start.
- Status-poll timeout (120s) -> "Could not free the server - try again" error state.
- Status-poll network failures -> silent retry next tick (server-down is surfaced by
  existing app-level indicators).
- Slot stolen by another client between free and our start -> a fresh `session_busy`
  arrives and the flow branches correctly again (popup if salvage, generic error
  otherwise).

### 8. Testing

- Backend (run full suite from `server/backend/` with the build venv):
  - `TranscriptionJobTracker` salvage-flag lifecycle (mark, expose in `get_status()`,
    cleared on `end_job()` and on new `try_start_job()`).
  - `session_busy` payload includes `is_salvage`/`salvage_job_id` (watch the known
    trap: the three session test-factories break on any new session attribute).
  - Cancelled-salvage rows persist the new error message and stay retryable.
- Dashboard (vitest, Node 22):
  - Update the existing `session_busy` test (`useTranscription.test.ts:301`); add
    `busyInfo` coverage for both salvage and non-salvage payloads plus old servers
    (field absent).
  - Popup flow: confirm -> cancel POST -> poll -> auto-start; decline -> idle; the
    "already finished" cancel race.
  - `useSalvageProgress`: notification upsert with progress, all four terminal
    transitions, nudge triggers.
- UI contract: run `npm run ui:contract:check` from `dashboard/` after the SessionView
  edits (mind the comment quote-parity trap).

## Out of scope

- No new WS/SSE event channel.
- No changes to Live Mode concurrency or to HTTP busy responses.
- No per-client targeting for `POST /api/transcribe/cancel` (stays global, as today).
- No attempt to interrupt non-whisper.cpp backend compute mid-flight.
