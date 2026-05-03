---
title: 'Wave 3 — Recover From Everything'
type: 'feature'
created: '2026-03-30'
status: 'done'
baseline_commit: 'f4a9d4e29e36f755b755e8607b1d9b59739baaf2'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After a server crash or `docker stop`, jobs that were mid-transcription remain
stuck in `status='processing'` forever (no startup recovery), the dashboard has no way to
surface undelivered results to the user, active recordings are killed without completing,
and results larger than ~1 MB can overflow WebSocket frame limits.

**Approach:** Add four targeted fixes: (1) on startup, find orphaned `processing` jobs and
mark them failed with a retry hint; (2) on the dashboard, poll for undelivered results and
show a dismissible notification; (3) on graceful shutdown, stop recording sessions and let
their transcriptions complete before the container exits; (4) for results >1 MB, send a
`result_ready` reference instead of the full payload, and let the client fetch via HTTP.

## Boundaries & Constraints

**Always:**
- `recover_orphaned_jobs()` runs AFTER `init_db()`, BEFORE model preload — no DB access before init
- Orphaned = `status='processing'` AND `created_at < now − orphan_job_timeout_minutes`
- If `audio_path` on disk: mark failed `"Server restarted — use retry to re-transcribe"`
- If no `audio_path` or file absent: mark failed `"Server restarted — audio not preserved"`
- `GET /recent` enforces the same client-name auth pattern as `GET /result/{job_id}`
- Large-result threshold is **1,000,000 bytes** of the serialized `result_payload` JSON
- Graceful drain: `asyncio.wait_for(session.stop_recording(), timeout=120)` per recording
  session; eat `TimeoutError` with a warning — Wave 1 already persisted the result to DB
- `stop_grace_period: 130s` added to `docker-compose.yml` service block (not healthcheck)
- Read `orphan_job_timeout_minutes` from `config.yaml` `durability.orphan_job_timeout_minutes`
  (key already exists in Wave 2 config block, default 10)

**Ask First:** None — all decisions follow established Wave 1/2 patterns.

**Never:**
- Do not add a new Alembic migration — schema is complete from Wave 1
- Do not cancel in-progress executor threads in shutdown; only stop `is_recording=True` sessions
- Do not block startup if orphan recovery fails — wrap in try/except, log and continue
- Do not add `stop_grace_period` to the healthcheck block — it belongs on the service level
- Do not change the Docker overlay files — only `docker-compose.yml` (base)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Startup — orphaned job w/ audio | `processing`, `audio_path` on disk | `mark_failed("Server restarted — use retry...")` + log | — |
| Startup — orphaned job, no audio | `processing`, no `audio_path` or file missing | `mark_failed("Server restarted — audio not preserved")` + log | — |
| Startup — orphan recovery throws | DB error during scan | Log error, continue startup — never crash | try/except around whole function |
| GET /recent — results exist | Client w/ completed+undelivered rows | List of `{job_id, completed_at, text_preview}` (limit 5) | — |
| GET /recent — no results | No undelivered rows for client | `[]` | — |
| Large result | Serialized payload > 1 MB | `result_ready` msg with `job_id`; client fetches via HTTP | — |
| Normal result | Serialized payload ≤ 1 MB | `final` msg with full payload (unchanged) | — |
| Graceful drain — recording active | `is_recording=True` at shutdown | `stop_recording()` completes; result persisted + delivered | Timeout 120s: log warning, proceed |
| Dismiss notification | User clicks Dismiss | `POST /api/transcribe/result/{job_id}/dismiss` → `mark_delivered`; notification gone | 404/403: ignore silently |

</frozen-after-approval>

## Code Map

