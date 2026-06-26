# GH #172 — whisper.cpp Segment-Cap Data Loss + WebSocket Segment Drop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the whisper.cpp backend from silently discarding transcription segments on long audio (GH #172), and stop the WebSocket longform path from dropping segment-level data from persistence + delivery (separate verified bug folded in per the user's decision).

**Architecture:** Replace the flat, audio-duration-independent `_MAX_SEGMENTS`/`_MAX_WORDS_PER_SEGMENT` caps with **duration-proportional** sanity bounds that real speech can never reach, and **fail loud** (raise) on overflow instead of silently slicing — overflow now definitionally means a malformed/hostile sidecar payload, which the existing GH #168 chunk-salvage machinery already converts into a surfaced partial result. Add a ceiling to the chunk-duration config so long audio is always chunked (closing the un-chunked re-exposure path), and add a real HTTP-read byte guard (the memory bound the old cap only pretended to be). Finally, make the WebSocket longform result payload carry the full `result.to_dict()` (segments + `partial_reason`) so it matches the HTTP path and the new truncation signal actually reaches WS clients.

**Tech Stack:** Python 3.13, FastAPI, httpx, numpy, pytest (run via the **build venv**, not the server venv).

---

## Background & Root Cause (read before starting)

- **Symptom (GH #172):** `whisper-server returned 11152 segment dicts, truncating to 10000 to bound memory` — ~1152 segments of irreplaceable transcript silently dropped. Violates the project's #1 invariant ("AVOID DATA LOSS AT ALL COSTS / never silently discard a completed transcription").
- **Mechanism:** `server/backend/core/stt/backends/whispercpp_backend.py:51` `_MAX_SEGMENTS = 10_000`, applied in `_parse_response` (lines 798-804) as `logger.warning(...)` + `dict_segments[:_MAX_SEGMENTS]`. Sibling `_MAX_WORDS_PER_SEGMENT = 5_000` (line 52, truncation 391-397) is the same bug class.
- **Why a flat cap is wrong:** it cannot distinguish "11k segments for 5 min of audio" (impossible → hostile/buggy) from "11k segments for 6 h of audio" (legitimate). The fix makes the bound proportional to audio duration.
- **Exposure:** All released builds (≤ v1.3.6) are fully exposed (the GH #168 chunking fix is main-only). On `main` + default config the symptom is unreachable (cap is per-10-min-chunk), but it is re-exposed by raising `WHISPERCPP_CHUNK_DURATION_S` above the file length (`_resolve_chunk_duration_config`, line 142, floors at 60s with **no ceiling**), and any truncation is still silent.
- **The "bound memory" justification is illusory:** `resp.json()` (`_transcribe_chunk`, line 737) materializes the whole body before the post-parse slice runs (line 798). The list slice frees almost nothing. The real memory guard belongs at HTTP read time (Task 5).
- **Folded-in WS bug (verified):** `server/backend/api/routes/websocket.py:375-382` (`process_transcription`, the LONGFORM path) builds `result_payload` with only `{text, words, language, duration}` — dropping `segments`, `num_speakers`, `partial`, `partial_reason`. That payload is both persisted as `result_json` (line 391) and sent to the client (line 420); `GET /result/{job_id}` replays `result_json` (transcription.py:1382-1384), so the loss is permanent across both channels. The HTTP submit path persists the full `result.to_dict()` (transcription.py:532). NOTE: the live and preview WS paths are **out of scope** (preview is a sanctioned ephemeral exception; live is incremental and has a different result shape).

## Impact / Safety Note (project rule)

Per `CLAUDE.md` (GitNexus), **run `gitnexus_impact({target, direction:"upstream"})` before editing each symbol** and report blast radius; if HIGH/CRITICAL, warn before proceeding. Run `gitnexus_detect_changes()` before committing. Manually-traced blast radius for reference:
- `_parse_response` ← `_transcribe_chunk` ← `transcribe` ← engine (`stt/engine.py`) — internal to the whisper.cpp backend; signature change is private (leading underscore).
- `_parse_words` ← `_parse_response` only.
- `_resolve_chunk_duration_config` ← `load()` only.
- WS payload construction ← `process_transcription` only.

## File Structure

- **Modify:** `server/backend/core/stt/backends/whispercpp_backend.py` — constants, cap helpers, `_parse_response`/`_parse_words` signatures + fail-loud, `_transcribe_chunk` (duration threading + byte guard), `_resolve_chunk_duration_config` ceiling, comment block.
- **Modify:** `server/backend/api/routes/websocket.py` — extract `_build_longform_result_payload` helper; use full `result.to_dict()`.
- **Modify (tests):** `server/backend/tests/test_whispercpp_backend.py` — replace the flat-cap boundary tests with proportional + fail-loud tests; add chunk-ceiling test; add byte-guard test.
- **Modify (tests):** `server/backend/tests/test_websocket_*.py` (or a new `test_websocket_longform_payload.py`) — unit-test the new payload helper.

**Test command (use the build venv):**
```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py -v --tb=short
```

---

## Task 1: Proportional-cap constants + pure cap helpers

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py:44-52` (constants) and add helpers near the other module-level helpers (e.g. after `_resolve_chunk_duration_config`, ~line 150).
- Test: `server/backend/tests/test_whispercpp_backend.py`

- [ ] **Step 1: Write the failing test**

Add to `test_whispercpp_backend.py` (top-level, near the other module-function tests; import the new names):

```python
from server.core.stt.backends.whispercpp_backend import (
    _segment_cap_for,
    _word_cap_for,
    _SEGMENT_CAP_FLOOR,
    _WORDS_CAP_FLOOR,
    _MAX_SEGMENTS_PER_AUDIO_SECOND,
    _MAX_WORDS_PER_AUDIO_SECOND,
)


@pytest.mark.parametrize(
    "duration_s,expected",
    [
        (0.0, _SEGMENT_CAP_FLOOR),          # empty/floor
        (1.0, _SEGMENT_CAP_FLOOR),          # short clip pinned to floor
        (100.0, 100 * _MAX_SEGMENTS_PER_AUDIO_SECOND),  # proportional regime
        (600.0, 600 * _MAX_SEGMENTS_PER_AUDIO_SECOND),  # 10-min chunk
    ],
)
def test_segment_cap_for_is_proportional_with_floor(duration_s, expected):
    assert _segment_cap_for(duration_s) == expected


@pytest.mark.parametrize(
    "duration_s,expected",
    [
        (0.0, _WORDS_CAP_FLOOR),
        (1.0, _WORDS_CAP_FLOOR),
        (100.0, 100 * _MAX_WORDS_PER_AUDIO_SECOND),
    ],
)
def test_word_cap_for_is_proportional_with_floor(duration_s, expected):
    assert _word_cap_for(duration_s) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py::test_segment_cap_for_is_proportional_with_floor -v`
Expected: FAIL — `ImportError: cannot import name '_segment_cap_for'`.

- [ ] **Step 3: Write minimal implementation**

Replace the constant block at `whispercpp_backend.py:44-52`:

```python
# Defensive sanity bounds on the sidecar response. A buggy or hostile
# whisper-server (e.g. one reached through a misconfigured
# ``WHISPERCPP_SERVER_URL`` pointing at a malicious service) could return a
# payload with far more segments/words than the audio could possibly justify.
# We bound the count PROPORTIONALLY to the chunk's audio duration: whisper.cpp
# realistically emits well under ~2-3 segments/sec and ~3-4 words/sec, so the
# rates below sit ~7-10x above any legitimate output and are unreachable by
# real speech at ANY duration. Exceeding a proportional bound therefore means
# a malformed/hostile payload, not a long recording — so we RAISE rather than
# silently truncate (GH #172: never silently discard a completed transcription).
# Floors keep very short clips from false-tripping the bound.
_MAX_SEGMENTS_PER_AUDIO_SECOND = 20
_MAX_WORDS_PER_AUDIO_SECOND = 40
_SEGMENT_CAP_FLOOR = 200
_WORDS_CAP_FLOOR = 1_000
```

Add helpers (after `_resolve_chunk_duration_config`, ~line 150; `math` is already imported):

```python
def _segment_cap_for(audio_duration_s: float) -> int:
    """Max plausible segment count for ``audio_duration_s`` of audio.

    Proportional to duration with a floor for very short clips. A real
    transcript can never reach this; exceeding it means a malformed/hostile
    sidecar payload (GH #172).
    """
    return max(_SEGMENT_CAP_FLOOR, math.ceil(audio_duration_s * _MAX_SEGMENTS_PER_AUDIO_SECOND))


def _word_cap_for(audio_duration_s: float) -> int:
    """Max plausible per-segment word count for ``audio_duration_s`` of audio."""
    return max(_WORDS_CAP_FLOOR, math.ceil(audio_duration_s * _MAX_WORDS_PER_AUDIO_SECOND))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py -k "cap_for" -v`
Expected: PASS (both parametrized tests).

NOTE: the legacy tests `test_segment_cap_boundary` and `test_word_cap_boundary` and any `_MAX_SEGMENTS`/`_MAX_WORDS_PER_SEGMENT` imports now reference deleted constants and will FAIL TO IMPORT/COLLECT. That is expected — Tasks 2 and 3 replace them. Do not run the whole file green yet.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_backend.py server/backend/tests/test_whispercpp_backend.py
git commit -m "refactor(stt): add duration-proportional segment/word cap helpers for whisper.cpp (GH #172)"
```

---

## Task 2: Thread chunk duration into the parser; fail loud on segment overflow

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py` — add `WhisperCppResponseError` (near other errors, ~top of file after imports), `_transcribe_chunk` (line 746 call site), `_parse_response` (signature ~763 + cap block 798-804).
- Test: `server/backend/tests/test_whispercpp_backend.py` (replace `test_segment_cap_boundary`).

- [ ] **Step 1: Write the failing test**

Replace `test_segment_cap_boundary` (lines 867-890) with the proportional + fail-loud version. `_seconds_of_audio` makes the intent explicit (16 kHz mono):

```python
from server.core.stt.backends.whispercpp_backend import WhisperCppResponseError


def _seconds_of_audio(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * 16000), dtype=np.float32)


class TestSegmentProportionalCap:
    def _respond_with(self, mock_httpx, n_segments):
        bloated = [{"text": "x", "start": 0.0, "end": 0.1} for _ in range(n_segments)]
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": bloated}),
        )

    def test_legit_long_audio_is_not_truncated(self, loaded_backend, mock_httpx):
        """GH #172 regression: a real long transcript keeps ALL its segments."""
        # 100s audio → cap = 2000; 1500 segments is legitimate and must survive.
        self._respond_with(mock_httpx, 1500)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(100))
        assert len(segments) == 1500

    def test_count_at_proportional_cap_is_kept(self, loaded_backend, mock_httpx):
        # 100s → cap 2000; exactly at cap is kept (boundary).
        self._respond_with(mock_httpx, 2000)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(100))
        assert len(segments) == 2000

    def test_count_over_proportional_cap_raises(self, loaded_backend, mock_httpx):
        # 100s → cap 2000; one over is an impossible payload → raise, do NOT truncate.
        self._respond_with(mock_httpx, 2001)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(100))

    def test_floor_applies_to_short_clips(self, loaded_backend, mock_httpx):
        # 1s → cap = floor 200; 200 kept, 201 raises.
        self._respond_with(mock_httpx, 200)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(1))
        assert len(segments) == 200
        self._respond_with(mock_httpx, 201)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))

    def test_hostile_small_audio_huge_count_raises(self, loaded_backend, mock_httpx):
        # The literal #172 attack shape: thousands of segments for ~1s of audio.
        self._respond_with(mock_httpx, 11152)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))
