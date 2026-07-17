"""Base classes for STT backend abstraction."""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np


class BackendDependencyError(RuntimeError):
    """Raised when an STT backend's optional dependency is missing or broken.

    Attributes:
        backend_type: The backend identifier (e.g. "nemo", "vibevoice_asr", "mlx_parakeet").
        remedy: Actionable instruction for the user (e.g. "Set INSTALL_NEMO=true").
    """

    def __init__(self, message: str, *, backend_type: str, remedy: str) -> None:
        super().__init__(message)
        self.backend_type = backend_type
        self.remedy = remedy


class PartialTranscriptionError(RuntimeError):
    """Raised by a chunking backend when a chunk fails *after* ≥1 chunk succeeded.

    Carries the transcript completed so far so the engine can persist it instead
    of discarding the whole job (the project's "avoid data loss at all costs"
    invariant). A failure on the very first chunk raises the original error
    instead — there is nothing partial to salvage.

    Attributes:
        segments: BackendSegment list for the chunks that completed (timestamps
            already offset onto the global timeline).
        info: BackendTranscriptionInfo from the first completed chunk.
        completed_seconds: Seconds of audio successfully transcribed.
    """

    def __init__(
        self,
        message: str,
        *,
        segments: list[BackendSegment],
        info: BackendTranscriptionInfo,
        completed_seconds: float,
    ) -> None:
        super().__init__(message)
        self.segments = segments
        self.info = info
        self.completed_seconds = completed_seconds


@dataclass
class BackendSegment:
    """Normalized transcription segment returned by any backend."""

    text: str
    start: float
    end: float
    words: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BackendTranscriptionInfo:
    """Metadata about a transcription result."""

    language: str | None = None
    language_probability: float = 0.0


@dataclass
class DiarizedTranscriptionResult:
    """Result from a backend that performs integrated diarization."""

    segments: list[dict[str, Any]]
    words: list[dict[str, Any]]
    num_speakers: int
    language: str | None = None
    language_probability: float = 0.0


class STTBackend(abc.ABC):
    """Abstract base class for speech-to-text backends."""

    _decode_options: dict[str, Any] = {}

    def configure_decode_options(self, options: dict[str, Any]) -> None:
        """Store extra decode/anti-hallucination options for Whisper-family backends.

        These are merged into the ``transcribe()`` kwargs by backends that
        support them (WhisperX, faster-whisper, Whisper).  Non-Whisper backends
        silently ignore them.

        Args:
            options: Mapping of faster-whisper ``WhisperModel.transcribe`` kwargs
                (e.g. ``no_speech_threshold``, ``compression_ratio_threshold``).
        """
        # Instance copy — avoids mutating the class default.
        self._decode_options = dict(options)

    @abc.abstractmethod
    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        """Load the model.

        Args:
            model_name: Model identifier (HuggingFace repo or local path).
            device: Target device ("cuda" or "cpu").
            **kwargs: Backend-specific options (compute_type, gpu_device_index, etc.).
        """

    @abc.abstractmethod
    def unload(self) -> None:
        """Unload the model and free resources."""

    @abc.abstractmethod
    def is_loaded(self) -> bool:
        """Return True if a model is currently loaded."""

    @abc.abstractmethod
    def warmup(self) -> None:
        """Run a warmup transcription to initialise the model."""

    @abc.abstractmethod
    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = 16000,
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
        """Transcribe audio and return normalised segments + info.

        Args:
            audio: Float32 numpy array, mono.
            audio_sample_rate: Sample rate of ``audio`` in Hz.
            language: Language code or None for auto-detect.
            task: "transcribe" or "translate".
            beam_size: Beam size for decoding.
            initial_prompt: Optional prompt to guide transcription.
            suppress_tokens: Token IDs to suppress.
            vad_filter: Whether to apply the backend's built-in VAD filter.
            word_timestamps: Whether to produce word-level timestamps.
            translation_target_language: Target language code for translation
                (e.g. "en", "fr"). Canary supports any EU language; Whisper
                only supports "en".
            progress_callback: Optional callback receiving
                (processed_seconds, total_seconds) as the backend advances
                through the audio (GH-211). Backends that cannot report
                mid-call progress may ignore it.

        Returns:
            Tuple of (list of BackendSegment, BackendTranscriptionInfo).
        """

    @abc.abstractmethod
    def supports_translation(self) -> bool:
        """Return True if this backend supports the ``translate`` task."""

    def supports_cancellation(self) -> bool:
        """Return True if ``transcribe`` accepts a ``cancellation_check`` and
        honours it *mid-call* (e.g. between chunks of long audio).

        Default ``False``: the engine then relies on its post-call cancellation
        check (after ``transcribe`` returns). Backends that chunk long audio can
        override this so the engine forwards ``cancellation_check`` and the job
        can stop within a chunk instead of after the whole file.
        """
        return False

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        """Preferred audio sample rate for this backend's input pipeline."""
        return 16000

    def transcribe_with_diarization(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = 16000,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        num_speakers: int | None = None,
        hf_token: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DiarizedTranscriptionResult | None:
        """Transcribe with integrated diarization (single-pass).

        Backends that support integrated diarization (e.g. WhisperX) should
        override this.  The default implementation returns ``None``, signalling
        that the caller should fall back to the legacy two-step pipeline.
        """
        del audio_sample_rate
        return None

    @property
    @abc.abstractmethod
    def backend_name(self) -> str:
        """Short identifier for this backend (e.g. ``"whisper"``, ``"parakeet"``)."""


def use_integrated_diarization_for(backend: STTBackend | None, resolved_engine: str) -> bool:
    """True when the route should use a backend's single-pass diarization.

    A backend qualifies only if it overrides ``transcribe_with_diarization``.
    For SenseVoice, the single-pass (CAM++) path is additionally gated on the
    resolved engine: ``"funasr"`` uses single-pass, ``"pyannote"`` routes to the
    two-pass pipeline. Every OTHER integrated backend (WhisperX, VibeVoice) keeps
    its single-pass path unconditionally — the SenseVoice engine resolver does
    not apply to them.
    """
    if backend is None:
        return False
    overrides = (
        type(backend).transcribe_with_diarization is not STTBackend.transcribe_with_diarization
    )
    if not overrides:
        return False
    if backend.backend_name == "sensevoice":
        return resolved_engine == "funasr"
    return True
