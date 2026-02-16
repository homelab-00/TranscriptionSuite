"""
Live Mode Engine for real-time sentence-by-sentence transcription.

Provides continuous transcription designed for dictation-style workflows.
Audio is received via WebSocket from the client and fed to the transcription
engine. Each completed sentence triggers a callback.

Unlike the main transcription (which processes complete recordings), Live Mode
operates continuously and delivers sentences as they are detected via VAD.
"""

import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Optional, Union

import numpy as np

logger = logging.getLogger(__name__)

# Target sample rate for Whisper
SAMPLE_RATE = 16000


class LiveModeState(Enum):
    """State of the Live Mode engine."""

    STOPPED = auto()
    STARTING = auto()
    LISTENING = auto()
    PROCESSING = auto()
    ERROR = auto()


@dataclass
class LiveModeConfig:
    """Configuration for Live Mode."""

    # Whisper model settings
    # Empty string defers to server config default resolution.
    model: str = ""
    language: str = ""
    translation_enabled: bool = False
    translation_target_language: str = "en"
    compute_type: str = "float16"
    device: str = "cuda"
    gpu_device_index: int = 0

    # VAD settings
    silero_sensitivity: float = 0.6
    webrtc_sensitivity: int = 3
    post_speech_silence_duration: float = 0.4
    min_length_of_recording: float = 0.5
    min_gap_between_recordings: float = 0.3

    # Behavior
    ensure_sentence_starting_uppercase: bool = True
    ensure_sentence_ends_with_period: bool = True

    # Performance
    beam_size: int = 5
    batch_size: int = 16