```

Keep `test_segment_cap_applies_after_filter` (lines 892-911) — with 1s audio (cap 200) and 100 real dicts it still asserts 100 kept; no change needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py::TestSegmentProportionalCap -v`
Expected: FAIL — `ImportError: cannot import name 'WhisperCppResponseError'` (and, once that exists, the over-cap tests fail because the code still silently truncates).

- [ ] **Step 3: Write minimal implementation**

(a) Add the error type near the top of `whispercpp_backend.py` (after the imports / before the constants):

```python
class WhisperCppResponseError(RuntimeError):
    """The sidecar returned a structurally implausible payload — more segments
    or words than the audio duration could justify. Raised instead of silently
    truncating so a malformed/hostile response can never masquerade as a
    complete transcript (GH #172).
    """
```

(b) Change `_parse_response` to take the chunk's audio duration and enforce the proportional cap by RAISING. Replace the signature (lines 763-766) and the cap block (798-804):

```python
    @staticmethod
    def _parse_response(
        result: dict[str, Any],
        audio_duration_s: float,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
```

Replace lines 793-804 (`# Filter to dict-typed segments FIRST ...` through the truncating slice) with:

```python
        # Filter to dict-typed segments FIRST, bound afterwards. If we bounded
        # first and the payload had thousands of stray non-dict entries at the
        # front, the bound would reject real segments that followed.
        dict_segments = [s for s in raw_segments if isinstance(s, dict)]
        seg_cap = _segment_cap_for(audio_duration_s)
        if len(dict_segments) > seg_cap:
            # A real transcript cannot exceed the proportional bound; this is a
            # malformed/hostile sidecar payload. RAISE rather than silently
            # truncate (GH #172). In the chunked path transcribe()'s per-chunk
            # handler converts this into a surfaced partial result; in the
            # single-request path it fails the job loudly with no data lost.
            raise WhisperCppResponseError(
                f"whisper-server returned {len(dict_segments)} segment dicts for "
                f"{audio_duration_s:.0f}s of audio (max {seg_cap}); refusing to "
                f"silently truncate a transcript"
            )
```

