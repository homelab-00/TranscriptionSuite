# Session Ephemeral Retention — Design Spec

**Date:** 2026-08-09
**Status:** Approved (design review with user), pending implementation plan

## Problem

The Session tab is meant to be ephemeral: transcribe, hand the result to the client, keep
nothing. Two things currently violate that intent:

1. **The duplicate dialog.** Re-importing a previously transcribed file through the
   Session tab pops `DedupPromptModal` ("Possible duplicate detected… Create new /
   Use existing"). Root cause: `POST /api/transcribe/import` hashes the upload and writes
   a `transcription_jobs` row that exists *purely* as a dedup anchor
   (`server/backend/api/routes/transcription.py:936-940`). No code path ever deletes
   `transcription_jobs` rows, so every past import matches forever. Worse, the dialog's
   "Use existing" button is not actually wired to load anything — a session dedup match
   is a bare hash anchor with no retrievable transcript
   (`dashboard/src/stores/importQueueStore.ts:255-264`).

2. **Permanent retention of session artifacts.** Mic session recordings keep their WAV in
   `durability.recordings_dir` (deleted only after 7 days, and only when delivered) and
   their full `result_text`/`result_json` in the DB **forever** — DB rows are never
   deleted (`server/backend/database/audio_cleanup.py:5-8`).

A related known bug is folded into this work: `_run_file_import` never calls
`save_result`/`mark_failed` on its durability row, so import results live only in the
in-memory `job_tracker` (lost on restart, violating the persist-before-deliver
invariant), and the orphan sweep later flips completed imports to a false
`status='failed'` (`transcription.py:684-875`, `api/main.py:172-175`).

## Goals

1. A Session-tab transcription (mic recording **or** file import) leaves **no server-side
   trace** — no DB row, no audio file — once its result has been **confirmed delivered**
   to the client. The only permanent copy is the Audio Notebook entry, and only when
   auto-add-to-notebook is enabled (mic recordings only).
2. The duplicate dialog never appears in any Session flow.
3. The durability invariant is fully preserved: nothing is deleted before confirmed
   delivery; failed and undelivered jobs are untouched (salvage banner, `/recent`,
   `/result`, `/retry` all keep working exactly as today).
4. The `/import` durability bug is fixed as part of the same lifecycle change.

## Non-goals

- Notebook flows (notebook import, its dedup prompt, manual add, retro-diarize) are
  unchanged.
- Live Mode and the rolling preview are unchanged.
- Auto-add-to-notebook stays **mic-only** (user decision 2026-08-09): session file
  imports are always ephemeral; permanent file imports go through the Notebook import.
- No new UI for browsing/retrying failed jobs.

## User decisions (2026-08-09)

- Scope: the **whole Session tab** (mic + file imports), not just the import flow.
- Auto-add-to-notebook remains mic-only.
- Approach chosen: full durability-pipeline integration ("Approach A"), over
  dialog-suppression-only or no-DB-row-at-all alternatives.

## Design

### 1. Unified session job lifecycle

"Session-source" means exactly: `source='file_import'` rows plus rows created by the WS
mic-session path (whatever `source` value `websocket.py` passes to `create_job` —
implementation must scope purge to these two values only, so rows created by any other
route, e.g. a notebook import, are never touched).

For session-source jobs:

```
create_job (processing)
  → transcribe
  → save_result (completed, delivered=0)      # always BEFORE delivery — unchanged
  → deliver to client
  → confirmed → mark_delivered (delivered=1)
  → [auto-add ON, mic only: notebook save must have succeeded]
  → purge: delete audio file (if any) + DELETE the transcription_jobs row
```

Purge is the only new step. It fires **only** on `delivered=1`.

- **WS mic path:** purge runs during session teardown after `mark_delivered` succeeds
  (`websocket.py:609-616` sets it only when the final actually reached the client) and,
  when auto-add is ON, only after `_save_session_to_notebook` completed successfully. If
  the notebook save fails, purge is **cancelled** — row + WAV are kept so nothing is
  lost, and the existing `_warn_notebook_autoadd_failed` warning fires.
- **Recovery paths:** `GET /result/{job_id}` already calls `mark_delivered` on a 200;
  it now also purges session-source jobs after marking delivered.
  `POST /result/{job_id}/dismiss` (recovery-banner dismiss) now purges as well —
  dismiss means "I don't want it", so nothing needs to remain.
- **Retry:** a successful `/retry` leaves `delivered=0` on purpose so the result
  re-surfaces via `/recent`; it purges like any other job once the client fetches or
  dismisses it.

New repository function `delete_job(job_id)` (DELETE the row; unlink `audio_path` first,
`missing_ok=True`). Purge failures are log-warning only — delivery never fails because
cleanup failed; the backstop sweep (§5) catches stragglers.

### 2. Import path joins the durability pipeline

- `_run_file_import` calls `save_result(...)` on success and `mark_failed(...)` on
  failure/cancel, before touching the in-memory `job_tracker`. This honors
  persist-before-deliver and stops the orphan sweep's false `failed` flips for
  completed imports.
- The dashboard's `pollForSessionResult` stops reading results out of
  `/api/admin/status`'s `job_tracker` snapshot. It polls `GET /api/transcribe/result/{job_id}`
  instead: 202 while processing, 410 + error on failure, 200 (+ `mark_delivered` + purge)
  on success. `job_tracker`/admin-status remains for **progress reporting only**.
- Net durability win: an import that completes while the dashboard is down survives a
  server restart and is recoverable — today it is silently lost with the in-memory
  tracker.

### 3. Dedup removed from session imports

- `/import` stops computing `audio_hash`/`normalized_audio_hash` and stops calling
  `find_duplicates_anywhere`; `dedup_matches` disappears from its response (the
  normalized-PCM hash decodes the entire file, so this also speeds up import startup).
  `create_job` for imports no longer stores hashes.
- Dashboard: session flows (`session-normal`, `session-auto`) never prompt.
  `resolveDuplicateChoice`'s session branches, the `DuplicatePolicy` type, and the
  `folderWatch.duplicatePolicy` config key (+ its Settings UI) are removed — the policy
  existed only to keep unattended Folder Watch batches from blocking on this dialog
  (GH-120), which can no longer happen. `DedupPromptModal` itself stays: the Notebook
  import dedup (real, retrievable entries in `recordings`) is unchanged.

### 4. Safety net unchanged for anything not delivered

- Completed, `delivered=0` (WS drop, salvage, >1MB reference): kept; recovery banner via
  `/recent` exactly as today. Recover → fetch → purge. Dismiss → purge.
- Failed **mic** jobs (WAV on disk): row + WAV retained indefinitely (status quo) so
  `/retry/{job_id}` keeps working. Successful retry → redelivery → purge.
- Failed **import** jobs have no recoverable audio (`/import` always unlinks its temp
  file), so nothing retryable remains. The row is purged as soon as the polling client
  receives the failure (`GET /result/{job_id}` → 410): the error has been delivered and
  only an error message would be lost. A failed import whose client never polls (e.g.
  dashboard crash) is left in place and cleaned by the backstop sweep.
- The orphan sweep is unchanged (and, with §2, stops mislabeling imports).

### 5. Backstop sweep

`cleanup_old_recordings` currently deletes only the WAV of
`completed AND delivered=1` jobs older than `audio_retention_days`. It is extended
(session sources only) to also delete the **row**, and to delete aged
`failed AND source='file_import'` rows (no audio, nothing retryable — covers a failed
import whose client never polled). With immediate purge in place this sweep only catches
crash-window stragglers (e.g. a crash between `mark_delivered` and purge). Existing
config keys keep their meaning; no new config is added.

### 6. One-time legacy cleanup

On startup (folded into the same cleanup task), purge what has already accumulated:

- All `source='file_import'` rows with `result_text IS NULL AND audio_path IS NULL` —
  bare dedup anchors, nothing recoverable, any status. This removes the rows that
  trigger today's dialog.
- All session-source rows with `status='completed' AND delivered=1` — already handed
  over; row + WAV purged.
- Anything failed or undelivered is **not** touched.

## Error handling summary

| Failure | Behavior |
|---|---|
| Purge fails (DB or unlink) | Warning log; delivery unaffected; backstop sweep retries later |
| Crash between mark_delivered and purge | Backstop sweep deletes row + WAV |
| Notebook auto-add save fails | Purge cancelled; row + WAV kept; existing warning surfaces |
| Import fails | `mark_failed`; row purged once the client polls the 410 (nothing retryable — imports keep no audio); backstop sweep if never polled |
| Client never fetches import result | Row stays `completed/delivered=0`; recovery banner offers it; purge on fetch/dismiss |

## Testing

- **Backend** (direct-call route-test pattern, full suite via build venv):
  import success → `save_result` called, row completed; import failure → `mark_failed`;
  `/result` fetch of a session job → row gone + WAV gone; dismiss → purged;
  retry → redeliver → purged; notebook-save failure → not purged; legacy sweep deletes
  anchors + delivered rows but never failed/undelivered; backstop sweep row deletion.
- **Dashboard** (vitest, Node 22): `importQueueStore` polls `/result`, handles
  202/410/200; no dedup prompt on any session flow; Folder Watch unaffected by config
  key removal.
- **Traps:** the three WS session test-factories break on any new session attribute;
  `ui:contract:check` after touching SettingsModal; electron-store defaulted keys never
  read back as `undefined` (removing the `duplicatePolicy` default is safe — stale stored
  values are simply ignored).

## Risks

- **GH #202:** the >1MB recovery fetch resolves to `file://` in packaged builds. Import
  polling must go through the standard `apiClient` base-URL plumbing (same as
  `getAdminStatus`), not the code path with that bug; verify large-result import fetch
  in a packaged build during smoke.
- Moving import delivery from admin-status polling to `/result` changes timing/shape of
  the import happy path — the import queue tests and the PR #285 progress block both
  touch `pollForSessionResult`; coordinate to avoid conflicts.
- Deleting delivered rows removes the "ask the DB later" last-resort for session jobs.
  Accepted by design: the Session tab is ephemeral; permanent copies belong to the
  Notebook.

## Key code references

- Dialog: `dashboard/components/import/DedupPromptModal.tsx`,
  `dashboard/src/stores/dedupChoiceStore.ts`,
  `dashboard/src/stores/importQueueStore.ts:283-295, 356-413`
- Import route: `server/backend/api/routes/transcription.py:878-1032` (handler),
  `:684-875` (`_run_file_import`)
- Dedup query: `server/backend/database/dedup_query.py:28-87`
- Job repo: `server/backend/database/job_repository.py` (`save_result:152`,
  `mark_delivered:189`, `mark_failed:203`, `get_jobs_for_cleanup:352`)
- WS persist/deliver ordering: `server/backend/api/routes/websocket.py:563-620`;
  auto-add: `:645-665`, `_save_session_to_notebook:99-176`
- Cleanup: `server/backend/database/audio_cleanup.py`, `server/backend/api/main.py:465-482`
- Recovery endpoints: `transcription.py:1088-1128` (`/result`), `:1488-1515` (`/recent`),
  `:1518-1538` (dismiss), `:1131-1207` (`/retry`)
