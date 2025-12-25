"""
Real-time transcription engine wrapper.

Provides a clean async interface between WebSocket connections
and the STT engine. Handles:
- Engine lifecycle management
- Audio feeding from WebSocket streams
- Async transcription results
- Preview mode support (for standalone clients)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np

from server.core.stt.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BEAM_SIZE,
    DEFAULT_COMPUTE_TYPE,
    DEFAULT_DEVICE,
    DEFAULT_MODEL,
    DEFAULT_POST_SPEECH_SILENCE_DURATION,
    DEFAULT_PRE_RECORDING_BUFFER_DURATION,
    DEFAULT_SILERO_SENSITIVITY,
    DEFAULT_WEBRTC_SENSITIVITY,
    SAMPLE_RATE,
)

logger = logging.getLogger(__name__)


@dataclass
class RealtimeTranscriptionResult:
    """Result from real-time transcription."""

    text: str
    language: Optional[str] = None
    duration: float = 0.0
    words: List[Dict[str, Any]] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)
    is_preview: bool = False


class RealtimeTranscriptionEngine:
    """
    Real-time transcription engine for WebSocket connections.

    Wraps the AudioToTextRecorder for server use:
    - Receives audio chunks via feed_audio()
    - Provides VAD events via callbacks
    - Returns transcription when speech ends

    Can optionally run with a preview engine for standalone clients.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        enable_preview: bool = False,
        on_recording_start: Optional[Callable[[], None]] = None,
        on_recording_stop: Optional[Callable[[], None]] = None,
        on_vad_start: Optional[Callable[[], None]] = None,
        on_vad_stop: Optional[Callable[[], None]] = None,
        on_preview_text: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the real-time transcription engine.

        Args:
            config: Server configuration dict
            enable_preview: Enable preview transcription (for standalone clients)
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops
            on_vad_start: Callback when voice activity detected
            on_vad_stop: Callback when voice activity ends
            on_preview_text: Callback for preview transcription text
        """
        self.config = config
        self.enable_preview = enable_preview
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop
        self.on_vad_start = on_vad_start
        self.on_vad_stop = on_vad_stop
        self.on_preview_text = on_preview_text

        self._engine: Optional[Any] = None
        self._preview_engine: Optional[Any] = None
        self._initialized = False
        self._is_recording = False
        self._language: Optional[str] = None

    def initialize(self, language: Optional[str] = None) -> None:
        """
        Initialize the underlying STT engine.

        Args:
            language: Target language code (None for auto-detect)
        """
        if self._initialized:
            return

        from server.core.stt.engine import AudioToTextRecorder

        self._language = language

        # Get transcription config
        trans_config = self.config.get("transcription", {})
        main_config = trans_config.get("main_transcriber", trans_config)

        # Create main transcription engine
        self._engine = AudioToTextRecorder(
            instance_name="realtime_main",
            model=main_config.get("model", DEFAULT_MODEL),
            language=language or "",
            compute_type=main_config.get("compute_type", DEFAULT_COMPUTE_TYPE),
            device=main_config.get("device", DEFAULT_DEVICE),
            batch_size=main_config.get("batch_size", DEFAULT_BATCH_SIZE),
            beam_size=main_config.get("beam_size", DEFAULT_BEAM_SIZE),
            silero_sensitivity=main_config.get(
                "silero_sensitivity", DEFAULT_SILERO_SENSITIVITY
            ),
            webrtc_sensitivity=main_config.get(
                "webrtc_sensitivity", DEFAULT_WEBRTC_SENSITIVITY
            ),
            post_speech_silence_duration=main_config.get(
                "post_speech_silence_duration", DEFAULT_POST_SPEECH_SILENCE_DURATION
            ),
            pre_recording_buffer_duration=main_config.get(
                "pre_recording_buffer_duration", DEFAULT_PRE_RECORDING_BUFFER_DURATION
            ),
            faster_whisper_vad_filter=main_config.get(
                "faster_whisper_vad_filter", True
            ),
            normalize_audio=main_config.get("normalize_audio", False),
            on_recording_start=self._handle_recording_start,
            on_recording_stop=self._handle_recording_stop,
            on_vad_start=self._handle_vad_start,
            on_vad_stop=self._handle_vad_stop,
        )

        # Create preview engine if enabled
        if self.enable_preview:
            self._init_preview_engine()

        self._initialized = True
        logger.info(
            f"RealtimeTranscriptionEngine initialized "
            f"(preview={'enabled' if self.enable_preview else 'disabled'})"
        )

    def _init_preview_engine(self) -> None:
        """Initialize the preview transcription engine."""
        from server.core.stt.engine import AudioToTextRecorder
        from server.core.stt.constants import DEFAULT_PREVIEW_MODEL

        preview_config = self.config.get("transcription", {}).get(
            "preview_transcriber", {}
        )

        if not preview_config.get("enabled", True):
            logger.info("Preview transcriber disabled in config")
            return

        self._preview_engine = AudioToTextRecorder(
            instance_name="realtime_preview",
            model=preview_config.get("model", DEFAULT_PREVIEW_MODEL),
            language=self._language or "",
            compute_type=preview_config.get("compute_type", DEFAULT_COMPUTE_TYPE),
            device=preview_config.get("device", DEFAULT_DEVICE),
            batch_size=preview_config.get("batch_size", 8),
            beam_size=preview_config.get("beam_size", 3),
            # Faster response for preview
            post_speech_silence_duration=preview_config.get(
                "post_speech_silence_duration", 0.3
            ),
            # Enable early transcription for preview
            early_transcription_on_silence=preview_config.get(
                "early_transcription_on_silence", 0.5
            ),
        )

        logger.info("Preview transcription engine initialized")

    def _handle_recording_start(self) -> None:
        """Handle recording start event."""
        self._is_recording = True
        if self.on_recording_start:
            self.on_recording_start()

    def _handle_recording_stop(self) -> None:
        """Handle recording stop event."""
        self._is_recording = False
        if self.on_recording_stop:
            self.on_recording_stop()

    def _handle_vad_start(self) -> None:
        """Handle VAD start event."""
        if self.on_vad_start:
            self.on_vad_start()

    def _handle_vad_stop(self) -> None:
        """Handle VAD stop event."""
        if self.on_vad_stop:
            self.on_vad_stop()

    def feed_audio(
        self,
        audio_data: Union[bytes, bytearray, np.ndarray],
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """
        Feed audio data to the engine.

        Args:
            audio_data: Audio data (PCM Int16 bytes or numpy array)
            sample_rate: Sample rate of the audio

        Raises:
            RuntimeError: If engine not initialized
        """
        if not self._initialized:
            raise RuntimeError("Engine not initialized. Call initialize() first.")

        self._engine.feed_audio(audio_data, sample_rate)

        # Also feed to preview engine if enabled
        if self._preview_engine:
            self._preview_engine.feed_audio(audio_data, sample_rate)

    def start_recording(self, language: Optional[str] = None) -> None:
        """
        Start recording session.

        Args:
            language: Target language code (None for auto-detect)
        """
        if not self._initialized:
            self.initialize(language)
        elif language and language != self._language:
            self._language = language
            # Note: Language change mid-session not fully supported
            logger.warning("Language changed mid-session, may not take effect")

        self._engine.listen()
        if self._preview_engine:
            self._preview_engine.listen()

    def stop_recording(self) -> None:
        """Stop the current recording session."""
        if self._engine:
            self._engine.stop()
        if self._preview_engine:
            self._preview_engine.stop()

    async def get_transcription(self) -> RealtimeTranscriptionResult:
        """
        Get the transcription result.

        Blocks until transcription is complete.

        Returns:
            RealtimeTranscriptionResult with the transcription
        """
        if not self._initialized or not self._engine:
            raise RuntimeError("Engine not initialized")

        # Run transcription in thread pool (blocking operation)
        result = await asyncio.to_thread(self._engine.text)

        # Get detailed result from engine
        engine_result = self._engine._perform_transcription(self._engine.audio)

        return RealtimeTranscriptionResult(
            text=engine_result.text,
            language=engine_result.language,
            duration=engine_result.duration,
            words=engine_result.words,
            segments=engine_result.segments,
            is_preview=False,
        )

    async def get_preview_transcription(self) -> Optional[RealtimeTranscriptionResult]:
        """
        Get preview transcription if available.

        Returns:
            RealtimeTranscriptionResult or None if preview not enabled
        """
        if not self._preview_engine:
            return None

        # Run in thread pool
        result = await asyncio.to_thread(self._preview_engine.text)

        return RealtimeTranscriptionResult(
            text=result,
            is_preview=True,
        )

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording

    @property
    def is_initialized(self) -> bool:
        """Check if engine is initialized."""
        return self._initialized

    def shutdown(self) -> None:
        """Shutdown the engine and release resources."""
        if self._engine:
            self._engine.shutdown()
            self._engine = None

        if self._preview_engine:
            self._preview_engine.shutdown()
            self._preview_engine = None

        self._initialized = False
        logger.info("RealtimeTranscriptionEngine shutdown complete")

    def __enter__(self) -> "RealtimeTranscriptionEngine":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()


def create_realtime_engine(
    config: Dict[str, Any],
    enable_preview: bool = False,
    **callbacks: Any,
) -> RealtimeTranscriptionEngine:
    """
    Factory function to create a real-time transcription engine.

    Args:
        config: Server configuration dict
        enable_preview: Enable preview transcription
        **callbacks: Optional callback functions

    Returns:
        Configured RealtimeTranscriptionEngine
    """
    return RealtimeTranscriptionEngine(
        config=config,
        enable_preview=enable_preview,
        on_recording_start=callbacks.get("on_recording_start"),
        on_recording_stop=callbacks.get("on_recording_stop"),
        on_vad_start=callbacks.get("on_vad_start"),
        on_vad_stop=callbacks.get("on_vad_stop"),
        on_preview_text=callbacks.get("on_preview_text"),
    )