(c) Update the call site in `_transcribe_chunk` (line 746) to compute and pass the duration:

```python
        audio_duration_s = len(chunk) / sample_rate if sample_rate else 0.0
        return self._parse_response(result, audio_duration_s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py::TestSegmentProportionalCap tests/test_whispercpp_backend.py::*::test_segment_cap_applies_after_filter -v`
Expected: PASS for all `TestSegmentProportionalCap` cases. (`_parse_words` still has the old signature — that is Task 3.)

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_backend.py server/backend/tests/test_whispercpp_backend.py
git commit -m "fix(stt): fail loud on implausible whisper.cpp segment count instead of silently truncating (GH #172)"
```

---

## Task 3: Fail loud on per-segment word overflow (proportional)

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py` — `_parse_words` (signature line 381 + cap block 391-397) and its caller in `_parse_response` (line 807).
- Test: `server/backend/tests/test_whispercpp_backend.py` (replace `test_word_cap_boundary`).

- [ ] **Step 1: Write the failing test**

Replace `test_word_cap_boundary` (lines 913-942) with:

```python
class TestWordProportionalCap:
    def _respond_with_words(self, mock_httpx, n_words):
        bloated = [
            {"word": "x", "start": i * 0.001, "end": i * 0.001 + 0.0005}
            for i in range(n_words)
        ]
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "segments": [{"text": "seg", "start": 0.0, "end": 30.0, "words": bloated}]
                }
            ),
        )

    def test_legit_words_kept(self, loaded_backend, mock_httpx):
        # 100s audio → word cap 4000; 800 words on one segment is fine.
        self._respond_with_words(mock_httpx, 800)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(100))
        assert len(segments[0].words) == 800

    def test_words_over_cap_raise(self, loaded_backend, mock_httpx):
        # 1s audio → word cap = floor 1000; 1001 words is implausible → raise.
        self._respond_with_words(mock_httpx, 1001)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py::TestWordProportionalCap -v`
