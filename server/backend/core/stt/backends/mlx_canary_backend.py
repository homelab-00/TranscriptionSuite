"""MLX Canary STT backend (Apple Silicon / Metal acceleration).

Uses the ``canary-mlx`` package which runs NVIDIA Canary models via
Apple's MLX framework, giving Metal GPU acceleration on Apple Silicon Macs.

Supported model IDs on HuggingFace:
    eelcor/canary-1b-v2-mlx       (bfloat16, ~3.7 GB)
    Mediform/canary-1b-v2-mlx-q8  (Q8 quantised, ~1.1 GB)
    qfuxa/canary-mlx              (Canary 1B v1, bfloat16, ~3.9 GB)

Key characteristics:
- 25 European languages with native punctuation and capitalisation
- No translation task support (ASR only in the MLX port)
- Token-level timestamps exposed as word timestamps for diarization
- Chunked processing for long audio files (120 s chunks)

The model is downloaded and cached by ``canary-mlx`` on first load.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)

# Mapping from full language names (as stored in transcription config) to ISO 639-1 codes.
# Canary 1B v2 supports these 25 EU languages.
_LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "english": "en",
    "bulgarian": "bg",
    "croatian": "hr",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "estonian": "et",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hungarian": "hu",
    "italian": "it",
    "latvian": "lv",
    "lithuanian": "lt",
    "maltese": "mt",
    "polish": "pl",
    "portuguese": "pt",
    "romanian": "ro",
    "russian": "ru",
    "slovak": "sk",
    "slovenian": "sl",
    "spanish": "es",
    "swedish": "sv",
    "ukrainian": "uk",
}


def _resolve_language_code(language: str | None) -> str:
    """Return a 2-letter ISO 639-1 code suitable for Canary.

    Accepts full language names (e.g. "English"), 2-letter codes (e.g. "en"),
    or None; defaults to "en" if the value is unrecognised.
    """
    if not language:
        return "en"
    lang = language.strip()
    if len(lang) == 2:
        return lang.lower()
    return _LANGUAGE_NAME_TO_CODE.get(lang.lower(), "en")


def _tokens_to_words(tokens: list[Any]) -> list[dict[str, Any]]:
    """Group canary-mlx AlignedToken objects into word-level dicts.

    canary-mlx tokens use SentencePiece conventions: a token whose ``.text``
    starts with a space marks the beginning of a new word; continuation pieces
    have no leading space.  Pure-whitespace tokens are treated as separators
    and discarded.

    canary-mlx AlignedToken has no ``confidence`` field, so probability is
    set to 1.0 for all words.

    Returns a list of dicts compatible with the engine's word format:
    ``{"word", "start", "end", "probability"}``.
    """
    words: list[dict[str, Any]] = []
    buf_pieces: list[str] = []
    buf_start: float = 0.0
    buf_end: float = 0.0

    def flush() -> None:
        text = "".join(buf_pieces).strip()
        if text:
            words.append(
                {
                    "word": text,
                    "start": round(buf_start, 3),
                    "end": round(buf_end, 3),
                    "probability": 1.0,
                }
            )
        buf_pieces.clear()

    for tok in tokens:
        text: str = tok.text
        if not text or not text.strip():
            flush()
            continue

        starts_word = text.startswith(" ")
        stripped = text.lstrip(" ")

        if starts_word and buf_pieces:
            flush()

        if not buf_pieces:
            buf_start = float(tok.start)

        buf_pieces.append(stripped)
        buf_end = float(tok.end)

    flush()
    return words


class MLXCanaryBackend(STTBackend):
    """Apple MLX / Metal-accelerated Canary backend.

    Wraps ``canary-mlx`` for NVIDIA Canary model inference on Apple Silicon.
    Supports 25 European languages; native punctuation and capitalisation.
    Only available on macOS with Apple Silicon.
    """

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._model: Any | None = None
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        """Load the Canary model via ``canary_mlx.load_model``."""
        del device, kwargs
        try:
            from canary_mlx import load_model  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "canary-mlx is not installed. "
                "Run: uv sync --extra mlx  (requires macOS + Apple Silicon)"
            ) from exc

        logger.info(f"Loading MLX Canary model: {model_name}")
        try:
            from canary_mlx import load_model

            self._model = load_model(model_name)
            self._model_name = model_name
            self._loaded = True
            logger.info(f"MLX Canary model loaded: {model_name}")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load MLX Canary model '{model_name}': {exc}"
            ) from exc

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
                self._model.transcribe(tmp_path, language="en")
            finally:
                Path(tmp_path).unlink(missing_ok=True)
            logger.debug("MLX Canary warmup complete")
        except Exception as e:
            logger.warning(f"MLX Canary warmup failed (non-critical): {e}")

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
        # Translation is not supported by the canary-mlx port; task and
        # translation params are accepted for interface compatibility only.
        del (
            task,
            beam_size,
            initial_prompt,
            suppress_tokens,
            vad_filter,
            word_timestamps,
            translation_target_language,
            progress_callback,
        )

        if not self._loaded or self._model is None:
            raise RuntimeError("MLX Canary model is not loaded")

        lang_code = _resolve_language_code(language)

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

        # canary-mlx expects a file path; write audio to a temp WAV.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            result = self._model.transcribe(
                tmp_path,
                language=lang_code,
                timestamps=True,
                punctuation=True,
                # Process in 120-second chunks so long recordings don't OOM.
                chunk_duration=120.0,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Convert AlignedResult.sentences → BackendSegment list.
        #
        # sentence.text is the library's authoritative decode:
        # "".join(t.text for t in tokens), which preserves all punctuation
        # and spacing exactly as produced by the model.
        #
        # _tokens_to_words() is used solely to generate word-level timestamps
        # for the diarization pipeline.
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

        info = BackendTranscriptionInfo(
            language=lang_code,
            language_probability=1.0,
        )
        return segments, info

    def supports_translation(self) -> bool:
        return False

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_canary"
