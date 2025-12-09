#!/usr/bin/env python3
"""
Service to perform transcription using NeMo Canary.

Now uses direct imports since everything runs in the same Python 3.11 environment!
No more subprocess or TCP server needed for basic usage.

For persistent model (avoiding reload each time), use CanaryService with
keep_loaded=True, or use the TCP server mode for external processes.
"""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path for imports
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from SCRIPT.utils import safe_print
except ImportError:
    # Fallback if utils not available
    def safe_print(msg, style=None):
        print(msg)


# Import from same module (relative imports)
from .canary_transcriber import CanaryTranscriber, TranscriptionResult, get_transcriber

logger = logging.getLogger("canary_service")


@dataclass
class WordTimestamp:
    """Represents a word with timing information."""

    word: str
    start: float
    end: float
    confidence: float = 1.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordTimestamp":
        return cls(
            word=data["word"],
            start=data["start"],
            end=data["end"],
            confidence=data.get("confidence", 1.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


@dataclass
class CanaryTranscriptionResult:
    """Result from Canary transcription."""

    text: str
    language: str
    duration: float
    word_timestamps: List[WordTimestamp]
    processing_time: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanaryTranscriptionResult":
        return cls(
            text=data["text"],
            language=data["language"],
            duration=data["duration"],
            word_timestamps=[
                WordTimestamp.from_dict(w) for w in data.get("word_timestamps", [])
            ],
            processing_time=data.get("processing_time", 0.0),
        )

    @classmethod
    def from_internal(cls, result: TranscriptionResult) -> "CanaryTranscriptionResult":
        """Create from internal TranscriptionResult."""
        return cls(
            text=result.text,
            language=result.language,
            duration=result.duration,
            word_timestamps=[
                WordTimestamp(
                    word=w.word,
                    start=w.start,
                    end=w.end,
                    confidence=w.confidence,
                )
                for w in result.word_timestamps
            ],
            processing_time=result.processing_time,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration": self.duration,
            "word_timestamps": [w.to_dict() for w in self.word_timestamps],
            "processing_time": self.processing_time,
        }


class CanaryService:
    """
    Service to perform transcription using NeMo Canary.

    Now uses direct imports - no subprocess or TCP server needed!

    For persistent model loading, use keep_loaded=True to avoid
    reloading the model on each transcription.
    """

    def __init__(
        self,
        device: str = "cuda",
        beam_size: int = 1,
        default_language: str = "en",
        keep_loaded: bool = True,
    ):
        """
        Initialize the Canary service.

        Args:
            device: Device for model ("cuda" or "cpu")
            beam_size: Beam size for decoding (1 = greedy, faster)
            default_language: Default language for transcription
            keep_loaded: Keep model loaded between transcriptions
        """
        self.device = device
        self.beam_size = beam_size
        self.default_language = default_language
        self.keep_loaded = keep_loaded
        self._transcriber: Optional[CanaryTranscriber] = None

        logger.info(
            f"CanaryService initialized (direct import mode, keep_loaded={keep_loaded})"
        )

    def _get_transcriber(self) -> CanaryTranscriber:
        """Get or create the transcriber."""
        if self._transcriber is None:
            if self.keep_loaded:
                # Use singleton for persistent model
                self._transcriber = get_transcriber(
                    device=self.device,
                    beam_size=self.beam_size,
                    default_language=self.default_language,
                )
            else:
                # Create new instance each time
                self._transcriber = CanaryTranscriber(
                    device=self.device,
                    beam_size=self.beam_size,
                    default_language=self.default_language,
                )
        return self._transcriber

    def ensure_model_loaded(self) -> bool:
        """Ensure the model is loaded."""
        transcriber = self._get_transcriber()
        if not transcriber.is_loaded:
            safe_print("Loading Canary model...", "info")
            transcriber.load_model()
            safe_print("Canary model loaded!", "success")
        return True

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        pnc: bool = True,
    ) -> CanaryTranscriptionResult:
        """
        Transcribe an audio file using Canary.

        Args:
            audio_path: Path to the audio file
            language: Language code (e.g., "el" for Greek)
            pnc: Include punctuation and capitalization

        Returns:
            CanaryTranscriptionResult with text and word timestamps
        """
        # Ensure model is loaded
        self.ensure_model_loaded()

        # Resolve audio path
        audio_path = str(Path(audio_path).resolve())

        logger.info(f"Transcribing: {audio_path}")
        safe_print(f"Transcribing with Canary: {Path(audio_path).name}", "info")

        transcriber = self._get_transcriber()
        internal_result = transcriber.transcribe(
            audio_path=audio_path,
            language=language or self.default_language,
            pnc=pnc,
        )

        result = CanaryTranscriptionResult.from_internal(internal_result)

        safe_print(
            f"Transcription complete: {len(result.text)} chars in "
            f"{result.processing_time:.2f}s",
            "success",
        )

        return result

    def get_status(self) -> Dict[str, Any]:
        """Get the service status."""
        transcriber = self._get_transcriber()
        status = transcriber.get_status()
        status["service_mode"] = "direct"
        status["keep_loaded"] = self.keep_loaded
        return status

    def unload(self) -> None:
        """Unload the model to free memory."""
        if self._transcriber is not None:
            self._transcriber.unload_model()
            if not self.keep_loaded:
                self._transcriber = None
            logger.info("Canary model unloaded")

    # Legacy API compatibility methods

    def is_server_running(self) -> bool:
        """Legacy method - always returns True since we use direct imports."""
        return True

    def start_server(self, **kwargs) -> bool:
        """Legacy method - just ensures model is loaded."""
        return self.ensure_model_loaded()

    def stop_server(self) -> bool:
        """Legacy method - unloads the model."""
        self.unload()
        return True

    def ensure_server_running(self, **kwargs) -> bool:
        """Legacy method - just ensures model is loaded."""
        return self.ensure_model_loaded()


# Module-level singleton
_service_instance: Optional[CanaryService] = None


def get_service(
    default_language: str = "en",
    keep_loaded: bool = True,
) -> CanaryService:
    """Get or create the singleton service instance."""
    global _service_instance

    if _service_instance is None:
        _service_instance = CanaryService(
            default_language=default_language,
            keep_loaded=keep_loaded,
        )

    return _service_instance


def transcribe_audio(
    audio_path: str,
    language: Optional[str] = None,
    pnc: bool = True,
) -> CanaryTranscriptionResult:
    """
    Convenience function to transcribe an audio file.

    Args:
        audio_path: Path to the audio file
        language: Language code (e.g., "el" for Greek)
        pnc: Include punctuation and capitalization

    Returns:
        CanaryTranscriptionResult
    """
    service = get_service()
    return service.transcribe(audio_path, language=language, pnc=pnc)


def get_server_status() -> Dict[str, Any]:
    """Get the service status (legacy name for compatibility)."""
    service = get_service()
    return service.get_status()


def shutdown_server() -> bool:
    """Shutdown/unload the model (legacy name for compatibility)."""
    service = get_service()
    service.unload()
    return True