Expected: FAIL — `test_words_over_cap_raise` does not raise (code still truncates words silently).

- [ ] **Step 3: Write minimal implementation**

Change `_parse_words` to accept a precomputed cap and raise on overflow. Replace the signature (line 381) and cap block (391-397):

```python
def _parse_words(raw_words: Any, word_cap: int) -> list[dict[str, Any]]:
    """Convert a sidecar ``words`` array into the normalised word-dict list.

    Applies the same filter-then-bound discipline as the segment-level parser
    and silently drops per-word entries that fail validation (non-dict,
    missing text, missing bounds, non-monotonic bounds). Raises
    ``WhisperCppResponseError`` if the count exceeds ``word_cap`` — an
    implausible count means a malformed/hostile payload, not real speech
    (GH #172).
    """
    if not isinstance(raw_words, list):
        return []
    dict_words = [w for w in raw_words if isinstance(w, dict)]
    if len(dict_words) > word_cap:
        raise WhisperCppResponseError(
            f"whisper-server segment had {len(dict_words)} word dicts "
            f"(max {word_cap}); refusing to silently truncate"
        )
```

Update the caller in `_parse_response` (line 807). Compute the word cap once from the chunk duration before the segment loop and pass it in:

```python
        word_cap = _word_cap_for(audio_duration_s)
        for seg in dict_segments:
            words = _parse_words(seg.get("words"), word_cap)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py::TestWordProportionalCap -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_backend.py server/backend/tests/test_whispercpp_backend.py
git commit -m "fix(stt): fail loud on implausible whisper.cpp per-segment word count (GH #172)"
```

