"""Tests for the MLX GigaAM backend (routing, word timing, segmentation, chunk loop).

The real model needs Apple Silicon; these tests stub the model object and
``mlx.core`` so they run anywhere.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest
from server.core.stt.backends.base import PartialTranscriptionError
from server.core.stt.backends.factory import (
    create_backend,
    detect_backend_type,
    is_mlx_model,
)
from server.core.stt.backends.gigaam_tokens import TimedToken, tokens_to_words
from server.core.stt.capabilities import supports_english_translation

SR = 16000

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "al-bo/gigaam-v3-e2e-rnnt-mlx",
        "al-bo/gigaam-v3-ctc-mlx",
        " AL-BO/GigaAM-v3-RNNT-MLX ",
    ],
)
def test_gigaam_mlx_repos_route_to_mlx_gigaam(model: str) -> None:
    assert detect_backend_type(model) == "mlx_gigaam"
    assert is_mlx_model(model)
    assert not supports_english_translation(model)


def test_gigaam_routing_does_not_capture_other_repos() -> None:
    # Not an MLX conversion → default backend, unchanged behaviour.
    assert detect_backend_type("ai-sage/GigaAM-v3") == "whisper"
    assert detect_backend_type("mlx-community/whisper-large-v3-asr-fp16") == "mlx_whisper"
    assert detect_backend_type("mlx-community/parakeet-tdt-0.6b-v3") == "mlx_parakeet"


def test_create_backend_returns_gigaam_backend() -> None:
    backend = create_backend("al-bo/gigaam-v3-e2e-rnnt-mlx")
    assert backend.backend_name == "mlx_gigaam"
    assert not backend.supports_translation()
    assert backend.supports_cancellation()


# ---------------------------------------------------------------------------
# Token → word grouping
# ---------------------------------------------------------------------------

_SP_VOCAB = ["<unk>", ".", ",", "▁", "▁При", "вет", "▁мир", "!"]


def test_sentencepiece_tokens_group_into_timed_words() -> None:
    tokens = [
        TimedToken(4, 3, 0.9),  # ▁При
        TimedToken(5, 5, 0.8),  # вет
        TimedToken(2, 6, 0.99),  # ,
        TimedToken(6, 10, 0.7),  # ▁мир
        TimedToken(7, 12, 0.95),  # !
    ]
    words = tokens_to_words(
        tokens, _SP_VOCAB, sentencepiece=True, frame_duration_s=0.04, offset_s=100.0
    )
    assert [w["word"] for w in words] == ["Привет,", "мир!"]
    assert words[0]["start"] == pytest.approx(100.12)
    assert words[0]["end"] == pytest.approx(100.24)
    assert words[0]["probability"] == pytest.approx(0.8)
    assert words[1]["start"] == pytest.approx(100.4)
    # Late trailing punctuation does not stretch the word.
    assert words[1]["end"] == pytest.approx(100.44)


def test_detached_punctuation_piece_attaches_to_previous_word() -> None:
    vocab = ["<unk>", "▁да", "▁,", "▁нет"]
    tokens = [TimedToken(1, 0, 1.0), TimedToken(2, 50, 1.0), TimedToken(3, 60, 1.0)]
    words = tokens_to_words(tokens, vocab, sentencepiece=True, frame_duration_s=0.04)
    assert [w["word"] for w in words] == ["да,", "нет"]
    assert words[0]["end"] == pytest.approx(0.04)


def test_charwise_vocabulary_splits_on_space_and_skips_unknown_ids() -> None:
    vocab = [" ", "д", "а", "н", "е", "т"]
    tokens = [
        TimedToken(1, 0, 1.0),
        TimedToken(2, 1, 1.0),
        TimedToken(0, 2, 1.0),
        TimedToken(99, 3, 1.0),  # out of range → ignored
        TimedToken(3, 4, 1.0),
        TimedToken(4, 5, 1.0),
        TimedToken(5, 6, 1.0),
    ]
    words = tokens_to_words(tokens, vocab, sentencepiece=False, frame_duration_s=0.04)
    assert [w["word"] for w in words] == ["да", "нет"]


# ---------------------------------------------------------------------------
# Sentence segmentation + fallback splitter
# ---------------------------------------------------------------------------


def _w(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end, "probability": 1.0}


def test_words_to_segments_splits_on_sentence_end_gap_and_length() -> None:
    from server.core.stt.backends.mlx_gigaam_backend import _words_to_segments

    words = [
        _w("Привет.", 0.0, 0.5),
        _w("Как", 0.6, 0.8),
        _w("дела", 0.9, 1.2),
        _w("сегодня", 5.0, 5.5),  # > max_gap after previous word
        _w("утром", 5.6, 6.0),
    ]
    segments = _words_to_segments(words, max_sentence_s=15.0, max_gap_s=1.0)
    assert [s.text for s in segments] == ["Привет.", "Как дела", "сегодня утром"]
    assert segments[1].start == 0.6 and segments[1].end == 1.2
    assert [w["word"] for w in segments[2].words] == ["сегодня", "утром"]

    long_run = [_w(f"w{i}", i * 1.0, i * 1.0 + 0.5) for i in range(10)]
    capped = _words_to_segments(long_run, max_sentence_s=4.0, max_gap_s=1.0)
    assert all(s.end - s.start <= 4.0 for s in capped)
    assert sum(len(s.words) for s in capped) == 10


def test_cover_windows_cut_at_pauses_and_cover_everything() -> None:
    from server.core.stt.backends.mlx_gigaam_backend import _cover_windows

    rng = np.random.default_rng(0)
    audio = rng.normal(0, 0.1, SR * 65).astype(np.float32)
    cuts = [SR * 3, SR * 12, SR * 17, SR * 30, SR * 52]
    windows = _cover_windows(audio, max_segment_s=20.0, cut_points=cuts)

    assert windows[0][0] == 0 and windows[-1][1] == len(audio)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:], strict=False))
    assert all(end - start <= SR * 20 for start, end in windows)
    # Latest pause within the limit wins; a pause too close to the start is skipped.
    assert windows[0] == (0, SR * 17)
    assert windows[1] == (SR * 17, SR * 30)


def test_cover_windows_without_pauses_cut_at_quietest_point() -> None:
    from server.core.stt.backends.mlx_gigaam_backend import _cover_windows

    rng = np.random.default_rng(0)
    audio = rng.normal(0, 0.1, SR * 45).astype(np.float32)
    audio[SR * 18 : SR * 18 + 1600] = 0.0  # a quiet spot inside the search region
    windows = _cover_windows(audio, max_segment_s=20.0, cut_points=[])
    assert windows[-1][1] == len(audio)
    assert SR * 18 <= windows[0][1] <= SR * 18 + 1600


# ---------------------------------------------------------------------------
# transcribe(): windows, offsets, progress, cancellation, partial results
# ---------------------------------------------------------------------------


class _FakeGigaAM:
    """Stub model: each window yields one word at the window's first frame."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def transcribe_tokens(self, audio: np.ndarray) -> list[TimedToken]:
        self.calls += 1
        if self.fail_on_call is not None and self.calls == self.fail_on_call:
            raise RuntimeError("metal exploded")
        return [TimedToken(self.calls, 0, 1.0)]

    def tokens_to_words(self, tokens: list[TimedToken], offset_s: float = 0.0) -> list[dict]:
        return [_w(f"слово{t.token_id}.", offset_s, offset_s + 0.4) for t in tokens]


