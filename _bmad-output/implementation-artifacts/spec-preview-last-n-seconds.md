---
title: 'Preview last N seconds during main recording'
type: 'feature'
created: '2026-06-14'
status: 'done'
baseline_commit: '180cfbbaf6bb1939afa0c6da95f45a94fab4acd5'
context:
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** During a long main (longform) recording the user loses their train of thought and has no way to glance back at what they just said — the full transcription only appears after "Stop Recording". They need a quick, in-the-moment reminder.

**Approach:** Add a "Preview" button next to Stop Recording / Cancel that, while recording, asks the server to transcribe only the **last N seconds** of audio already buffered server-side and display it ephemerally in the Main Transcription card (labeled "Preview · last Ns"). N defaults to 20s, user-configurable 10–60s in Settings. The preview is a throwaway UX aid — it never interrupts, alters, or replaces the ongoing recording or its final result.

## Boundaries & Constraints

**Always:**
- Reuse audio already accumulated in `TranscriptionSession.audio_chunks` (server memory during recording) — slice only the tail, no client-side buffering, no new transport.
- Run preview as a background task so the WS receive loop keeps consuming incoming audio chunks during transcription.
- Reuse the session's existing `language`, `translation_enabled`, `translation_target_language` so preview output matches what the final result will look like.
- Clamp duration defensively on the server to 10–60s regardless of client value.
- The preview box uses the same visual style/location as the existing result box.

**Ask First:**
- Any change that would make the preview persist a job, write to the DB, or touch `create_job`/`save_result` — this feature is deliberately ephemeral (see Never).
- Adding a new STT model load path or changing the model-swap lifecycle.