---

## Task 4: Add a ceiling to the chunk-duration config

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py` — add `_MAX_CHUNK_DURATION_CEILING_S` constant (near line 35) and clamp in `_resolve_chunk_duration_config` (line 142).
- Test: `server/backend/tests/test_whispercpp_backend.py`

- [ ] **Step 1: Write the failing test**

```python
from server.core.stt.backends.whispercpp_backend import (
    _resolve_chunk_duration_config,
    _MAX_CHUNK_DURATION_CEILING_S,
)


def test_chunk_duration_config_is_ceilinged(monkeypatch):
    """A huge WHISPERCPP_CHUNK_DURATION_S must NOT disable chunking (GH #172):
    long audio must always be split so the per-chunk proportional cap applies."""
    monkeypatch.setenv("WHISPERCPP_CHUNK_DURATION_S", "86400")  # 1 day
    assert _resolve_chunk_duration_config() == _MAX_CHUNK_DURATION_CEILING_S


def test_chunk_duration_config_floor_still_applies(monkeypatch):
    monkeypatch.setenv("WHISPERCPP_CHUNK_DURATION_S", "5")
    assert _resolve_chunk_duration_config() == 60
```

(If `_read_whispercpp_setting` reads config rather than env, set the value via the same mechanism the existing config tests use; check the other `_resolve_*` tests in this file for the established monkeypatch pattern and mirror it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py -k chunk_duration_config -v`
Expected: FAIL — `ImportError: cannot import name '_MAX_CHUNK_DURATION_CEILING_S'`, then a value mismatch (returns 86400).

- [ ] **Step 3: Write minimal implementation**

Add near line 35:

```python
# Hard ceiling on the configurable chunk duration. Even a deliberately huge
# WHISPERCPP_CHUNK_DURATION_S must not route a whole multi-hour file through a
# single un-chunked /inference request — that path re-exposes the GH #172
# truncation and defeats per-chunk progress/cancellation. 30 min keeps each
# chunk's plausible segment count far below any proportional cap.
_MAX_CHUNK_DURATION_CEILING_S = 30 * 60
```