@pytest.fixture
def gigaam(monkeypatch):
    import server.core.stt.backends.mlx_gigaam_backend as mod

    fake_mlx = types.ModuleType("mlx")
    fake_core = types.ModuleType("mlx.core")
    fake_core.clear_cache = lambda: None  # type: ignore[attr-defined]
    fake_mlx.core = fake_core  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", fake_mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", fake_core)
    monkeypatch.setattr(mod, "_gigaam_config", lambda: {})
    windows = [(0, SR * 5), (SR * 10, SR * 20), (SR * 30, SR * 32)]
    monkeypatch.setattr(mod, "_plan_windows", lambda audio, cfg: windows)

    backend = mod.MLXGigaAMBackend()
    yield backend
    backend.shutdown_mlx_thread()


def test_transcribe_offsets_windows_and_reports_progress(gigaam) -> None:
    gigaam._model = _FakeGigaAM()
    progress: list[tuple[int, int]] = []
    audio = np.zeros(SR * 40, dtype=np.float32)

    segments, info = gigaam.transcribe(
        audio, language="ru", progress_callback=lambda a, b: progress.append((a, b))
    )

    assert info.language == "ru"
    assert [s.start for s in segments] == [0.0, 10.0, 30.0]
    assert [s.text for s in segments] == ["слово1.", "слово2.", "слово3."]
    assert progress == [(5, 40), (20, 40), (32, 40)]


def test_cancel_after_first_window_keeps_partial_transcript(gigaam) -> None:
    gigaam._model = _FakeGigaAM()
    checks = iter([False, True])

    with pytest.raises(PartialTranscriptionError) as exc_info:
        gigaam.transcribe(
            np.zeros(SR * 40, dtype=np.float32), cancellation_check=lambda: next(checks)
        )

    assert [s.text for s in exc_info.value.segments] == ["слово1."]
    assert exc_info.value.completed_seconds == 5.0


def test_cancel_before_any_window_raises_plain_cancellation(gigaam) -> None:
    from server.core.model_manager import TranscriptionCancelledError

    gigaam._model = _FakeGigaAM()
    with pytest.raises(TranscriptionCancelledError):
        gigaam.transcribe(np.zeros(SR * 40, dtype=np.float32), cancellation_check=lambda: True)


def test_failure_after_first_window_returns_partial(gigaam) -> None:
    gigaam._model = _FakeGigaAM(fail_on_call=2)
    with pytest.raises(PartialTranscriptionError) as exc_info:
        gigaam.transcribe(np.zeros(SR * 40, dtype=np.float32))
    assert [s.text for s in exc_info.value.segments] == ["слово1."]


def test_failure_on_first_window_propagates_original_error(gigaam) -> None:
    gigaam._model = _FakeGigaAM(fail_on_call=1)
    with pytest.raises(RuntimeError, match="metal exploded"):
        gigaam.transcribe(np.zeros(SR * 40, dtype=np.float32))