**Never:**
- **Never persist preview results** (no `create_job`, no `save_result`, no `transcription_jobs` row). This is the one deliberate exception to the persist-before-deliver invariant — justified because the live recording continues uninterrupted and its full result IS persisted at Stop, and a preview is trivially reproducible. Data-loss invariant is unaffected.
- Never stop, cancel, mutate, or clear `audio_chunks` / recording state when previewing.
- Never block the WS message loop on transcription.
- No new backend config.yaml key — duration is a client setting sent per-request.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Recording active, ≥N s buffered, `{type:'preview', data:{duration_seconds:20}}` | `preview_result` with `{text, language, requested_seconds, actual_seconds}` for last 20s; recording unaffected | N/A |
| Short buffer | Recording active, only 6s buffered, request 20s | Transcribe whatever exists; `actual_seconds≈6` | N/A |
| Out-of-range duration | request `duration_seconds:5` or `900` | Clamp to 10 / 60 before slicing | N/A |
| Not recording | `preview` received while not recording | `preview_error` "Not recording" | Send error, no crash |
| No audio yet | Recording active, `audio_chunks` empty | `preview_error` "No audio captured yet" | Send error |
| Overlapping request | preview already running | Ignore/reject second request | `preview_error` "Preview already in progress" |
| Transcription throws | engine error mid-preview | `preview_error` with message; recording continues | Catch, log, send error |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/websocket.py` -- `TranscriptionSession` + `handle_client_message` dispatch (line ~644); add `preview` branch + `preview_transcription()` method; `add_audio_chunk`/`audio_chunks` (88,122), float32 conversion pattern (141-144), engine call pattern (206-262), `self.sample_rate`/`language`/`translation_enabled` attrs. Flip leftover `preview_enabled:False` (489) → True.
- `server/backend/core/stt/engine.py` -- `AudioToTextRecorder.transcribe_audio(audio_data, sample_rate, language, task, translation_target_language, word_timestamps=False)` (~839) — in-memory primitive for the tail buffer.
- `server/backend/core/model_manager.py` -- `ensure_transcription_loaded()` (~721) — guarantees model loaded before preview.
- `dashboard/src/hooks/useTranscription.ts` -- add `preview()` method + preview state; handle `preview_result`/`preview_error` in `handleMessage` (206-272); clear preview in `start`/`reset`; expose in return object (424).
- `dashboard/components/views/SessionView.tsx` -- add Preview `<Button>` in control group (1681-1712, shown only when `isRecording`); `handlePreview` reading `audio.previewDurationSeconds`; preview display box after the button row (~1719) mirroring result box (1722-1757).
- `dashboard/components/views/SettingsModal.tsx` -- add numeric input in Client tab mirroring grace-period spinner (~1197-1240); `clientSettings` state/load/save (224,380,529).
- `dashboard/src/config/store.ts` + `dashboard/electron/main.ts` -- add `audio.previewDurationSeconds` (default 20) to interface, `DEFAULT_CONFIG`, and electron-store defaults.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/websocket.py` -- Add `elif msg_type == "preview":` → `asyncio.create_task(session.preview_transcription(int(message.get("data",{}).get("duration_seconds",20))))`. Add `async def preview_transcription(self, duration_seconds)`: guard `is_recording` + non-empty `audio_chunks`; reject if `self._preview_in_progress`; clamp 10–60; slice tail bytes (`bytes_needed = clamped * self.sample_rate * 2`, walk `audio_chunks` from end, drop odd trailing byte); int16→float32 (mirror 141-144); `engine = await asyncio.to_thread(model_manager.ensure_transcription_loaded)`; run `engine.transcribe_audio(..., word_timestamps=False, language=self.language, task/translation from session)` via `run_in_executor`; send `preview_result`; wrap in try/except→`preview_error`; reset flag in `finally`. Set `_preview_in_progress=False` in `__init__`; cancel any preview task in `cleanup`. Flip `preview_enabled` (489) to True.
- [x] `dashboard/src/hooks/useTranscription.ts` -- Add state `previewText/previewLanguage/previewSeconds/previewLoading/previewError`; `preview(durationSeconds)` guarded on `status==='recording'` and not already loading → `sendJSON({type:'preview',data:{duration_seconds}})`; handle `preview_result`/`preview_error`; clear all preview state in `start()` and `reset()`; expose in return.
- [x] `dashboard/components/views/SessionView.tsx` -- Add `handlePreview` (read `audio.previewDurationSeconds` via config API, clamp 10–60 default 20, call `transcription.preview`). Add Preview `<Button variant="secondary" className="shrink-0">` (icon `Eye`/`ScanText`) shown when `isRecording`, disabled while `previewLoading`. Add preview box after control row: shown when `previewLoading||previewText||previewError`, header "Preview · last {n}s", spinner while loading, error styled like existing error block, reuse result-box classes.
- [x] `dashboard/src/config/store.ts`, `dashboard/electron/main.ts` -- Add `audio.previewDurationSeconds: number` default `20`.
- [x] `dashboard/components/views/SettingsModal.tsx` -- Add "Preview Duration (seconds)" numeric spinner (min 10, max 60, step 5) in Client tab; wire state/load/save; helper text "Seconds of recent audio the Preview button transcribes (10–60)."
- [x] `server/backend/tests/test_websocket_preview.py` -- Unit-test the I/O matrix: happy path, short buffer, clamp, not-recording, empty-audio, overlap, engine-throws; assert NO `create_job`/`save_result` called. Mock `webrtcvad` via `sys.modules`, build session via `object.__new__`, stub engine `transcribe_audio` + `ensure_transcription_loaded`.
- [x] `dashboard/src/hooks/useTranscription.test.ts` -- (if hook test exists / else add) assert `preview()` sends correct WS message and `preview_result`/`preview_error` update state.

**Acceptance Criteria:**
- Given an active recording with ≥20s captured, when the user clicks Preview, then within a few seconds a "Preview · last 20s" box shows the transcribed tail and the recording continues uninterrupted (Stop still produces the full transcript).
- Given the user set Preview Duration to 45 in Settings, when they click Preview, then the request carries 45 and ~45s are transcribed.
- Given no preview job is ever written, when a preview runs, then no row appears in `transcription_jobs` and no audio file is created for it.
- Given the user is not recording, when a `preview` arrives, then the server replies `preview_error` and does not crash.

## Spec Change Log

