#!/usr/bin/env python3
"""
Core recording and transcription module for TranscriptionSuite.

Wraps the RealtimeSTT library to handle audio capture, VAD, and transcription.
Can be configured to either actively use the microphone or passively receive
audio via a feed method.
"""

import contextlib
import time
import logging
import threading
from typing import Any, Callable, Optional, TYPE_CHECKING

import pyperclip
from platform_utils import ensure_platform_init

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

PLATFORM_MANAGER = ensure_platform_init()


class LongFormRecorder:
    """Manages an instance of a transcription process."""

    def __init__(
        self,
        config: dict,
        on_recording_start: Optional[Callable] = None,
        on_recording_stop: Optional[Callable] = None,
        on_recorded_chunk: Optional[Callable[[bytes], None]] = None,
    ):
        if not HAS_REALTIME_STT or AudioToTextRecorder is None:
            raise ImportError("RealtimeSTT library is not available.")

        self.is_running = True
        self.is_recording = False
        self._recording_started_at: Optional[float] = None
        self.last_transcription = ""

        self.recorder_config = config.copy()
        self.recorder_config["spinner"] = False
        self.recorder_config["on_recording_start"] = self._internal_on_start
        self.recorder_config["on_recording_stop"] = self._internal_on_stop
        if on_recorded_chunk:
            self.recorder_config["on_recorded_chunk"] = on_recorded_chunk

        self.external_on_recording_start = on_recording_start
        self.external_on_recording_stop = on_recording_stop

        self.recorder: Optional[AudioToTextRecorderType] = self._initialize_recorder()

        if self.recorder:
            stt_logger = logging.getLogger("realtimestt")
            stt_logger.propagate = True
        logging.info("LongFormRecorder instance initialized.")

    def _initialize_recorder(self) -> Optional[AudioToTextRecorderType]:
        suppress_ctx = getattr(PLATFORM_MANAGER, "suppress_audio_warnings", None)
        context_manager = suppress_ctx() if suppress_ctx else contextlib.nullcontext()
        try:
            with context_manager:
                if AudioToTextRecorder is None:
                    raise RuntimeError("RealtimeSTT is unavailable at runtime.")

                # Remove keys not understood by the underlying library
                library_config = self.recorder_config.copy()
                library_config.pop("use_default_input", None)

                return AudioToTextRecorder(**library_config)
        except Exception as e:
            logging.error(
                "Failed to initialize AudioToTextRecorder: %s", e, exc_info=True
            )
            return None

    def _internal_on_start(self, *args):
        self.is_recording = True
        self._recording_started_at = time.monotonic()
        if self.external_on_recording_start:
            # Pass the start time if the callback needs it
            self.external_on_recording_start(self._recording_started_at)

    def _internal_on_stop(self, *args):
        self.is_recording = False
        if self.external_on_recording_stop:
            self.external_on_recording_stop()

    def start_recording(self):
        if self.is_recording:
            return
        if self.recorder:
            self.recorder.start()

    def stop_recording(self):
        if not self.is_recording:
            return
        if self.recorder:
            self.recorder.stop()

    def feed_audio(self, chunk: bytes):
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
                        logging.error(f"Error in transcription loop: {e}", exc_info=True)
                        time.sleep(1)

        thread = threading.Thread(target=transcription_loop, daemon=True)
        thread.start()

    def stop_and_transcribe(self) -> tuple[str, dict]:
        """Stops recording, processes audio, and returns transcription."""
        if not self.recorder:
            return "", {}

        # This call is now primarily for the main_transcriber instance
        self.stop_recording()
        self.recorder.wait_audio()
        audio_data = self.recorder.audio

        start_time = time.monotonic()
        try:
            transcription = self.recorder.perform_final_transcription(audio_data)
        except Exception as e:
            logging.error("Error during final transcription: %s", e, exc_info=True)
            transcription = ""

        processing_time = time.monotonic() - start_time
        self.last_transcription = str(transcription) if transcription else ""

        if self.last_transcription:
            self._safe_clipboard_copy(self.last_transcription)

        audio_duration = self._recording_started_at and (
            time.monotonic() - self._recording_started_at
        )
        metrics = {
            "audio_duration": audio_duration or 0,
            "processing_time": processing_time,
        }
        return self.last_transcription, metrics

    def clean_up(self):
        self.is_running = False
        if self.recorder:
            self.recorder.shutdown()
            self.recorder = None
            logging.info("LongFormRecorder instance cleaned up.")

    def _safe_clipboard_copy(self, text: str):
        try:
            pyperclip.copy(text)
            logging.info("Transcription copied to clipboard.")
        except Exception as e:
            logging.error("Failed to copy to clipboard: %s", e)