Change the success return of `_resolve_chunk_duration_config` (line 142):

```python
        return min(_MAX_CHUNK_DURATION_CEILING_S, max(60, int(float(raw))))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py -k chunk_duration_config -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_backend.py server/backend/tests/test_whispercpp_backend.py
git commit -m "fix(stt): ceiling whisper.cpp chunk duration so long audio is always chunked (GH #172)"
```

---

## Task 5: Real HTTP-read byte guard (hardening — the memory bound the old cap only pretended to be)

> This restores/upgrades the genuine memory protection. It can be deferred if the team wants the minimal #172 fix, but it is the correct place for the "bound memory" intent — `resp.json()` currently materializes any payload size before any cap runs.

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py` — `_MAX_RESPONSE_BYTES` constant; switch `_transcribe_chunk`'s POST (lines 708-744) to a streaming read with a byte accumulator.
- Test: `server/backend/tests/test_whispercpp_backend.py`

- [ ] **Step 1: Write the failing test**

```python
def test_oversized_response_body_is_rejected(loaded_backend, mock_httpx):
    """A multi-MB sidecar body must be rejected at read time, before json()."""
    # Simulate a streaming response whose body exceeds the byte cap.
    # Adapt to the streaming shape used in Step 3 (client.stream(...) context
    # manager yielding a response with iter_bytes()).
    from server.core.stt.backends.whispercpp_backend import (
        WhisperCppResponseError,
        _MAX_RESPONSE_BYTES,
    )

    chunk = b"x" * (1024 * 1024)
    n = (_MAX_RESPONSE_BYTES // len(chunk)) + 2

    class _FakeStream:
        headers = {}
        def raise_for_status(self): ...
        def iter_bytes(self):
            for _ in range(n):
                yield chunk

    class _FakeStreamCtx:
        def __enter__(self_): return _FakeStream()
        def __exit__(self_, *a): return False

    mock_httpx.stream.return_value = _FakeStreamCtx()
    with pytest.raises(WhisperCppResponseError):
        loaded_backend.transcribe(_seconds_of_audio(1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py::test_oversized_response_body_is_rejected -v`
Expected: FAIL — `_MAX_RESPONSE_BYTES` missing / `mock_httpx.stream` unused.

- [ ] **Step 3: Write minimal implementation**

Add a constant near the other caps:

```python
# Hard ceiling on a single /inference response body, enforced while reading so
# a hostile multi-GB body is rejected BEFORE it is deserialized into memory.
# A 6-hour verbose_json transcript with word timestamps is well under this.
_MAX_RESPONSE_BYTES = 256 * 1024 * 1024  # 256 MiB
```

Replace the body-read in `_transcribe_chunk` (the `client.post(...)` through `resp.json()` block, lines 708-744) with a streaming read that accumulates with a cap. Keep the existing exception mapping (`NetworkError`/`OSError`, `TimeoutException`, `HTTPStatusError`, `DecodingError`, non-JSON `ValueError`):

```python
        client = self._ensure_client()
        body = bytearray()
        try:
            with client.stream(
                "POST",
                f"{self._server_url}/inference",
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data=data,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("Content-Length")
                if (
                    content_length is not None
                    and content_length.isdigit()
                    and int(content_length) > _MAX_RESPONSE_BYTES
                ):
                    raise WhisperCppResponseError(
                        f"whisper.cpp sidecar at {self._server_url} declared a "
                        f"{int(content_length)}-byte /inference response (max {_MAX_RESPONSE_BYTES})"
                    )
                for piece in resp.iter_bytes():
                    body += piece
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise WhisperCppResponseError(
                            f"whisper.cpp sidecar at {self._server_url} returned a "
                            f"/inference response over {_MAX_RESPONSE_BYTES} bytes; aborting read"
                        )
        except (httpx.NetworkError, OSError) as exc:
            raise RuntimeError(_SIDECAR_UNREACHABLE_MSG.format(url=self._server_url)) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                _SIDECAR_INFERENCE_TIMEOUT_MSG.format(url=self._server_url, timeout=timeout)
            ) from exc
        except HttpxHTTPStatusError as exc:
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned HTTP "
                f"{exc.response.status_code} for /inference"
            ) from exc
        except HttpxDecodingError as exc:
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned an "
                f"undecodable response for /inference: {exc}"
            ) from exc

        try:
            result = json.loads(bytes(body))
        except ValueError as exc:
            body_preview = _sanitize_for_error_preview(bytes(body)) or "(empty)"
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned non-JSON "
                f"response from /inference: {body_preview}"
            ) from exc
