"""
Cross-platform audio recording using PyAudio.
"""

import io
import logging
import threading
import wave
from typing import Optional

import numpy as np

try:
    import pyaudio

    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    pyaudio = None  # type: ignore

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024
SAMPLE_WIDTH = 2  # 16-bit audio


class AudioRecorder:
    """
    Records audio from the default microphone.

    Thread-safe recording with start/stop controls.
    Returns audio data as WAV bytes or numpy array.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        device_index: Optional[int] = None,
    ):
        if not HAS_PYAUDIO:
            raise ImportError(
                "PyAudio is required for audio recording. "
                "Install with: pip install pyaudio"
            )

        self.sample_rate = sample_rate
        self.device_index = device_index
        self.audio: Optional[pyaudio.PyAudio] = None
        self.stream: Optional[pyaudio.Stream] = None
        self.recording = False
        self.frames: list[bytes] = []
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def start(self) -> None:
        """Start recording in a background thread."""
        if self.recording:
            logger.warning("Already recording")
            return

        self.audio = pyaudio.PyAudio()
        self.frames = []
        self.recording = True

        # Get format constant
        format_type = pyaudio.paInt16

        # Open stream
        stream_kwargs = {
            "format": format_type,
            "channels": CHANNELS,
            "rate": self.sample_rate,
            "input": True,
            "frames_per_buffer": CHUNK_SIZE,
        }

        if self.device_index is not None:
            stream_kwargs["input_device_index"] = self.device_index

        try:
            self.stream = self.audio.open(**stream_kwargs)
        except OSError as e:
            logger.error(f"Failed to open audio stream: {e}")
            self.recording = False
            self.audio.terminate()
            self.audio = None
            raise RuntimeError(f"Failed to open microphone: {e}")

        # Start recording thread
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()

        logger.info("Recording started")

    def _record_loop(self) -> None:
        """Recording loop running in background thread."""
        while self.recording and self.stream:
            try:
                data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)
                with self.lock:
                    self.frames.append(data)
            except Exception as e:
                logger.error(f"Recording error: {e}")
                break

    def stop(self) -> bytes:
        """
        Stop recording and return audio data as WAV bytes.

        Returns:
            WAV file content as bytes
        """
        self.recording = False

        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

        if self.audio:
            self.audio.terminate()
            self.audio = None

        # Get frames
        with self.lock:
            frames = self.frames.copy()
            self.frames = []

        if not frames:
            logger.warning("No audio recorded")
            return self._create_empty_wav()

        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b"".join(frames))

        wav_bytes = wav_buffer.getvalue()
        duration = len(b"".join(frames)) / (self.sample_rate * SAMPLE_WIDTH * CHANNELS)
        logger.info(f"Recording stopped: {duration:.1f}s")

        return wav_bytes

    def stop_as_numpy(self) -> np.ndarray:
        """
        Stop recording and return audio data as numpy array.

        Returns:
            NumPy array of audio samples (float32, mono, 16kHz)
        """
        self.recording = False

        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

        if self.audio:
            self.audio.terminate()
            self.audio = None

        # Get frames
        with self.lock:
            frames = self.frames.copy()
            self.frames = []

        if not frames:
            logger.warning("No audio recorded")
            return np.array([], dtype=np.float32)

        # Convert to numpy array
        audio_data = b"".join(frames)
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        audio_np /= 32768.0  # Normalize to [-1, 1]

        logger.info(f"Recording stopped: {len(audio_np) / self.sample_rate:.1f}s")
        return audio_np

    def _create_empty_wav(self) -> bytes:
        """Create an empty WAV file."""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b"")
        return wav_buffer.getvalue()

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self.recording

    def get_duration(self) -> float:
        """Get current recording duration in seconds."""
        with self.lock:
            total_bytes = sum(len(f) for f in self.frames)
        return total_bytes / (self.sample_rate * SAMPLE_WIDTH * CHANNELS)

    @staticmethod
    def list_devices() -> list[dict]:
        """List available audio input devices."""
        if not HAS_PYAUDIO:
            return []

        audio = pyaudio.PyAudio()
        devices = []

        try:
            for i in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    devices.append(
                        {
                            "index": i,
                            "name": info.get("name", "Unknown"),
                            "channels": info.get("maxInputChannels", 0),
                            "sample_rate": int(info.get("defaultSampleRate", 0)),
                        }
                    )
        finally:
            audio.terminate()

        return devices
