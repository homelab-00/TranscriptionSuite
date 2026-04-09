"""MLX Parakeet STT backend (Apple Silicon / Metal acceleration).

Uses the ``parakeet-mlx`` package which runs NVIDIA Parakeet-TDT models via
Apple's MLX framework, giving Metal GPU acceleration on Apple Silicon Macs.

Recommended model ID (mlx-community namespace on HuggingFace):
    mlx-community/parakeet-tdt-0.6b-v3

key characteristics:
- 25 European languages with native punctuation and capitalisation
- No translation task support
- Token-level timestamps exposed as word timestamps for diarization
- Sentence segmentation via silence-gap and duration heuristics

Note: mlx-community/parakeet-tdt-1.1b is the older (pre-2025) model trained
on 64K hours of English-only data without native punctuation or capitalisation.
``parakeet-tdt-0.6b-v3`` supersedes it: 660K hours, 25 languages, P&C native.

The model is downloaded and cached by ``parakeet-mlx`` on first load.
"""

from __future__ import annotations

import logging
import math
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.config import get_config
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

# Default maximum audio duration (seconds) to pass to parakeet-mlx in a single
# call.  Longer files are split into chunks to avoid Metal buffer OOM errors on
# Apple Silicon (the MLX framework allocates all processing buffers up-front,
# so very long audio can trigger "Attempting to allocate X bytes which is
# greater than the maximum allowed buffer size" failures).
# Overridden at load-time by the ``parakeet.max_chunk_duration_s`` config key
# (the same key used by the NeMo Parakeet backend).
DEFAULT_MAX_CHUNK_DURATION_S = 300  # 5 minutes

logger = logging.getLogger(__name__)


def _tokens_to_words(tokens: list[Any]) -> list[dict[str, Any]]:
    """Group Parakeet AlignedToken objects into word-level dicts.

    parakeet-mlx replaces the SentencePiece word-boundary character `▁`
    (U+2581) with a plain space in each token's ``.text`` field.  A token
    whose ``.text`` starts with a space marks the beginning of a new word;
    continuation pieces have no leading space.  Pure-whitespace tokens are
    treated as separators and discarded.

    Returns a list of dicts compatible with the engine's word format:
    ``{"word", "start", "end", "probability"}``.
    """
    words: list[dict[str, Any]] = []
    buf_pieces: list[str] = []
    buf_start: float = 0.0
    buf_end: float = 0.0
    buf_conf: list[float] = []

    def flush() -> None:
        text = "".join(buf_pieces).strip()
        if text:
            words.append(
                {
                    "word": text,
                    "start": round(buf_start, 3),
                    "end": round(buf_end, 3),
                    # Use minimum confidence across pieces (conservative).
                    "probability": round(min(buf_conf, default=1.0), 3),
                }
            )
        buf_pieces.clear()
        buf_conf.clear()

    for tok in tokens:
        text: str = tok.text
        if not text or not text.strip():
            # Pure whitespace / blank token — word separator.
            flush()
            continue

        starts_word = text.startswith(" ")
        stripped = text.lstrip(" ")

        if starts_word and buf_pieces:
            flush()

        if not buf_pieces:
            # First piece of a new word — record its start time.
            buf_start = float(tok.start)  # type: ignore[attr-defined]

        buf_pieces.append(stripped)
        buf_end = float(tok.end)  # type: ignore[attr-defined]
        buf_conf.append(float(tok.confidence))  # type: ignore[attr-defined]

    flush()
    return words


