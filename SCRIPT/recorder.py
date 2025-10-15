#!/usr/bin/env python3
"""
Core long-form recording and transcription module.

This module contains the LongFormRecorder class, which wraps the RealtimeSTT
library to handle audio capture, voice activity detection, and final
transcription processing. It is decoupled from any UI/display logic.
"""

import contextlib
import logging
import time
from typing import Any, Callable, Iterable, List, Optional, Union, TYPE_CHECKING

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
        # General Parameters
        model: str = "Systran/faster-whisper-large-v3",
        language: str = "en",
        compute_type: str = "default",
        device: str = "cuda",
        input_device_index: Optional[int] = None,
        gpu_device_index: Union[int, List[int]] = 0,
        batch_size: int = 16,
        # Voice Activation Parameters
        silero_sensitivity: float = 0.4,
        silero_use_onnx: bool = False,
        silero_deactivity_detection: bool = False,
        webrtc_sensitivity: int = 3,
        post_speech_silence_duration: float = 0.6,
        min_length_of_recording: float = 0.5,
        min_gap_between_recordings: float = 0.0,
        pre_recording_buffer_duration: float = 1.0,
        # Advanced Parameters
        beam_size: int = 5,
        initial_prompt: Optional[Union[str, Iterable[int]]] = None,
        faster_whisper_vad_filter: bool = True,
        ensure_sentence_starting_uppercase: bool = True,
        ensure_sentence_ends_with_period: bool = True,
        allowed_latency_limit: int = 100,
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

        self.is_recording = False
        self._recording_started_at: Optional[float] = None
        self._last_recording_duration = 0.0
        self._last_transcription_duration = 0.0
        self.last_transcription = ""

        # Store external callbacks
        self.external_on_recording_start = on_recording_start
        self.external_on_recording_stop = on_recording_stop

        # Prepare configuration for the underlying AudioToTextRecorder
        self.recorder_config = {
            "model": model,
            "language": language,
            "compute_type": compute_type,
            "device": device,
            "input_device_index": input_device_index,
            "gpu_device_index": gpu_device_index,
            "batch_size": batch_size,
            "silero_sensitivity": silero_sensitivity,
            "silero_use_onnx": silero_use_onnx,
            "silero_deactivity_detection": silero_deactivity_detection,
            "webrtc_sensitivity": webrtc_sensitivity,
            "post_speech_silence_duration": post_speech_silence_duration,
            "min_length_of_recording": min_length_of_recording,
            "min_gap_between_recordings": min_gap_between_recordings,
            "pre_recording_buffer_duration": pre_recording_buffer_duration,
            "beam_size": beam_size,
            "initial_prompt": initial_prompt,
            "faster_whisper_vad_filter": faster_whisper_vad_filter,
            "ensure_sentence_starting_uppercase": ensure_sentence_starting_uppercase,
            "ensure_sentence_ends_with_period": ensure_sentence_ends_with_period,
            "allowed_latency_limit": allowed_latency_limit,
            "on_recording_start": self._internal_on_start,
            "on_recording_stop": self._internal_on_stop,
            "on_recorded_chunk": on_recorded_chunk,
            "use_microphone": True,  # This class always uses the microphone
            "spinner": False,
        }

        self.recorder: Optional[AudioToTextRecorderType] = self._initialize_recorder()
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
                return AudioToTextRecorder(**self.recorder_config)
        except Exception as e:
            logging.error("Failed to initialize AudioToTextRecorder: %s", e)
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

    def stop_and_transcribe(self) -> tuple[str, dict]:
        """Stops recording, processes the audio, and returns the transcription."""
        if not self.is_recording or not self.recorder:
            logging.warning("No active recording to stop.")
            return "", {}

        logging.info("Stopping recording and starting transcription...")
        self.recorder.stop()
        self.recorder.wait_audio()  # Ensure audio buffer is fully processed
        audio_data = self.recorder.audio

        transcription = ""
        transcription_start_time = time.monotonic()

        try:
            transcription = self.recorder.perform_final_transcription(audio_data)
        except Exception as e:
            logging.error("Error during final transcription: %s", e)

        self._last_transcription_duration = time.monotonic() - transcription_start_time

        self.last_transcription = str(transcription) if transcription else ""

        if self.last_transcription:
            self._safe_clipboard_copy(self.last_transcription)

        metrics = self._get_transcription_metrics()

        return self.last_transcription, metrics

    def clean_up(self):
        """Shuts down the recorder and releases resources."""
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
            return False
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

    def _get_transcription_metrics(self) -> dict:
        """Logs metrics about the last transcription cycle."""
        audio_duration = self._last_recording_duration
        processing_time = self._last_transcription_duration

        if processing_time > 0:
            speed_ratio = audio_duration / processing_time
        else:
            speed_ratio = float("inf")

        if audio_duration > 0:
            realtime_factor = processing_time / audio_duration
        else:
            realtime_factor = float("inf")

        metrics_msg = (
            "Transcription Metrics | "
            f"Audio: {self._format_duration(audio_duration)} | "
            f"Processing: {self._format_duration(processing_time)} | "
            f"Speed Ratio: {speed_ratio:.2f}x | "
            f"RT Factor: {realtime_factor:.2f}"
        )
        logging.info(metrics_msg)
        return {
            "audio_duration": audio_duration,
            "processing_time": processing_time,
        }
