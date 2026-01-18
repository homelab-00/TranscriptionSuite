"""
Live transcription engine for real-time text transcription.

Provides live transcription using a smaller, faster model
while the main transcriber processes for final accuracy.

Only loaded when:
1. config.yaml has live_transcriber.enabled = true
2. Client is the standalone app (not web browser)

This saves GPU memory when live transcription isn't needed.
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
class LiveTranscriberConfig:
    """Configuration for live transcription."""

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
    def from_dict(cls, config: Dict[str, Any]) -> "LiveTranscriberConfig":
        """Create LiveTranscriberConfig from configuration dict."""
        live_config = config.get("live_transcriber", {})
        if not live_config:
            live_config = config.get("transcription", {}).get("live_transcriber", {})

        # Get stt config for webrtc_sensitivity
        stt_config = config.get("stt", {})

        return cls(
            enabled=live_config.get("enabled", False),
            model=live_config.get("model", "Systran/faster-whisper-base"),
            device=live_config.get("device", "cuda"),
            compute_type=live_config.get("compute_type", "default"),
            batch_size=live_config.get("batch_size", 8),
            beam_size=live_config.get("beam_size", 3),
            post_speech_silence_duration=live_config.get(
                "post_speech_silence_duration", 0.3
            ),
            early_transcription_on_silence=live_config.get(
                "early_transcription_on_silence", 0.5
            ),
            silero_sensitivity=live_config.get("silero_sensitivity", 0.4),
            webrtc_sensitivity=stt_config.get("webrtc_sensitivity", 3),
        )

    @classmethod
    def from_server_config(cls) -> "LiveTranscriberConfig":
        """Create LiveTranscriberConfig from the global server configuration."""
        cfg = get_config()
        live_config = cfg.get("live_transcriber", default={})
        stt_config = cfg.stt

        return cls(
            enabled=live_config.get("enabled", False),
            model=live_config.get("model", "Systran/faster-whisper-base"),
            device=live_config.get("device", "cuda"),
            compute_type=live_config.get("compute_type", "default"),
            batch_size=live_config.get("batch_size", 8),
            beam_size=live_config.get("beam_size", 3),
            post_speech_silence_duration=live_config.get(
                "post_speech_silence_duration", 0.3
            ),
            early_transcription_on_silence=live_config.get(
                "early_transcription_on_silence", 0.5
            ),
            silero_sensitivity=live_config.get("silero_sensitivity", 0.4),
            webrtc_sensitivity=stt_config.get("webrtc_sensitivity", 3),
        )


class LiveTranscriptionEngine:
    """
    Secondary transcription engine for real-time live transcription.

    Uses a smaller, faster model to provide live transcription text
    while the main transcriber processes for final accuracy.

    Only loaded when:
    1. config.yaml has live_transcriber.enabled = true
    2. Client is the standalone app (not web browser)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        on_live_text: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the live transcription engine.

        Args:
            config: Server configuration dict
            on_live_text: Callback for live transcription text
        """
        self.config = LiveTranscriberConfig.from_dict(config)
        self.on_live_text = on_live_text

        self._engine: Optional[Any] = None
        self._loaded = False
        self._lock = threading.Lock()
        self._language: Optional[str] = None

    @property
    def should_load(self) -> bool:
        """Check if live transcriber should be loaded based on config."""
        return self.config.enabled

    @property
    def is_loaded(self) -> bool:
        """Check if the live transcription engine is currently loaded."""
        return self._loaded

    def load(self, language: Optional[str] = None) -> bool:
        """
        Load the live transcription model.

        Args:
            language: Target language code

        Returns:
            True if successfully loaded, False if disabled or error
        """
        if not self.should_load:
            logger.info("Live transcriber disabled in config")
            return False

        if self._loaded:
            logger.debug("Live transcription engine already loaded")
            return True

        with self._lock:
            if self._loaded:
                return True

            try:
                from server.core.stt.engine import AudioToTextRecorder

                self._language = language

                self._engine = AudioToTextRecorder(
                    instance_name="live_transcriber",
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
                logger.info(f"Live transcriber loaded with model: {self.config.model}")
                return True

            except Exception as e:
                logger.exception(f"Failed to load live transcriber: {e}")
                return False

    def unload(self) -> None:
        """Unload the live transcriber model to free memory."""
        with self._lock:
            if self._engine:
                try:
                    self._engine.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down live transcriber engine: {e}")
                self._engine = None
            self._loaded = False
            logger.info("Live transcriber unloaded")

    def feed_audio(
        self,
        audio_data: Union[bytes, bytearray, np.ndarray],
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """
        Feed audio data to the live transcriber engine.

        Args:
            audio_data: Audio data (PCM Int16 bytes or numpy array)
            sample_rate: Sample rate of the audio
        """
        if not self._loaded or not self._engine:
            return

        try:
            self._engine.feed_audio(audio_data, sample_rate)
        except Exception as e:
            logger.warning(f"Error feeding audio to live transcriber engine: {e}")

    def start_recording(self, language: Optional[str] = None) -> None:
        """
        Start live transcriber recording session.

        Args:
            language: Target language code
        """
        if not self._loaded:
            if not self.load(language):
                return

        if self._engine:
            self._engine.listen()

    def stop_recording(self) -> None:
        """Stop the live transcriber recording session."""
        if self._engine:
            self._engine.stop()

    async def get_live_text(self) -> Optional[str]:
        """
        Get the current live transcription text.

        Returns:
            Live transcription text or None if not available
        """
        if not self._loaded or not self._engine:
            return None

        try:
            # Run in thread pool (blocking operation)
            text = await asyncio.to_thread(self._engine.text)
            return text if text else None
        except Exception as e:
            logger.warning(f"Error getting live transcription text: {e}")
            return None

    def get_status(self) -> Dict[str, Any]:
        """Get status information about the live transcriber engine."""
        return {
            "enabled": self.config.enabled,
            "loaded": self._loaded,
            "model": self.config.model if self._loaded else None,
        }


# Module-level singleton for live transcriber engine
_live_transcriber_engine: Optional[LiveTranscriptionEngine] = None
_live_transcriber_lock = threading.Lock()


def get_live_transcriber_engine(
    config: Optional[Dict[str, Any]] = None,
) -> Optional[LiveTranscriptionEngine]:
    """
    Get or create the live transcriber engine singleton.

    Args:
        config: Server configuration dict (required on first call)

    Returns:
        LiveTranscriptionEngine or None if not configured
    """
    global _live_transcriber_engine

    with _live_transcriber_lock:
        if _live_transcriber_engine is None:
            if config is None:
                return None
            _live_transcriber_engine = LiveTranscriptionEngine(config)

    return _live_transcriber_engine


def cleanup_live_transcriber_engine() -> None:
    """Clean up the live transcriber engine."""
    global _live_transcriber_engine

    with _live_transcriber_lock:
        if _live_transcriber_engine is not None:
            _live_transcriber_engine.unload()
            _live_transcriber_engine = None
