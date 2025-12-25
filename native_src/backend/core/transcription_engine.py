"""
Unified transcription engine for TranscriptionSuite server.

Consolidates transcription functionality from:
- MAIN/stt_engine.py (real-time transcription)
- REMOTE_SERVER/transcription_engine.py (file transcription)
- MAIN/static_transcriber.py (static file processing)

Provides a single interface for all transcription operations.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from server.core.audio_utils import (
    clear_gpu_cache,
    load_audio,
    normalize_audio,
)

logger = logging.getLogger(__name__)

# Optional imports
try:
    import faster_whisper

    HAS_FASTER_WHISPER = True
except ImportError:
    faster_whisper = None  # type: ignore
    HAS_FASTER_WHISPER = False


@dataclass
class WordInfo:
    """Word-level transcription information."""

    word: str
    start: float
    end: float
    probability: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 3),
        }


@dataclass
class TranscriptionSegment:
    """A segment of transcribed text with timing and optional speaker info."""

    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    words: List[WordInfo] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
        }
        if self.speaker:
            result["speaker"] = self.speaker
        if self.words:
            result["words"] = [w.to_dict() for w in self.words]
        return result


@dataclass
class TranscriptionResult:
    """Complete transcription result."""

    text: str
    segments: List[TranscriptionSegment]
    language: str
    language_probability: float
    duration: float
    num_speakers: int = 0

    def to_dict(self) -> Dict[str, Any]:
        all_words = []
        for seg in self.segments:
            all_words.extend([w.to_dict() for w in seg.words])

        return {
            "text": self.text,
            "segments": [s.to_dict() for s in self.segments],
            "words": all_words,
            "language": self.language,
            "language_probability": round(self.language_probability, 3),
            "duration": round(self.duration, 3),
            "num_speakers": self.num_speakers,
            "total_words": len(all_words),
            "metadata": {
                "num_segments": len(self.segments),
            },
        }


class TranscriptionEngine:
    """
    Unified transcription engine for all transcription operations.

    Supports:
    - File transcription with word timestamps
    - Real-time audio stream transcription
    - Optional speaker diarization
    """

    def __init__(
        self,
        model: str = "Systran/faster-whisper-large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
        beam_size: int = 5,
        vad_filter: bool = True,
        language: Optional[str] = None,
    ):
        """
        Initialize the transcription engine.

        Args:
            model: Whisper model path or name
            device: Device to run on ("cuda" or "cpu")
            compute_type: Compute type for inference
            beam_size: Beam size for decoding
            vad_filter: Whether to use VAD filtering
            language: Language code (None for auto-detect)
        """
        if not HAS_FASTER_WHISPER:
            raise ImportError("faster_whisper is required for transcription")

        self.model_path = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.language = language

        self._model: Optional[Any] = None
        self._model_loaded = False

        logger.info(f"TranscriptionEngine initialized: model={model}, device={device}")

    def load_model(self) -> None:
        """Load the Whisper model."""
        if self._model_loaded:
            logger.debug("Model already loaded")
            return

        logger.info(f"Loading Whisper model: {self.model_path}")

        try:
            self._model = faster_whisper.WhisperModel(
                model_size_or_path=self.model_path,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._model_loaded = True
            logger.info("Whisper model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def unload_model(self) -> None:
        """Unload the model to free GPU memory."""
        if not self._model_loaded:
            return

        logger.info("Unloading Whisper model")
        del self._model
        self._model = None
        self._model_loaded = False
        clear_gpu_cache()
        logger.info("Model unloaded")

    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model_loaded

    def transcribe_audio(
        self,
        audio_data: np.ndarray,
        language: Optional[str] = None,
        word_timestamps: bool = True,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio data.

        Args:
            audio_data: Audio samples as float32 numpy array (16kHz, mono)
            language: Language code (overrides engine default)
            word_timestamps: Whether to include word-level timestamps
            initial_prompt: Optional prompt for context

        Returns:
            TranscriptionResult with full transcription data
        """
        if not self._model_loaded:
            self.load_model()

        if self._model is None:
            raise RuntimeError("Model not available")

        # Normalize audio
        audio_data = normalize_audio(audio_data)

        lang = language or self.language
        logger.info(f"Transcribing {len(audio_data) / 16000:.2f}s of audio")

        try:
            segments_iter, info = self._model.transcribe(
                audio_data,
                language=lang,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                word_timestamps=word_timestamps,
                initial_prompt=initial_prompt,
            )

            # Process segments
            segments: List[TranscriptionSegment] = []
            full_text_parts: List[str] = []

            for segment in segments_iter:
                words: List[WordInfo] = []

                if segment.words:
                    for word in segment.words:
                        words.append(
                            WordInfo(
                                word=word.word,
                                start=word.start,
                                end=word.end,
                                probability=word.probability,
                            )
                        )

                seg = TranscriptionSegment(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    words=words,
                )
                segments.append(seg)
                full_text_parts.append(segment.text.strip())

            result = TranscriptionResult(
                text=" ".join(full_text_parts),
                segments=segments,
                language=info.language,
                language_probability=info.language_probability,
                duration=info.duration,
            )

            logger.info(
                f"Transcription complete: {len(segments)} segments, "
                f"language={info.language}"
            )

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise

    def transcribe_file(
        self,
        file_path: str,
        language: Optional[str] = None,
        word_timestamps: bool = True,
    ) -> TranscriptionResult:
        """
        Transcribe an audio/video file.

        Args:
            file_path: Path to the audio/video file
            language: Language code (overrides engine default)
            word_timestamps: Whether to include word-level timestamps

        Returns:
            TranscriptionResult with full transcription data
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Transcribing file: {file_path}")

        # Load and convert audio
        audio_data, sample_rate = load_audio(str(path), target_sample_rate=16000)

        # Transcribe
        result = self.transcribe_audio(
            audio_data,
            language=language,
            word_timestamps=word_timestamps,
        )

        return result

    def get_status(self) -> Dict[str, Any]:
        """Get engine status information."""
        return {
            "model": self.model_path,
            "device": self.device,
            "compute_type": self.compute_type,
            "loaded": self._model_loaded,
            "language": self.language,
        }


# Factory functions for creating engines
def create_transcription_engine(config: Dict[str, Any]) -> TranscriptionEngine:
    """
    Create a TranscriptionEngine from configuration dict.

    Args:
        config: Configuration with transcription settings

    Returns:
        Configured TranscriptionEngine instance
    """
    trans_config = config.get("transcription", config.get("main_transcriber", {}))

    return TranscriptionEngine(
        model=trans_config.get("model", "Systran/faster-whisper-large-v3"),
        device=trans_config.get("device", "cuda"),
        compute_type=trans_config.get("compute_type", "float16"),
        beam_size=trans_config.get("beam_size", 5),
        vad_filter=trans_config.get(
            "vad_filter", trans_config.get("faster_whisper_vad_filter", True)
        ),
        language=trans_config.get("language"),
    )


def create_transcription_callbacks(
    config: Dict[str, Any],
) -> tuple[
    Callable[[np.ndarray, Optional[str]], Dict[str, Any]],
    Callable[[np.ndarray], Optional[str]],
    TranscriptionEngine,
]:
    """
    Create transcription callbacks for backward compatibility.

    Args:
        config: Full application config dict

    Returns:
        Tuple of (transcribe_callback, realtime_callback, engine)
    """
    engine = create_transcription_engine(config)

    def transcribe_callback(
        audio_data: np.ndarray, language: Optional[str] = None
    ) -> Dict[str, Any]:
        result = engine.transcribe_audio(audio_data, language=language)
        return result.to_dict()

    def realtime_callback(audio_chunk: np.ndarray) -> Optional[str]:
        # Real-time preview not implemented in unified engine yet
        return None

    return transcribe_callback, realtime_callback, engine
