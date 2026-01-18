"""
Live Mode Engine using RealtimeSTT.

Provides real-time, sentence-by-sentence transcription using RealtimeSTT's
AudioToTextRecorder. This is designed for dictation-style use cases where
text is continuously transcribed as the user speaks.

Unlike the preview transcriber (which shows partial real-time text during
recording), Live Mode operates independently and delivers complete sentences
as they are detected.
"""

import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Try to import RealtimeSTT
try:
    from RealtimeSTT import AudioToTextRecorder

    HAS_REALTIMESTT = True
except ImportError:
    HAS_REALTIMESTT = False
    AudioToTextRecorder = None  # type: ignore
    logger.warning("RealtimeSTT not installed. Live Mode will not be available.")


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
    model: str = "base"
    language: str = ""
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
    Live Mode transcription engine using RealtimeSTT.

    This engine provides continuous sentence-by-sentence transcription,
    designed for real-time dictation workflows. Each completed sentence
    triggers a callback, and can optionally be auto-pasted at the cursor.
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
        if not HAS_REALTIMESTT:
            raise ImportError(
                "RealtimeSTT is required for Live Mode. "
                "Install with: pip install realtimestt"
            )

        self.config = config or LiveModeConfig()
        self._on_sentence = on_sentence
        self._on_realtime_update = on_realtime_update
        self._on_state_change = on_state_change

        self._recorder: Optional[AudioToTextRecorder] = None
        self._state = LiveModeState.STOPPED
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sentence_queue: queue.Queue[str] = queue.Queue()

        # Track history for the UI
        self._sentence_history: list[str] = []
        self._max_history = 50

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

    def _on_realtime_transcription(self, text: str) -> None:
        """Callback for real-time partial transcription updates."""
        if self._on_realtime_update:
            try:
                self._on_realtime_update(text)
            except Exception as e:
                logger.error(f"Realtime update callback error: {e}")

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

            # Create recorder with configuration
            self._recorder = AudioToTextRecorder(
                model=self.config.model,
                language=self.config.language if self.config.language else None,
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
                on_realtime_transcription_update=self._on_realtime_transcription,
                enable_realtime_transcription=self._on_realtime_update is not None,
                spinner=False,
                level=logging.WARNING,
            )

            self._set_state(LiveModeState.LISTENING)
            logger.info("Live Mode started")

            # Process sentences in a loop
            while not self._stop_event.is_set():
                try:
                    # text() blocks until a sentence is complete
                    self._recorder.text(self._process_sentence)
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
                except Exception:
                    pass
                self._recorder = None

            if self._state != LiveModeState.ERROR:
                self._set_state(LiveModeState.STOPPED)
            logger.info("Live Mode stopped")

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
        self._loop_thread = threading.Thread(
            target=self._transcription_loop, daemon=True, name="LiveModeThread"
        )
        self._loop_thread.start()
        return True

    def stop(self) -> None:
        """Stop Live Mode transcription."""
        if not self.is_running:
            return

        logger.info("Stopping Live Mode...")
        self._stop_event.set()

        # Shutdown recorder to unblock text() call
        if self._recorder:
            try:
                self._recorder.shutdown()
            except Exception:
                pass

        # Wait for thread to finish
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5.0)
            if self._loop_thread.is_alive():
                logger.warning("Live Mode thread did not stop gracefully")

        self._loop_thread = None

    def clear_history(self) -> None:
        """Clear sentence history."""
        self._sentence_history.clear()


# Singleton instance for server-wide use
_live_engine: Optional[LiveModeEngine] = None


def get_live_engine() -> Optional[LiveModeEngine]:
    """Get the global Live Mode engine instance."""
    return _live_engine


def create_live_engine(
    config: Optional[LiveModeConfig] = None, **kwargs: Any
) -> LiveModeEngine:
    """
    Create or reconfigure the global Live Mode engine.

    Args:
        config: Configuration for the engine
        **kwargs: Additional arguments passed to LiveModeEngine

    Returns:
        The Live Mode engine instance
    """
    global _live_engine

    # Stop existing engine if running
    if _live_engine and _live_engine.is_running:
        _live_engine.stop()

    _live_engine = LiveModeEngine(config=config, **kwargs)
    return _live_engine


def shutdown_live_engine() -> None:
    """Shutdown the global Live Mode engine."""
    global _live_engine
    if _live_engine:
        _live_engine.stop()
        _live_engine = None