class MLXParakeetBackend(STTBackend):
    """Apple MLX / Metal-accelerated Parakeet-TDT backend.

    Wraps ``parakeet-mlx`` for NVIDIA Parakeet-TDT inference on Apple Silicon.
    25 EU languages (auto-detected from audio); sentence-level timestamps; no translation.
    Only available on macOS with Apple Silicon.
    """

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._model: Any | None = None
        self._loaded: bool = False
        self._max_chunk_duration_s: int = DEFAULT_MAX_CHUNK_DURATION_S

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        """Load the Parakeet model via ``parakeet_mlx.from_pretrained``."""
        del device, kwargs
        try:
            from parakeet_mlx import from_pretrained  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "parakeet-mlx is not installed. "
                "Run: uv sync --extra mlx  (requires macOS + Apple Silicon)"
            ) from exc

        logger.info(f"Loading MLX Parakeet model: {model_name}")
        try:
            from parakeet_mlx import from_pretrained

            self._model = from_pretrained(model_name)
            self._model_name = model_name
            self._loaded = True
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load MLX Parakeet model '{model_name}': {exc}"
            ) from exc

        # Configurable chunk duration — shared config key with the NeMo backend.
        cfg = get_config()
        parakeet_cfg = cfg.get("parakeet", default={}) or {}
        try:
            self._max_chunk_duration_s = max(
                60,
                int(parakeet_cfg.get("max_chunk_duration_s", DEFAULT_MAX_CHUNK_DURATION_S) or DEFAULT_MAX_CHUNK_DURATION_S),
            )
        except (TypeError, ValueError):
            self._max_chunk_duration_s = DEFAULT_MAX_CHUNK_DURATION_S

        logger.info(
            "MLX Parakeet model loaded: %s (max_chunk_duration_s=%d)",
            model_name,
            self._max_chunk_duration_s,
        )

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def warmup(self) -> None:
        if not self._loaded or self._model is None:
            return
        try:
            warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, warmup_audio, SAMPLE_RATE)
                tmp_path = tmp.name
            try:
                self._model.transcribe(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
            logger.debug("MLX Parakeet warmup complete")
        except Exception as e:
            logger.warning(f"MLX Parakeet warmup failed (non-critical): {e}")

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
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        # parakeet-mlx exposes no language-hint API; language/task parameters are
        # accepted for interface compatibility but have no effect. The model
        # auto-detects the language from the audio content.
        del (
            language,
            task,
            beam_size,
            initial_prompt,
            suppress_tokens,
            vad_filter,
            word_timestamps,
            translation_target_language,
        )

        if not self._loaded or self._model is None:
            raise RuntimeError("MLX Parakeet model is not loaded")

        # Resample if needed.
        if audio_sample_rate != SAMPLE_RATE:
            from scipy.signal import resample as sp_resample

            target_length = int(len(audio) * SAMPLE_RATE / audio_sample_rate)
            audio = sp_resample(audio, target_length).astype(np.float32)

        if audio.dtype != np.float32:
            if np.issubdtype(audio.dtype, np.integer):
                audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
            else:
                audio = audio.astype(np.float32)

        total_duration = len(audio) / SAMPLE_RATE
        if total_duration > self._max_chunk_duration_s:
            return self._transcribe_long(audio, progress_callback=progress_callback)

        segments = self._transcribe_chunk(audio)
        info = BackendTranscriptionInfo(
            language="en",
            language_probability=1.0,
        )
        return segments, info

    def _transcribe_chunk(self, audio: np.ndarray) -> list[BackendSegment]:
        """Write *audio* to a temp WAV and transcribe it as a single chunk.

        Returns the raw ``BackendSegment`` list with timestamps relative to the
        start of *audio* (i.e. not yet offset for multi-chunk processing).
        """
        # parakeet-mlx expects a file path, write audio to a temp WAV.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            from parakeet_mlx import DecodingConfig, SentenceConfig

            decoding_config = DecodingConfig(
                sentence=SentenceConfig(
                    # Split on silence gaps ≥ 0.5 s and cap each sentence at
                    # 30 s.  This ensures the 1.1b model (which rarely emits
                    # sentence-ending punctuation) still produces meaningful
                    # segments rather than one monolithic utterance.
                    silence_gap=0.5,
                    max_duration=30.0,
                )
            )
            result = self._model.transcribe(tmp_path, decoding_config=decoding_config)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Convert AlignedResult.sentences → BackendSegment list.
        #
        # sentence.text is the library's authoritative decode: it joins all
        # token texts as "".join(t.text for t in tokens), where each token's
        # text is vocabulary[id].replace("▁", " ").  This correctly places
        # spaces only at word boundaries (word-initial SentencePiece pieces
        # carry "▁" → space; continuation pieces do not) and preserves all
        # punctuation tokens exactly as the model produced them.
        #
        # _tokens_to_words() is retained solely to generate word-level
        # timestamps for the diarization pipeline.  We no longer use it to
        # reconstruct segment text, which avoids two problems that occurred
        # when joining stripped word groups with " ".join():
        #   1. Punctuation tokens that start with a space in the vocabulary
        #      (e.g. " ," or " .") became isolated words, producing
        #      "boundary . Okay" instead of "boundary. Okay".
        #   2. Any punctuation at a word-group boundary could be dropped or
        #      misattributed when the join added an extra space before it.
        #
        # parakeet-tdt-0.6b-v3 produces punctuation and capitalisation natively
        # (those are part of its token vocabulary from training).
        segments: list[BackendSegment] = []
        if hasattr(result, "sentences") and result.sentences:
            for sentence in result.sentences:
                words = _tokens_to_words(sentence.tokens)
                segments.append(
                    BackendSegment(
                        text=str(sentence.text).strip(),
                        start=float(sentence.start),
                        end=float(sentence.end),
                        words=words,
                    )
                )
        elif hasattr(result, "text") and str(result.text).strip():
            # Fallback: no sentence segmentation — create one segment.
            segments.append(
                BackendSegment(
                    text=str(result.text).strip(),
                    start=0.0,
                    end=float(len(audio)) / SAMPLE_RATE,
                    words=[],
                )
            )

        return segments

    def _transcribe_long(
        self,
        audio: np.ndarray,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Split *audio* into chunks and transcribe each one sequentially.

        Timestamps in each chunk's segments are adjusted by the chunk's time
        offset so that the returned segments have correct absolute timestamps
        relative to the start of the full audio.
        """
        chunk_samples = int(self._max_chunk_duration_s * SAMPLE_RATE)
        total_samples = len(audio)
        num_chunks = math.ceil(total_samples / chunk_samples)

        all_segments: list[BackendSegment] = []
        time_offset = 0.0

        for i in range(num_chunks):
            start = i * chunk_samples
            end = min(start + chunk_samples, total_samples)
            chunk = audio[start:end]
            chunk_duration = len(chunk) / SAMPLE_RATE

            logger.info(
                "MLX Parakeet: transcribing chunk %d/%d (%.0fs – %.0fs)",
                i + 1,
                num_chunks,
                time_offset,
                time_offset + chunk_duration,
            )
            if progress_callback is not None:
                progress_callback(i + 1, num_chunks)

            chunk_segments = self._transcribe_chunk(chunk)

            # Shift timestamps so they are relative to the full audio start.
            for seg in chunk_segments:
                seg.start += time_offset
                seg.end += time_offset
                for w in seg.words:
                    w["start"] = w["start"] + time_offset
                    w["end"] = w["end"] + time_offset

            all_segments.extend(chunk_segments)
            time_offset += chunk_duration

        info = BackendTranscriptionInfo(
            language="en",
            language_probability=1.0,
        )
        return all_segments, info

    def supports_translation(self) -> bool:
        return False

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_parakeet"
