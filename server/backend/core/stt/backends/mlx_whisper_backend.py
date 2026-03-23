"""MLX Whisper STT backend (Apple Silicon / Metal acceleration).

Uses the ``mlx-whisper`` package which runs Whisper models via Apple's MLX
framework, giving Metal GPU acceleration on Apple Silicon Macs.

Model names are HuggingFace repo IDs in the ``mlx-community`` namespace, e.g.:
    mlx-community/whisper-tiny-mlx
    mlx-community/whisper-small-mlx
    mlx-community/whisper-medium-mlx
    mlx-community/whisper-large-v3-mlx

The ``mlx_whisper.transcribe()`` function downloads and caches the model on
first call, so ``load()`` here only stores the name; the actual model weights
are loaded lazily by MLX on the first transcription.
"""

from __future__ import annotations

import logging
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


class MLXWhisperBackend(STTBackend):
    """Apple MLX / Metal-accelerated Whisper backend.

    Wraps ``mlx-whisper`` (https://github.com/ml-explore/mlx-examples/tree/main/whisper).
    Only available on macOS with Apple Silicon.
    """

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        """Store the model name; MLX loads weights lazily on first transcription."""
        # device is ignored — MLX always uses the Metal GPU on Apple Silicon
        del device, kwargs
        try:
            import mlx_whisper  # noqa: F401 — verify package is importable
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper is not installed. "
                "Run: uv sync --extra mlx  (requires macOS + Apple Silicon)"
            ) from exc

        logger.info(f"MLX Whisper backend configured for model: {model_name}")
        self._model_name = model_name
        self._loaded = True

    def unload(self) -> None:
        self._model_name = None
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def warmup(self) -> None:
        if not self._loaded or self._model_name is None:
            return
        try:
            import mlx_whisper

            warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"
            if not warmup_path.exists():
                warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    sf.write(tmp.name, warmup_audio, SAMPLE_RATE)
                    warmup_path_str = tmp.name
            else:
                warmup_path_str = str(warmup_path)

            mlx_whisper.transcribe(
                warmup_path_str,
                path_or_hf_repo=self._model_name,
                language="en",
            )
            logger.debug("MLX Whisper warmup complete")
        except Exception as e:
            logger.warning(f"MLX Whisper warmup failed (non-critical): {e}")

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
        del suppress_tokens, vad_filter, progress_callback  # not used by MLX Whisper

        if not self._loaded or self._model_name is None:
            raise RuntimeError("MLX Whisper model is not loaded")

        import mlx_whisper

        # mlx_whisper.transcribe accepts:
        #   - a file path (str), or
        #   - a float32 numpy array at 16 kHz
        # Resample if needed.
        if audio_sample_rate != SAMPLE_RATE:
            from scipy.signal import resample as sp_resample

            target_length = int(len(audio) * SAMPLE_RATE / audio_sample_rate)
            audio = sp_resample(audio, target_length).astype(np.float32)

        # Ensure float32 in [-1, 1]
        if audio.dtype != np.float32:
            if np.issubdtype(audio.dtype, np.integer):
                audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
            else:
                audio = audio.astype(np.float32)

        effective_task = task
        if translation_target_language and translation_target_language != "en":
            # MLX Whisper only translates to English in v1
            logger.warning(
                "MLX Whisper only supports translation to English; "
                f"ignoring target language '{translation_target_language}'"
            )

        result: dict[str, Any] = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self._model_name,
            language=language,
            task=effective_task,
            initial_prompt=initial_prompt,
            word_timestamps=word_timestamps,
            beam_size=beam_size,
        )

        # Convert MLX Whisper output to BackendSegment list.
        # MLX Whisper returns:
        #   {"text": str, "language": str, "segments": [
        #       {"id", "seek", "start", "end", "text", "tokens", "temperature",
        #        "avg_logprob", "compression_ratio", "no_speech_prob",
        #        "words": [{"word", "start", "end", "probability"}]}, ...
        #   ]}
        result_segments: list[BackendSegment] = []
        for seg in result.get("segments", []):
            words: list[dict[str, Any]] = []
            if word_timestamps:
                for w in seg.get("words", []):
                    words.append(
                        {
                            "word": w.get("word", ""),
                            "start": float(w.get("start", 0.0)),
                            "end": float(w.get("end", 0.0)),
                            "probability": float(w.get("probability", 0.0)),
                        }
                    )
            result_segments.append(
                BackendSegment(
                    text=seg.get("text", ""),
                    start=float(seg.get("start", 0.0)),
                    end=float(seg.get("end", 0.0)),
                    words=words,
                )
            )

        detected_language: str | None = result.get("language")
        info = BackendTranscriptionInfo(
            language=detected_language,
            language_probability=1.0,  # MLX Whisper doesn't expose a probability
        )
        return result_segments, info

    def supports_translation(self) -> bool:
        return True

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_whisper"
