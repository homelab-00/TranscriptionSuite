"""MLX GigaAM STT backend (Apple Silicon / Metal acceleration).

Runs SaluteDevices' GigaAM v3 — a Russian-only Conformer ASR model — through the
self-contained MLX runtime in :mod:`gigaam_mlx`.

Supported model IDs (``al-bo`` MLX conversions on HuggingFace):
    al-bo/gigaam-v3-e2e-rnnt-mlx   (punctuation + casing, ~445 MB) — recommended
    al-bo/gigaam-v3-rnnt-mlx       (lowercase, no punctuation)
    al-bo/gigaam-v3-ctc-mlx        (lowercase, no punctuation)

Key characteristics:
- Russian only; no translation task; ``language`` is ignored
- GigaAM was trained on short utterances, so long audio is cut into contiguous
  windows of at most ``gigaam.max_segment_s`` seconds — at pauses found by
  Silero VAD — and each window is decoded independently (bounded memory and
  time on multi-hour files). The whole file is decoded: VAD only picks cut
  points, so quiet speech it misses is still transcribed
- Word-level timestamps from the decoder's emission frames (40 ms resolution),
  used by the two-pass diarization merge
- Segments are sentences: split on . ? ! and on long pauses
"""

from __future__ import annotations

import gc
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from server.config import get_config
from server.core.stt.backends.base import (
    BackendDependencyError,
    BackendSegment,
    BackendTranscriptionInfo,
    PartialTranscriptionError,
    STTBackend,
)
from server.core.stt.backends.mlx_thread_pin import MLXThreadAffinityMixin, mlx_pinned

SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)

_SENTENCE_END = (".", "?", "!", "…")


def _gigaam_config() -> dict[str, Any]:
    cfg = get_config()
    return cfg.get("gigaam", default={}) or {}


def _vad_cut_points(audio: np.ndarray, gigaam_cfg: dict[str, Any]) -> list[int] | None:
    """Sample positions in the middle of the pauses Silero VAD finds.

    Returns ``None`` when faster-whisper's bundled Silero VAD is unavailable so
    the caller can fall back to energy-based cut points.
    """
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return None

    options = VadOptions(
        threshold=float(gigaam_cfg.get("vad_threshold", 0.5)),
        min_speech_duration_ms=250,
        min_silence_duration_ms=int(gigaam_cfg.get("vad_min_silence_ms", 300)),
        speech_pad_ms=0,
    )
    chunks = get_speech_timestamps(audio, options, sampling_rate=SAMPLE_RATE)
    return [
        (int(prev["end"]) + int(nxt["start"])) // 2
        for prev, nxt in zip(chunks, chunks[1:], strict=False)
        if int(nxt["start"]) > int(prev["end"])
    ]


def _quietest_point(audio: np.ndarray, start: int, end: int) -> int:
    """Centre of the quietest 50 ms frame in ``audio[start:end]``."""
    frame = int(0.05 * SAMPLE_RATE)
    region = audio[start:end]
    n_frames = len(region) // frame
    if n_frames == 0:
        return end
    energy = np.square(region[: n_frames * frame].reshape(n_frames, frame)).mean(axis=1)
    return start + int(energy.argmin()) * frame + frame // 2


def _cover_windows(
    audio: np.ndarray, max_segment_s: float, cut_points: list[int]
) -> list[tuple[int, int]]:
    """Contiguous windows of at most ``max_segment_s`` covering the whole audio.

    Each window ends at the latest pause (``cut_points``) that keeps it within
    the limit, else at the quietest moment of its last few seconds. Nothing is
    dropped: VAD only chooses where to cut, because Silero misses quiet or
    distant speech, and GigaAM emits nothing for silence anyway.
    """
    import bisect

    total = len(audio)
    max_samples = int(max_segment_s * SAMPLE_RATE)
    min_samples = max_samples // 4
    search = int(min(5.0, max_segment_s / 4) * SAMPLE_RATE)
    windows: list[tuple[int, int]] = []
    pos = 0
    while pos < total:
        limit = pos + max_samples
        if limit >= total:
            windows.append((pos, total))
            break
        idx = bisect.bisect_right(cut_points, limit) - 1
        if idx >= 0 and cut_points[idx] > pos + min_samples:
            end = cut_points[idx]
        else:
            end = _quietest_point(audio, limit - search, limit)
        windows.append((pos, end))
        pos = end
    return windows


def _plan_windows(audio: np.ndarray, gigaam_cfg: dict[str, Any]) -> list[tuple[int, int]]:
    max_segment_s = float(gigaam_cfg.get("max_segment_s", 20.0))
    cut_points = _vad_cut_points(audio, gigaam_cfg)
    if cut_points is None:
        logger.warning("Silero VAD unavailable (faster-whisper missing); cutting at energy minima")
        cut_points = []
    return _cover_windows(audio, max_segment_s, cut_points)


def _words_to_segments(
    words: list[dict[str, Any]], max_sentence_s: float, max_gap_s: float
) -> list[BackendSegment]:
    """Group timed words into sentence-like segments."""
    segments: list[BackendSegment] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if current:
            segments.append(
                BackendSegment(
                    text=" ".join(w["word"] for w in current),
                    start=current[0]["start"],
                    end=current[-1]["end"],
                    words=list(current),
                )
            )
            current.clear()

    for i, word in enumerate(words):
        current.append(word)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        if (
            word["word"].endswith(_SENTENCE_END)
            or nxt["start"] - word["end"] > max_gap_s
            or nxt["end"] - current[0]["start"] > max_sentence_s
        ):
            flush()
    flush()
    return segments


