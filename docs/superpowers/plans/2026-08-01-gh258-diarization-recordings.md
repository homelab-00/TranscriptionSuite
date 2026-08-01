# GH-258 Diarization for Session-Tab Recordings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a normal microphone/system-audio recording on the Session tab be speaker-diarized, delivering a speaker-labelled transcript that also reaches the Audio Notebook with real speaker segments.

**Architecture:** Twelve self-contained commits. A new `core/diarization_dispatch.py` owns the transcribe-with-optional-diarization decision tree (Tasks 2-3); a new `format_speaker_text()` renders the labelled text (Task 1); the WebSocket longform path gains two `start` fields and calls the helper instead of `engine.transcribe_file` (Tasks 4-6); the dashboard gains a toggle plus speaker-count stepper on the Main Transcription card and threads both through the `start` frame (Tasks 7-10); docs and the UI contract close it out (Tasks 11-12).

**Spec:** `docs/superpowers/specs/2026-08-01-gh258-diarization-recordings-design.md`

**Tech Stack:** Python 3.13 / FastAPI backend (`server/backend/`), pytest via the build venv; TypeScript / React / Electron dashboard (`dashboard/`), vitest via Node 22.

---

## Project conventions (read first, they bite)

- **Branch:** already created — `feat/gh258-diarization-recordings`, based on `main` @ `02921d69`. Do not create another.
- **Backend tests** run from `server/backend/` using the **build venv**, never the server venv:
  ```bash
  cd server/backend
  ../../build/.venv/bin/pytest tests/ -v --tb=short
  ```
  Always finish with the FULL suite, not just the new files.
- **Dashboard tests** need Node 22: `cd dashboard && nvm use`, then `npx vitest run`.
- **`ruff format` runs as a pre-commit hook and MODIFIES files**, which aborts the commit. Run `../../build/.venv/bin/ruff format .` from `server/backend/` before `git add`, not after.
- **Never `pip`, always `uv`** (no new dependencies are needed here).
- **GitNexus:** before modifying a listed function, run `impact({target: "<symbol>", direction: "upstream", repo: "TranscriptionSuite"})` and report the blast radius. Run `detect_changes()` before committing. Warn the user on HIGH/CRITICAL.
- **Commit style** — no line-splitting of long lines, and **no AI attribution of any kind** (no `Co-Authored-By`, no "Generated with"):
  ```
  feat(server): <summary of all changes>

  * feat(server): change 1
  * fix(server): change 2
  ```
- **Dashboard source must not contain `#NNN`** issue references — the UI-contract scanner reads `#258` as a CSS colour literal. Write `GH-258`. Files under `dashboard/electron/` are exempt.
- **Do not restart the user's Docker container.** All work is code plus host-venv tests.

---

## File structure

**Create**

| File | Responsibility |
|------|----------------|
| `server/backend/core/diarization_dispatch.py` | The transcribe-with-optional-diarization decision tree, plus the `DiarizationOutcome` / `DiarizedTranscription` value objects |
| `server/backend/tests/test_diarization_dispatch.py` | Unit tests for the above, with fake engine / model_manager doubles |
| `server/backend/tests/test_format_speaker_text.py` | Unit tests for the new formatter |
| `server/backend/tests/test_websocket_diarization_start.py` | `start`-message field validation |
| `dashboard/components/__tests__/SessionView.diarization.test.tsx` | Toggle rendering, availability gate, start-frame wiring |

**Modify**

| File | Change |
|------|--------|
| `server/backend/core/formatters.py` | Add `format_speaker_text()` |
| `server/backend/core/parallel_diarize.py` | Add the optional `on_diarization_error` callback to both entry points |
| `server/backend/api/routes/websocket.py` | `start` fields, session attributes, dispatch call, phase in progress, `diarization` in the final payload, real webhook `num_speakers`, notebook speaker segments |
| `dashboard/src/config/store.ts` | New `diarization.enabledForRecordings`; flip the `constrainSpeakers` default |
| `dashboard/electron/main.ts` | Mirror both config defaults |
| `dashboard/src/hooks/useTranscription.ts` | `start()` options, `start` frame, result fields, progress phase |
| `dashboard/components/views/SessionView.tsx` | Toggle + stepper + gate + start wiring + skipped-diarization notice |
| `docs/README.md` | Compatibility-matrix note |
| `docs/api-contracts-server.md` | New WebSocket `start` fields and `final` block |

---

### Task 1: `format_speaker_text()` formatter

Renders a diarized result as speaker-labelled paragraphs. Lives beside the other formatters so the speaker-label policy (`_normalize_speaker_value`) stays in one file.

**Files:**
- Modify: `server/backend/core/formatters.py` (append after `format_text`, line 42)
- Test: `server/backend/tests/test_format_speaker_text.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `server/backend/tests/test_format_speaker_text.py`:

```python
"""Tests for the speaker-labelled plain-text formatter (GH-258)."""

from __future__ import annotations

from server.core.formatters import format_speaker_text
from server.core.stt.engine import TranscriptionResult


def _result(segments, text="flat fallback text"):
    return TranscriptionResult(text=text, segments=segments)


def test_alternating_speakers_become_labelled_paragraphs():
    result = _result(
        [
            {"text": "Good morning.", "speaker": "SPEAKER_00"},
            {"text": "Morning.", "speaker": "SPEAKER_01"},
        ]
    )

    assert format_speaker_text(result) == "SPEAKER_00: Good morning.\n\nSPEAKER_01: Morning."


def test_consecutive_same_speaker_segments_coalesce_into_one_paragraph():
    result = _result(
        [
            {"text": "Good morning.", "speaker": "SPEAKER_00"},
            {"text": "Let us begin.", "speaker": "SPEAKER_00"},
            {"text": "Ready.", "speaker": "SPEAKER_01"},
        ]
    )

    assert format_speaker_text(result) == (
        "SPEAKER_00: Good morning. Let us begin.\n\nSPEAKER_01: Ready."
    )


def test_returns_flat_text_when_no_segment_carries_a_speaker():
    result = _result([{"text": "Just dictation."}, {"text": "No speakers here."}])

    assert format_speaker_text(result) == "flat fallback text"


def test_returns_flat_text_when_there_are_no_segments():
    assert format_speaker_text(_result([])) == "flat fallback text"


def test_unknown_sentinel_yields_an_unlabelled_paragraph():
    result = _result(
        [
            {"text": "Attributed line.", "speaker": "SPEAKER_00"},
            {"text": "Unattributable line.", "speaker": "UNKNOWN"},
        ]
    )

    assert format_speaker_text(result) == "SPEAKER_00: Attributed line.\n\nUnattributable line."


def test_blank_and_whitespace_segments_are_skipped():
    result = _result(
        [
            {"text": "Real line.", "speaker": "SPEAKER_00"},
            {"text": "   ", "speaker": "SPEAKER_01"},
            {"text": "", "speaker": "SPEAKER_01"},
            {"text": "Second real line.", "speaker": "SPEAKER_00"},
        ]
    )

    # The blank SPEAKER_01 segments contribute nothing, so the two SPEAKER_00
    # turns stay separate paragraphs rather than silently merging.
    assert format_speaker_text(result) == (
        "SPEAKER_00: Real line.\n\nSPEAKER_00: Second real line."
    )


