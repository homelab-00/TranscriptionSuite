#!/usr/bin/env python3
"""
Core long-form recording and transcription module.

This module contains the LongFormRecorder class, which wraps the RealtimeSTT
library to handle audio capture, voice activity detection, and final
transcription processing. It is designed to work without direct microphone
access, receiving audio via a feed method.
"""

import contextlib
import time
import logging
import threading
from typing import Any, Callable, Optional, TYPE_CHECKING

import pyperclip
from platform_utils import ensure_platform_init

# Import RealtimeSTT and handle potential ImportError
try:
    from RealtimeSTT import AudioToTextRecorder

    HAS_REALTIME_STT = True
except ImportError:
    AudioToTextRecorder = None
    HAS_REALTIME_STT = False

if TYPE_CHECKING:
    from RealtimeSTT import AudioToTextRecorder as AudioToTextRecorderType
else:
    AudioToTextRecorderType = Any

# Initialize platform-specific settings (console encoding, etc.)
PLATFORM_MANAGER = ensure_platform_init()


class LongFormRecorder:
    """
    Manages the audio recording and transcription process for long-form dictation.
    """

    def __init__(
        self,
        config: dict,
        # Callbacks for decoupling
        on_recording_start: Optional[Callable] = None,
        on_recording_stop: Optional[Callable] = None,
        on_recorded_chunk: Optional[Callable[[bytes], None]] = None,
    ):
        """
        Initializes the recorder with transcription and VAD parameters.
        """
        if not HAS_REALTIME_STT or AudioToTextRecorder is None:
            raise ImportError("RealtimeSTT library is not available.")

        self.is_running = True
        self.is_recording = False
        self._recording_started_at: Optional[float] = None
        self._last_recording_duration = 0.0
        self._last_transcription_duration = 0.0
        self.last_transcription = ""

        # Prepare configuration for the underlying AudioToTextRecorder
        self.recorder_config = dict(config) if config else {}
        # This is now controlled by the orchestrator via the config dict.
        self.recorder_config["spinner"] = False
        # Store external callbacks
        self.external_on_recording_start = on_recording_start
        self.external_on_recording_stop = on_recording_stop
        # Add internal/external callbacks to the config
        self.recorder_config["on_recording_start"] = self._internal_on_start
        self.recorder_config["on_recording_stop"] = self._internal_on_stop
        if on_recorded_chunk:
            self.recorder_config["on_recorded_chunk"] = on_recorded_chunk

        self.recorder: Optional[AudioToTextRecorderType] = self._initialize_recorder()

        # --- FIX: Re-enable log propagation from RealtimeSTT ---
        # The library disables propagation by default. We re-enable it so its
        # logs flow into our main application log file.
        if self.recorder:
            stt_logger = logging.getLogger("realtimestt")
            stt_logger.propagate = True
        logging.info("LongFormRecorder initialized successfully.")

    def _initialize_recorder(self) -> Optional[AudioToTextRecorderType]:
        """Creates an instance of the underlying recorder."""
        suppress_ctx = getattr(PLATFORM_MANAGER, "suppress_audio_warnings", None)
        try:
            context_manager: contextlib.AbstractContextManager[Any]
            context_manager = suppress_ctx() if suppress_ctx else contextlib.nullcontext()
            with context_manager:
                if AudioToTextRecorder is None:
                    raise RuntimeError(
                        "RealtimeSTT AudioToTextRecorder is unavailable at runtime."
                    )
                # Create a clean config for the underlying library,
                # removing our custom keys.
                library_config = self.recorder_config.copy()
                library_config.pop("use_default_input", None)

                return AudioToTextRecorder(**library_config)
        except Exception as e:
            logging.error(
                "Failed to initialize AudioToTextRecorder: %s", e, exc_info=True
            )
            return None

    def _internal_on_start(self):
        """Internal callback for when recording starts."""
        self.is_recording = True
        self._recording_started_at = time.monotonic()
        self.last_transcription = ""
        if self.external_on_recording_start:
            self.external_on_recording_start(self._recording_started_at)

    def _internal_on_stop(self):
        """Internal callback for when recording stops."""
        if self._recording_started_at:
            self._last_recording_duration = time.monotonic() - self._recording_started_at
        self.is_recording = False
        if self.external_on_recording_stop:
            self.external_on_recording_stop()

    def start_recording(self):
        """Starts the audio recording process."""
        if self.is_recording:
            logging.warning("Recording is already in progress.")
            return

        if not self.recorder:
            logging.error("Recorder is not initialized. Cannot start recording.")
            return

        suppress_ctx = getattr(PLATFORM_MANAGER, "suppress_audio_warnings", None)
        context_manager: contextlib.AbstractContextManager[Any]
        context_manager = suppress_ctx() if suppress_ctx else contextlib.nullcontext()
        with context_manager:
            self.recorder.start()

    def stop_recording(self):
        """Stops the audio recording process without transcribing."""
        if not self.is_recording:
            logging.warning("No active recording to stop.")
            return

        if not self.recorder:
            logging.error("Recorder is not initialized. Cannot stop recording.")
            return

        self.recorder.stop()

    def feed_audio(self, chunk: bytes):
        """Feeds an audio chunk to the underlying recorder."""
        if self.recorder and self.is_running:
            self.recorder.feed_audio(chunk)

    def start_chunked_transcription(self, on_sentence_transcribed: Callable[[str], None]):
        """Starts a background thread for continuous, chunked transcription."""

        def transcription_loop():
            while self.is_running:
                if self.recorder:
                    try:
                        self.recorder.text(on_sentence_transcribed)
                    except Exception as e:
                        logging.error(
                            f"Error in preview transcription loop: {e}", exc_info=True
                        )
                        # Avoid a fast-spinning error loop
                        time.sleep(1)

        thread = threading.Thread(target=transcription_loop, daemon=True)
        thread.start()

    def stop_and_transcribe(self) -> tuple[str, dict]:
        """Stops recording, processes the audio, and returns the transcription."""
        if not self.is_recording or not self.recorder:
            logging.warning("No active recording to stop.")
            return "", {}

        # This call is now primarily for the main_transcriber instance
        self.stop_recording()
        self.recorder.wait_audio()
        audio_data = self.recorder.audio

        transcription = ""
        transcription_start_time = time.monotonic()

        try:
            transcription = self.recorder.perform_final_transcription(audio_data)
        except Exception as e:
            logging.error("Error during final transcription: %s", e, exc_info=True)

        self._last_transcription_duration = time.monotonic() - transcription_start_time

        self.last_transcription = str(transcription) if transcription else ""

        if self.last_transcription:
            self._safe_clipboard_copy(self.last_transcription)

        audio_duration = self._recording_started_at and (
            time.monotonic() - self._recording_started_at
        )
        metrics = self._get_transcription_metrics(
            audio_duration or 0, self._last_transcription_duration
        )

        return self.last_transcription, metrics

    def clean_up(self):
        """Shuts down the recorder and releases resources."""
        self.is_running = False
        if self.recorder:
            self.recorder.shutdown()
            self.recorder = None
            logging.info("LongFormRecorder cleaned up.")

    def _safe_clipboard_copy(self, text: str) -> bool:
        """Safely copy text to clipboard with error handling."""
        try:
            pyperclip.copy(text)
            if pyperclip.paste() == text:
                logging.info("Transcription successfully copied to clipboard.")
                return True
            logging.warning("Clipboard copy verification failed.")
        except Exception as e:
            logging.error("Failed to copy to clipboard: %s", e)
        return False

    def _format_duration(self, seconds: float) -> str:
        """Format seconds as a human-friendly string."""
        if seconds <= 0:
            return "0.00s"
        minutes, secs = divmod(seconds, 60.0)
        if minutes >= 1:
            return f"{int(minutes)}m {secs:04.1f}s"
        return f"{secs:.2f}s"

    def _get_transcription_metrics(
        self, audio_duration: float, processing_time: float
    ) -> dict:
        """Logs metrics about the last transcription cycle."""
        if processing_time > 0:
            speed_ratio = audio_duration / processing_time
        else:
            speed_ratio = float("inf")

        metrics_msg = (
            "Transcription Metrics | "
            f"Audio: {self._format_duration(audio_duration)} | "
            f"Processing: {self._format_duration(processing_time)} | "
            f"Speed Ratio: {speed_ratio:.2f}x"
        )
        logging.info(metrics_msg)
        return {
            "audio_duration": audio_duration,
            "processing_time": processing_time,
        }