class LiveModeEngine:
    """
    Live Mode transcription engine.

    This engine provides continuous sentence-by-sentence transcription,
    designed for real-time dictation workflows. Audio is fed externally
    via feed_audio() from WebSocket streams, and completed sentences
    trigger callbacks.
    """

    def __init__(
        self,
        config: Optional[LiveModeConfig] = None,
        on_sentence: Optional[Callable[[str], None]] = None,
        on_realtime_update: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable[[LiveModeState], None]] = None,
    ):
        """
        Initialize the Live Mode engine.

        Args:
            config: Configuration for the engine
            on_sentence: Callback for completed sentences
            on_realtime_update: Callback for real-time partial updates
            on_state_change: Callback for state changes
        """
        self.config = config or LiveModeConfig()
        self._on_sentence = on_sentence
        self._on_realtime_update = on_realtime_update
        self._on_state_change = on_state_change

        self._recorder: Optional[Any] = None
        self._state = LiveModeState.STOPPED
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Track history for the UI
        self._sentence_history: list[str] = []
        self._max_history = 50

        # Audio queue for feeding from WebSocket
        self._audio_queue: queue.Queue[bytes] = queue.Queue()

    @property
    def state(self) -> LiveModeState:
        """Get current state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if Live Mode is running."""
        return self._state in (LiveModeState.LISTENING, LiveModeState.PROCESSING)

    @property
    def sentence_history(self) -> list[str]:
        """Get history of transcribed sentences."""
        return self._sentence_history.copy()

    def _set_state(self, state: LiveModeState) -> None:
        """Set state and trigger callback."""
        self._state = state
        if self._on_state_change:
            try:
                self._on_state_change(state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def _on_recording_start(self) -> None:
        """Callback when voice activity starts."""
        logger.debug("Live Mode: Voice activity detected")
        self._set_state(LiveModeState.PROCESSING)

    def _on_recording_stop(self) -> None:
        """Callback when voice activity stops."""
        logger.debug("Live Mode: Voice activity ended")
        if self._state == LiveModeState.PROCESSING:
            self._set_state(LiveModeState.LISTENING)

    def _process_sentence(self, text: str) -> None:
        """Process a completed sentence."""
        if not text or not text.strip():
            return

        text = text.strip()
        logger.info(f"Live Mode sentence: {text}")

        # Add to history
        self._sentence_history.append(text)
        if len(self._sentence_history) > self._max_history:
            self._sentence_history = self._sentence_history[-self._max_history :]

        # Trigger callback
        if self._on_sentence:
            try:
                self._on_sentence(text)
            except Exception as e:
                logger.error(f"Sentence callback error: {e}")

    def _transcription_loop(self) -> None:
        """Main transcription loop (runs in separate thread)."""
        try:
            self._set_state(LiveModeState.STARTING)

            # Import server's AudioToTextRecorder (not RealtimeSTT's)
            from server.core.stt.engine import AudioToTextRecorder

            # Create recorder with configuration
            self._recorder = AudioToTextRecorder(
                instance_name="live_mode",
                model=self.config.model,
                language=self.config.language if self.config.language else "",
                task="translate" if self.config.translation_enabled else "transcribe",
                translation_target_language=self.config.translation_target_language,
                compute_type=self.config.compute_type,
                device=self.config.device,
                gpu_device_index=self.config.gpu_device_index,
                silero_sensitivity=self.config.silero_sensitivity,
                webrtc_sensitivity=self.config.webrtc_sensitivity,
                post_speech_silence_duration=self.config.post_speech_silence_duration,
                min_length_of_recording=self.config.min_length_of_recording,
                min_gap_between_recordings=self.config.min_gap_between_recordings,
                ensure_sentence_starting_uppercase=self.config.ensure_sentence_starting_uppercase,
                ensure_sentence_ends_with_period=self.config.ensure_sentence_ends_with_period,
                beam_size=self.config.beam_size,
                batch_size=self.config.batch_size,
                on_recording_start=self._on_recording_start,
                on_recording_stop=self._on_recording_stop,
            )

            self._set_state(LiveModeState.LISTENING)
            logger.info("Live Mode started")

            # Process sentences in a loop
            while not self._stop_event.is_set():
                try:
                    # text() blocks until a sentence is complete
                    text = self._recorder.text()
                    if text:
                        self._process_sentence(text)
                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.error(f"Live Mode transcription error: {e}")
                        self._set_state(LiveModeState.ERROR)
                        break

        except Exception as e:
            logger.error(f"Live Mode initialization error: {e}")
            self._set_state(LiveModeState.ERROR)
        finally:
            if self._recorder:
                try:
                    self._recorder.shutdown()
                except Exception as e:
                    logger.debug("Error while shutting down Live Mode recorder: %s", e)
                self._recorder = None

            if self._state != LiveModeState.ERROR:
                self._set_state(LiveModeState.STOPPED)
            logger.info("Live Mode stopped")

    def _audio_feeder_loop(self) -> None:
        """Feed audio from queue to recorder (runs in separate thread)."""
        while not self._stop_event.is_set():
            try:
                # Get audio chunk from queue with timeout
                try:
                    chunk = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Feed to recorder if available
                if self._recorder and self.is_running:
                    self._recorder.feed_audio(chunk, SAMPLE_RATE)

            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"Audio feeder error: {e}")

    def feed_audio(
        self,
        audio_data: Union[bytes, bytearray, np.ndarray],
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """
        Feed audio data to the engine from WebSocket.

        Args:
            audio_data: Audio data (PCM Int16 bytes or numpy array)
            sample_rate: Sample rate of the audio
        """
        if not self.is_running:
            return

        # Convert numpy array to bytes if needed
        if isinstance(audio_data, np.ndarray):
            audio_data = audio_data.astype(np.int16).tobytes()

        # Add to queue
        try:
            self._audio_queue.put_nowait(audio_data)
        except queue.Full:
            logger.warning("Live Mode audio queue full, dropping chunk")

    def start(self) -> bool:
        """
        Start Live Mode transcription.

        Returns:
            True if started successfully
        """
        if self.is_running:
            logger.warning("Live Mode already running")
            return False

        self._stop_event.clear()

        # Clear audio queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        # Start transcription loop thread
        self._loop_thread = threading.Thread(
            target=self._transcription_loop, daemon=True, name="LiveModeThread"
        )
        self._loop_thread.start()

        # Start audio feeder thread
        self._feeder_thread = threading.Thread(
            target=self._audio_feeder_loop, daemon=True, name="LiveModeAudioFeeder"
        )
        self._feeder_thread.start()

        return True

    def stop(self) -> None:
        """Stop Live Mode transcription."""
        if not self.is_running and self._state == LiveModeState.STOPPED:
            return

        logger.info("Stopping Live Mode...")
        self._stop_event.set()

        # Shutdown recorder to unblock text() call
        if self._recorder:
            try:
                self._recorder.shutdown()
            except Exception as e:
                logger.debug("Error while stopping Live Mode recorder: %s", e)

        # Wait for threads to finish
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5.0)
            if self._loop_thread.is_alive():
                logger.warning("Live Mode thread did not stop gracefully")

        if hasattr(self, "_feeder_thread") and self._feeder_thread.is_alive():
            self._feeder_thread.join(timeout=2.0)

        self._loop_thread = None
        self._recorder = None

    def clear_history(self) -> None:
        """Clear sentence history."""
        self._sentence_history.clear()
