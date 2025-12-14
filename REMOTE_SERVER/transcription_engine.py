"""
Integration layer between RemoteTranscriptionServer and existing transcription engine.

This module provides the callbacks that connect the WebSocket server
to the actual faster-whisper transcription functionality.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np

# Add project root to path for imports
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from SCRIPT.static_transcriber import (  # noqa: E402
    get_cached_whisper_model,
    unload_cached_whisper_model,
)
from SCRIPT.shared.utils import clear_gpu_cache  # noqa: E402

logger = logging.getLogger(__name__)


class TranscriptionEngine:
    """
    Provides transcription capabilities for the remote server.

    This wraps the existing faster-whisper functionality and provides
    both real-time (preview) and final transcription callbacks.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the transcription engine.

        Args:
            config: Full application config dict
        """
        self.config = config
        self._model = None
        self._model_loaded = False

        # Extract model configuration
        main_config = config.get("main_transcriber", {})
        self.model_path = main_config.get("model", "Systran/faster-whisper-large-v3")
        self.device = main_config.get("device", "cuda")
        self.compute_type = main_config.get("compute_type", "default")
        self.beam_size = main_config.get("beam_size", 5)
        self.vad_filter = main_config.get("faster_whisper_vad_filter", True)

        # Preview model (smaller, faster for real-time)
        preview_config = config.get("preview_transcriber", {})
        self.preview_model_path = preview_config.get(
            "model", "Systran/faster-whisper-base"
        )
        self._preview_model = None

        logger.info(f"TranscriptionEngine initialized with model: {self.model_path}")

    def load_model(self) -> None:
        """Load the transcription model."""
        if self._model_loaded:
            logger.debug("Model already loaded")
            return

        logger.info(f"Loading transcription model: {self.model_path}")
        self._model = get_cached_whisper_model(
            self.model_path, self.device, self.compute_type
        )
        self._model_loaded = True
        logger.info("Transcription model loaded")

    def unload_model(self) -> None:
        """Unload the transcription model to free GPU memory."""
        if not self._model_loaded:
            return

        logger.info("Unloading transcription model")
        unload_cached_whisper_model()
        self._model = None
        self._model_loaded = False
        clear_gpu_cache()
        logger.info("Transcription model unloaded")

    def transcribe(
        self, audio_data: np.ndarray, language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe audio data.

        Args:
            audio_data: Audio samples as float32 numpy array [-1, 1]
            language: Optional language code (e.g., "en", "el")

        Returns:
            Dict with transcription results:
            {
                "text": str,
                "words": list of word dicts,
                "duration": float,
                "language": str
            }
        """
        # Ensure model is loaded
        if not self._model_loaded:
            self.load_model()

        if self._model is None:
            raise RuntimeError("Model not available")

        logger.info(f"Transcribing {len(audio_data) / 16000:.2f}s of audio")

        # Transcribe with word timestamps
        segments, info = self._model.transcribe(
            audio_data,
            language=language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            word_timestamps=True,
        )

        # Process segments
        full_text = []
        all_words = []

        for segment in segments:
            full_text.append(segment.text.strip())

            if segment.words:
                for word in segment.words:
                    all_words.append(
                        {
                            "word": word.word,
                            "start": round(word.start, 3),
                            "end": round(word.end, 3),
                            "probability": round(word.probability, 3),
                        }
                    )

        result = {
            "text": " ".join(full_text),
            "words": all_words,
            "duration": round(info.duration, 3),
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
        }

        logger.info(
            f"Transcription complete: {len(all_words)} words, language={info.language}"
        )

        return result

    def transcribe_realtime(self, audio_chunk: np.ndarray) -> Optional[str]:
        """
        Real-time transcription for preview.

        This uses a smaller model for faster response during live streaming.
        Currently returns None (preview disabled for remote mode).

        Args:
            audio_chunk: Audio samples as float32 numpy array

        Returns:
            Partial transcription text or None
        """
        # Real-time preview is complex to implement correctly
        # For now, return None (no preview)
        # The final transcription will still work
        return None


def create_transcription_callbacks(
    config: Dict[str, Any],
) -> tuple[
    Callable[[np.ndarray, Optional[str]], Dict[str, Any]],  # transcribe_callback
    Callable[[np.ndarray], Optional[str]],  # realtime_callback
    TranscriptionEngine,  # engine instance for cleanup
]:
    """
    Create transcription callbacks for the remote server.

    Args:
        config: Full application config dict

    Returns:
        Tuple of (transcribe_callback, realtime_callback, engine)
    """
    engine = TranscriptionEngine(config)

    def transcribe_callback(
        audio_data: np.ndarray, language: Optional[str] = None
    ) -> Dict[str, Any]:
        return engine.transcribe(audio_data, language)

    def realtime_callback(audio_chunk: np.ndarray) -> Optional[str]:
        return engine.transcribe_realtime(audio_chunk)

    return transcribe_callback, realtime_callback, engine
