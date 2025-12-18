"""
Cross-platform audio recording for TranscriptionSuite client.

Handles microphone recording with:
- PyAudio for audio capture
- Configurable sample rate and device
- Callback-based audio streaming
"""

import logging
import threading
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Try to import PyAudio
try:
    import pyaudio

    HAS_PYAUDIO = True
except ImportError:
    pyaudio = None  # type: ignore
    HAS_PYAUDIO = False


class AudioRecorder:
    """
    Cross-platform audio recorder using PyAudio.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        device_index: Optional[int] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
    ):
        """
        Initialize the audio recorder.

        Args:
            sample_rate: Audio sample rate (default 16000 for Whisper)
            channels: Number of audio channels (default 1 for mono)
            chunk_size: Size of audio chunks
            device_index: Input device index (None for default)
            on_audio_chunk: Callback for audio data
        """
        if not HAS_PYAUDIO:
            raise ImportError("PyAudio is required for audio recording")

        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device_index = device_index
        self.on_audio_chunk = on_audio_chunk

        self._audio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._recording = False
        self._thread: Optional[threading.Thread] = None
        self._frames: list = []

    def _get_device_index(self) -> Optional[int]:
        """Get the audio device index to use."""
        if self.device_index is not None:
            return self.device_index

        if self._audio is None:
            return None

        try:
            default_info = self._audio.get_default_input_device_info()
            return int(default_info["index"])
        except Exception as e:
            logger.warning(f"Could not get default input device: {e}")
            return None

    def start(self) -> bool:
        """Start recording audio."""
        if self._recording:
            logger.warning("Already recording")
            return False

        try:
            self._audio = pyaudio.PyAudio()
            device_index = self._get_device_index()

            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                input_device_index=device_index,
            )

            self._recording = True
            self._frames = []

            # Start recording thread
            self._thread = threading.Thread(target=self._record_loop)
            self._thread.daemon = True
            self._thread.start()

            logger.info("Recording started")
            return True

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self._cleanup()
            return False

    def _record_loop(self) -> None:
        """Recording loop that runs in a separate thread."""
        while self._recording and self._stream:
            try:
                data = self._stream.read(self.chunk_size, exception_on_overflow=False)
                self._frames.append(data)

                if self.on_audio_chunk:
                    self.on_audio_chunk(data)

            except Exception as e:
                logger.error(f"Recording error: {e}")
                break

    def stop(self) -> bytes:
        """
        Stop recording and return the recorded audio.

        Returns:
            Raw audio bytes (int16, mono, sample_rate Hz)
        """
        self._recording = False

        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

        audio_data = b"".join(self._frames)
        self._frames = []

        self._cleanup()

        logger.info(f"Recording stopped: {len(audio_data)} bytes")
        return audio_data

    def cancel(self) -> None:
        """Cancel recording and discard audio."""
        self._recording = False
        self._frames = []

        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

        self._cleanup()
        logger.info("Recording cancelled")

    def _cleanup(self) -> None:
        """Clean up audio resources."""
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._audio:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    def get_audio_as_numpy(self, audio_bytes: bytes) -> np.ndarray:
        """
        Convert raw audio bytes to numpy array.

        Args:
            audio_bytes: Raw audio data (int16)

        Returns:
            Float32 numpy array normalized to [-1, 1]
        """
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        return audio_array.astype(np.float32) / 32768.0

    @staticmethod
    def list_devices() -> list:
        """List available audio input devices."""
        if not HAS_PYAUDIO:
            return []

        devices = []
        try:
            audio = pyaudio.PyAudio()
            for i in range(audio.get_device_count()):
                try:
                    info = audio.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        devices.append(
                            {
                                "index": i,
                                "name": info.get("name", f"Device {i}"),
                                "channels": info.get("maxInputChannels"),
                                "sample_rate": info.get("defaultSampleRate"),
                            }
                        )
                except Exception:
                    continue
            audio.terminate()
        except Exception as e:
            logger.error(f"Error listing devices: {e}")

        return devices