- `server/backend/database/job_repository.py` — add `get_orphaned_jobs(timeout_minutes)` query
- `server/backend/api/main.py` — `recover_orphaned_jobs()` startup fn; graceful drain in shutdown; import `_connected_sessions` from websocket
- `server/backend/api/routes/transcription.py` — add `GET /recent` + `POST /result/{job_id}/dismiss`
- `server/backend/api/routes/websocket.py` — add result-size check before `send_message("final", ...)`
- `dashboard/src/hooks/useTranscription.ts` — handle `result_ready` message type
- `dashboard/components/views/SessionView.tsx` — recovery notification state + render banner
- `server/docker/docker-compose.yml` — add `stop_grace_period: 130s` to service definition

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/database/job_repository.py` — ADD `get_orphaned_jobs(timeout_minutes: int) -> list[dict]`: query `WHERE status='processing' AND created_at < cutoff`; cutoff = `(datetime.now(UTC) - timedelta(minutes=timeout_minutes)).isoformat()`; return list of dicts — provides input for startup recovery scan
- [x] `server/backend/api/main.py` — ADD `async def recover_orphaned_jobs(timeout_minutes: int) -> None`: call `get_orphaned_jobs()`; for each row: if `audio_path and Path(audio_path).exists()` → `mark_failed(job_id, "Server restarted — use retry to re-transcribe")` else → `mark_failed(job_id, "Server restarted — audio not preserved")`; `logger.info("Recovered orphaned job %s (%s)", job_id, status_reason)`; wrap entire function in try/except with `logger.error`; add `# Adapted from Scriberr (https://github.com/rishikanthc/Scriberr) — startup recovery pattern` attribution comment — marks orphaned jobs so users see actionable status
- [x] `server/backend/api/main.py` — CALL `await recover_orphaned_jobs(orphan_job_timeout_minutes)` in lifespan, after `init_db()` and before model preload; read `orphan_job_timeout_minutes` from the already-read `durability_config` dict (`durability_config.get("orphan_job_timeout_minutes", 10)`) — startup recovery runs exactly once per boot
- [x] `server/backend/api/main.py` — MODIFY lifespan shutdown block (after `yield`): `from server.api.routes.websocket import _connected_sessions`; iterate sessions where `session.is_recording`; call `await asyncio.wait_for(session.stop_recording(), timeout=120.0)` in a try/except `TimeoutError` (log warning on timeout) — drains active recording sessions before container exits
- [x] `server/backend/api/routes/transcription.py` — ADD `GET /recent`: call `get_client_name(request)`; call `get_recent_undelivered(client_name, limit=5)`; for each row parse `result_json` and build `{"job_id": ..., "completed_at": ..., "text_preview": result_data.get("text","")[:100]}`; return list — enables dashboard recovery notification
- [x] `server/backend/api/routes/transcription.py` — ADD `POST /result/{job_id}/dismiss`: call `get_client_name(request)`; `get_job(job_id)` → 404 if missing; 403 if client mismatch; call `mark_delivered(job_id)`; return `{"job_id": job_id}` — lightweight dismiss that doesn't transfer result payload
- [x] `server/backend/api/routes/websocket.py` — MODIFY `process_transcription()` after `save_result()`: `_result_size = len(json.dumps(result_payload))`; `if _result_size > 1_000_000 and self._current_job_id:` → `await self.send_message("result_ready", {"job_id": self._current_job_id})` + skip `send_message("final", ...)` else → existing `send_message("final", result_payload)` logic unchanged — prevents oversized WebSocket frames for very long transcriptions
- [x] `dashboard/src/hooks/useTranscription.ts` — ADD case `result_ready` in `handleMessage`: extract `job_id = msg.data?.job_id as string`; call `fetch(`/api/transcribe/result/${job_id}`)`; on 200: parse and `setResult(...)` + `setStatusTracked('complete')`; on error: `setError('Result too large to stream — fetch failed')` + `setStatusTracked('error')` — client-side handler for large-result redirect
- [x] `dashboard/components/views/SessionView.tsx` — ADD recovery notification: import `useState, useEffect`; `const [recoveryJobs, setRecoveryJobs] = useState<Array<{job_id:string, completed_at:string, text_preview:string}>>([])`;  `useEffect(() => { fetch('/api/transcribe/recent').then(r=>r.json()).then(setRecoveryJobs).catch(()=>{}) }, [])`; render a dismissible banner per job: `"A transcription from [relative_time] is available. [View] [Dismiss]"`; View → `fetch(/api/transcribe/result/${job.job_id})` then load result into transcription panel; Dismiss → `fetch(/api/transcribe/result/${job_id}/dismiss, {method:'POST'})` then remove from list — surfaces recovered results without interrupting normal workflow
- [x] `server/docker/docker-compose.yml` — ADD `stop_grace_period: 130s` to the `transcriptionsuite:` service block (at the same indentation level as `restart:`) — gives Docker 130s before SIGKILL, matching the 120s drain timeout

