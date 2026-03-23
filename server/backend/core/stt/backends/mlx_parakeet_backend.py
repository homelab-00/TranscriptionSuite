"""MLX Parakeet STT backend (Apple Silicon / Metal acceleration).

Uses the ``parakeet-mlx`` package which runs NVIDIA Parakeet-TDT models via
Apple's MLX framework, giving Metal GPU acceleration on Apple Silicon Macs.

Supported model IDs (mlx-community namespace on HuggingFace):
    mlx-community/parakeet-tdt-0.6b-v3
    mlx-community/parakeet-tdt-1.1b

Key characteristics:
- English-only (Parakeet-TDT does not support multilingual input)
- No translation task support
- Token-level timestamps exposed as word timestamps for diarization
- Sentence segmentation via silence-gap and duration heuristics
- Automatic language identification not applicable (always English)

The model is downloaded and cached by ``parakeet-mlx`` on first load.
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


class MLXParakeetBackend(STTBackend):
    """Apple MLX / Metal-accelerated Parakeet-TDT backend.

    Wraps ``parakeet-mlx`` for NVIDIA Parakeet-TDT inference on Apple Silicon.
    English-only; sentence-level timestamps; no translation support.
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
            logger.info(f"MLX Parakeet model loaded: {model_name}")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load MLX Parakeet model '{model_name}': {exc}"
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
        # Parakeet-TDT is English-only; all the language/task parameters are
        # accepted for interface compatibility but have no effect.
        del (
            language,
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
        # Each sentence has .text, .start, .end and a .tokens list
        # (AlignedToken: .text, .start, .end, .confidence).
        # Populate words so the diarization pipeline has timestamps to work
        # with — each word dict uses the key names expected by the engine:
        # {"word", "start", "end", "probability"}.
        segments: list[BackendSegment] = []
        if hasattr(result, "sentences") and result.sentences:
            for sentence in result.sentences:
                words = [
                    {
                        "word": tok.text,
                        "start": round(float(tok.start), 3),
                        "end": round(float(tok.end), 3),
                        "probability": round(float(tok.confidence), 3),
                    }
                    for tok in sentence.tokens
                    if tok.text.strip()
                ]
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
            language="en",
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
        return "mlx_parakeet"