class MLXGigaAMBackend(MLXThreadAffinityMixin, STTBackend):
    """Apple MLX / Metal-accelerated GigaAM v3 backend (Russian)."""

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._model: Any | None = None

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    @mlx_pinned
    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        del device, kwargs
        try:
            import mlx.core  # noqa: F401
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise BackendDependencyError(
                "mlx is not installed. Run: uv sync --extra mlx  (requires macOS + Apple Silicon)",
                backend_type="mlx_gigaam",
                remedy="Run: uv sync --extra mlx  (requires macOS + Apple Silicon)",
            ) from exc

        from server.core.stt.backends.gigaam_mlx import load_model

        logger.info("Loading MLX GigaAM model: %s", model_name)
        try:
            local = Path(model_name)
            model_dir = (
                local
                if local.is_dir()
                else Path(
                    snapshot_download(
                        model_name, allow_patterns=["config.json", "model.safetensors"]
                    )
                )
            )
            self._model = load_model(model_dir)
        except Exception as exc:
            raise RuntimeError(f"Failed to load MLX GigaAM model '{model_name}': {exc}") from exc
        self._model_name = model_name
        logger.info(
            "MLX GigaAM model loaded: %s (%s head, %s tokenizer)",
            model_name,
            self._model.cfg.head_type,
            self._model.cfg.tokenizer_type or "char",
        )

    @mlx_pinned
    def unload(self) -> None:
        if self._model is not None:
            import mlx.core as mx

            del self._model
            self._model = None
            self._model_name = None
            mx.clear_cache()
            gc.collect()
            logger.info("MLX GigaAM model unloaded")

    def is_loaded(self) -> bool:
        return self._model is not None

    @mlx_pinned
    def warmup(self) -> None:
        if self._model is None:
            return
        try:
            self._model.transcribe_tokens(np.zeros(SAMPLE_RATE, dtype=np.float32))
            logger.debug("MLX GigaAM warmup complete")
        except Exception as e:
            logger.warning("MLX GigaAM warmup failed (non-critical): %s", e)

    @mlx_pinned
    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        # GigaAM is Russian-only greedy ASR: no language hint, prompt, beam
        # search or translation. Segmentation always uses VAD (the model needs
        # short windows), so vad_filter is ignored too.
        del task, beam_size, initial_prompt, suppress_tokens, vad_filter
        del word_timestamps, translation_target_language
        if language and not language.lower().startswith("ru"):
            logger.warning("MLX GigaAM is Russian-only; ignoring language=%r", language)

        if self._model is None:
            raise RuntimeError("MLX GigaAM model is not loaded")

        if audio_sample_rate != SAMPLE_RATE:
            from scipy.signal import resample_poly

            audio = resample_poly(audio, SAMPLE_RATE, audio_sample_rate)
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.squeeze()

        gigaam_cfg = _gigaam_config()
        windows = _plan_windows(audio, gigaam_cfg)

        total_s = len(audio) / SAMPLE_RATE
        info = BackendTranscriptionInfo(language="ru", language_probability=1.0)
        logger.info("MLX GigaAM: %.0fs audio → %d windows", total_s, len(windows))

        import mlx.core as mx

        words: list[dict[str, Any]] = []
        completed_s = 0.0
        try:
            for i, (start, end) in enumerate(windows):
                if cancellation_check is not None and cancellation_check():
                    logger.info("MLX GigaAM: cancelled at window %d/%d", i + 1, len(windows))
                    raise self._cancelled_or_partial(words, info, completed_s)
                try:
                    tokens = self._model.transcribe_tokens(audio[start:end])
                except Exception as exc:
                    if not words:
                        raise
                    logger.warning(
                        "MLX GigaAM: window %d/%d failed (%s); returning %.0fs partial transcript",
                        i + 1,
                        len(windows),
                        exc,
                        completed_s,
                    )
                    raise PartialTranscriptionError(
                        str(exc),
                        segments=self._segments(words, gigaam_cfg),
                        info=info,
                        completed_seconds=completed_s,
                    ) from exc
                words.extend(self._model.tokens_to_words(tokens, offset_s=start / SAMPLE_RATE))
                completed_s = end / SAMPLE_RATE
                if i % 32 == 31:
                    # Encoder activations differ in shape per window; keep the
                    # Metal buffer pool from growing over thousands of windows.
                    mx.clear_cache()
                if progress_callback is not None:
                    progress_callback(int(completed_s), int(total_s))
        finally:
            try:
                mx.clear_cache()
            except Exception:
                logger.debug("mlx cache clear failed (non-critical)", exc_info=True)

        return self._segments(words, gigaam_cfg), info

    def supports_translation(self) -> bool:
        return False

    def supports_cancellation(self) -> bool:
        # transcribe() polls cancellation_check between VAD windows.
        return True

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_gigaam"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _segments(words: list[dict[str, Any]], gigaam_cfg: dict[str, Any]) -> list[BackendSegment]:
        return _words_to_segments(
            words,
            max_sentence_s=float(gigaam_cfg.get("max_sentence_s", 15.0)),
            max_gap_s=float(gigaam_cfg.get("sentence_gap_s", 1.0)),
        )

    def _cancelled_or_partial(
        self,
        words: list[dict[str, Any]],
        info: BackendTranscriptionInfo,
        completed_s: float,
    ) -> Exception:
        """A cancel after some windows keeps their transcript (no data loss)."""
        from server.core.model_manager import TranscriptionCancelledError

        if not words:
            return TranscriptionCancelledError("Transcription cancelled by user")
        return PartialTranscriptionError(
            "Cancelled by user",
            segments=self._segments(words, _gigaam_config()),
            info=info,
            completed_seconds=completed_s,
        )
