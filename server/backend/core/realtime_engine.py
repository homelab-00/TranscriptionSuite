"""
Real-time transcription engine wrapper.

Provides a clean async interface between WebSocket connections
and the STT engine. Handles:
- Engine lifecycle management
- Audio feeding from WebSocket streams
- Async transcription results
- Live transcriber support (for standalone clients)
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

    Can optionally run with a live transcriber engine for standalone clients.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        enable_live_transcriber: bool = False,
        live_transcriber_engine: Optional[Any] = None,
        on_recording_start: Optional[Callable[[], None]] = None,
        on_recording_stop: Optional[Callable[[], None]] = None,
        on_vad_start: Optional[Callable[[], None]] = None,
        on_vad_stop: Optional[Callable[[], None]] = None,
        on_live_text: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the real-time transcription engine.

        Args:
            config: Server configuration dict
            enable_live_transcriber: Enable live transcriber (for standalone clients)
            live_transcriber_engine: External live transcriber engine (AudioToTextRecorder) to use
                                     instead of creating a new one. If provided, this engine will
                                     be used for live transcription to avoid duplicate model loading.
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops
            on_vad_start: Callback when voice activity detected
            on_vad_stop: Callback when voice activity ends
            on_live_text: Callback for live transcription text
        """
        self.config = config
        self.enable_live_transcriber = enable_live_transcriber
        self._external_live_transcriber_engine = live_transcriber_engine
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop
        self.on_vad_start = on_vad_start
        self.on_vad_stop = on_vad_stop
        self.on_live_text = on_live_text

        self._engine: Optional[Any] = None
        self._live_transcriber_engine: Optional[Any] = None
        self._initialized = False
        self._is_recording = False
        self._language: Optional[str] = None
        self._sharing_single_engine = False

    def initialize(self, language: Optional[str] = None) -> None:
        """
        Initialize the underlying STT engine.

        When live_transcriber is enabled and uses the same model as main_transcriber,
        we use a single shared engine for both purposes to conserve GPU memory.

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
        live_config = self.config.get(
            "live_transcriber", trans_config.get("live_transcriber", {})
        )

        # Determine model names
        main_model = main_config.get("model", "Systran/faster-whisper-large-v3")
        live_model = live_config.get("model", main_model)  # Defaults to main model

        # Check if we should share a single engine (same model = share to save VRAM)
        self._sharing_single_engine = (
            self.enable_live_transcriber
            and self._external_live_transcriber_engine is not None
            and self._is_same_model(main_model, live_model)
        )

        if self._sharing_single_engine:
            # Use the shared live transcriber engine for BOTH main and live transcription
            # This saves ~6GB VRAM by not loading the model twice
            self._engine = self._external_live_transcriber_engine
            self._live_transcriber_engine = self._external_live_transcriber_engine
            logger.info(
                f"Using single shared engine for both main and live transcription "
                f"(model: {live_model}, saves ~6GB VRAM)"
            )
        else:
            # Create separate main transcription engine
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

            # Set up live transcriber engine if enabled
            if self.enable_live_transcriber:
                if self._external_live_transcriber_engine is not None:
                    # Use the shared live transcriber engine (separate from main)
                    self._live_transcriber_engine = (
                        self._external_live_transcriber_engine
                    )
                    logger.info("Using shared live transcriber engine (separate model)")
                else:
                    # Create our own live transcriber engine (fallback)
                    self._init_live_transcriber_engine()

        self._initialized = True
        logger.info(
            f"RealtimeTranscriptionEngine initialized "
            f"(live_transcriber={'enabled' if self.enable_live_transcriber else 'disabled'}, "
            f"sharing_engine={self._sharing_single_engine})"
        )

    def _is_same_model(self, model_a: str, model_b: str) -> bool:
        """Check if two model names refer to the same model."""

        def normalize(name: str) -> str:
            name = name.lower().strip()
            for prefix in ["systran/", "faster-whisper-", "openai/whisper-"]:
                if name.startswith(prefix):
                    name = name[len(prefix) :]
            return name

        return normalize(model_a) == normalize(model_b)

    def _init_live_transcriber_engine(self) -> None:
        """Initialize the live transcription engine."""
        from server.core.stt.engine import AudioToTextRecorder

        # Get live transcriber config from passed dict or global config
        trans_config = self.config.get("transcription", {})
        live_transcriber_config = self.config.get(
            "live_transcriber", trans_config.get("live_transcriber", {})
        )

        if not live_transcriber_config.get("enabled", True):
            logger.info("Live transcriber disabled in config")
            return

        # AudioToTextRecorder resolves defaults from config internally
        self._live_transcriber_engine = AudioToTextRecorder(
            instance_name="realtime_live_transcriber",
            model=live_transcriber_config.get("model"),
            language=self._language or "",
            compute_type=live_transcriber_config.get("compute_type"),
            device=live_transcriber_config.get("device"),
            batch_size=live_transcriber_config.get("batch_size", 8),
            beam_size=live_transcriber_config.get("beam_size", 3),
            # Faster response for live transcription
            post_speech_silence_duration=live_transcriber_config.get(
                "post_speech_silence_duration", 0.3
            ),
            # Enable early transcription for live transcriber
            early_transcription_on_silence=live_transcriber_config.get(
                "early_transcription_on_silence", 0.5
            ),
        )

        logger.info("Live transcription engine initialized")

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

        # Also feed to live transcriber engine if enabled AND it's a separate engine
        # (when sharing single engine, _engine and _live_transcriber_engine are the same)
        if self._live_transcriber_engine and not self._sharing_single_engine:
            self._live_transcriber_engine.feed_audio(audio_data, sample_rate)

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
        # Only call listen() on live transcriber if it's a separate engine
        if self._live_transcriber_engine and not self._sharing_single_engine:
            self._live_transcriber_engine.listen()

    def stop_recording(self) -> None:
        """Stop the current recording session."""
        if self._engine:
            self._engine.stop()
        # Only call stop() on live transcriber if it's a separate engine
        if self._live_transcriber_engine and not self._sharing_single_engine:
            self._live_transcriber_engine.stop()

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

    async def get_live_transcription(self) -> Optional[RealtimeTranscriptionResult]:
        """
        Get live transcription if available.

        Returns:
            RealtimeTranscriptionResult or None if live transcriber not enabled
        """
        if not self._live_transcriber_engine:
            return None

        # Run in thread pool
        result = await asyncio.to_thread(self._live_transcriber_engine.text)

        return RealtimeTranscriptionResult(
            text=result,
            is_live_transcription=True,
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
        # When sharing a single engine, DON'T shutdown it - it's owned by model_manager
        if self._sharing_single_engine:
            logger.info("Releasing shared engine reference (not shutting down)")
            self._engine = None
            self._live_transcriber_engine = None
        else:
            # Shutdown main engine if we created it
            if self._engine:
                self._engine.shutdown()
                self._engine = None

            # Only shutdown the live transcriber engine if we created it (not if it's external/shared)
            if (
                self._live_transcriber_engine
                and self._external_live_transcriber_engine is None
            ):
                self._live_transcriber_engine.shutdown()
            self._live_transcriber_engine = None

        self._initialized = False
        self._sharing_single_engine = False
        logger.info("RealtimeTranscriptionEngine shutdown complete")

    def __enter__(self) -> "RealtimeTranscriptionEngine":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()


def create_realtime_engine(
    config: Dict[str, Any],
    enable_live_transcriber: bool = False,
    live_transcriber_engine: Optional[Any] = None,
    **callbacks: Any,
) -> RealtimeTranscriptionEngine:
    """
    Factory function to create a real-time transcription engine.

    Args:
        config: Server configuration dict
        enable_live_transcriber: Enable live transcriber
        live_transcriber_engine: External live transcriber engine to use (avoids duplicate model loading)
        **callbacks: Optional callback functions

    Returns:
        Configured RealtimeTranscriptionEngine
    """
    return RealtimeTranscriptionEngine(
        config=config,
        enable_live_transcriber=enable_live_transcriber,
        live_transcriber_engine=live_transcriber_engine,
        on_recording_start=callbacks.get("on_recording_start"),
        on_recording_stop=callbacks.get("on_recording_stop"),
        on_vad_start=callbacks.get("on_vad_start"),
        on_vad_stop=callbacks.get("on_vad_stop"),
        on_live_text=callbacks.get("on_live_text"),
    )
