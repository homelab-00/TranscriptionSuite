---
title: 'GH-88: Diarization over OpenAI-compatible /v1/audio/transcriptions'
type: 'feature'
created: '2026-04-20'
status: 'done'
baseline_commit: '8b817e3'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The OpenAI-compatible endpoints `POST /v1/audio/transcriptions` and `/v1/audio/translations` call `engine.transcribe_file()` directly and never run diarization, regardless of what the dashboard has configured. `response_format=diarized_json` returns 400 because the format is not registered. External OpenAI-compat clients (Open-WebUI, LM Studio, curl scripts) cannot obtain speaker-attributed transcripts through these endpoints.

**Approach:** Add form fields (`diarization`, `expected_speakers`, `parallel_diarization`) to both endpoints and reuse the orchestration already proven in `routes/transcription.py`: WhisperX integrated `transcribe_with_diarization` → `transcribe_and_diarize` / `transcribe_then_diarize` → `speaker_merge.build_speaker_segments`. Register a new `diarized_json` response format and extend `verbose_json`, `srt`, `vtt` to carry speakers when diarization ran. Mirror the reference route's fail-open pattern: any diarization failure returns the transcript without speakers, not 500.

## Boundaries & Constraints

**Always:**
- `diarization=false` by default (back-compat with GH-68 callers, parity with OpenAI's real API).
- Fail open: diarization errors become warning logs + plain transcript, never 5xx.
- Route by `parallel_diarization` form param, falling back to `config.diarization.parallel`.
- Force `word_timestamps=True` internally when `diarization=true` (required by `build_speaker_segments`); only *emit* per-word fields when the client requested them via `timestamp_granularities[]=word`.
- Validate `expected_speakers` ∈ [1,10]; out-of-range → 400 `invalid_request_error` with `param=expected_speakers`.
- Diarized path must work identically on both `/transcriptions` and `/translations`.
- `response_format=json` keeps its minimal `{"text": ...}` shape even when diarization ran — do not leak speakers into formats that never carried them.

**Never:**
- New side-route for diarization (OpenAI-compat clients can't discover it).
- Expose HF tokens or engine internals in error messages.
- Per-backend capability negotiation UI — the endpoint uses whatever diarization engine the server is already configured with.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Default (no diarization) | `diarization` absent/false | Unchanged existing behavior | N/A |
| `diarized_json` + success | `diarization=true`, `response_format=diarized_json`, engine loaded | `{task, language, duration, text, num_speakers, segments:[{speaker,start,end,text,words?}]}` | N/A |
| `verbose_json` + success | `diarization=true`, `response_format=verbose_json` | Standard verbose shape + per-segment `speaker` + top-level `num_speakers` | Segment without speaker → omit `speaker` key |
| `srt`/`vtt` + success | `diarization=true`, subtitle formats | Cue text prefixed `SPEAKER_XX: …` via existing `_format_cue_text` | Unspeakered cue → unprefixed |
| `json` + success | `diarization=true`, `response_format=json` | `{"text": full_text}` — speakers computed internally but not leaked | N/A |
| Diarization fails | `diarization=true`, engine raises (no HF token, OOM, merge error) | 200 transcript without speakers; `num_speakers=0`; WARNING logged | Fail open; do not 500 |
| Invalid `expected_speakers` | 0 or 11 | 400 `invalid_request_error`, `param=expected_speakers` | N/A |
| `diarized_json` without flag | `response_format=diarized_json`, `diarization=false` | 200 with `num_speakers=0`, segments lacking `speaker` | N/A |
| Translation + diarization | `/translations`, `diarization=true` | Same shape/failure semantics; translated text + speakers | Same fail-open |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/openai_audio.py` — add form fields, orchestration helper, response builder updates.
- `server/backend/core/formatters.py` — add `format_diarized_json`; extend `format_verbose_json` with speakers + `num_speakers`; extend `_result_to_cues` to propagate `speaker` into `SubtitleCue`.
- `server/backend/api/routes/transcription.py` — **reference only**; mirror the `use_integrated_diarization` / `if diarization:` orchestration (lines ~281–443). Do not import from it.
- `server/backend/core/parallel_diarize.py` — `transcribe_and_diarize`, `transcribe_then_diarize` (reused as-is).
- `server/backend/core/speaker_merge.py` — `build_speaker_segments`, `build_speaker_segments_nowords` (reused as-is).
- `server/backend/core/subtitle_export.py` — `_format_cue_text` already formats `SPEAKER_XX: text`; no change.
- `server/backend/tests/test_openai_audio_routes.py` — extend with diarization cases.
- `docs/api-contracts-server.md` — document new fields + `diarized_json` schema.
- `README.md` — note diarization support under the OpenAI-compat section.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/formatters.py` — added `format_diarized_json(result, task, include_words)`; extended `format_verbose_json` so segments carry `speaker` when present and body carries `num_speakers`; extended `_result_to_cues` to bake normalized `Speaker N:` prefix into cue text (subtitle_export's existing `render_srt`/`_render_vtt` dump `cue.text` verbatim, so pre-formatting is how the prefix reaches subtitle output).
- [x] `server/backend/api/routes/openai_audio.py` — added `diarization`, `expected_speakers`, `parallel_diarization` form fields to both endpoints; registered `"diarized_json"` in `_VALID_RESPONSE_FORMATS`; added `_validate_expected_speakers` returning a 400 for out-of-range values; added `_run_transcription(...)` helper mirroring the three-path orchestration from `routes/transcription.py` (integrated → parallel → sequential → plain) with matching catch semantics.
- [x] `server/backend/api/routes/openai_audio.py` — `_build_response` now routes `diarized_json` to `format_diarized_json`; `include_words` gated on the client's original `timestamp_granularities[]=word` request regardless of diarization internal word-timestamp coercion.
- [x] `server/backend/tests/test_openai_audio_routes.py` — 14 new tests in `TestDiarizationOverOpenAI` covering diarized `diarized_json`/`verbose_json`/`srt`/`vtt`; `json` format never leaking speakers; `expected_speakers` range validation; fail-open on orchestration exception; translation endpoint parity; legacy-shape preservation; word-granularity emission.
- [x] `docs/api-contracts-server.md` — new "OpenAI-Compatible Audio Endpoints" section documenting form fields, response formats, speaker-label policy, and the `diarized_json` schema.
- [x] `docs/README.md` — updated `/v1/audio/transcriptions` and `/v1/audio/translations` tables with diarization form fields, expanded response-format table, added diarized-curl example and speaker-label-convention notes.

**Acceptance Criteria:**
- Given Sortformer or PyAnnote is configured and loaded, when a client POSTs `diarization=true&response_format=diarized_json` to either endpoint, then the body carries `num_speakers >= 1` and each segment has a `SPEAKER_XX` speaker label.
- Given `response_format=srt` with diarization, when the response returns, then each cue is prefixed `SPEAKER_XX: …`.
- Given diarization is requested but the engine raises, when the request completes, then the endpoint returns 200 with a plain transcript and a WARNING is logged.
- Given `expected_speakers=0` or `expected_speakers=11`, when the request is received, then the endpoint returns 400 `invalid_request_error` with `param=expected_speakers`.
- Given `diarization=false` (default), when a client calls either endpoint in any format, then the response matches the pre-change shape byte-for-byte.

## Spec Change Log

- **2026-04-20 — SRT/VTT label form corrected during implementation.** The I/O matrix and ACs originally specified cue prefix `SPEAKER_XX: …`. The existing `subtitle_export.normalize_speaker_labels` helper (already used by the longform pipeline) converts raw `SPEAKER_00` → `Speaker 1`, and that is the form users already see in the dashboard. Implementation follows the existing convention: subtitle formats (srt/vtt) render `Speaker 1: …`; JSON bodies (verbose_json, diarized_json) retain the raw `SPEAKER_00` form for programmatic consumers. **KEEP:** diarized JSON bodies keep raw `SPEAKER_NN` — do not normalize there, because API clients need stable identifiers across requests.
- **2026-04-20 — Review patch: fail-open on integrated-path ValueError.** Edge Case Hunter found that the Path 1 `except ValueError: raise` violated the spec's fail-open promise for missing HF token (WhisperX raises `ValueError` for that specific misconfig). Removed the ValueError special-case; all non-cancellation exceptions in the integrated path now warn-and-fall-through to plain transcription. Genuine client-side input errors still surface as 400 via the outer `except ValueError` when Path 3 also rejects them. **KEEP:** `TranscriptionCancelledError` is still re-raised separately so client cancellations continue to propagate.
- **2026-04-20 — Review patch: strip `UNKNOWN` speaker sentinel in formatters.** Blind Hunter found that `speaker_merge.build_speaker_segments_nowords`'s `UNKNOWN` sentinel passed the `if speaker:` truthy check and leaked into JSON bodies alongside `num_speakers=0`. Added `_normalize_speaker_value()` helper in `formatters.py`; every speaker-field access in `format_verbose_json`, `format_diarized_json`, and `_result_to_cues` funnels through it. Result: `UNKNOWN` is dropped consistently from JSON and subtitle output. **KEEP:** raw `SPEAKER_00` labels still pass through unchanged — only `None`, empty, and case-insensitive `"UNKNOWN"` are normalized away.
- **2026-04-20 — Review patch: `diarized_json` word fallback.** Edge Case Hunter found that `format_diarized_json` gated per-segment words on `seg.get("words")`, silently dropping words when segments lacked the nested key even though `result.words` had the data. Added a flat-`result.words` slice-by-time fallback inside each segment when `include_words=True` and the segment has no nested `words`. **KEEP:** when a segment does carry its own `words`, those take precedence (the integrated-diarization path's richer per-segment data is never overridden).

## Design Notes

Golden `diarized_json` shape:

```json
{
  "task": "transcribe",
  "language": "el",
  "duration": 12.4,
  "text": "Γεια σας. Καλώς ήρθατε.",
  "num_speakers": 2,
  "segments": [
    {"speaker": "SPEAKER_00", "start": 0.0, "end": 4.1, "text": "Γεια σας."},
    {"speaker": "SPEAKER_01", "start": 4.5, "end": 12.4, "text": "Καλώς ήρθατε."}
  ]
}
```

The integrated-vs-orchestrator branch stays inside the route module (local `_run_transcription` helper) rather than being pushed into `engine.transcribe_file`: the STT engine has no diarization concept today and exporting `model_manager` + the parallel helpers into it would break the current separation (engine = STT only, orchestration = routes + `parallel_diarize`).

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_openai_audio_routes.py -v --tb=short` — expected: all new + existing tests pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -q --tb=short` — expected: no regressions in the wider suite.

**Manual checks:**
- `curl -F file=@sample.wav -F diarization=true -F response_format=diarized_json http://localhost:9786/v1/audio/transcriptions` returns JSON with `num_speakers >= 1` and per-segment `speaker`.
- Same request with `response_format=srt` emits cues prefixed `Speaker 1: …` (subtitle labels normalized per the Spec Change Log).
- With no HF token, the same request returns 200 with a plain transcript and a WARNING line in the server log.

## Suggested Review Order

**Orchestration — the three-path engine selector**

- Entry point: `_run_transcription` encapsulates integrated → parallel → sequential → plain fallback, mirroring the non-OpenAI route.
  [`openai_audio.py:102`](../../server/backend/api/routes/openai_audio.py#L102)

- Fail-open policy on the integrated path — treats every non-cancellation exception (including ValueError for missing HF token) as a warn-and-fall-through trigger. This is the patch from the Edge Case Hunter review.
  [`openai_audio.py:189`](../../server/backend/api/routes/openai_audio.py#L189)

- `expected_speakers` range validation, reused by both endpoints.
  [`openai_audio.py:288`](../../server/backend/api/routes/openai_audio.py#L288)

**Public endpoints — form fields and response routing**

- `create_transcription` now takes `diarization`, `expected_speakers`, `parallel_diarization` form fields and runs through `_run_transcription`.
  [`openai_audio.py:326`](../../server/backend/api/routes/openai_audio.py#L326)

- `create_translation` is the mirror surface — same orchestration, `task="translate"`, `translation_target_language="en"`.
  [`openai_audio.py:446`](../../server/backend/api/routes/openai_audio.py#L446)

- `_VALID_RESPONSE_FORMATS` gains `"diarized_json"`; `_build_response` routes it to the new formatter.
  [`openai_audio.py:44`](../../server/backend/api/routes/openai_audio.py#L44)

**Formatters — where speaker data reaches the wire**

- `format_diarized_json` is the new non-OpenAI-standard format; notice the `include_words` flat-words fallback patched after Edge Case review.
  [`formatters.py:102`](../../server/backend/core/formatters.py#L102)

- `format_verbose_json` gains per-segment `speaker` and top-level `num_speakers` only when present — preserves exact pre-change shape under `diarization=false`.
  [`formatters.py:45`](../../server/backend/core/formatters.py#L45)

- `_result_to_cues` normalizes raw `SPEAKER_00` → `Speaker 1` and bakes the prefix into cue text for SRT/VTT.
  [`formatters.py:186`](../../server/backend/core/formatters.py#L186)

- `_normalize_speaker_value` helper funnels every speaker-field access through the same UNKNOWN-sentinel filter (Blind Hunter patch).
  [`formatters.py:17`](../../server/backend/core/formatters.py#L17)

**Tests — diarization over the OpenAI surface**

- Full acceptance suite lives in `TestDiarizationOverOpenAI` — covers all response formats, validation, fail-open, translation parity, and the three review patches.
  [`test_openai_audio_routes.py:776`](../../server/backend/tests/test_openai_audio_routes.py#L776)

- The three regression tests guarding the review patches: UNKNOWN sentinel filtering [`test_openai_audio_routes.py:960`](../../server/backend/tests/test_openai_audio_routes.py#L960), flat-words fallback [`test_openai_audio_routes.py:1006`](../../server/backend/tests/test_openai_audio_routes.py#L1006), integrated-path ValueError fail-open [`test_openai_audio_routes.py:1048`](../../server/backend/tests/test_openai_audio_routes.py#L1048).

**Docs — public contract update**

- `docs/README.md` — updated endpoint tables with diarization fields, expanded response formats, added diarized-curl example.
  [`README.md:613`](../../docs/README.md#L613)

- `docs/api-contracts-server.md` — new "OpenAI-Compatible Audio Endpoints" section with speaker-label policy and `diarized_json` schema.
  [`api-contracts-server.md:100`](../../docs/api-contracts-server.md#L100)