```

Confirm `json` is imported at the top of the module (it is used elsewhere; if not, add `import json`). Update the existing happy-path tests that set `mock_httpx.post.return_value` — they must now drive `mock_httpx.stream` instead. Provide a shared test helper (e.g. `_mock_stream_json(mock_httpx, payload)`) and update the prior tasks' tests to use it so the whole file is consistent. (If this churn is judged too large, gate Task 5 as a follow-up and keep `client.post` + a post-`json()` `len(resp.content)` check as a weaker interim guard — note explicitly in the commit that it does not bound deserialization memory.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py -v`
Expected: PASS (oversized-body test plus all migrated happy-path tests).

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_backend.py server/backend/tests/test_whispercpp_backend.py
git commit -m "fix(stt): bound whisper.cpp /inference response at read time, before deserialization (GH #172)"
```

---

## Task 6: WebSocket longform payload carries the full result (segments + partial_reason)

**Files:**
- Modify: `server/backend/api/routes/websocket.py` — add module-level `_build_longform_result_payload`; use it in `process_transcription` (lines 375-382).
- Test: `server/backend/tests/test_websocket_longform_payload.py` (new) or an existing websocket test module.

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_websocket_longform_payload.py`:

```python
from server.core.stt.engine import TranscriptionResult
from server.api.routes.websocket import _build_longform_result_payload


def test_longform_payload_includes_segments_and_partial():
    result = TranscriptionResult(
        text="hello world",
        segments=[{"text": "hello world", "start": 0.0, "end": 1.0}],
        words=[{"word": "hello", "start": 0.0, "end": 0.5}],
        language="en",
        duration=1.0,
        num_speakers=2,
        partial=True,
        partial_reason="sidecar returned implausible segment count",
    )
    payload = _build_longform_result_payload(result)
    assert payload["segments"] == [{"text": "hello world", "start": 0.0, "end": 1.0}]
    assert payload["num_speakers"] == 2
    assert payload["partial"] is True
    assert payload["partial_reason"] == "sidecar returned implausible segment count"
    # Backwards-compatible: existing keys the dashboard already reads remain.
    assert payload["text"] == "hello world"
    assert payload["language"] == "en"
    assert payload["duration"] == 1.0
    assert payload["words"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_longform_payload.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_longform_result_payload'`.

- [ ] **Step 3: Write minimal implementation**

Add a module-level helper in `websocket.py` (near the other module helpers; `sanitize_for_json` is already imported):

```python
def _build_longform_result_payload(result: Any) -> dict[str, Any]:
    """Full longform result for persistence + delivery.

    Mirrors the HTTP path (transcription.py uses ``result.to_dict()``) so a
    WebSocket-submitted longform job keeps its segment-level data and any
    ``partial``/``partial_reason`` truncation signal — previously this path
    dropped segments, num_speakers, and partial flags from BOTH the persisted
    result_json and the client message (GH #172 follow-up).
    """
    return sanitize_for_json(result.to_dict())
```

Replace the inline construction in `process_transcription` (lines 375-382):

```python
            # Build and sanitize result payload (full result — see GH #172).
            result_payload = _build_longform_result_payload(result)
```