**Acceptance Criteria:**
- Given orphaned `processing` jobs exist on startup, when the server boots, then each is marked `failed` with an appropriate message and logged within 5s of `init_db()`
- Given orphan recovery throws an exception, when the server boots, then startup proceeds normally (no crash)
- Given a client has undelivered completed jobs, when `GET /api/transcribe/recent` is called, then the list is returned and the dashboard shows a notification banner
- Given a user clicks "Dismiss", when `POST /api/transcribe/result/{job_id}/dismiss` is called, then `delivered=1` is set and the notification disappears
- Given a transcription result is >1 MB serialized, when processing completes, then the client receives `result_ready` with a job_id and fetches the result via HTTP
- Given `docker stop` with an active recording, when the container receives SIGTERM, then the recording stops and the transcription completes (or times out after 120s with a warning)
- Given all of the above, when the existing test suite runs, then all previously-passing tests still pass

## Design Notes

**Orphan timeout:** The 10-minute default for `orphan_job_timeout_minutes` means jobs created within the last 10 minutes are NOT orphaned — they might be legitimately in-progress on first boot. This guards against falsely orphaning a job that just started when the server was restarted for unrelated reasons.

**Recovery notification timing:** `useEffect(..., [])` fires after the component mounts. The fetch is fire-and-forget with `.catch(()=>{})` — if the server is unreachable, the notification simply doesn't appear. Do not block rendering or show an error for this.

**`stop_grace_period` placement:** This must be at the service level in `docker-compose.yml`, not inside the `healthcheck:` block. Correct placement:
```yaml
services:
  transcriptionsuite:
    ...
    restart: "no"
    stop_grace_period: 130s
    healthcheck: ...
```

**Large result note:** Results >1 MB require a transcription of roughly 3+ hours. This is an edge case today, but becomes relevant with NeMo backends that produce dense word-level timestamps.

## Verification

**Commands:**
- `cd server && python -m pytest backend/tests/ -x -q` — expected: same pass count as baseline, no new failures
- `cd server && python -m alembic upgrade head` — expected: no new migration (already at head)

**Manual checks:**
- Inject a `processing` row into `transcription_jobs` with `created_at` > 10 min ago; restart server; verify row becomes `failed` in DB
- `GET /api/transcribe/recent` with an undelivered completed job; verify list returned
- `POST /api/transcribe/result/{job_id}/dismiss`; verify `delivered=1` in DB
- Start a recording; run `docker stop` (with grace period); verify transcription completes in logs

## Suggested Review Order

**Startup recovery**

- DB query with strftime fix: matches SQLite's `YYYY-MM-DD HH:MM:SS` default, not isoformat
  [`job_repository.py:180`](../../server/backend/database/job_repository.py#L180)

- Recovery function: audio-path check determines retry-able vs. lost message
  [`main.py:83`](../../server/backend/api/main.py#L83)

- Called in lifespan after `init_db()`, before model preload — ordering is critical
  [`main.py:407`](../../server/backend/api/main.py#L407)

**Graceful shutdown drain**

- Iterates `is_recording` sessions; `asyncio.wait_for(stop_recording(), 120s)` then continue
  [`main.py:531`](../../server/backend/api/main.py#L531)

**Large-result WebSocket bypass**

- Size check post-`save_result`; >1 MB sends reference, skips inline payload
  [`websocket.py:292`](../../server/backend/api/routes/websocket.py#L292)

- `result_ready` handler fetches via HTTP; `jobIdRef` cleared before disconnect to kill poll race
  [`useTranscription.ts:191`](../../dashboard/src/hooks/useTranscription.ts#L191)

**Recovery notification (dashboard)**

- `recoveryJobs` state + mount-time fire-and-forget fetch; `loadResult` on the interface
  [`useTranscription.ts:60`](../../dashboard/src/hooks/useTranscription.ts#L60)

- `loadResult` implementation: sets result + transitions to complete in one call
  [`useTranscription.ts:373`](../../dashboard/src/hooks/useTranscription.ts#L373)

- `GET /recent` builds `{job_id, completed_at, text_preview}` list; same auth as result fetch
  [`transcription.py:1068`](../../server/backend/api/routes/transcription.py#L1068)

- `POST /dismiss`: marks delivered without transferring payload — lightweight dismiss path
  [`transcription.py:1100`](../../server/backend/api/routes/transcription.py#L1100)

- Amber banner render with View/Dismiss; View calls `transcription.loadResult(r)` directly
  [`SessionView.tsx:1037`](../../dashboard/components/views/SessionView.tsx#L1037)

- Recovery state + mount-time effect that populates the banner
  [`SessionView.tsx:877`](../../dashboard/components/views/SessionView.tsx#L877)

**Config / peripherals**

- `stop_grace_period: 130s` at service level (120s drain + 10s buffer before SIGKILL)
  [`docker-compose.yml:118`](../../server/docker/docker-compose.yml#L118)
