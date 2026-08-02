# GH-258 — Speaker Diarization for Session-Tab Recordings — Design Spec

- **Date:** 2026-08-01
- **Status:** Approved design (pending spec review) → next step: implementation plan
- **Area:** WebSocket longform path (`server/backend/api/routes/websocket.py`), new shared dispatch helper (`server/backend/core/`), Session tab UI (`dashboard/components/views/SessionView.tsx`), client config
- **Issue:** [#258](https://github.com/homelab-00/TranscriptionSuite/issues/258) — "Enable diarization for regular recordings on the main Session Tab (not Import)", opened from [#256](https://github.com/homelab-00/TranscriptionSuite/issues/256)
- **Code baseline:** `main` @ `02921d69` (PR #272). All line references below were re-verified against this commit on 2026-08-01, after PRs #269 / #270 / #272 merged.

---

## 1. Problem

Speaker diarization has never run on the microphone/system-audio recording path. It exists only on the three REST import routes:

| Route | File | Diarization dispatch |
|-------|------|----------------------|
| `POST /transcribe` | `api/routes/transcription.py` | lines 349-529 |
| `POST /transcribe/import` | `api/routes/transcription.py` | lines 929-1100 (`_run_import_transcription`) |
| Notebook upload | `api/routes/notebook.py` | lines 877-1041 |
| OpenAI-compatible audio | `api/routes/openai_audio.py` | ~line 181 |

The recording path is the WebSocket: `websocket.py:855` (`start` message) → `TranscriptionSession.process_transcription()` (line 348) → `engine.transcribe_file()` (line 452). The `start` message accepts only `language`, `use_vad`, `translation_enabled`, `translation_target_language`, `profile_id` and `auto_add_to_notebook` (lines 873-927). **There is no diarization field in the protocol at all**, and `AudioToTextRecorder.transcribe_file()` has no diarization parameter — the gap is architectural, not merely unwired.

The reporter in #256 recorded a meeting through the Session tab with the Server-tab "Diarization" card configured, and got no speaker labels. That card only writes `DIARIZATION_MODEL` / `SENSEVOICE_DIARIZATION_ENGINE` env vars at container start (`dockerManager.ts`): it picks **which** engine, never **whether** diarization runs.

### 1.1 The pieces already exist

Nothing new needs to be invented on the ML side:

- `core/parallel_diarize.py` — `transcribe_and_diarize()` (parallel STT + PyAnnote) and `transcribe_then_diarize()` (sequential, for GPUs under ~16 GB VRAM). Both are backend-agnostic and already degrade to `(result, None)` when diarization fails. Since PR #269 both also release the diarization model in a guarded `finally` (lines 103-118 and 269-283), so callers must **not** add their own unload.
- `core/stt/backends/base.py::as_gpu_oom()` (line 62) and `GpuOutOfMemoryError` (line 27), added in PR #269 — translate a CUDA/CTranslate2/torch out-of-memory failure into a typed error carrying an actionable `remedy` string.
- `core/speaker_merge.py` — `build_speaker_segments()` (line 204) merges diarization turns onto word timestamps; `build_speaker_segments_nowords()` (line 282) is the segment-level fallback for backends without word timings (MLX Canary).
- `core/stt/backends/base.py::use_integrated_diarization_for()` (line 282) — decides whether a backend's own single-pass `transcribe_with_diarization()` should be used (WhisperX, VibeVoice always; SenseVoice only when the resolved engine is `funasr`).
- `config.py::resolve_parallel_diarization_default()` (line 540) and `resolve_sensevoice_diarization_engine()` (line 586).

### 1.2 Adjacent findings surfaced during investigation

1. **`expected_speakers` is dead client-side.** `apiClient` accepts it (`client.ts:562`, `:806`, `:882`) but no caller ever populates it. The `diarization.constrainSpeakers` / `diarization.numSpeakers` settings in `SettingsModal.tsx` are written to electron-store and read by nothing. This design revives them.
2. **The `constrainSpeakers` default is a trap.** It ships as `true` with `numSpeakers: 2`. Because the setting is inert today, no user's stored value has any effect anywhere, which makes this the only safe moment to change the shipped default. Per the electron-store gotcha, `config.get()` never returns `undefined` for a defaulted key, so "user chose true" and "default true" are indistinguishable after the fact.
3. **The notebook auto-add path drops speakers.** `_save_session_to_notebook()` (`websocket.py:99`) never passes `diarization_segments` to `save_longform_to_database()`, even though the DB helper accepts it and performs word alignment via `_insert_diarization_segments_with_words()`.
4. **The longform webhook lies.** `websocket.py:598` hardcodes `"num_speakers": 0`.

---

## 2. Goals / Non-Goals

**Goals**

- G1. A normal Session-tab recording can be diarized, with or without VAD, for microphone and system-audio capture.
- G2. The resulting transcript reads as speaker-labelled paragraphs, and the clipboard/paste-at-cursor payload matches exactly what the editor shows.
- G3. The user controls diarization (and optionally an exact speaker count) from the Session tab itself, gated on the server-reported feature availability.
- G4. When auto-add-to-notebook is on, the notebook entry carries real speaker segments, so the existing Notebook speaker UI and `DiarizationReviewView` work on recordings.
- G5. A diarization failure never costs the user their transcript.
- G6. The new dispatch logic lives in one tested module rather than becoming a fourth copy.

**Non-Goals**

- N1. Real-time diarization in Live Mode. Not feasible with publicly available models; explicitly out of scope per #256.
- N2. Wiring `expected_speakers` into the import routes. Those routes work today; changing what they send is a separate PR with its own regression surface.
- N3. Migrating `transcription.py`, `notebook.py` and `openai_audio.py` onto the new shared helper. **Deferred to a dedicated follow-up PR (user decision, 2026-08-01).** The helper is written to serve them, but this PR does not touch working paths.
- N4. Any change to the ephemeral rolling preview (`preview_transcription`, line 248). Previews stay fast and undiarized.

---

## 3. Architecture

### 3.1 New module: `server/backend/core/diarization_dispatch.py`

A single entry point that turns "an audio file plus a diarization request" into "a transcription result whose segments carry speakers".

```python
@dataclass(frozen=True)
class DiarizationOutcome:
    """Why diarization did or did not happen, for client-facing reporting."""
    requested: bool
    performed: bool
    reason: str | None          # "ready" | "token_missing" | "out_of_memory" | "unavailable" | None
    remedy: str | None = None   # actionable hint, populated for out_of_memory


@dataclass(frozen=True)
class DiarizedTranscription:
    result: TranscriptionResult          # .segments carry `speaker`; .num_speakers populated
    speaker_segments: list[dict] | None  # for DB persistence (notebook auto-add)
    outcome: DiarizationOutcome


def transcribe_with_optional_diarization(
    *,
    engine: AudioToTextRecorder,
    model_manager: ModelManager,
    file_path: str,
    enable_diarization: bool,
    language: str | None = None,
    task: str | None = None,
    translation_target_language: str | None = None,
    word_timestamps: bool = True,
    expected_speakers: int | None = None,
    parallel_diarization: bool | None = None,
    diarization_engine: str | None = None,
    sensevoice_engine_default: str = "funasr",
    progress_callback: Callable[[int, int], None] | None = None,
    cancellation_check: Callable[[], bool] | None = None,
) -> DiarizedTranscription: ...
```

Internal flow, mirroring the proven sequence in `transcription.py:349-529`:

1. **Resolve engine strategy** — only when `enable_diarization` is true, so the plain path does zero resolution work. `resolve_sensevoice_diarization_engine()` → `use_integrated_diarization_for()`.
2. **Integrated single-pass path** — `load_audio()` at the backend's `preferred_input_sample_rate_hz`, then `backend.transcribe_with_diarization()`, then build a `TranscriptionResult` from the returned segments/words.
3. **Standard path** — `transcribe_and_diarize()` or `transcribe_then_diarize()` per the resolved parallel flag, then `build_speaker_segments()` on `result.words`, with `build_speaker_segments_nowords()` as the no-word-timestamps fallback.
4. **Plain path** — `engine.transcribe_file()` when diarization is off, unavailable, or already failed.
5. **Return** the result plus the outcome.

**Error contract (load-bearing).** The rule is about *which operation* raised, not which exception type:

- Anything raised by the **diarization attempt** is swallowed: `outcome.performed=False`, `outcome.reason` from `model_manager.get_diarization_feature_status()`, and the full transcript is still returned.
- Anything raised by the **plain transcription** call propagates — that is a genuine transcription failure, and the caller owns it.
- Two exceptions propagate from either operation:
  - `TranscriptionCancelledError` — the user pressed Cancel; it must reach the caller's cancellation handling, not be laundered into "diarization unavailable".
  - `AudioDecodeError` — a corrupt file is not a diarization problem, and plain transcription would fail on it too (the FINDING #1 carve-out at `notebook.py:961-964`).

This deliberately diverges from `transcription.py:440`, which re-raises `ValueError` so the route can answer HTTP 400. The WebSocket path has no status code to choose and one overriding invariant — never lose a completed transcript — so a `ValueError` out of the diarizer (the "diarization requires a HuggingFace token" case) degrades instead, matching the background-worker behaviour at `notebook.py:965-972`.

**Integrated-path fallback.** When a backend's own `transcribe_with_diarization()` fails, the helper falls back to **plain transcription**, not to the two-pass PyAnnote path. This follows `transcription.py:451` rather than `notebook.py:979-985`, which retries. Rationale: the dominant failure is a missing HF token, which the retry cannot fix either, and a user is waiting on a live recording — a second full pass buys nothing and costs minutes.

**OOM classification.** Before falling back to the generic `"unavailable"` reason, a swallowed diarization exception is passed through `as_gpu_oom()`. When it classifies, the outcome becomes `reason="out_of_memory"` with the error's `remedy` attached.

There is a wrinkle: on the standard path, `parallel_diarize` swallows the diarization exception itself and returns `(result, None)`, so no exception ever reaches the helper — exactly the path where a small GPU OOMs. This design therefore adds an optional `on_diarization_error: Callable[[BaseException], None] | None = None` keyword to both `parallel_diarize` entry points, invoked from their existing `except` blocks. Existing callers pass nothing and are byte-for-byte unaffected; the helper passes a collector so the error stays classifiable. This is precisely the #256 reporter's failure mode — a 4 GB RTX 500 Ada running concurrent STT + PyAnnote — and "Diarization ran out of VRAM; free some and retry, or switch to sequential mode" is a far better message than "unavailable". Note that OOM is deliberately excluded from the CUDA retry backoff (`diarization_engine.py::_is_transient_cuda_error`, line 53: `if "out of memory" in msg: return False`), so classification at this layer is the only place the condition can be made legible to the user.

**Word timestamps.** Diarization forces `word_timestamps=True` internally regardless of the caller's flag, because speaker alignment needs them. This mirrors `need_word_timestamps = word_timestamps or diarization` at `transcription.py:455`.

### 3.2 New formatter: `format_speaker_text()` in `core/formatters.py`

```python
def format_speaker_text(result: TranscriptionResult) -> str
```

Coalesces consecutive segments sharing a `speaker` value into one paragraph, prefixes `SPEAKER_00: `, separates turns with a blank line. Reuses the existing `_normalize_speaker_value()` helper (line 17). Returns `result.text` unchanged when no segment carries a speaker, so it is safe to call unconditionally.

This is deliberately **not** `plaintext_export.stream_plaintext()`: that function is notebook-oriented (emits a `# Title` header, bolds labels as `**Speaker:**` for Markdown consumers, and streams for memory-bounded 8-hour exports). The Session tab needs a plain in-memory string with no header.

### 3.3 `api/routes/websocket.py`

**Protocol.** The `start` message gains two optional fields, validated with the same untrusted-input discipline as `profile_id` (lines 879-882):

| Field | Type | Validation |
|-------|------|------------|
| `diarization` | bool | `isinstance(x, bool)` else `False` |
| `expected_speakers` | int \| null | `isinstance(x, int) and 1 <= x <= 10` else `None` |

`TranscriptionSession.__init__` gains `self.diarization_enabled = False` and `self.expected_speakers: int | None = None`; `start_recording()` (line 678) gains the matching keyword arguments, and `handle_client_message` (line 849) resolves them alongside the existing `auto_add_to_notebook` block before calling it at line 922.

**`process_transcription()` changes, in order:**

1. Replace the `engine.transcribe_file(...)` lambda inside `loop.run_in_executor` (line 450-467) with `transcribe_with_optional_diarization(...)`. The keepalive loop, progress plumbing and dual cancellation check (`self._client_disconnected or job_tracker.is_cancelled()`) are unchanged.
2. `parallel_diarization` resolves from `resolve_parallel_diarization_default(get_config())` — this is a threaded worker with no request object, same as `notebook.py:890`.
3. If `outcome.performed`, set `result.text = format_speaker_text(result)` **before** `_build_longform_result_payload()` (line 489).
4. `processing_progress` messages gain a `phase` field read from `model_manager.job_tracker`, so the client can render the existing `jobProgress.ts` labels.
5. The `final` payload gains `"diarization": {"requested":…, "performed":…, "reason":…}`.
6. `_save_session_to_notebook()` gains a `diarization_segments` parameter, forwarded to `save_longform_to_database()`.
7. The `longform_complete` webhook reports `result.num_speakers` instead of the hardcoded `0` (line 598).

`★ Ordering constraint:` the `format_speaker_text()` call (step 3) must happen before the existing persistence block at lines 489-527, which builds the payload, writes it to the database, and only then delivers it. Formatting after persistence would store bare text while sending labelled text, so a post-crash recovery through `GET /result/{job_id}` would silently lose the speakers.

`★ Model-swap note:` `transcribe_then_diarize()` unloads the STT model (`parallel_diarize.py:73`) and reloads it in its `finally` block. The WebSocket path holds a live `engine` reference obtained before the call and uses it afterwards only for `getattr(engine, "model_name", None)`, which stays valid. The import routes already do exactly this. A code comment must record it so nobody "fixes" the reference later.

`★ Post-#269 constraint:` `process_transcription`'s `finally` block now ends with `post_job_gpu_cleanup()` (lines 657-676), and its own comment states it **must stay last** — a cancellation landing inside that `await` would skip anything appended after it, and today that would be the temp-file cleanup and state reset. No new statement may be added below it. Relatedly, both `parallel_diarize` entry points already release the diarization model in their own guarded `finally`, so `diarization_dispatch` must not unload anything itself; doing so would be a redundant second unload with a real cost, since an unguarded raise there could replace an in-flight `TranscriptionCancelledError` (the exact bug #269 fixed).

### 3.4 Dashboard

**Client config (`src/config/store.ts` + `electron/main.ts` defaults):**

| Key | Change | Default |
|-----|--------|---------|
| `diarization.enabledForRecordings` | new | `false` |
| `diarization.constrainSpeakers` | default flipped `true` → `false` | `false` |
| `diarization.numSpeakers` | unchanged | `2` |

`constrainSpeakers` + `numSpeakers` become the single source for the expected-speaker count, shared between the Session card and the existing Settings > Diarization controls. Both surfaces read and write the same keys, so they stay in sync by construction.

**`SessionView.tsx`:**

- A new row inside the Main Transcription `GlassCard` (around line 1762, below the Source Language / Translate row): an `AppleSwitch` labelled "Speaker Diarization", with an inline speaker-count stepper rendered only when the switch is on.
- Availability gate copied from `SessionImportTab.tsx:144-152` (GH-209): read `admin.status.models.features.diarization`, disable the switch when `available === false`, and show the `token_missing` hint in the tooltip. `effectiveDiarization = unavailable ? false : enabled`.
- `handleStartRecording` (line 775) reads the config keys alongside the existing `notebook.autoAdd` read (line 805) and passes `diarization` + `expectedSpeakers` to `transcription.start()`.
- The result pane (around line 1952) renders an amber note when the final payload reports `requested && !performed`, using the same visual language as the existing partial-transcript banner at line 1959.

**`src/hooks/useTranscription.ts`:**

- `start()` options, the `startOptsRef` shape, and the `start` frame (line 271-278) gain `diarization` and `expected_speakers`.
- `TranscriptionResult` gains `numSpeakers?: number` and `diarization?: { requested: boolean; performed: boolean; reason: string | null }`.
- The `processing_progress` handler stores the new `phase` so the Session tab can call `describeJobProgress()`.

**UI contract.** New CSS classes require the full `ui-contract` workflow (extract → build → bump `meta.spec_version` → `--update-baseline` → check). Note the scanner gotchas: no apostrophes in `//` comments near `className` tokens, and write "GH-258" rather than "#258" in dashboard source (a `#NNN` token reads as a CSS color literal).

---

## 4. Data flow

```
SessionView  ──start({diarization, expectedSpeakers})──▶  useTranscription
                                                              │
                                          WS start frame {diarization, expected_speakers}
                                                              ▼
                                                    websocket.py handle_client_message
                                                      (validate bool / int 1-10)
                                                              ▼
                                                    TranscriptionSession.start_recording
                                                              │
                                                        (audio streams in)
                                                              ▼
                                                    process_transcription()
                                                       │ write WAV to recordings_dir
                                                       │ set_audio_path()
                                                       ▼
                                       transcribe_with_optional_diarization()
                                          ├─ integrated single-pass, or
                                          ├─ transcribe_and_diarize / transcribe_then_diarize
                                          └─ build_speaker_segments (+ nowords fallback)
                                                              ▼
                                              result.text = format_speaker_text(result)
                                                              ▼
                                                   _save_result()   ◀── PERSIST FIRST
                                                              ▼
                                              send "final" (or "result_ready" if >1 MB)
                                                              ▼
                                                       mark_delivered()
                                                              ▼
                                   _save_session_to_notebook(diarization_segments=…)
                                                              ▼
                                              dispatch_webhook(num_speakers=…)
```

---

## 5. Error handling

| Failure | Behaviour |
|---------|-----------|
| Diarization model missing / no HF token | Transcript delivered in full; `outcome.reason = "token_missing"`; amber note in the UI |
| Diarization OOMs on a small GPU | `parallel_diarize` returns `(result, None)`; transcript delivered; `as_gpu_oom()` classifies it, so `reason = "out_of_memory"` with the remedy shown in the amber note. Mitigations to suggest: turn off parallel diarization (sequential never co-resides the two models) and `main_transcriber.low_vram_mode` (`config.py:560`) |
| Diarization crashes for any other reason | `parallel_diarize` returns `(result, None)`; transcript delivered; `reason = "unavailable"` |
| Speaker merge raises | Caught inside the helper; transcript delivered without speakers |
| User cancels | `TranscriptionCancelledError` propagates; existing `mark_failed` path unchanged |
| Corrupt audio | `AudioDecodeError` propagates as a clean decode error, not mislabelled as a diarization problem |
| DB persist fails | Unchanged: log CRITICAL, still deliver, then `mark_failed` (the R-001 zombie-job guard, lines 541-556) |
| Notebook auto-add fails | Unchanged: warning event only; the transcript is already persisted and delivered |

The single invariant: **no diarization outcome may prevent a completed transcript from being persisted and delivered.**

---

## 6. Testing

**Backend** — pytest from `server/backend/` using the build venv (`../../build/.venv/bin/pytest tests/ -v --tb=short`), finishing with the full suite:

- `test_format_speaker_text.py` — turn coalescing, blank-line separation, passthrough when no segment has a speaker, empty segments, `None`/empty speaker values.
- `test_diarization_dispatch.py` — with fake engine/model_manager doubles: integrated single-pass path, standard parallel path, standard sequential path, degrade-on-diarization-failure, `TranscriptionCancelledError` propagation, `AudioDecodeError` propagation, `nowords` fallback, and that `word_timestamps` is forced on when diarization is requested.
- `test_websocket_start_diarization.py` — `start` field validation: correct bool, non-bool rejected, `expected_speakers` in range / out of range / wrong type; and that `start_recording` receives the resolved values.

Mocking rules that bite: patch `audio_utils.*` rather than `model_manager.*`, and stub `webrtcvad` via `sys.modules` before importing anything that pulls the audio stack.

**Frontend** — vitest, Node 22 (`cd dashboard && nvm use`):

- `SessionView.diarization.test.tsx` — the switch renders; it is disabled when `features.diarization.available === false`; the speaker stepper appears only when the switch is on; `transcription.start` is called with the expected flags.
- `useTranscription` — the emitted `start` frame contains `diarization` and `expected_speakers`.

---

## 7. Documentation

- `docs/README.md` — the features bullet (line 91) and the compatibility matrix (lines 127-137) present diarization as a general per-family capability with no carve-out; the only exclusion anywhere is GGML. Add a Notes bullet (after line 143) stating that diarization applies to file imports and to Session-tab recordings, but never to Live Mode.
- `docs/api-contracts-server.md` — document the two new WS `start` fields and the `diarization` block in the `final` payload.

---

## 8. Related work

- **Follow-up PR (agreed 2026-08-01, done as GH-274):** migrated `transcription.py` (both the /audio route and the /import worker), `notebook.py` and `openai_audio.py` onto `diarization_dispatch`. Route edges preserved: HTTP status codes (with one deliberate change — a missing-HF-token `ValueError` on /audio now degrades to a 200 + plain transcript instead of a 400, matching the documented failure-tolerance contract), the `X-Diarization-Status` header (kept: documented public API, though nothing in the dashboard reads it), and the differing DB write paths. The dispatch gained an `initial_prompt` parameter for the OpenAI endpoints' client prompt; the OpenAI routes keep their plain-retry failure tolerance route-side.
- **VRAM discipline (PR #269, merged 2026-08-01)** shipped four things this design must build on rather than duplicate: the parallel-diarization VRAM leak fix (both `parallel_diarize` paths now unload the diarization model in a guarded `finally`), `post_job_gpu_cleanup()` at every job-completion site including `process_transcription`, the `GpuOutOfMemoryError` / `as_gpu_oom()` classification pair, and the opt-in `main_transcriber.low_vram_mode` config key. The recording path inherits the leak fix for free. See the two `★` constraint notes in §3.3.
- **Live-start synchronisation (PR #272, merged)** touched `useTranscription.ts` only in `loadResult()` (it now clears the stale error on a delivered transcript) and did not change the `start` frame, so §3.4's plan applies unchanged. PR #272 also reshaped `ServerStatus.gpu_memory` in `types.ts` from a string to a nested `GpuMemoryInfo` object — unrelated to this work, but worth knowing before touching that file.
- **GH-256** remains unanswered on GitHub. Once this ships, the issue should be answered and closed with the README correction noted.
