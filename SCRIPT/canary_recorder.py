#!/usr/bin/env python3
"""
Simple audio recorder for Canary transcription mode.

This module provides a lightweight audio recorder that captures microphone
input without requiring any transcription model to be loaded. The audio
is saved to a temporary file which is then sent to the Canary server
for transcription.

This is used when Canary mode is active, as the regular LongFormRecorder
requires faster-whisper models which would conflict with Canary's VRAM usage.
"""

import logging
import os
import queue
import tempfile
import threading
import time
from typing import Any, Callable, Optional

import numpy as np
import pyperclip
import sounddevice as sd
import soundfile as sf

from platform_utils import ensure_platform_init

logger = logging.getLogger(__name__)

# Initialize platform-specific settings
PLATFORM_MANAGER = ensure_platform_init()


class CanaryRecorder:
    """
    Simple audio recorder for use with Canary transcription.

    Records audio from the microphone and saves it to a temporary WAV file
    for Canary to transcribe. Does not load any ML models.
    """

    SAMPLE_RATE = 16000  # Canary expects 16kHz audio
    CHANNELS = 1  # Mono audio
    DTYPE = np.float32

    def __init__(
        self,
        config: dict[str, Any],
        on_recording_start: Optional[Callable[[float], None]] = None,
        on_recording_stop: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the Canary recorder.

        Args:
            config: Audio configuration dict with keys like:
                   - input_device_index: Microphone device index
                   - use_default_input: Whether to use default mic
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops
        """
        self.config = config
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop

        # Recording state
        self.is_recording = False
        self._recording_started_at: Optional[float] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._audio_data: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._last_audio_data: Optional[np.ndarray] = None
        self._last_recording_duration: float = 0.0

        # Get input device
        self._input_device = self._get_input_device()

        logger.info("CanaryRecorder initialized")

    def _get_input_device(self) -> Optional[int]:
        """Determine which input device to use."""
        if self.config.get("use_default_input", True):
            return None  # Use system default
        return self.config.get("input_device_index")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """Callback for audio stream - called for each audio chunk."""
        if status:
            logger.warning(f"Audio callback status: {status}")
        if self.is_recording:
            # Make a copy since indata buffer is reused
            self._audio_queue.put(indata.copy())

    def start_recording(self) -> bool:
        """
        Start recording audio from the microphone.

        Returns:
            True if recording started successfully
        """
        if self.is_recording:
            logger.warning("Already recording")
            return False

        try:
            # Clear any previous data
            self._audio_data = []
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

            # Start the audio stream
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                device=self._input_device,
                callback=self._audio_callback,
                blocksize=1024,
            )
            self._stream.start()

            self.is_recording = True
            self._recording_started_at = time.monotonic()

            # Start background thread to collect audio chunks
            self._collector_thread = threading.Thread(
                target=self._collect_audio,
                daemon=True,
            )
            self._collector_thread.start()

            if self.on_recording_start:
                self.on_recording_start(self._recording_started_at)

            logger.info("CanaryRecorder: Recording started")
            return True

        except Exception as e:
            logger.error(f"Failed to start recording: {e}", exc_info=True)
            self.is_recording = False
            return False

    def _collect_audio(self) -> None:
        """Background thread to collect audio chunks from the queue."""
        while self.is_recording:
            try:
                chunk = self._audio_queue.get(timeout=0.1)
                self._audio_data.append(chunk)
            except queue.Empty:
                continue

    def stop_recording(self) -> Optional[np.ndarray]:
        """
        Stop recording and return the captured audio.

        Returns:
            NumPy array of audio samples (float32, 16kHz), or None on error
        """
        if not self.is_recording:
            logger.warning("Not currently recording")
            return None

        self.is_recording = False

        # Calculate duration
        if self._recording_started_at:
            self._last_recording_duration = time.monotonic() - self._recording_started_at

        # Stop the stream
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"Error stopping audio stream: {e}")
            self._stream = None

        # Wait for collector thread to finish
        if hasattr(self, "_collector_thread"):
            self._collector_thread.join(timeout=1.0)

        # Collect any remaining audio from queue
        while not self._audio_queue.empty():
            try:
                chunk = self._audio_queue.get_nowait()
                self._audio_data.append(chunk)
            except queue.Empty:
                break

        if self.on_recording_stop:
            self.on_recording_stop()

        # Concatenate all audio chunks
        if self._audio_data:
            audio = np.concatenate(self._audio_data, axis=0)
            # Flatten to 1D if needed
            if audio.ndim > 1:
                audio = audio.flatten()
            self._last_audio_data = audio
            logger.info(
                f"CanaryRecorder: Recording stopped. "
                f"Duration: {self._last_recording_duration:.1f}s, "
                f"Samples: {len(audio)}"
            )
            return audio
        else:
            logger.warning("No audio data captured")
            self._last_audio_data = None
            return None

    def save_to_temp_file(self, audio_data: Optional[np.ndarray] = None) -> Optional[str]:
        """
        Save audio data to a temporary WAV file.

        Args:
            audio_data: Audio to save, or None to use last recording

        Returns:
            Path to the temporary WAV file, or None on error
        """
        if audio_data is None:
            audio_data = self._last_audio_data

        if audio_data is None or len(audio_data) == 0:
            logger.error("No audio data to save")
            return None

        try:
            # Create temp file
            fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="canary_recording_")
            os.close(fd)

            # Save as WAV
            sf.write(temp_path, audio_data, self.SAMPLE_RATE)

            logger.info(f"Saved audio to: {temp_path}")
            return temp_path

        except Exception as e:
            logger.error(f"Failed to save audio: {e}", exc_info=True)
            return None

    def get_last_audio_data(self) -> Optional[np.ndarray]:
        """Return the audio data from the last recording."""
        return self._last_audio_data

    def get_last_duration(self) -> float:
        """Return the duration of the last recording in seconds."""
        return self._last_recording_duration

    def clean_up(self) -> None:
        """Clean up resources."""
        if self.is_recording:
            self.stop_recording()
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        logger.info("CanaryRecorder cleaned up")

    @staticmethod
    def copy_to_clipboard(text: str) -> bool:
        """Copy text to clipboard."""
        try:
            pyperclip.copy(text)
            if pyperclip.paste() == text:
                logger.info("Text copied to clipboard")
                return True
        except Exception as e:
            logger.error(f"Clipboard copy failed: {e}")
        return False
