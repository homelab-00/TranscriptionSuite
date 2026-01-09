"""
Preview transcription engine for real-time text preview.

Provides live preview transcription using a smaller, faster model
while the main transcriber processes for final accuracy.

Only loaded when:
1. config.yaml has preview_transcriber.enabled = true
2. Client is the standalone app (not web browser)

This saves GPU memory when preview isn't needed.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union

import numpy as np

from server.config import get_config

# Target sample rate for Whisper (technical requirement, not configurable)
SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


@dataclass
class PreviewConfig:
    """Configuration for preview transcription."""

    enabled: bool = False
    model: str = "Systran/faster-whisper-base"
    device: str = "cuda"
    compute_type: str = "default"
    batch_size: int = 8
    beam_size: int = 3
    post_speech_silence_duration: float = 0.3
    early_transcription_on_silence: float = 0.5
    silero_sensitivity: float = 0.4
    webrtc_sensitivity: int = 3

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "PreviewConfig":
        """Create PreviewConfig from configuration dict."""
        # Support both raw dict and nested dict format
        preview_config = config.get("preview_transcriber", {})
        if not preview_config:
            preview_config = config.get("transcription", {}).get(
                "preview_transcriber", {}
            )

        # Get stt config for webrtc_sensitivity
        stt_config = config.get("stt", {})

        return cls(
            enabled=preview_config.get("enabled", False),
            model=preview_config.get("model", "Systran/faster-whisper-base"),
            device=preview_config.get("device", "cuda"),
            compute_type=preview_config.get("compute_type", "default"),
            batch_size=preview_config.get("batch_size", 8),
            beam_size=preview_config.get("beam_size", 3),
            post_speech_silence_duration=preview_config.get(
                "post_speech_silence_duration", 0.3
            ),
            early_transcription_on_silence=preview_config.get(
                "early_transcription_on_silence", 0.5
            ),
            silero_sensitivity=preview_config.get("silero_sensitivity", 0.4),
            webrtc_sensitivity=stt_config.get("webrtc_sensitivity", 3),
        )

    @classmethod
    def from_server_config(cls) -> "PreviewConfig":
        """Create PreviewConfig from the global server configuration."""
        cfg = get_config()
        preview_config = cfg.get("preview_transcriber", default={})
        stt_config = cfg.stt

        return cls(
            enabled=preview_config.get("enabled", False),
            model=preview_config.get("model", "Systran/faster-whisper-base"),
            device=preview_config.get("device", "cuda"),
            compute_type=preview_config.get("compute_type", "default"),
            batch_size=preview_config.get("batch_size", 8),
            beam_size=preview_config.get("beam_size", 3),
            post_speech_silence_duration=preview_config.get(
                "post_speech_silence_duration", 0.3
            ),
            early_transcription_on_silence=preview_config.get(
                "early_transcription_on_silence", 0.5
            ),
            silero_sensitivity=preview_config.get("silero_sensitivity", 0.4),
            webrtc_sensitivity=stt_config.get("webrtc_sensitivity", 3),
        )


class PreviewTranscriptionEngine:
    """
    Secondary transcription engine for real-time preview.

    Uses a smaller, faster model to provide live preview text
    while the main transcriber processes for final accuracy.

    Only loaded when:
    1. config.yaml has preview_transcriber.enabled = true
    2. Client is the standalone app (not web browser)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        on_preview_text: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the preview engine.

        Args:
            config: Server configuration dict
            on_preview_text: Callback for preview transcription text
        """
        self.config = PreviewConfig.from_dict(config)
        self.on_preview_text = on_preview_text

        self._engine: Optional[Any] = None
        self._loaded = False
        self._lock = threading.Lock()
        self._language: Optional[str] = None

    @property
    def should_load(self) -> bool:
        """Check if preview should be loaded based on config."""
        return self.config.enabled

    @property
    def is_loaded(self) -> bool:
        """Check if the preview engine is currently loaded."""
        return self._loaded

    def load(self, language: Optional[str] = None) -> bool:
        """
        Load the preview model.

        Args:
            language: Target language code

        Returns:
            True if successfully loaded, False if disabled or error
        """
        if not self.should_load:
            logger.info("Preview transcriber disabled in config")
            return False

        if self._loaded:
            logger.debug("Preview engine already loaded")
            return True

        with self._lock:
            if self._loaded:
                return True

            try:
                from server.core.stt.engine import AudioToTextRecorder

                self._language = language

                self._engine = AudioToTextRecorder(
                    instance_name="preview_transcriber",
                    model=self.config.model,
                    language=language or "",
                    compute_type=self.config.compute_type,
                    device=self.config.device,
                    batch_size=self.config.batch_size,
                    beam_size=self.config.beam_size,
                    silero_sensitivity=self.config.silero_sensitivity,
                    webrtc_sensitivity=self.config.webrtc_sensitivity,
                    post_speech_silence_duration=self.config.post_speech_silence_duration,
                    early_transcription_on_silence=int(
                        self.config.early_transcription_on_silence * 1000
                    ),  # Convert to ms
                    # Simplified settings for preview
                    ensure_sentence_starting_uppercase=False,
                    ensure_sentence_ends_with_period=False,
                )

                self._loaded = True
                logger.info(
                    f"Preview transcriber loaded with model: {self.config.model}"
                )
                return True

            except Exception as e:
                logger.exception(f"Failed to load preview transcriber: {e}")
                return False

    def unload(self) -> None:
        """Unload the preview model to free memory."""
        with self._lock:
            if self._engine:
                try:
                    self._engine.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down preview engine: {e}")
                self._engine = None
            self._loaded = False
            logger.info("Preview transcriber unloaded")

    def feed_audio(
        self,
        audio_data: Union[bytes, bytearray, np.ndarray],
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """
        Feed audio data to the preview engine.

        Args:
            audio_data: Audio data (PCM Int16 bytes or numpy array)
            sample_rate: Sample rate of the audio
        """
        if not self._loaded or not self._engine:
            return

        try:
            self._engine.feed_audio(audio_data, sample_rate)
        except Exception as e:
            logger.warning(f"Error feeding audio to preview engine: {e}")

    def start_recording(self, language: Optional[str] = None) -> None:
        """
        Start preview recording session.

        Args:
            language: Target language code
        """
        if not self._loaded:
            if not self.load(language):
                return

        if self._engine:
            self._engine.listen()

    def stop_recording(self) -> None:
        """Stop the preview recording session."""
        if self._engine:
            self._engine.stop()

    async def get_preview_text(self) -> Optional[str]:
        """
        Get the current preview transcription.

        Returns:
            Preview text or None if not available
        """
        if not self._loaded or not self._engine:
            return None

        try:
            # Run in thread pool (blocking operation)
            text = await asyncio.to_thread(self._engine.text)
            return text if text else None
        except Exception as e:
            logger.warning(f"Error getting preview text: {e}")
            return None

    def get_status(self) -> Dict[str, Any]:
        """Get status information about the preview engine."""
        return {
            "enabled": self.config.enabled,
            "loaded": self._loaded,
            "model": self.config.model if self._loaded else None,
        }


# Module-level singleton for preview engine
_preview_engine: Optional[PreviewTranscriptionEngine] = None
_preview_lock = threading.Lock()


def get_preview_engine(
    config: Optional[Dict[str, Any]] = None,
) -> Optional[PreviewTranscriptionEngine]:
    """
    Get or create the preview engine singleton.

    Args:
        config: Server configuration dict (required on first call)

    Returns:
        PreviewTranscriptionEngine or None if not configured
    """
    global _preview_engine

    with _preview_lock:
        if _preview_engine is None:
            if config is None:
                return None
            _preview_engine = PreviewTranscriptionEngine(config)

    return _preview_engine


def cleanup_preview_engine() -> None:
    """Clean up the preview engine."""
    global _preview_engine

    with _preview_lock:
        if _preview_engine is not None:
            _preview_engine.unload()
            _preview_engine = None
