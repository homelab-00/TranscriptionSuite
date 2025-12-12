#!/usr/bin/env python3
"""
Service to perform transcription using OmniASR.

Uses direct imports since everything runs in the same Python 3.11 environment.
For persistent model loading, use OmniASRService with keep_loaded=True.
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
from .omniasr_transcriber import (
    OmniASRTranscriber,
    TranscriptionResult,
    get_transcriber,
    convert_language_code,
)

logger = logging.getLogger("omniasr_service")


@dataclass
class OmniASRTranscriptionResult:
    """Result from OmniASR transcription."""

    text: str
    language: str
    duration: float
    processing_time: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OmniASRTranscriptionResult":
        return cls(
            text=data["text"],
            language=data["language"],
            duration=data["duration"],
            processing_time=data.get("processing_time", 0.0),
        )

    @classmethod
    def from_internal(cls, result: TranscriptionResult) -> "OmniASRTranscriptionResult":
        """Create from internal TranscriptionResult."""
        return cls(
            text=result.text,
            language=result.language,
            duration=result.duration,
            processing_time=result.processing_time,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration": self.duration,
            "processing_time": self.processing_time,
        }


class OmniASRService:
    """
    Service to perform transcription using OmniASR.

    Uses direct imports - no subprocess or TCP server needed.

    For persistent model loading, use keep_loaded=True to avoid
    reloading the model on each transcription.
    """

    def __init__(
        self,
        model: str = "omniASR_LLM_3B",
        device: str = "cuda",
        default_language: str = "eng_Latn",
        batch_size: int = 1,
        keep_loaded: bool = True,
    ):
        """
        Initialize the OmniASR service.

        Args:
            model: Model card name ("omniASR_LLM_3B" or "omniASR_LLM_1B")
            device: Device for model ("cuda" or "cpu")
            default_language: Default language for transcription
            batch_size: Batch size for inference
            keep_loaded: Keep model loaded between transcriptions
        """
        self.model = model
        self.device = device
        self.default_language = convert_language_code(default_language)
        self.batch_size = batch_size
        self.keep_loaded = keep_loaded
        self._transcriber: Optional[OmniASRTranscriber] = None

        logger.info(
            f"OmniASRService initialized (model={model}, keep_loaded={keep_loaded})"
        )

    def _get_transcriber(self) -> OmniASRTranscriber:
        """Get or create the transcriber."""
        if self._transcriber is None:
            if self.keep_loaded:
                # Use singleton for persistent model
                self._transcriber = get_transcriber(
                    model=self.model,
                    device=self.device,
                    default_language=self.default_language,
                    batch_size=self.batch_size,
                )
            else:
                # Create new instance each time
                self._transcriber = OmniASRTranscriber(
                    model=self.model,
                    device=self.device,
                    default_language=self.default_language,
                    batch_size=self.batch_size,
                )
        return self._transcriber

    def ensure_model_loaded(self) -> bool:
        """Ensure the model is loaded."""
        transcriber = self._get_transcriber()
        if not transcriber.is_loaded:
            safe_print("Loading OmniASR model...", "info")
            transcriber.load_model()
            safe_print("OmniASR model loaded!", "success")
        return True

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> OmniASRTranscriptionResult:
        """
        Transcribe an audio file using OmniASR.

        Args:
            audio_path: Path to the audio file
            language: Language code (ISO 639-1 or OmniASR format)

        Returns:
            OmniASRTranscriptionResult with text
        """
        # Ensure model is loaded
        self.ensure_model_loaded()

        # Resolve audio path
        audio_path = str(Path(audio_path).resolve())

        logger.info(f"Transcribing: {audio_path}")
        safe_print(f"Transcribing with OmniASR: {Path(audio_path).name}", "info")

        transcriber = self._get_transcriber()
        internal_result = transcriber.transcribe(
            audio_path=audio_path,
            language=language or self.default_language,
        )

        result = OmniASRTranscriptionResult.from_internal(internal_result)

        safe_print(
            f"Transcription complete: {len(result.text)} chars in "
            f"{result.processing_time:.2f}s",
            "success",
        )

        return result

    def transcribe_batch(
        self,
        audio_paths: List[str],
        languages: Optional[List[str]] = None,
    ) -> List[OmniASRTranscriptionResult]:
        """
        Transcribe multiple audio files in a batch.

        Args:
            audio_paths: List of paths to audio files
            languages: List of language codes (one per file, or single for all)

        Returns:
            List of OmniASRTranscriptionResult objects
        """
        # Ensure model is loaded
        self.ensure_model_loaded()

        # Resolve paths
        audio_paths = [str(Path(p).resolve()) for p in audio_paths]

        logger.info(f"Batch transcribing {len(audio_paths)} files")
        safe_print(f"Batch transcribing {len(audio_paths)} files with OmniASR", "info")

        transcriber = self._get_transcriber()
        internal_results = transcriber.transcribe_batch(
            audio_paths=audio_paths,
            languages=languages,
        )

        results = [OmniASRTranscriptionResult.from_internal(r) for r in internal_results]

        safe_print(
            f"Batch transcription complete: {len(results)} files",
            "success",
        )

        return results

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
            logger.info("OmniASR model unloaded")

    # Legacy API compatibility methods (matching Canary pattern)

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


# =============================================================================
# Module-level singleton
# =============================================================================

_service_instance: Optional[OmniASRService] = None


def get_service(
    model: str = "omniASR_LLM_3B",
    default_language: str = "eng_Latn",
    keep_loaded: bool = True,
) -> OmniASRService:
    """Get or create the singleton service instance."""
    global _service_instance

    if _service_instance is None:
        _service_instance = OmniASRService(
            model=model,
            default_language=default_language,
            keep_loaded=keep_loaded,
        )

    return _service_instance


def transcribe_audio(
    audio_path: str,
    language: Optional[str] = None,
) -> OmniASRTranscriptionResult:
    """
    Convenience function to transcribe an audio file.

    Args:
        audio_path: Path to the audio file
        language: Language code

    Returns:
        OmniASRTranscriptionResult
    """
    service = get_service()
    return service.transcribe(audio_path, language=language)


def get_server_status() -> Dict[str, Any]:
    """Get the service status (legacy name for compatibility)."""
    service = get_service()
    return service.get_status()


def shutdown_server() -> bool:
    """Shutdown/unload the model (legacy name for compatibility)."""
    service = get_service()
    service.unload()
    return True
