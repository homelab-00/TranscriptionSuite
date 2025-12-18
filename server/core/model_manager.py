"""
Model lifecycle management for TranscriptionSuite server.

Handles:
- Model loading and caching
- GPU memory management
- Model switching between modes
- Graceful cleanup
"""

import logging
from typing import Any, Dict, Optional

from server.core.audio_utils import (
    check_cuda_available,
    clear_gpu_cache,
    get_gpu_memory_info,
)
from server.core.transcription_engine import (
    TranscriptionEngine,
    create_transcription_engine,
)

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Manages AI model lifecycle for the transcription server.

    Keeps one model loaded at a time to manage GPU memory efficiently.
    Handles model caching and switching between different configurations.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the model manager.

        Args:
            config: Full application configuration dict
        """
        self.config = config
        self._transcription_engine: Optional[TranscriptionEngine] = None
        self._diarization_engine: Optional[Any] = None  # Will be DiarizationEngine

        # Check GPU availability
        self.gpu_available = check_cuda_available()
        if self.gpu_available:
            gpu_info = get_gpu_memory_info()
            logger.info(
                f"GPU available with {gpu_info.get('total_gb', 'unknown')} GB memory"
            )
        else:
            logger.warning("No GPU available, using CPU for transcription")

    @property
    def transcription_engine(self) -> TranscriptionEngine:
        """Get or create the transcription engine."""
        if self._transcription_engine is None:
            self._transcription_engine = create_transcription_engine(self.config)
        return self._transcription_engine

    def load_transcription_model(self) -> None:
        """Explicitly load the transcription model."""
        engine = self.transcription_engine
        if not engine.is_loaded():
            logger.info("Loading transcription model...")
            engine.load_model()
            logger.info("Transcription model ready")

    def unload_transcription_model(self) -> None:
        """Unload the transcription model to free memory."""
        if self._transcription_engine is not None:
            self._transcription_engine.unload_model()

    def load_diarization_model(self) -> None:
        """Load the speaker diarization model."""
        if self._diarization_engine is not None:
            logger.debug("Diarization model already loaded")
            return

        # Import and load diarization engine
        try:
            from server.core.diarization_engine import create_diarization_engine

            self._diarization_engine = create_diarization_engine(self.config)
            logger.info("Diarization model loaded")
        except ImportError as e:
            logger.warning(f"Diarization not available: {e}")
        except Exception as e:
            logger.error(f"Failed to load diarization model: {e}")

    def unload_diarization_model(self) -> None:
        """Unload the diarization model."""
        if self._diarization_engine is not None:
            try:
                self._diarization_engine.unload()
            except AttributeError:
                pass
            self._diarization_engine = None
            clear_gpu_cache()
            logger.info("Diarization model unloaded")

    def unload_all(self) -> None:
        """Unload all models and free GPU memory."""
        logger.info("Unloading all models...")
        self.unload_transcription_model()
        self.unload_diarization_model()
        clear_gpu_cache()
        logger.info("All models unloaded")

    def get_status(self) -> Dict[str, Any]:
        """Get status information about loaded models."""
        status = {
            "gpu_available": self.gpu_available,
            "gpu_memory": get_gpu_memory_info() if self.gpu_available else None,
            "transcription": {
                "loaded": self._transcription_engine is not None
                and self._transcription_engine.is_loaded(),
                "config": self._transcription_engine.get_status()
                if self._transcription_engine
                else None,
            },
            "diarization": {
                "loaded": self._diarization_engine is not None,
            },
        }
        return status

    def reload_config(self, new_config: Dict[str, Any]) -> None:
        """
        Reload with new configuration.

        Unloads current models if configuration has changed.
        """
        old_trans_config = self.config.get("transcription", {})
        new_trans_config = new_config.get("transcription", {})

        # Check if transcription config changed
        if old_trans_config.get("model") != new_trans_config.get("model"):
            logger.info("Transcription model changed, reloading...")
            self.unload_transcription_model()
            self._transcription_engine = None

        self.config = new_config


# Global model manager instance
_manager: Optional[ModelManager] = None


def get_model_manager(config: Optional[Dict[str, Any]] = None) -> ModelManager:
    """Get or create the global model manager instance."""
    global _manager
    if _manager is None:
        if config is None:
            raise RuntimeError("Model manager not initialized and no config provided")
        _manager = ModelManager(config)
    return _manager


def cleanup_models() -> None:
    """Clean up all loaded models."""
    global _manager
    if _manager is not None:
        _manager.unload_all()
        _manager = None
