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
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Target sample rate for Whisper
SAMPLE_RATE = 16000

# How long ``start()`` waits for the background thread to finish building the
# recorder before it gives up and reports failure (GH-271).  Initialization can
# legitimately take minutes: the whisper.cpp sidecar gets up to 180s to report
# /health, and a first-run faster-whisper model still has to be downloaded.
# This ceiling exists only so ``start()`` always reaches a definite answer
# instead of blocking a client forever; pass ``timeout=None`` to wait outright.
INIT_TIMEOUT_SECONDS = 300.0


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

    # Whisper model settings (Live Mode is whisper-only in v1)
    # Empty string defers to server config default resolution.
    model: str = ""
    language: str = ""
    translation_enabled: bool = False
    translation_target_language: str = "en"
    compute_type: str = "default"
    device: str = "cuda"
    gpu_device_index: int = 0

    # VAD settings
    silero_sensitivity: float = 0.6
    webrtc_sensitivity: int = 3
    post_speech_silence_duration: float = 1.0
    min_length_of_recording: float = 0.5
    min_gap_between_recordings: float = 0.3

    # Behavior
    ensure_sentence_starting_uppercase: bool = True
    ensure_sentence_ends_with_period: bool = True

    # Performance
    beam_size: int = 5
    batch_size: int = 16

    # Reliability — retry-with-backoff on transcription errors, and a watchdog
    # that restarts the recorder if it stops producing sentences despite
    # incoming audio (a hung text() call).
    max_consecutive_errors: int = 5
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 30.0
    watchdog_timeout_seconds: float = 90.0


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
        config: LiveModeConfig | None = None,
        on_sentence: Callable[[str], None] | None = None,
        on_realtime_update: Callable[[str], None] | None = None,
        on_state_change: Callable[[LiveModeState], None] | None = None,
        shared_backend: Any | None = None,
    ):
        """
        Initialize the Live Mode engine.

        Args:
            config: Configuration for the engine
            on_sentence: Callback for completed sentences
            on_realtime_update: Callback for real-time partial updates
            on_state_change: Callback for state changes
            shared_backend: Pre-loaded STT backend to reuse from the main
                engine instead of loading a new one.
        """
        self.config = config or LiveModeConfig()
        self._on_sentence = on_sentence
        self._on_realtime_update = on_realtime_update
        self._on_state_change = on_state_change
        self._shared_backend = shared_backend

        self._recorder: Any | None = None
        self._state = LiveModeState.STOPPED
        self._loop_thread: threading.Thread | None = None
        self._feeder_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # GH-271: initialization handshake between start() and
        # _transcription_loop.  The recorder (and therefore the model load) is
        # built on the background thread, so start() waits on this event to
        # report the REAL outcome instead of "thread spawned successfully".
        # The loop writes _init_ok / _init_error BEFORE setting the event, so a
        # released caller always reads a settled result.
        self._init_complete = threading.Event()
        self._init_ok = False
        self._init_error: BaseException | None = None

        # Track history for the UI
        self._sentence_history: list[str] = []
        self._max_history = 50

        # Audio queue for feeding from WebSocket
        self._audio_queue: queue.Queue[bytes] = queue.Queue()

        # Watchdog timing — updated from their respective threads
        self._last_audio_time: float | None = None
        self._last_sentence_time: float | None = None
        self._watchdog_restart_requested = False

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

    @property
    def start_error(self) -> BaseException | None:
        """Exception that aborted the last ``start()``, or None if it succeeded.

        Set by the transcription thread when the recorder cannot be built, and
        by ``start()`` itself when initialization exceeds its timeout.  Callers
        use it to tell the client *why* Live Mode did not come up (GH-271).
        """
        return self._init_error

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
        self._last_sentence_time = time.monotonic()
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

    def _create_recorder(self) -> None:
        """Shut down the current recorder (if any) and create a fresh one.

        Used both for the initial build in ``_transcription_loop`` and to
        rebuild after a transient error or a watchdog-triggered restart.
        """
        if self._recorder:
            try:
                self._recorder.shutdown()
            except Exception as e:
                logger.debug("Error shutting down recorder during rebuild: %s", e)
            self._recorder = None

        # Import server's AudioToTextRecorder (not RealtimeSTT's)
        from server.core.stt.engine import AudioToTextRecorder

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
            shared_backend=self._shared_backend,
        )

    def _watchdog_loop(self) -> None:
        """Detect hung text() calls and trigger a recorder restart."""
        while not self._stop_event.is_set():
            self._stop_event.wait(10.0)
            if self._stop_event.is_set():
                break

            now = time.monotonic()
            last_audio = self._last_audio_time
            last_sentence = self._last_sentence_time

            if last_audio is None or last_sentence is None:
                continue

            # If audio has arrived recently but no sentence in watchdog_timeout_seconds,
            # the text() call is likely stuck — kick the recorder to unblock it.
            audio_is_recent = (now - last_audio) < 30.0
            sentence_is_stale = (now - last_sentence) > self.config.watchdog_timeout_seconds
            if audio_is_recent and sentence_is_stale and not self._watchdog_restart_requested:
                logger.warning(
                    "Live Mode watchdog: no sentence in %.0fs despite active audio — "
                    "triggering recorder restart",
                    now - last_sentence,
                )
                self._watchdog_restart_requested = True
                if self._recorder:
                    try:
                        self._recorder.shutdown()
                    except Exception as e:
                        logger.debug("Watchdog recorder shutdown error: %s", e)

    def _transcription_loop(self) -> None:
        """Main transcription loop (runs in separate thread).

        Initialization - importing and constructing the recorder, which loads
        the model - happens here rather than in ``start()`` because it can take
        minutes.  ``start()`` blocks on ``_init_complete`` until this method has
        published a definite outcome, so a model-load failure can no longer be
        reported to the caller as a successful start (GH-271).
        """
        try:
            self._set_state(LiveModeState.STARTING)

            try:
                self._create_recorder()
            except Exception as e:
                # Record the failure and publish the terminal state BEFORE
                # releasing start(), so the caller reads a settled outcome
                # rather than racing this thread for it.
                logger.error(f"Live Mode initialization error: {e}")
                self._init_error = e
                self._set_state(LiveModeState.ERROR)
                self._init_complete.set()
                return

            if self._stop_event.is_set():
                # start() already gave up (timeout), or stop() raced us. Do not
                # advertise LISTENING for a session nobody is waiting for - the
                # client would begin streaming audio into a dead session. The
                # finally block below shuts the freshly built recorder down.
                logger.warning("Live Mode initialized after the start was abandoned - discarding")
                self._init_complete.set()
                return

            self._init_ok = True
            self._set_state(LiveModeState.LISTENING)
            # Seed last_sentence_time so the watchdog waits a full timeout
            # before it considers the engine stale right after startup.
            self._last_sentence_time = time.monotonic()
            logger.info("Live Mode started")
            self._init_complete.set()

            # Process sentences in a loop, retrying transient errors (including
            # watchdog-triggered restarts) with backoff before giving up.
            consecutive_errors = 0
            while not self._stop_event.is_set():
                try:
                    # text() blocks until a sentence is complete or the recorder
                    # is shut down (e.g. by the watchdog or stop()).
                    text = self._recorder.text()  # type: ignore[union-attr]

                    if self._watchdog_restart_requested:
                        # Watchdog detected a hang — treat as a transient error
                        # and rebuild the recorder.
                        self._watchdog_restart_requested = False
                        raise RuntimeError("Watchdog triggered recorder restart")

                    if text:
                        self._process_sentence(text)
                        consecutive_errors = 0

                except Exception as e:
                    if self._stop_event.is_set():
                        break
                    consecutive_errors += 1
                    if consecutive_errors >= self.config.max_consecutive_errors:
                        logger.error(
                            "Live Mode: %d consecutive errors, giving up: %s",
                            consecutive_errors,
                            e,
                        )
                        self._set_state(LiveModeState.ERROR)
                        break
                    delay = min(
                        self.config.retry_backoff_base_seconds * (2 ** (consecutive_errors - 1)),
                        self.config.retry_backoff_max_seconds,
                    )
                    logger.warning(
                        "Live Mode error #%d (retrying in %.1fs): %s",
                        consecutive_errors,
                        delay,
                        e,
                    )
                    self._stop_event.wait(delay)
                    if self._stop_event.is_set():
                        break
                    self._create_recorder()

        except Exception as e:
            logger.error(f"Live Mode loop error: {e}")
            self._set_state(LiveModeState.ERROR)
        finally:
            # Backstop: an exotic exit (a BaseException such as SystemExit
            # escaping the recorder constructor) must never leave start()
            # blocked. _init_ok is still False there, so it reports failure.
            self._init_complete.set()

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
                    self._last_audio_time = time.monotonic()

            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"Audio feeder error: {e}")

    def feed_audio(
        self,
        audio_data: bytes | bytearray | np.ndarray,
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

    def start(self, timeout: float | None = INIT_TIMEOUT_SECONDS) -> bool:
        """
        Start Live Mode transcription.

        Blocks until initialization reaches a definite outcome - the recorder is
        built and listening, or it failed - and reports that outcome (GH-271).
        The model load runs on the background thread, so callers on an event
        loop must run this in a worker thread (``asyncio.to_thread``) to keep
        the loop responsive while the model is loading.

        Args:
            timeout: Seconds to wait for initialization before giving up.
                ``None`` waits indefinitely.

        Returns:
            True when Live Mode is listening.  False when initialization failed
            or timed out - ``start_error`` then holds the reason.
        """
        if self.is_running:
            logger.warning("Live Mode already running")
            return False

        self._stop_event.clear()
        self._init_complete.clear()
        self._init_ok = False
        self._init_error = None
        self._last_audio_time = None
        self._last_sentence_time = None
        self._watchdog_restart_requested = False

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

        if not self._init_complete.wait(timeout):
            self._init_error = TimeoutError(
                f"Live Mode initialization did not finish within {timeout}s"
            )
            logger.error(str(self._init_error))

        if not self._init_ok:
            # Release the feeder thread and let the (possibly still-loading)
            # transcription thread unwind on its own: it discards whatever it
            # builds as soon as it sees the stop event.
            self._stop_event.set()
            return False

        # Start watchdog thread now that the recorder is confirmed listening
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="LiveModeWatchdog"
        )
        self._watchdog_thread.start()

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

        if self._feeder_thread and self._feeder_thread.is_alive():
            self._feeder_thread.join(timeout=2.0)

        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=2.0)

        self._loop_thread = None
        self._feeder_thread = None
        self._watchdog_thread = None
        self._recorder = None

    def clear_history(self) -> None:
        """Clear sentence history."""
        self._sentence_history.clear()
