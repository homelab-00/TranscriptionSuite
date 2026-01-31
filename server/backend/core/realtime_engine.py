"""
Real-time transcription engine wrapper.

Provides a clean async interface between WebSocket connections
and the STT engine. Handles:
- Engine lifecycle management
- Audio feeding from WebSocket streams
- Async transcription results
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np

# Target sample rate for Whisper (technical requirement, not configurable)
SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


@dataclass
class RealtimeTranscriptionResult:
    """Result from real-time transcription."""

    text: str
    language: Optional[str] = None
    duration: float = 0.0
    words: List[Dict[str, Any]] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)
    is_live_transcription: bool = False


class RealtimeTranscriptionEngine:
    """
    Real-time transcription engine for WebSocket connections.

    Wraps the AudioToTextRecorder for server use:
    - Receives audio chunks via feed_audio()
    - Provides VAD events via callbacks
    - Returns transcription when speech ends

    """

    def __init__(
        self,
        config: Dict[str, Any],
        on_recording_start: Optional[Callable[[], None]] = None,
        on_recording_stop: Optional[Callable[[], None]] = None,
        on_vad_start: Optional[Callable[[], None]] = None,
        on_vad_stop: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the real-time transcription engine.

        Args:
            config: Server configuration dict
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops
            on_vad_start: Callback when voice activity detected
            on_vad_stop: Callback when voice activity ends
        """
        self.config = config
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop
        self.on_vad_start = on_vad_start
        self.on_vad_stop = on_vad_stop

        self._engine: Optional[Any] = None
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

        # Get transcription config from passed dict or global config
        trans_config = self.config.get("transcription", {})
        main_config = self.config.get(
            "main_transcriber", trans_config.get("main_transcriber", {})
        )
        # AudioToTextRecorder resolves defaults from config internally,
        # so we only pass values if they're explicitly configured
        self._engine = AudioToTextRecorder(
            instance_name="realtime_main",
            model=main_config.get("model"),
            language=language or "",
            compute_type=main_config.get("compute_type"),
            device=main_config.get("device"),
            batch_size=main_config.get("batch_size"),
            beam_size=main_config.get("beam_size"),
            silero_sensitivity=main_config.get("silero_sensitivity"),
            webrtc_sensitivity=main_config.get("webrtc_sensitivity"),
            post_speech_silence_duration=main_config.get(
                "post_speech_silence_duration"
            ),
            pre_recording_buffer_duration=main_config.get(
                "pre_recording_buffer_duration"
            ),
            faster_whisper_vad_filter=main_config.get("faster_whisper_vad_filter"),
            normalize_audio=main_config.get("normalize_audio"),
            on_recording_start=self._handle_recording_start,
            on_recording_stop=self._handle_recording_stop,
            on_vad_start=self._handle_vad_start,
            on_vad_stop=self._handle_vad_stop,
        )

        self._initialized = True
        logger.info("RealtimeTranscriptionEngine initialized")

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

    def stop_recording(self) -> None:
        """Stop the current recording session."""
        if self._engine:
            self._engine.stop()

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
        # Note: we call text() to trigger transcription but use
        # _perform_transcription() to get detailed results
        await asyncio.to_thread(self._engine.text)

        # Get detailed result from engine
        engine_result = self._engine._perform_transcription(self._engine.audio)

        return RealtimeTranscriptionResult(
            text=engine_result.text,
            language=engine_result.language,
            duration=engine_result.duration,
            words=engine_result.words,
            segments=engine_result.segments,
            is_live_transcription=False,
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
        self._initialized = False
        logger.info("RealtimeTranscriptionEngine shutdown complete")

    def __enter__(self) -> "RealtimeTranscriptionEngine":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()


def create_realtime_engine(
    config: Dict[str, Any],
    **callbacks: Any,
) -> RealtimeTranscriptionEngine:
    """
    Factory function to create a real-time transcription engine.

    Args:
        config: Server configuration dict
        **callbacks: Optional callback functions

    Returns:
        Configured RealtimeTranscriptionEngine
    """
    return RealtimeTranscriptionEngine(
        config=config,
        on_recording_start=callbacks.get("on_recording_start"),
        on_recording_stop=callbacks.get("on_recording_stop"),
        on_vad_start=callbacks.get("on_vad_start"),
        on_vad_stop=callbacks.get("on_vad_stop"),
    )