def test_missing_text_key_is_tolerated():
    result = _result([{"speaker": "SPEAKER_00"}, {"text": "Present.", "speaker": "SPEAKER_00"}])

    assert format_speaker_text(result) == "SPEAKER_00: Present."
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_format_speaker_text.py -v --tb=short
```

Expected: collection error — `ImportError: cannot import name 'format_speaker_text' from 'server.core.formatters'`.

- [ ] **Step 3: Write the implementation**

Insert into `server/backend/core/formatters.py` immediately after `format_text()` (which ends at line 42):

```python
def format_speaker_text(result: TranscriptionResult) -> str:
    """Render a diarized result as speaker-labelled paragraphs (GH-258).

    One paragraph per speaker turn: consecutive segments sharing a speaker are
    joined with a space, turns are separated by a blank line, and a labelled
    turn is prefixed ``"SPEAKER_00: "``. Segments whose speaker is missing,
    empty or the ``UNKNOWN`` sentinel produce an unlabelled paragraph.

    Returns ``result.text`` unchanged when no segment carries a speaker, so
    callers can invoke this unconditionally on any result.

    Labels stay in the raw ``SPEAKER_00`` form rather than the ``Speaker 1``
    form ``subtitle_export.normalize_speaker_labels`` produces: this string is
    persisted as the job's ``result_text`` and must match the ``speaker`` keys
    stored alongside it on the segments.
    """
    segments = result.segments or []
    if not any(_normalize_speaker_value(seg.get("speaker")) for seg in segments):
        return result.text

    # Accumulate (speaker, [text, ...]) turns, opening a new turn whenever the
    # speaker changes. Building the list first keeps the join logic trivial.
    turns: list[tuple[str | None, list[str]]] = []
    for seg in segments:
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        speaker = _normalize_speaker_value(seg.get("speaker"))
        if turns and turns[-1][0] == speaker:
            turns[-1][1].append(text)
        else:
            turns.append((speaker, [text]))

    return "\n\n".join(
        f"{speaker}: {' '.join(parts)}" if speaker else " ".join(parts)
        for speaker, parts in turns
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_format_speaker_text.py -v --tb=short
```

Expected: 7 passed.

- [ ] **Step 5: Format and commit**

```bash
cd server/backend
../../build/.venv/bin/ruff format core/formatters.py tests/test_format_speaker_text.py
cd ../..
git add server/backend/core/formatters.py server/backend/tests/test_format_speaker_text.py
git commit -m "feat(server): render diarized results as speaker-labelled paragraphs (GH-258)

* feat(server): add format_speaker_text, which coalesces consecutive same-speaker segments into one paragraph and prefixes each turn with its raw SPEAKER_NN label
* feat(server): return the flat transcript unchanged when no segment carries a speaker, so callers can invoke the formatter unconditionally
* test(server): cover coalescing, the UNKNOWN sentinel, blank segments, missing text keys and the no-speaker passthrough"
```

---

### Task 2: `on_diarization_error` callback on `parallel_diarize`

`parallel_diarize` swallows diarization failures internally and returns `(result, None)`, so callers cannot tell an out-of-memory failure from a missing model. This adds a strictly optional observer so the caller can classify. Existing callers pass nothing and behave identically.

**Files:**
- Modify: `server/backend/core/parallel_diarize.py` (both entry points)
- Test: `server/backend/tests/test_parallel_diarize.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `server/backend/tests/test_parallel_diarize.py`:

```python
def test_sequential_reports_the_diarization_error_to_the_observer():
    """GH-258: the caller needs the exception to classify it (e.g. as OOM)."""
    boom = RuntimeError("CUDA out of memory")
    seen: list[BaseException] = []

    engine = _make_engine(result=MagicMock(words=[], segments=[]))
    mm = _make_model_manager(diarize_error=boom)

    with patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000)):
        result, diar = transcribe_then_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
            on_diarization_error=seen.append,
        )

    assert diar is None
    assert result is not None
    assert seen == [boom]


def test_parallel_reports_the_diarization_error_to_the_observer():
    boom = RuntimeError("CUDA failed with error out of memory")
    seen: list[BaseException] = []

    engine = _make_engine(result=MagicMock(words=[], segments=[]))
    mm = _make_model_manager(diarize_error=boom)

    with patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000)):
        result, diar = transcribe_and_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
            on_diarization_error=seen.append,
        )

    assert diar is None
    assert result is not None
    assert seen == [boom]


def test_observer_is_optional_and_a_raising_observer_cannot_break_the_run():
    """A misbehaving observer must never cost the user their transcript."""
    engine = _make_engine(result=MagicMock(words=[], segments=[]))
    mm = _make_model_manager(diarize_error=RuntimeError("nope"))

    def _bad_observer(_exc: BaseException) -> None:
        raise ValueError("observer blew up")

    with patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000)):
        result, diar = transcribe_and_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
            on_diarization_error=_bad_observer,
        )

    assert diar is None
    assert result is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_parallel_diarize.py -k observer -v --tb=short
```

Expected: FAIL with `TypeError: transcribe_then_diarize() got an unexpected keyword argument 'on_diarization_error'`.

- [ ] **Step 3: Write the implementation**

In `server/backend/core/parallel_diarize.py`, add a module-level helper after the `logger` assignment (line 29):

```python
def _report_diarization_error(
    on_diarization_error: Callable[[BaseException], None] | None,
    exc: BaseException,
) -> None:
    """Hand a swallowed diarization failure to an optional observer (GH-258).

    Diarization failures are swallowed here by design so a transcript is never
    lost, but that erases the reason - a caller cannot tell an out-of-memory
    failure from a missing model. The observer restores it without changing the
    return contract. Never raises: an observer defect must not become the
    failure that costs the user their transcript.
    """
    if on_diarization_error is None:
        return
    try:
        on_diarization_error(exc)
    except Exception:
        logger.warning("on_diarization_error observer raised; ignoring", exc_info=True)
```

Add the keyword to **both** signatures, immediately after `progress_callback`:

```python
    progress_callback: Callable[[int, int], None] | None = None,
    on_diarization_error: Callable[[BaseException], None] | None = None,
) -> tuple[TranscriptionResult, DiarizationResult | None]:
```

In `transcribe_then_diarize`, the Phase 2 `except` block currently reads:

```python
    except Exception:
        logger.warning(
            "Diarization failed during sequential run — returning transcript without speakers",
            exc_info=True,
        )
        return result, None
```

Replace it with:

```python
    except Exception as diar_exc:
        logger.warning(
            "Diarization failed during sequential run — returning transcript without speakers",
            exc_info=True,
        )
        _report_diarization_error(on_diarization_error, diar_exc)
        return result, None
```

In `transcribe_and_diarize`, the pre-load `except` block currently reads:

```python
    except Exception:
        logger.warning(
            "Diarization pre-load failed — falling back to transcription only",
            exc_info=True,
        )
```

Replace it with:

```python
    except Exception as preload_exc:
        logger.warning(
            "Diarization pre-load failed — falling back to transcription only",
            exc_info=True,
        )
        _report_diarization_error(on_diarization_error, preload_exc)
```

And the Phase 3 collection `except` block currently reads:

```python
        except Exception:
            logger.warning(
                "Diarization failed during parallel run — returning transcript without speakers",
                exc_info=True,
            )
            return result, None
```

Replace it with:

```python
        except Exception as diar_exc:
            logger.warning(
                "Diarization failed during parallel run — returning transcript without speakers",
                exc_info=True,
            )
            _report_diarization_error(on_diarization_error, diar_exc)
            return result, None
```

Finally, the Sortformer delegation inside `transcribe_and_diarize` must forward the observer. Add one line to that `return transcribe_then_diarize(...)` call:

```python
                progress_callback=progress_callback,
                on_diarization_error=on_diarization_error,
            )
```

- [ ] **Step 4: Run the full parallel_diarize suite**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_parallel_diarize.py -v --tb=short
```

Expected: all pre-existing tests still pass, plus the 3 new ones.

- [ ] **Step 5: Format and commit**

```bash
cd server/backend
../../build/.venv/bin/ruff format core/parallel_diarize.py tests/test_parallel_diarize.py
cd ../..
git add server/backend/core/parallel_diarize.py server/backend/tests/test_parallel_diarize.py
git commit -m "feat(server): let callers observe the diarization failure parallel_diarize swallows (GH-258)

* feat(server): add an optional on_diarization_error keyword to transcribe_then_diarize and transcribe_and_diarize, invoked from the three existing except blocks so a caller can classify the failure it never sees
* feat(server): forward the observer through the Sortformer sequential delegation
* fix(server): swallow anything the observer itself raises, so an observer defect can never cost the user their transcript
* test(server): cover the sequential path, the parallel path and a raising observer"
```

---

### Task 3: `core/diarization_dispatch.py`

The decision tree, extracted so the WebSocket path is not a fourth copy.

**Files:**
- Create: `server/backend/core/diarization_dispatch.py`
- Test: `server/backend/tests/test_diarization_dispatch.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `server/backend/tests/test_diarization_dispatch.py`:

```python
"""Tests for the shared transcribe-with-optional-diarization dispatch (GH-258)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from server.core.diarization_dispatch import (
    DiarizationOutcome,
    transcribe_with_optional_diarization,
)
from server.core.model_manager import TranscriptionCancelledError
from server.core.stt.engine import TranscriptionResult


def _plain_result(text="hello world"):
    return TranscriptionResult(
        text=text,
        segments=[{"text": text, "start": 0.0, "end": 1.0}],
        words=[{"word": "hello", "start": 0.0, "end": 0.5}],
        duration=1.0,
    )


def _make_engine(result=None, side_effect=None, backend=None):
    engine = MagicMock()
    engine.model_name = "large-v3"
    engine.beam_size = 5
    # Default to None, NOT a MagicMock: the real use_integrated_diarization_for
    # reads `type(backend).transcribe_with_diarization`, and the MagicMock CLASS
    # has no such attribute, so a mock backend raises AttributeError. None short-
    # circuits the check to False, which is what the standard-path tests want.
    engine._backend = backend
    if side_effect is not None:
        engine.transcribe_file.side_effect = side_effect
    else:
        engine.transcribe_file.return_value = result or _plain_result()
    return engine


def _make_model_manager(reason="unavailable"):
    mm = MagicMock()
    mm.get_diarization_feature_status.return_value = {"available": False, "reason": reason}
    return mm


def test_diarization_off_runs_plain_transcription_and_reports_not_requested():
    expected = _plain_result()
    engine = _make_engine(result=expected)

    dispatched = transcribe_with_optional_diarization(
        engine=engine,
        model_manager=_make_model_manager(),
        file_path="/tmp/a.wav",
        enable_diarization=False,
    )

    assert dispatched.result is expected
    assert dispatched.speaker_segments is None
    assert dispatched.outcome == DiarizationOutcome(requested=False, performed=False)
    engine.transcribe_file.assert_called_once()


def test_diarization_forces_word_timestamps_even_when_the_caller_said_no():
    engine = _make_engine()
    mm = _make_model_manager()
    diar_result = MagicMock(segments=[], num_speakers=0)

    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        return_value=(_plain_result(), diar_result),
    ) as diarize_fn:
        transcribe_with_optional_diarization(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/a.wav",
            enable_diarization=True,
            word_timestamps=False,
            parallel_diarization=True,
        )

    assert diarize_fn.call_args.kwargs["word_timestamps"] is True


def test_standard_path_merges_speakers_onto_the_result():
    base = _plain_result()
    diar_seg = MagicMock()
    diar_seg.to_dict.return_value = {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}
    diar_result = MagicMock(segments=[diar_seg], num_speakers=1)

    merged_segments = [{"text": "hello world", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    merged_words = [{"word": "hello", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"}]

    with (
        patch(
            "server.core.parallel_diarize.transcribe_and_diarize",
            return_value=(base, diar_result),
        ),
        patch(
            "server.core.speaker_merge.build_speaker_segments",
            return_value=(merged_segments, merged_words, 1),
        ),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result.segments == merged_segments
    assert dispatched.result.num_speakers == 1
    assert dispatched.speaker_segments == [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}]
    assert dispatched.outcome.performed is True
    assert dispatched.outcome.reason == "ready"


def test_sequential_path_is_chosen_when_parallel_is_false():
    diar_result = MagicMock(segments=[], num_speakers=0)

    with (
        patch(
            "server.core.parallel_diarize.transcribe_then_diarize",
            return_value=(_plain_result(), diar_result),
        ) as sequential,
        patch("server.core.parallel_diarize.transcribe_and_diarize") as parallel,
    ):
        transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=False,
        )

    sequential.assert_called_once()
    parallel.assert_not_called()


def test_diarization_returning_none_degrades_with_the_feature_status_reason():
    base = _plain_result()

    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        return_value=(base, None),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(reason="token_missing"),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result is base
    assert dispatched.speaker_segments is None
    assert dispatched.outcome.performed is False
    assert dispatched.outcome.reason == "token_missing"


def test_observed_out_of_memory_is_classified_with_a_remedy():
    base = _plain_result()

    def _fake_diarize(*_args, on_diarization_error=None, **_kwargs):
        on_diarization_error(RuntimeError("CUDA failed with error out of memory"))
        return base, None

    with patch("server.core.parallel_diarize.transcribe_and_diarize", _fake_diarize):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.outcome.reason == "out_of_memory"
    assert dispatched.outcome.remedy
    assert "VRAM" in dispatched.outcome.remedy


def test_speaker_merge_failure_degrades_instead_of_raising():
    base = _plain_result()
    diar_seg = MagicMock()
    diar_seg.to_dict.return_value = {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}

    with (
        patch(
            "server.core.parallel_diarize.transcribe_and_diarize",
            return_value=(base, MagicMock(segments=[diar_seg], num_speakers=1)),
        ),
        patch(
            "server.core.speaker_merge.build_speaker_segments",
            side_effect=RuntimeError("merge exploded"),
        ),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result is base
    assert dispatched.outcome.performed is False


def test_cancellation_propagates_rather_than_degrading():
    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        side_effect=TranscriptionCancelledError("cancelled"),
    ):
        with pytest.raises(TranscriptionCancelledError):
            transcribe_with_optional_diarization(
                engine=_make_engine(),
                model_manager=_make_model_manager(),
                file_path="/tmp/a.wav",
                enable_diarization=True,
                parallel_diarization=True,
            )


def test_plain_transcription_failure_propagates():
    engine = _make_engine(side_effect=RuntimeError("model exploded"))

    with pytest.raises(RuntimeError, match="model exploded"):
        transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=False,
        )


def test_integrated_backend_single_pass_path():
    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    diar_segments = [{"text": "hi", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    backend.transcribe_with_diarization.return_value = MagicMock(
        segments=diar_segments,
        words=[],
        language="en",
        language_probability=0.99,
        num_speakers=1,
    )
    engine = _make_engine(backend=backend)

    with (
        patch("server.core.audio_utils.load_audio", return_value=([0.0] * 16000, 16000)),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
        )

    assert dispatched.outcome.performed is True
    assert dispatched.result.num_speakers == 1
    assert dispatched.speaker_segments == diar_segments
    engine.transcribe_file.assert_not_called()


def test_integrated_backend_failure_falls_back_to_plain_transcription():
    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    backend.transcribe_with_diarization.side_effect = ValueError("needs a HuggingFace token")
    expected = _plain_result()
    engine = _make_engine(result=expected, backend=backend)

    with (
        patch("server.core.audio_utils.load_audio", return_value=([0.0] * 16000, 16000)),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(reason="token_missing"),
            file_path="/tmp/a.wav",
            enable_diarization=True,
        )

    assert dispatched.result is expected
    assert dispatched.outcome.performed is False
    assert dispatched.outcome.reason == "token_missing"
    engine.transcribe_file.assert_called_once()


def test_audio_decode_error_propagates_from_the_integrated_path():
    from server.core.audio_utils import AudioDecodeError

    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    engine = _make_engine(backend=backend)

    with (
        patch("server.core.audio_utils.load_audio", side_effect=AudioDecodeError("corrupt")),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        with pytest.raises(AudioDecodeError):
            transcribe_with_optional_diarization(
                engine=engine,
                model_manager=_make_model_manager(),
                file_path="/tmp/a.wav",
                enable_diarization=True,
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_diarization_dispatch.py -v --tb=short
```

Expected: collection error — `ModuleNotFoundError: No module named 'server.core.diarization_dispatch'`.

- [ ] **Step 3: Write the implementation**

Create `server/backend/core/diarization_dispatch.py`:

```python
"""Shared transcribe-with-optional-diarization dispatch (GH-258).

One place that turns "an audio file plus a diarization request" into a
:class:`TranscriptionResult` whose segments carry speaker labels. Extracted so
the WebSocket recording path does not become a fourth copy of logic already
duplicated across ``transcription.py``, ``notebook.py`` and ``openai_audio.py``.
Those three routes are deliberately NOT migrated in this change; each has its
own HTTP status codes, response headers and database writes, and moving them is
a separate PR.

Error contract, which is about which operation raised rather than which type:
  * anything from the DIARIZATION attempt is swallowed - the transcript is
    still returned, with the reason recorded on the outcome;
  * anything from the PLAIN TRANSCRIPTION call propagates - that is a genuine
    transcription failure and the caller owns it;
  * ``TranscriptionCancelledError`` and ``AudioDecodeError`` propagate from
    either, because a user cancel must reach the caller's cancel handling and a
    corrupt file would defeat plain transcription too.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from server.core.model_manager import TranscriptionCancelledError

if TYPE_CHECKING:
    from server.core.model_manager import ModelManager
    from server.core.stt.engine import AudioToTextRecorder, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiarizationOutcome:
    """Why diarization did or did not happen, for client-facing reporting."""

    requested: bool
    performed: bool
    reason: str | None = None
    remedy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "performed": self.performed,
            "reason": self.reason,
            "remedy": self.remedy,
        }


@dataclass(frozen=True)
class DiarizedTranscription:
    """A transcription plus whatever the diarization attempt produced."""

    result: TranscriptionResult
    #: Speaker turns in the shape ``save_longform_to_database`` expects for
    #: word alignment. ``None`` when diarization did not run or did not succeed.
    speaker_segments: list[dict[str, Any]] | None
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
) -> DiarizedTranscription:
    """Transcribe *file_path*, attaching speaker labels when asked to."""
    if not enable_diarization:
        result = _transcribe_plain(
            engine=engine,
            file_path=file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=DiarizationOutcome(requested=False, performed=False),
        )

    backend = getattr(engine, "_backend", None)

    from server.config import resolve_sensevoice_diarization_engine
    from server.core.stt.backends import base as backend_base

    resolved_engine = resolve_sensevoice_diarization_engine(
        getattr(engine, "model_name", None),
        diarization_engine,
        sensevoice_engine_default,
        funasr_diar_available=getattr(backend, "_diarization_loaded", False),
    )

    if backend_base.use_integrated_diarization_for(backend, resolved_engine):
        integrated = _run_integrated(
            engine=engine,
            backend=backend,
            file_path=file_path,
            language=language,
            task=task,
            expected_speakers=expected_speakers,
            progress_callback=progress_callback,
        )
        if integrated is not None:
            return integrated
        # The backend's own pass failed. Fall back to PLAIN transcription
        # rather than the two-pass PyAnnote path: the dominant failure is a
        # missing HF token, which the second path cannot fix either, and a
        # user is waiting on a live recording.
        result = _transcribe_plain(
            engine=engine,
            file_path=file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=_failure_outcome(model_manager, None),
        )

    return _run_standard(
        engine=engine,
        model_manager=model_manager,
        file_path=file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        expected_speakers=expected_speakers,
        parallel_diarization=parallel_diarization,
        progress_callback=progress_callback,
        cancellation_check=cancellation_check,
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _transcribe_plain(
    *,
    engine: AudioToTextRecorder,
    file_path: str,
    language: str | None,
    task: str | None,
    translation_target_language: str | None,
    word_timestamps: bool,
    progress_callback: Callable[[int, int], None] | None,
    cancellation_check: Callable[[], bool] | None,
) -> TranscriptionResult:
    """Run transcription with no diarization. Failures propagate."""
    return engine.transcribe_file(
        file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        word_timestamps=word_timestamps,
        progress_callback=progress_callback,
        cancellation_check=cancellation_check,
    )


def _run_integrated(
    *,
    engine: AudioToTextRecorder,
    backend: Any,
    file_path: str,
    language: str | None,
    task: str | None,
    expected_speakers: int | None,
    progress_callback: Callable[[int, int], None] | None,
) -> DiarizedTranscription | None:
    """Single-pass diarization on backends that implement it themselves.

    Returns ``None`` when the backend path failed, so the caller can fall back.
    """
    from server.core.audio_utils import AudioDecodeError, load_audio
    from server.core.stt.engine import TranscriptionResult

    backend_label = getattr(backend, "backend_name", "integrated")
    try:
        preferred_rate = int(getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000)
        audio_data, audio_sample_rate = load_audio(file_path, target_sample_rate=preferred_rate)
        logger.info("Using %s single-pass diarization", backend_label)
        diar_result = backend.transcribe_with_diarization(
            audio_data,
            audio_sample_rate=audio_sample_rate,
            language=language,
            task=task,
            beam_size=getattr(engine, "beam_size", 5),
            num_speakers=expected_speakers,
            progress_callback=progress_callback,
        )
    except (TranscriptionCancelledError, AudioDecodeError):
        raise
    except Exception:
        logger.warning(
            "%s single-pass diarization failed; falling back to plain transcription",
            backend_label,
            exc_info=True,
        )
        return None

    result = TranscriptionResult(
        text=" ".join(seg.get("text", "") for seg in diar_result.segments).strip(),
        segments=diar_result.segments,
        words=diar_result.words,
        language=diar_result.language,
        language_probability=diar_result.language_probability,
        duration=len(audio_data) / audio_sample_rate,
        num_speakers=diar_result.num_speakers,
    )
    logger.info(
        "%s diarization complete: %s speakers found", backend_label, diar_result.num_speakers
    )
    return DiarizedTranscription(
        result=result,
        speaker_segments=list(diar_result.segments),
        outcome=DiarizationOutcome(requested=True, performed=True, reason="ready"),
    )


def _run_standard(
    *,
    engine: AudioToTextRecorder,
    model_manager: ModelManager,
    file_path: str,
    language: str | None,
    task: str | None,
    translation_target_language: str | None,
    expected_speakers: int | None,
    parallel_diarization: bool | None,
    progress_callback: Callable[[int, int], None] | None,
    cancellation_check: Callable[[], bool] | None,
) -> DiarizedTranscription:
    """Two-pass path: STT plus a separate diarizer, then a speaker merge."""
    from server.core import parallel_diarize

    if parallel_diarization is None:
        from server.config import get_config, resolve_parallel_diarization_default

        use_parallel = resolve_parallel_diarization_default(get_config())
    else:
        use_parallel = parallel_diarization

    diarize_fn = (
        parallel_diarize.transcribe_and_diarize
        if use_parallel
        else parallel_diarize.transcribe_then_diarize
    )

    # parallel_diarize swallows diarization failures by design; this collector
    # is the only way to learn WHY, which is what makes OOM reportable.
    observed: list[BaseException] = []

    result, diar_result = diarize_fn(
        engine=engine,
        model_manager=model_manager,
        file_path=file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        # Speaker alignment needs word timings regardless of what was asked for.
        word_timestamps=True,
        expected_speakers=expected_speakers,
        cancellation_check=cancellation_check,
        progress_callback=progress_callback,
        on_diarization_error=observed.append,
    )

    if diar_result is None:
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=_failure_outcome(model_manager, observed[0] if observed else None),
        )

    diar_dicts = [seg.to_dict() for seg in diar_result.segments]
    merged = _merge_speakers(result, diar_dicts)
    if not merged:
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=_failure_outcome(model_manager, observed[0] if observed else None),
        )

    logger.info("Diarization complete: %s speakers found", result.num_speakers)
    return DiarizedTranscription(
        result=result,
        speaker_segments=diar_dicts,
        outcome=DiarizationOutcome(requested=True, performed=True, reason="ready"),
    )


def _merge_speakers(result: TranscriptionResult, diar_dicts: list[dict[str, Any]]) -> bool:
    """Attach speakers to *result* in place. Returns False when nothing merged.

    Mutating the result matches what every existing route does
    (``transcription.py:502-504``); a copy here would silently diverge from
    them the moment ``TranscriptionResult`` gains a field.
    """
    from server.core import speaker_merge

    try:
        merged_segments, merged_words, num_speakers = speaker_merge.build_speaker_segments(
            result.words, diar_dicts
        )
        if merged_segments:
            result.segments = merged_segments
            result.words = merged_words
            result.num_speakers = num_speakers
            return True

        # No word timestamps (e.g. the MLX Canary backend) - fall back to
        # segment-level attribution so the segments still carry speakers.
        if not result.words and result.segments:
            fallback = speaker_merge.build_speaker_segments_nowords(result.segments, diar_dicts)
            if fallback:
                speakers = {seg["speaker"] for seg in fallback} - {"UNKNOWN"}
                result.segments = fallback
                result.num_speakers = len(speakers)
                return True
        return False
    except Exception:
        logger.warning(
            "Speaker merge failed; returning the transcript without speakers", exc_info=True
        )
        return False


def _failure_outcome(
    model_manager: ModelManager, exc: BaseException | None
) -> DiarizationOutcome:
    """Build the outcome for a diarization attempt that did not produce speakers."""
    from server.core.stt.backends.base import as_gpu_oom

    if exc is not None:
        oom = as_gpu_oom(exc)
        if oom is not None:
            return DiarizationOutcome(
                requested=True, performed=False, reason="out_of_memory", remedy=oom.remedy
            )

    try:
        reason = model_manager.get_diarization_feature_status().get("reason", "unavailable")
    except Exception:
        reason = "unavailable"
    return DiarizationOutcome(requested=True, performed=False, reason=reason or "unavailable")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_diarization_dispatch.py -v --tb=short
```

Expected: 12 passed.

- [ ] **Step 5: Format and commit**

```bash
cd server/backend
../../build/.venv/bin/ruff format core/diarization_dispatch.py tests/test_diarization_dispatch.py
cd ../..
git add server/backend/core/diarization_dispatch.py server/backend/tests/test_diarization_dispatch.py
git commit -m "feat(server): add a shared transcribe-with-optional-diarization dispatch (GH-258)

* feat(server): add core/diarization_dispatch.py owning the integrated single-pass, two-pass parallel/sequential and plain-transcription branches behind one call, returning the result plus a frozen DiarizationOutcome
* feat(server): classify a swallowed diarization failure through as_gpu_oom so an out-of-memory run reports an actionable remedy instead of a generic unavailable
* feat(server): force word timestamps whenever diarization is requested, since speaker alignment needs them regardless of the caller's flag
* fix(server): degrade on any diarization failure but propagate cancellation, audio-decode errors and plain-transcription failures
* test(server): cover both diarization paths, the no-words fallback, merge failure, OOM classification and every propagation rule"
```

---

### Task 4: WebSocket `start` protocol fields

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (`TranscriptionSession.__init__` line 181, `start_recording` line 678, `handle_client_message` line 849)
- Test: `server/backend/tests/test_websocket_diarization_start.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `server/backend/tests/test_websocket_diarization_start.py`:

```python
"""GH-258: the WebSocket `start` frame carries diarization options."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from server.api.routes import websocket as ws


def _session():
    # Plain MagicMock, NOT spec=TranscriptionSession: `spec` builds its allowed
    # attribute set from dir(cls), which excludes anything assigned in __init__,
    # so `session._current_job_id = None` would raise AttributeError.
    session = MagicMock()
    session.client_name = "test-client"
    session._current_job_id = None
    session.start_recording = AsyncMock()
    session.send_message = AsyncMock()
    return session


def _dispatch(data: dict) -> dict:
    """Run handle_client_message for a `start` frame; return start_recording kwargs."""
    session = _session()
    model_manager = MagicMock()
    model_manager.job_tracker.try_start_job.return_value = (True, "job-1", None)

    with (
        patch("server.core.model_manager.get_model_manager", return_value=model_manager),
        patch.object(ws, "_create_job"),
    ):
        asyncio.run(ws.handle_client_message(session, {"type": "start", "data": data}))

    assert session.start_recording.await_count == 1
    return session.start_recording.await_args.kwargs


def test_diarization_defaults_to_off_when_absent():
    kwargs = _dispatch({})
    assert kwargs["diarization"] is False
    assert kwargs["expected_speakers"] is None


def test_diarization_true_is_accepted():
    assert _dispatch({"diarization": True})["diarization"] is True


@pytest.mark.parametrize("bad", ["yes", 1, None, [], {}])
def test_non_bool_diarization_is_rejected(bad):
    assert _dispatch({"diarization": bad})["diarization"] is False


@pytest.mark.parametrize("value", [1, 2, 10])
def test_expected_speakers_in_range_is_accepted(value):
    kwargs = _dispatch({"diarization": True, "expected_speakers": value})
    assert kwargs["expected_speakers"] == value


@pytest.mark.parametrize("bad", [0, -1, 11, 99, "2", 2.5, None])
def test_expected_speakers_out_of_range_or_wrong_type_becomes_none(bad):
    kwargs = _dispatch({"diarization": True, "expected_speakers": bad})
    assert kwargs["expected_speakers"] is None


def test_bool_true_is_not_accepted_as_a_speaker_count():
    """`True` is an int in Python and 1 <= True <= 10 - it must still be rejected."""
    kwargs = _dispatch({"diarization": True, "expected_speakers": True})
    assert kwargs["expected_speakers"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_websocket_diarization_start.py -v --tb=short
```

Expected: FAIL with `KeyError: 'diarization'` — `start_recording` is not yet called with those kwargs.

- [ ] **Step 3: Write the implementation**

In `TranscriptionSession.__init__`, immediately after the `self.auto_add_to_notebook = False` line (currently line 213):

```python
        # Speaker diarization for this recording (GH-258). Resolved per-session
        # at `start` from the Session-tab toggle; OFF unless asked for.
        self.diarization_enabled = False
        self.expected_speakers: int | None = None
```

In `start_recording`, extend the signature and docstring:

```python
    async def start_recording(
        self,
        language: str | None = None,
        use_vad: bool = False,
        translation_enabled: bool = False,
        translation_target_language: str = "en",
        auto_add_to_notebook: bool = False,
        diarization: bool = False,
        expected_speakers: int | None = None,
    ) -> None:
        """
        Start a recording session.

        Args:
            language: Target language code
            use_vad: Use VAD for automatic start/stop detection
            translation_enabled: Enable source→target translation
            translation_target_language: Translation target (v1: "en" only)
            auto_add_to_notebook: Save the finished recording to the Audio Notebook
            diarization: Attach speaker labels to the finished transcript
            expected_speakers: Exact speaker count (1-10), or None to auto-detect
        """
```

and, next to the existing `self.auto_add_to_notebook = auto_add_to_notebook` assignment:

```python
        self.diarization_enabled = diarization
        self.expected_speakers = expected_speakers
```

In `handle_client_message`, immediately after the `_server_auto_add` block and before the `await session.start_recording(` call:

```python
        # GH-258: speaker diarization for this recording. Untrusted input, so
        # bool-only and an int strictly inside 1-10. The explicit bool guard on
        # expected_speakers matters: in Python `True` IS an int, and
        # `1 <= True <= 10` is True, so a client sending `true` would otherwise
        # silently pin the run to one speaker.
        _raw_diarization = _msg_data.get("diarization")
        _diarization = _raw_diarization if isinstance(_raw_diarization, bool) else False
        _raw_speakers = _msg_data.get("expected_speakers")
        _expected_speakers: int | None = (
            _raw_speakers
            if isinstance(_raw_speakers, int)
            and not isinstance(_raw_speakers, bool)
            and 1 <= _raw_speakers <= 10
            else None
        )
```

and extend the call:

```python
        await session.start_recording(
            language,
            use_vad,
            translation_enabled,
            translation_target_language,
            auto_add_to_notebook=_client_auto_add or _server_auto_add,
            diarization=_diarization,
            expected_speakers=_expected_speakers,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_websocket_diarization_start.py -v --tb=short
```

Expected: 20 passed (parametrized cases included).

- [ ] **Step 5: Format and commit**

```bash
cd server/backend
../../build/.venv/bin/ruff format api/routes/websocket.py tests/test_websocket_diarization_start.py
cd ../..
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_diarization_start.py
git commit -m "feat(server): accept diarization options on the WebSocket start frame (GH-258)

* feat(server): add diarization and expected_speakers to the start message, stored on the session and passed through start_recording
* fix(server): reject a bool as a speaker count, since True is an int in Python and would otherwise pin the run to a single speaker
* test(server): cover the default-off case, type rejection and the 1-10 range boundary"
```

---

### Task 5: Wire the dispatch into `process_transcription`

**Files:**
- Modify: `server/backend/api/routes/websocket.py:432-500` (transcribe call, keepalive, payload) and line 598 (webhook)

- [ ] **Step 1: Replace the transcribe call**

Replace the `transcribe_future = loop.run_in_executor(...)` block (currently lines 450-467) with:

```python
            from server.core.diarization_dispatch import transcribe_with_optional_diarization

            loop = asyncio.get_event_loop()
            transcribe_future = loop.run_in_executor(
                None,
                lambda: transcribe_with_optional_diarization(
                    engine=engine,
                    model_manager=model_manager,
                    file_path=str(self.temp_file),
                    enable_diarization=self.diarization_enabled,
                    language=self.language,
                    task=task,
                    translation_target_language=translation_target,
                    word_timestamps=True,
                    expected_speakers=self.expected_speakers,
                    # None: let the dispatcher read the server-wide default.
                    parallel_diarization=None,
                    progress_callback=_on_progress,
                    # Two independent stop signals, both of which must reach the
                    # backend: the client vanished, or the user pressed Cancel
                    # (POST /cancel -> job_tracker). Binding only the former left
                    # Cancel a no-op on this, the main longform path.
                    cancellation_check=lambda: (
                        self._client_disconnected or model_manager.job_tracker.is_cancelled()
                    ),
                ),
            )
```

- [ ] **Step 2: Report the processing phase on the keepalive**

Replace the keepalive `await self.send_message(...)` call (currently lines 478-484) with:

```python
                # GH-258: sequential diarization spends minutes in a phase that
                # reports no numeric progress. Forwarding the phase lets the
                # client render "Identifying speakers" instead of a frozen bar.
                _tracker_progress = model_manager.job_tracker.get_status().get("progress") or {}
                await self.send_message(
                    "processing_progress",
                    {
                        "current": _progress["current"],
                        "total": _progress["total"],
                        "phase": _tracker_progress.get("phase"),
                    },
                )
```

- [ ] **Step 3: Unpack the dispatch result and format the labelled text**

Replace `result = transcribe_future.result()` and the payload line that follows (currently lines 486-489) with:

```python
            dispatched = transcribe_future.result()
            result = dispatched.result
            diarization_outcome = dispatched.outcome

            # Speaker labels must be baked into result.text BEFORE the payload
            # is built: the payload is what gets persisted, and a recovery via
            # GET /result/{job_id} would otherwise return bare text while the
            # live client got labelled text.
            if diarization_outcome.performed:
                from server.core.formatters import format_speaker_text

                result.text = format_speaker_text(result)

            # Build and sanitize result payload (full result — see GH #172).
            result_payload = _build_longform_result_payload(result)
            if diarization_outcome.requested:
                result_payload["diarization"] = diarization_outcome.to_dict()
```

- [ ] **Step 4: Report the real speaker count on the webhook**

At line 598, replace:

```python
                        "num_speakers": 0,
```

with:

```python
                        "num_speakers": result.num_speakers,
```

- [ ] **Step 5: Run the full backend suite**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

Expected: everything passes. If a pre-existing WebSocket test asserts the exact `processing_progress` payload shape, update it to expect the new `phase` key — the added key is the intended change.

- [ ] **Step 6: Format and commit**

```bash
cd server/backend
../../build/.venv/bin/ruff format api/routes/websocket.py
cd ../..
git add server/backend/api/routes/websocket.py
git commit -m "feat(server): diarize Session-tab recordings on the longform WebSocket path (GH-258)

* feat(server): call transcribe_with_optional_diarization instead of engine.transcribe_file, so a recording can be diarized with the same engines the import routes use
* feat(server): bake speaker labels into result.text before the payload is persisted, so a recovered result carries the same text the live client received
* feat(server): report the diarization outcome on the final payload and forward the job phase on processing_progress, so a silent diarizing phase is visible
* fix(server): report the real speaker count on the longform webhook instead of a hardcoded zero"
```

---

### Task 6: Carry speaker segments into the Audio Notebook

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (`_save_session_to_notebook` line 99, and its call site around line 566)

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_websocket_diarization_start.py`:

```python
def test_notebook_auto_add_forwards_speaker_segments():
    """GH-258: a diarized recording must reach the Notebook WITH its speakers."""
    from pathlib import Path

    segments = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}]
    result = MagicMock(text="SPEAKER_00: hi", segments=[{"text": "hi", "words": []}])

    with (
        patch.object(Path, "exists", return_value=True),
        patch("server.config.get_config") as get_config,
        patch("server.core.audio_utils.convert_to_mp3"),
        patch("server.core.stt.backends.factory.detect_backend_type", return_value="whisperx"),
        patch("server.database.database.save_longform_to_database", return_value=7) as save,
    ):
        get_config.return_value.get.return_value = "/tmp/audio"
        recording_id = ws._save_session_to_notebook(
            audio_path=Path("/tmp/session.wav"),
            duration_seconds=12.0,
            result=result,
            model_name="large-v3",
            diarization_segments=segments,
        )

    assert recording_id == 7
    assert save.call_args.kwargs["diarization_segments"] == segments
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_websocket_diarization_start.py::test_notebook_auto_add_forwards_speaker_segments -v --tb=short
```

Expected: FAIL with `TypeError: _save_session_to_notebook() got an unexpected keyword argument 'diarization_segments'`.

- [ ] **Step 3: Write the implementation**

Extend the `_save_session_to_notebook` signature:

```python
def _save_session_to_notebook(
    *,
    audio_path: Path,
    duration_seconds: float,
    result: Any,
    model_name: str | None,
    diarization_segments: list[dict[str, Any]] | None = None,
) -> int | None:
```

Add to its docstring, after the existing "Returns" line:

```
    ``diarization_segments`` are the raw speaker turns; ``save_longform_to_database``
    aligns them against ``word_timestamps`` itself (GH-258). Passing None keeps
    the historical single-segment shape.
```

Extend the final call in that function:

```python
    return save_longform_to_database(
        audio_path=dest_path,
        duration_seconds=duration_seconds,
        transcription_text=getattr(result, "text", "") or "",
        word_timestamps=word_timestamps,
        diarization_segments=diarization_segments,
        transcription_backend=detect_backend_type(model_name or ""),
    )
```

At the call site inside `process_transcription`, add the new argument:

```python
                    recording_id = await asyncio.to_thread(
                        _save_session_to_notebook,
                        audio_path=self.temp_file,
                        duration_seconds=result.duration,
                        result=result,
                        model_name=getattr(engine, "model_name", None),
                        diarization_segments=dispatched.speaker_segments,
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_websocket_diarization_start.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Format and commit**

```bash
cd server/backend
../../build/.venv/bin/ruff format api/routes/websocket.py tests/test_websocket_diarization_start.py
cd ../..
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_diarization_start.py
git commit -m "feat(server): carry speaker segments into the Audio Notebook auto-add (GH-258)

* feat(server): forward the diarization segments through _save_session_to_notebook to save_longform_to_database, so an auto-added recording lands with real speakers instead of one flat segment
* test(server): assert the segments reach the database helper unchanged"
```

---

### Task 7: Client config keys

**Files:**
- Modify: `dashboard/src/config/store.ts:41-45` and `:122-125`
- Modify: `dashboard/electron/main.ts:490-492`

- [ ] **Step 1: Extend the config interface**

In `dashboard/src/config/store.ts`, replace the `diarization` block of the `ClientConfig` interface:

```ts
  /** Diarization settings */
  diarization: {
    /**
     * Run speaker diarization on Session-tab recordings (GH-258). Independent
     * of the Import tab's own per-import toggle.
     */
    enabledForRecordings: boolean;
    /**
     * Pin the diarizer to an exact speaker count instead of auto-detecting.
     * Shipped default is OFF: auto-detect is right for an unknown meeting, and
     * a wrong pinned count silently degrades every recording.
     */
    constrainSpeakers: boolean;
    numSpeakers: number;
  };
```

- [ ] **Step 2: Update the defaults**

In the same file, replace the `diarization` block of `DEFAULT_CONFIG`:

```ts
  diarization: {
    enabledForRecordings: false,
    constrainSpeakers: false,
    numSpeakers: 2,
  },
```

- [ ] **Step 3: Mirror the Electron-side defaults**

In `dashboard/electron/main.ts`, replace the two diarization default lines:

```ts
    'diarization.enabledForRecordings': false,
    'diarization.constrainSpeakers': false,
    'diarization.numSpeakers': 2,
```

- [ ] **Step 4: Align the Settings modal's own fallback**

`SettingsModal.tsx` seeds its local state before the config load resolves. Line 256 currently reads `constrainSpeakers: true`, which would flash the old behaviour and contradict the shipped default. Change it to:

```ts
    constrainSpeakers: false,
```

- [ ] **Step 5: Typecheck**

```bash
cd dashboard
nvm use
npx tsc --noEmit -p tsconfig.json
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/config/store.ts dashboard/electron/main.ts dashboard/components/views/SettingsModal.tsx
git commit -m "feat(dashboard): add the recording-diarization config key and flip the speaker-constraint default (GH-258)

* feat(dashboard): add diarization.enabledForRecordings, defaulting to off so dictation is unaffected
* fix(dashboard): ship diarization.constrainSpeakers as false so enabling diarization auto-detects the speaker count instead of silently pinning every recording to two, which the previously inert default would have done the moment it was wired up
* fix(dashboard): align the Settings modal's pre-load fallback with the new default so it no longer flashes the old value"
```

---

### Task 8: `useTranscription` — options, frame, result fields

**Files:**
- Modify: `dashboard/src/hooks/useTranscription.ts` (`TranscriptionResult` line 22, `start` options line 46, `startOptsRef` line 152, the `start` frame line 268, `processing_progress` line 342, `final` line 349, `result_ready` line 365, `start()` line 474)

- [ ] **Step 1: Extend the result type**

Add to the `TranscriptionResult` interface, after `partialReason`:

```ts
  /** Speakers found when diarization ran (GH-258). */
  numSpeakers?: number;
  /** Why diarization did or did not happen. Absent when it was not requested. */
  diarization?: {
    requested: boolean;
    performed: boolean;
    reason: string | null;
    remedy: string | null;
  };
```

- [ ] **Step 2: Extend the progress state type**

Replace the `processingProgress` declaration in `TranscriptionState`:

```ts
  /** Segment progress while server is processing (current/total segments) */
  processingProgress: { current: number; total: number; phase?: string | null } | null;
```

and its `useState` (line 104):

```ts
  const [processingProgress, setProcessingProgress] = useState<{
    current: number;
    total: number;
    phase?: string | null;
  } | null>(null);
```

- [ ] **Step 3: Extend the start options in both places**

Add to the `start:` options object in `TranscriptionState` (after `autoAddToNotebook`):

```ts
    /** Attach speaker labels to the finished transcript (GH-258). */
    diarization?: boolean;
    /** Exact speaker count (1-10), or undefined to auto-detect. */
    expectedSpeakers?: number;
```

Add the same two fields to the `startOptsRef` type (line 152) and to the inline options type on the `start` callback (line 474).

- [ ] **Step 4: Send the fields on the start frame**

In the `auth_ok` handler, extend the `data` object:

```ts
              // GH-199: server promotes the finished recording into the Notebook.
              auto_add_to_notebook: startOptsRef.current.autoAddToNotebook ?? false,
              // GH-258: speaker diarization for this recording.
              diarization: startOptsRef.current.diarization ?? false,
              expected_speakers: startOptsRef.current.expectedSpeakers ?? null,
```

- [ ] **Step 5: Read the new fields off the server messages**

Replace the `processing_progress` handler body:

```ts
        case 'processing_progress':
          setProcessingProgress({
            current: (msg.data?.current as number) ?? 0,
            total: (msg.data?.total as number) ?? 0,
            phase: (msg.data?.phase as string | null | undefined) ?? null,
          });
          break;
```

Replace the `setResult({...})` object in the `final` handler:

```ts
          setResult({
            text: (msg.data?.text as string) ?? '',
            words: (msg.data?.words as TranscriptionResult['words']) ?? [],
            language: msg.data?.language as string | undefined,
            duration: msg.data?.duration as number | undefined,
            partial: (msg.data?.partial as boolean | undefined) ?? false,
            partialReason: (msg.data?.partial_reason as string | null | undefined) ?? null,
            numSpeakers: (msg.data?.num_speakers as number | undefined) ?? 0,
            diarization: msg.data?.diarization as TranscriptionResult['diarization'],
          });
```

Replace the `setResult({...})` object in the `result_ready` HTTP-fetch branch, so a recovered large result reports the same thing:

```ts
                setResult({
                  text: r.text ?? '',
                  words: r.words ?? [],
                  language: r.language,
                  duration: r.duration,
                  partial: r.partial ?? false,
                  partialReason: r.partial_reason ?? null,
                  numSpeakers: r.num_speakers ?? 0,
                  diarization: r.diarization,
                });
```

- [ ] **Step 6: Typecheck and run the hook tests**

```bash
cd dashboard
nvm use
npx tsc --noEmit -p tsconfig.json
npx vitest run src/hooks
```

Expected: no type errors; hook tests pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/hooks/useTranscription.ts
git commit -m "feat(dashboard): thread diarization options and results through the transcription hook (GH-258)

* feat(dashboard): send diarization and expected_speakers on the WebSocket start frame
* feat(dashboard): expose numSpeakers and the diarization outcome on the result, reading them on both the inline final message and the large-result HTTP fetch so a recovered result reports the same thing
* feat(dashboard): carry the server-reported job phase on processing progress"
```

---

### Task 9: Session tab toggle and speaker-count stepper

**Files:**
- Modify: `dashboard/components/views/SessionView.tsx` (state near line 154, config hydration line 500, `handleStartRecording` line 775, the Main Transcription card around line 1762)
- Test: `dashboard/components/__tests__/SessionView.diarization.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `dashboard/components/__tests__/SessionView.diarization.test.tsx` by copying **lines 13-234 verbatim** from `dashboard/components/__tests__/SessionView.greek-sigma.test.tsx` (from `import React from 'react';` through the closing `};` of `baseProps`). That block is the whole mock harness: every `vi.mock` call, the `SessionView` / `SessionTab` imports, `createWrapper`, `baseLiveState` and `baseProps`. Then apply the three modifications below and append the test body.

Modification A — add `fireEvent` to the testing-library import:

```tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
```

Modification B — the `useAdminStatus` mock must expose the diarization feature flag so the test can drive the gate. Replace the copied mock with:

```tsx
// Replace the useAdminStatus mock from the copied preamble with this one, which
// exposes the diarization feature flag the toggle is gated on.
vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: {
      models_loaded: true,
      models: { features: { diarization: mockDiarizationFeature.value } },
      config: {
        main_transcriber: { model: 'large-v3' },
        live_transcriber: { model: 'large-v3' },
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));
```

Modification C — declare this hoisted state next to `mockGetConfig` (around copied line 45):

```tsx
const mockDiarizationFeature = {
  value: { available: true, reason: 'ready' } as { available: boolean; reason: string },
};
```

Test body to append:

```tsx
describe('SessionView - speaker diarization for recordings (GH-258)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiarizationFeature.value = { available: true, reason: 'ready' };
    mockTranscription.status = 'idle';
    // Reset between tests: the result-pane tests below mutate this, and a leak
    // would render the result block during the toggle tests.
    mockTranscription.result = null;
    mockGetConfig.mockImplementation((key: unknown) => {
      if (key === 'diarization.enabledForRecordings') return Promise.resolve(true);
      if (key === 'diarization.constrainSpeakers') return Promise.resolve(false);
      if (key === 'diarization.numSpeakers') return Promise.resolve(2);
      return Promise.resolve(undefined);
    });
    (window as any).electronAPI = {
      config: { get: vi.fn().mockResolvedValue(undefined), set: vi.fn().mockResolvedValue(undefined) },
      docker: { readComposeEnvValue: vi.fn().mockResolvedValue('false') },
    };
  });

  it('renders the diarization switch on the Main Transcription card', async () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    expect(toggle).toBeTruthy();
  });

  it('disables the switch when the server reports diarization unavailable', async () => {
    mockDiarizationFeature.value = { available: false, reason: 'token_missing' };
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'));
    expect((toggle as HTMLButtonElement).disabled).toBe(true);
  });

  it('passes diarization through to start() when the switch is on', async () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));

    fireEvent.click(await screen.findByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());
    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({
      diarization: true,
      expectedSpeakers: undefined,
    });
  });

  it('sends the pinned speaker count when constrainSpeakers is on', async () => {
    mockGetConfig.mockImplementation((key: unknown) => {
      if (key === 'diarization.enabledForRecordings') return Promise.resolve(true);
      if (key === 'diarization.constrainSpeakers') return Promise.resolve(true);
      if (key === 'diarization.numSpeakers') return Promise.resolve(4);
      return Promise.resolve(undefined);
    });
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));

    fireEvent.click(await screen.findByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());
    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({
      diarization: true,
      expectedSpeakers: 4,
    });
  });

  it('never sends diarization when the server says the feature is unavailable', async () => {
    mockDiarizationFeature.value = { available: false, reason: 'token_missing' };
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    fireEvent.click(await screen.findByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());
    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({ diarization: false });
  });
});
```

**If the Start Recording button turns out to be disabled** in this harness, do not weaken the assertion by clicking something else. The button's `disabled` prop is `isLive || !clientRunning || !serverConnection.ready || mainModelDisabled`; `baseProps` already satisfies the first three, so the cause would be `mainModelDisabled`. Fix it by making the `useAdminStatus` mock report a selected, enabled main transcriber (`models.transcription.selected_model` plus `disabled: false`) rather than by changing what the test asserts.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd dashboard
nvm use
npx vitest run components/__tests__/SessionView.diarization.test.tsx
```

Expected: FAIL — no switch named "Speaker Diarization" is found.

- [ ] **Step 3: Add the state and the feature gate**

In `SessionView.tsx`, next to the other Session state (after the `captureGain` block around line 154):

```tsx
  // GH-258: speaker diarization for the main recording. Persisted client-side;
  // the count is shared with Settings > Diarization so both surfaces agree.
  const [diarizationEnabled, setDiarizationEnabled] = useState(false);
  const [constrainSpeakers, setConstrainSpeakers] = useState(false);
  const [numSpeakers, setNumSpeakers] = useState(2);
```

After the `admin` hook is available (place it next to the other derived values, e.g. beside `canStartRecording` around line 770):

```tsx
  // GH-209 gate, same contract the Import tab uses: the server computes this
  // ONCE at container startup, so adding a token in Settings needs a restart.
  const diarizationFeature = (admin.status?.models as any)?.features?.diarization as
    | { available: boolean; reason: string }
    | undefined;
  const diarizationUnavailable = diarizationFeature?.available === false;
  const effectiveDiarization = diarizationUnavailable ? false : diarizationEnabled;
```

- [ ] **Step 4: Hydrate and persist the settings**

Extend the existing `Promise.all` hydration block (line 509) with three more reads and their assignments:

```tsx
        getConfig<boolean>('diarization.enabledForRecordings'),
        getConfig<boolean>('diarization.constrainSpeakers'),
        getConfig<number>('diarization.numSpeakers'),
```

adding the matching names to the destructuring array, then after the existing `if (savedHideTimestamps != null)` line:

```tsx
      if (typeof savedDiarizationEnabled === 'boolean') {
        setDiarizationEnabled(savedDiarizationEnabled);
      }
      if (typeof savedConstrainSpeakers === 'boolean') setConstrainSpeakers(savedConstrainSpeakers);
      if (typeof savedNumSpeakers === 'number' && savedNumSpeakers >= 1 && savedNumSpeakers <= 10) {
        setNumSpeakers(savedNumSpeakers);
      }
```

Add the persisting handlers next to `handleAudioSourceChange` (line 556):

```tsx
  const handleDiarizationToggle = useCallback((enabled: boolean) => {
    setDiarizationEnabled(enabled);
    void setConfig('diarization.enabledForRecordings', enabled).catch(() => {});
  }, []);

  const handleSpeakerCountChange = useCallback((next: number) => {
    // 0 means auto-detect: the stepper's floor releases the constraint rather
    // than pinning the run to a single speaker, which is never what is wanted.
    const clamped = Math.max(0, Math.min(10, next));
    if (clamped === 0) {
      setConstrainSpeakers(false);
      void setConfig('diarization.constrainSpeakers', false).catch(() => {});
      return;
    }
    setConstrainSpeakers(true);
    setNumSpeakers(clamped);
    void setConfig('diarization.constrainSpeakers', true).catch(() => {});
    void setConfig('diarization.numSpeakers', clamped).catch(() => {});
  }, []);
```

- [ ] **Step 5: Pass the values to `start()`**

In `handleStartRecording`, extend the `transcription.start({...})` call:

```tsx
        autoAddToNotebook,
        // GH-258: forced off when the server reports the feature unavailable.
        diarization: effectiveDiarization,
        expectedSpeakers:
          effectiveDiarization && constrainSpeakers ? numSpeakers : undefined,
```

and add `effectiveDiarization`, `constrainSpeakers` and `numSpeakers` to that `useCallback` dependency array.

- [ ] **Step 6: Render the control**

Insert this block inside the Main Transcription `GlassCard`, between the closing `</div>` of the Source Language / Translate row and the `{/* Record / Stop Button */}` comment:

```tsx
                    {/* GH-258: speaker diarization for this recording. Off by
                      default so plain dictation is untouched; the count row
                      only appears once it is on. */}
                    <div className="border-t border-white/5 pt-2">
                      <div
                        title={
                          diarizationUnavailable
                            ? diarizationFeature?.reason === 'token_missing'
                              ? 'Diarization needs a HuggingFace token — add one in Settings and restart the server.'
                              : 'Diarization is unavailable on this server.'
                            : 'Label who said what in the finished transcript.'
                        }
                      >
                        <AppleSwitch
                          checked={effectiveDiarization}
                          onChange={handleDiarizationToggle}
                          disabled={diarizationUnavailable}
                          label="Speaker Diarization"
                        />
                      </div>
                      {effectiveDiarization && (
                        <div className="mt-1 flex items-center justify-between pl-1">
                          <span className="text-xs text-slate-400">Speakers</span>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              aria-label="Fewer speakers"
                              onClick={() =>
                                handleSpeakerCountChange(constrainSpeakers ? numSpeakers - 1 : 0)
                              }
                              className="flex h-6 w-6 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition-colors hover:bg-white/10"
                            >
                              &minus;
                            </button>
                            <span className="w-14 text-center text-xs text-slate-300">
                              {constrainSpeakers ? numSpeakers : 'Auto'}
                            </span>
                            <button
                              type="button"
                              aria-label="More speakers"
                              onClick={() =>
                                handleSpeakerCountChange(constrainSpeakers ? numSpeakers + 1 : 2)
                              }
                              className="flex h-6 w-6 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition-colors hover:bg-white/10"
                            >
                              +
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
cd dashboard
nvm use
npx vitest run components/__tests__/SessionView.diarization.test.tsx
```

Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add dashboard/components/views/SessionView.tsx dashboard/components/__tests__/SessionView.diarization.test.tsx
git commit -m "feat(dashboard): add the speaker-diarization control to the Main Transcription card (GH-258)

* feat(dashboard): add a Speaker Diarization switch with an inline speaker-count stepper that reads Auto until the user pins a number, persisted to the shared diarization config keys
* feat(dashboard): gate the switch on the server-reported feature flag exactly as the Import tab does, forcing the sent value off when the server says diarization is unavailable
* test(dashboard): cover rendering, the unavailable gate, the auto-detect default and the pinned-count path"
```

---

### Task 10: Surface a skipped diarization in the result pane

**Files:**
- Modify: `dashboard/components/views/SessionView.tsx` (result block, line 2056)
- Test: `dashboard/components/__tests__/SessionView.diarization.test.tsx` (append)

- [ ] **Step 1: Write the failing test**

Append to the describe block in `SessionView.diarization.test.tsx`:

```tsx
  it('warns when diarization was requested but did not happen', async () => {
    mockTranscription.status = 'complete';
    mockTranscription.result = {
      text: 'plain transcript',
      words: [],
      language: 'en',
      duration: 12,
      partial: false,
      partialReason: null,
      numSpeakers: 0,
      diarization: {
        requested: true,
        performed: false,
        reason: 'out_of_memory',
        remedy: 'Free VRAM and try again.',
      },
    } as any;

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(await screen.findByText(/Speaker labels are missing/i)).toBeTruthy();
    expect(await screen.findByText(/Free VRAM and try again/i)).toBeTruthy();
  });

  it('shows no diarization warning when it succeeded', async () => {
    mockTranscription.status = 'complete';
    mockTranscription.result = {
      text: 'SPEAKER_00: hello',
      words: [],
      language: 'en',
      duration: 12,
      partial: false,
      partialReason: null,
      numSpeakers: 2,
      diarization: { requested: true, performed: true, reason: 'ready', remedy: null },
    } as any;

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    await screen.findByRole('switch', { name: 'Speaker Diarization' });
    expect(screen.queryByText(/Speaker labels are missing/i)).toBeNull();
  });
```

(The `beforeEach` written in Task 9 already resets `mockTranscription.result` to `null`, so these do not leak into the earlier tests.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd dashboard
nvm use
npx vitest run components/__tests__/SessionView.diarization.test.tsx
```

Expected: FAIL — the "Speaker labels are missing" text is not rendered.

- [ ] **Step 3: Write the implementation**

Insert immediately after the `{transcription.result.partial && (...)}` banner block (which ends at line 2084) and before `<FindReplaceTextEditor`:

```tsx
                        {/* GH-258: diarization degrades rather than failing, so a
                          transcript can arrive with no speakers even though the
                          user asked for them. Without this the silence reads as
                          a broken toggle. */}
                        {transcription.result.diarization?.requested &&
                          !transcription.result.diarization.performed && (
                            <div
                              role="status"
                              data-testid="diarization-skipped-notice"
                              className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-300"
                            >
                              Speaker labels are missing from this transcript
                              {transcription.result.diarization.reason
                                ? ` (${transcription.result.diarization.reason.replace(/_/g, ' ')})`
                                : ''}
                              .
                              {transcription.result.diarization.remedy
                                ? ` ${transcription.result.diarization.remedy}`
                                : ''}
                            </div>
                          )}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd dashboard
nvm use
npx vitest run components/__tests__/SessionView.diarization.test.tsx
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/views/SessionView.tsx dashboard/components/__tests__/SessionView.diarization.test.tsx
git commit -m "feat(dashboard): tell the user when a requested diarization did not happen (GH-258)

* feat(dashboard): show an amber notice on the result pane when the server reports diarization requested but not performed, including the remedy for an out-of-memory run
* test(dashboard): cover both the skipped and the successful case"
```

---

### Task 11: UI contract refresh

The new `className` strings must be re-extracted or `ui:contract:check` fails.

**Files:**
- Modify: `dashboard/ui-contract/transcription-suite-ui.contract.yaml`, `dashboard/ui-contract/contract-baseline.json`

- [ ] **Step 1: Re-extract and rebuild**

```bash
cd dashboard
nvm use
npm run ui:contract:extract
npm run ui:contract:build
```

- [ ] **Step 2: Bump the spec version**

Open `dashboard/ui-contract/transcription-suite-ui.contract.yaml`, find `meta.spec_version`, and increment the minor component (e.g. `1.7.0` → `1.8.0`). This MUST happen before the baseline update: `validate-contract.mjs` fails with `semver_bump_required` otherwise.

- [ ] **Step 3: Update the baseline and verify**

```bash
cd dashboard
node scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```

Expected: validation passes and the contract tests pass. If the YAML ends up corrupt, `git checkout -- dashboard/ui-contract/` and redo from Step 1.

- [ ] **Step 4: Commit**

```bash
git add dashboard/ui-contract/
git commit -m "chore(dashboard): refresh the UI contract for the diarization control (GH-258)

* chore(dashboard): re-extract and rebuild the contract for the new Main Transcription card rows and the skipped-diarization notice
* chore(dashboard): bump meta.spec_version and update the baseline"
```

---

### Task 12: Documentation

**Files:**
- Modify: `docs/README.md` (Notes list after line 143)
- Modify: `docs/api-contracts-server.md` (WebSocket section)

- [ ] **Step 1: Add the README carve-out**

In `docs/README.md`, add this bullet to the `> **Notes:**` list under the compatibility matrix, immediately after the PyAnnote bullet (line 143):

```markdown
> - **Where diarization runs:** file imports (Session tab > Import, Notebook tab > Import) and normal recordings on the Session tab, when the **Speaker Diarization** switch is on. **Live Mode never diarizes** - speaker attribution needs the whole recording, which a streaming transcriber does not have.
```

- [ ] **Step 2: Document the WebSocket fields**

In `docs/api-contracts-server.md`, find the `start` message description for the `/ws` endpoint and add the two fields to its table:

```markdown
| `diarization` | `bool` | `false` | Attach speaker labels to the finished transcript. Ignored when the server reports the diarization feature unavailable. |
| `expected_speakers` | `int \| null` | `null` | Exact speaker count, 1-10. Any other value (including `true`) is treated as `null` = auto-detect. |
```

and add the `diarization` block to the `final` message description:

```markdown
When `diarization` was requested, the `final` payload carries an extra block:

```json
{ "diarization": { "requested": true, "performed": false, "reason": "out_of_memory", "remedy": "Free VRAM and try again: ..." } }
```

`reason` is one of `ready`, `token_missing`, `out_of_memory`, `unavailable`. Diarization degrades rather than failing: a transcript is always delivered.
```

- [ ] **Step 3: Commit**

```bash
git add docs/README.md docs/api-contracts-server.md
git commit -m "docs: document diarization on Session-tab recordings (GH-258)

* docs: state in the compatibility notes where diarization runs and that Live Mode never diarizes, which the matrix previously left to inference
* docs(server): document the diarization and expected_speakers fields on the WebSocket start frame and the diarization block on the final payload"
```

---

### Task 13: Full verification

- [ ] **Step 1: Full backend suite**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

Expected: all pass. Report the total count.

- [ ] **Step 2: Full dashboard suite**

```bash
cd dashboard
nvm use
npx vitest run
```

Expected: all pass.

- [ ] **Step 3: Lint, typecheck, format, contract**

```bash
cd dashboard
npm run check
```

Expected: typecheck, lint, format check and the UI contract check all pass.

```bash
cd server/backend
../../build/.venv/bin/ruff check .
../../build/.venv/bin/ruff format --check .
```

Expected: clean.

- [ ] **Step 4: Scope check**

Run `detect_changes({scope: "compare", base_ref: "main"})` via GitNexus and confirm only the intended symbols and flows are affected. Report anything unexpected to the user.

- [ ] **Step 5: Report what is NOT verified**

State plainly in the final report that no GPU smoke test has been run: every backend test uses mocked engines, so the real diarization pipeline on a recording has never executed. The hardware checks the user must perform:

1. Record ~30s of two-speaker audio on the Session tab with the switch ON; confirm the transcript comes back as `SPEAKER_00:` / `SPEAKER_01:` paragraphs.
2. Confirm the clipboard contents match the editor exactly.
3. With auto-add-to-notebook ON, confirm the Notebook entry shows per-speaker segments rather than one flat block.
4. Record with the switch OFF; confirm the transcript is byte-identical to today's plain output.
5. Press Cancel mid-diarization; confirm a clean cancel, not a 500.
6. On a small GPU, force an OOM and confirm the amber notice shows the VRAM remedy.

---

## Deferred follow-up (agreed with the user, 2026-08-01)

After this feature lands, **remind the user to open a separate PR** migrating `transcription.py`, `notebook.py` and `openai_audio.py` onto `core/diarization_dispatch.py`. That removes roughly 400 lines of duplication. It must preserve each route's distinct edges: the HTTP status codes (400 on `ValueError`, 499 on cancel, 503 on a missing backend dependency), the `X-Diarization-Status` response header, and the differing database write paths. Note that the shared helper's error contract deliberately differs from `transcription.py`'s on `ValueError`, so that migration needs a per-route escape hatch rather than a straight swap.