(`Any` is needed in the signature; ensure `from typing import Any` is imported — it is used elsewhere in the file. The 1 MB size guard at lines 410-412 still applies: large segment payloads correctly route via the `result_ready` HTTP reference, which now also serves the full result from `result_json`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_longform_payload.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_longform_payload.py
git commit -m "fix(server): WebSocket longform path persists + delivers full result incl. segments and partial_reason (GH #172)"
```

---

## Task 7: Update the explanatory comment, run the full suite, and detect-changes

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py` (any remaining stale comment referencing the old flat 10k/5k caps).

- [ ] **Step 1: Update comments**

Grep for stale references and fix prose so no comment still claims a flat "10k segment" cap:

```bash
cd server/backend && grep -n "10k\|10,000\|10000\|5,000\|5000\|to bound memory\|2× safety margin" core/stt/backends/whispercpp_backend.py
```

Reword any hit to describe the proportional bound + fail-loud behavior introduced above.

- [ ] **Step 2: Run the full whisper.cpp + websocket test modules**

Run:
```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py tests/test_websocket_longform_payload.py -v --tb=short
```
Expected: all PASS, no skips for the cap/ceiling/byte-guard/payload tests.

- [ ] **Step 3: Run the broader backend suite to catch regressions**

Run:
```bash
cd server/backend && ../../build/.venv/bin/pytest tests/ -q --tb=short
```
Expected: green except the two known pre-existing failures (db migration version, swr_linear resample — see project memory). Investigate any NEW failure, especially in engine/diarization tests that consume segments/words.

- [ ] **Step 4: GitNexus change verification (project rule)**

Run `gitnexus_detect_changes()` and confirm only the expected symbols/flows changed (`_parse_response`, `_parse_words`, `_transcribe_chunk`, `_resolve_chunk_duration_config`, `process_transcription` + the new helpers). Warn if anything unexpected appears.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_backend.py
git commit -m "docs(stt): describe proportional fail-loud whisper.cpp response bounds (GH #172)"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage:** proportional cap (Task 1-3), fail-loud (Task 2-3), chunk ceiling (Task 4), real memory bound (Task 5), WS segment+partial surfacing (Task 6), comments/regression (Task 7). All requirements mapped.
- **Type/name consistency:** `WhisperCppResponseError`, `_segment_cap_for`/`_word_cap_for`, `_SEGMENT_CAP_FLOOR`/`_WORDS_CAP_FLOOR`, `_MAX_SEGMENTS_PER_AUDIO_SECOND`/`_MAX_WORDS_PER_AUDIO_SECOND`, `_MAX_CHUNK_DURATION_CEILING_S`, `_MAX_RESPONSE_BYTES`, `_build_longform_result_payload`, `_seconds_of_audio` used consistently across tasks. `_parse_response(result, audio_duration_s)` and `_parse_words(raw_words, word_cap)` signatures match their call sites.
- **No placeholders:** every code step shows full code; the one adaptation point (Task 5 mock shape) is called out explicitly with a documented interim fallback.

## Open Decisions (confirm before/at execution)

1. **Fail-loud vs. surface-and-keep on the single-request path.** This plan RAISES on a proportional overflow (correct because overflow ⇒ junk). If you'd rather *never* fail a job — even on a junk payload — the alternative is to keep up to the cap and set `partial=True`/`partial_reason`; but that persists a knowingly-truncated transcript, which the data-loss invariant prefers to avoid. Recommendation: keep RAISE.
2. **Rate/floor constants** (`20` seg/s, `40` w/s, floors `200`/`1000`) are deliberately ~7-10× above real whisper.cpp output. Adjust if you have evidence of higher legitimate density.
3. **Task 5 scope.** Include the streaming byte guard now (recommended — it's the only real memory bound) or ship Tasks 1-4 + 6 first and follow up. Task 5 carries the most test churn (migrating happy-path mocks from `.post` to `.stream`).
4. **Backport.** Released builds (≤ v1.3.6) are fully exposed and lack even the GH #168 chunking fix. Consider whether this lands only on `main` for the next release or is backported.