- **Review iteration 1 (patches, no loopback).** Adversarial review (blind hunter + edge-case hunter + acceptance auditor → PASS). Applied 4 patches without re-derivation: (1) dispatcher refuses to overwrite a live `_preview_task` so `cleanup()` always cancels the real in-flight task; (2) `asyncio.get_running_loop()` replaces deprecated `get_event_loop()`; (3) empty-text preview shows "(no speech detected)" instead of a blank box; (4) preview-loading state resets on the server-`error` message and socket `onError` paths so it can't get stuck. Added `test_dispatch_preview_rejected_while_task_running`. Doc-aligned the settings step (1→5). Rejected as safe/idiomatic: int16-mono byte math and `getattr` translation attrs (mirror existing `process_transcription`; attrs verified set in `start_recording`), clamp duplication (cross-codebase defense-in-depth), shared `transcription_lock` serialization (bounded, no data loss).

## Design Notes

Tail-slice without copying the whole buffer (can be ~100MB for long recordings):
```python
need = clamped * self.sample_rate * 2  # int16 mono
buf, total = [], 0
for chunk in reversed(self.audio_chunks):
    buf.append(chunk); total += len(chunk)
    if total >= need: break
tail = b"".join(reversed(buf))[-need:]
if len(tail) % 2: tail = tail[:-1]
audio = np.frombuffer(tail, dtype=np.int16).astype(np.float32) / 32768.0
```
Background task (not inline await) keeps `websocket.receive()` draining audio while the preview transcribes. Snapshot `tail` at task start; later appends to `audio_chunks` are harmless. Frontend gates Preview on `isRecording` only (not connecting/processing) — preview is meaningless once the full result is already coming.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_preview.py -v --tb=short` -- expected: all preview tests pass
- `cd dashboard && npm run typecheck` -- expected: no type errors
- `cd dashboard && npx vitest run src/hooks/useTranscription.test.ts` -- expected: pass (if added)
- `cd dashboard && npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` -- expected: contract check passes (bump `meta.spec_version` first)

**Manual checks:**
- Start a real recording, speak ~30s, click Preview → preview box shows recent words; keep talking, click Stop → full transcript unaffected. Change duration in Settings, repeat.

## Suggested Review Order

**Backend — the core (start here)**

- Entry point: slices the tail of the live buffer and transcribes a copy; never persists, never touches recording state.
  [`websocket.py:140`](../../server/backend/api/routes/websocket.py#L140)

- Dispatch branch: runs the preview as a background task and refuses to overwrite a live one.
  [`websocket.py:765`](../../server/backend/api/routes/websocket.py#L765)

- Cancels any in-flight preview task on session teardown.
  [`websocket.py:679`](../../server/backend/api/routes/websocket.py#L679)

- Server-side clamp bounds (10–60s, default 20).
  [`websocket.py:65`](../../server/backend/api/routes/websocket.py#L65)

**Frontend hook — protocol + state**

- `preview()` sends the WS message; guarded to recording-only and non-overlapping.
  [`useTranscription.ts:451`](../../dashboard/src/hooks/useTranscription.ts#L451)

- `preview_result` / `preview_error` handlers populate ephemeral state.
  [`useTranscription.ts:277`](../../dashboard/src/hooks/useTranscription.ts#L277)

**UI — button + display**

- The Preview button (recording-only, disabled while loading).
  [`SessionView.tsx:1711`](../../dashboard/components/views/SessionView.tsx#L1711)

- The ephemeral preview box (same style as the result box; "(no speech detected)" fallback).
  [`SessionView.tsx:1748`](../../dashboard/components/views/SessionView.tsx#L1748)

- `handlePreview` reads the configured duration and clamps it.
  [`SessionView.tsx:870`](../../dashboard/components/views/SessionView.tsx#L870)

**Settings — the duration knob**

- "Preview Duration (seconds)" numeric input in the Client tab.
  [`SettingsModal.tsx:1247`](../../dashboard/components/views/SettingsModal.tsx#L1247)

- The persisted config key + default (mirrored in electron-store).
  [`store.ts:31`](../../dashboard/src/config/store.ts#L31)

**Tests (peripheral)**

- Backend: I/O matrix + non-persistence + dispatch guard (14 tests).
  [`test_websocket_preview.py:79`](../../server/backend/tests/test_websocket_preview.py#L79)

- Frontend: hook preview behaviour (6 tests).
  [`useTranscription.test.ts:482`](../../dashboard/src/hooks/useTranscription.test.ts#L482)
