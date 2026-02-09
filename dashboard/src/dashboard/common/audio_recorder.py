"""
Cross-platform audio recording for TranscriptionSuite client.

Handles recording from:
- Microphone input (PyAudio)
- System audio loopback (soundcard)
- Configurable sample rate and device/source selection
- WAV output for server transcription
"""

import io
import logging
import threading
import wave
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

logger = logging.getLogger(__name__)

# Audio constants
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024
SAMPLE_WIDTH = 2  # 16-bit audio

# Try to import PyAudio
HAS_PYAUDIO = False
if TYPE_CHECKING:
    import pyaudio
else:
    try:
        import pyaudio

        HAS_PYAUDIO = True
    except ImportError:
        pyaudio = None

# Try to import soundcard (system audio loopback)
HAS_SOUNDCARD = False
if TYPE_CHECKING:
    import soundcard
else:
    try:
        import soundcard

        HAS_SOUNDCARD = True
    except ImportError:
        soundcard = None


class AudioRecorder:
    """
    Cross-platform audio recorder for microphone and system-audio sources.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        device_index: int | None = None,
        source_type: Literal["microphone", "system_audio"] = "microphone",
        system_output_id: str | None = None,
        on_audio_chunk: Callable[[bytes], None] | None = None,
    ):
        """
        Initialize the audio recorder.

        Args:
            sample_rate: Audio sample rate (default 16000 for Whisper)
            channels: Number of audio channels (default 1 for mono)
            chunk_size: Size of audio chunks
            device_index: Input device index (None for default)
            source_type: Audio source ("microphone" or "system_audio")
            system_output_id: System output device id (None for default output)
            on_audio_chunk: Callback for audio data
        """
        if source_type not in {"microphone", "system_audio"}:
            raise ValueError(f"Invalid source_type: {source_type}")

        if source_type == "microphone" and not HAS_PYAUDIO:
            raise ImportError("PyAudio is required for microphone recording")
        if source_type == "system_audio" and not HAS_SOUNDCARD:
            raise ImportError("soundcard is required for system audio recording")

        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device_index = device_index
        self.source_type = source_type
        self.system_output_id = system_output_id
        self.on_audio_chunk = on_audio_chunk

        self._audio: Any = None
        self._stream: Any = None
        self._system_recorder: Any = None
        self._system_recorder_ctx: Any = None
        self._recording = False
        self._thread: threading.Thread | None = None
        self._frames: list[bytes] = []
        self._actual_sample_rate: int = sample_rate
        self._actual_channels: int = channels
        self._needs_resampling: bool = False
        self._needs_channel_conversion: bool = False

    def _get_device_index(self) -> int | None:
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

    def _iter_loopback_microphones(self) -> list[Any]:
        """Return all loopback-capable microphones from soundcard."""
        if not HAS_SOUNDCARD:
            return []

        try:
            microphones = soundcard.all_microphones(include_loopback=True)
        except TypeError:
            # Older soundcard variants may not support include_loopback kwarg.
            microphones = soundcard.all_microphones()
        except Exception:
            return []

        loopbacks: list[Any] = []
        for mic in microphones:
            is_loopback = bool(getattr(mic, "isloopback", False))
            if is_loopback:
                loopbacks.append(mic)
        return loopbacks

    def _get_loopback_microphone(self) -> Any:
        """
        Resolve a loopback microphone for system audio capture.

        The soundcard API records loopback from microphone-style devices,
        not directly from speaker objects.
        """
        if not HAS_SOUNDCARD:
            raise RuntimeError("soundcard dependency is not available")

        loopbacks = self._iter_loopback_microphones()
        if not loopbacks:
            raise RuntimeError("No loopback capture devices available")

        if self.system_output_id:
            target_id = str(self.system_output_id)

            # First try direct lookup by selected output id.
            try:
                mic = soundcard.get_microphone(target_id, include_loopback=True)
                if mic is not None:
                    return mic
            except Exception:
                pass

            # Fallback: match by loopback microphone id/name.
            for mic in loopbacks:
                mic_id = str(getattr(mic, "id", ""))
                mic_name = str(getattr(mic, "name", ""))
                if target_id in {mic_id, mic_name}:
                    return mic

            # Additional fallback: map selected speaker id -> similarly named loopback mic.
            try:
                for speaker in soundcard.all_speakers():
                    speaker_id = str(getattr(speaker, "id", ""))
                    if speaker_id != target_id:
                        continue
                    speaker_name = str(getattr(speaker, "name", ""))
                    if not speaker_name:
                        break
                    for mic in loopbacks:
                        mic_name = str(getattr(mic, "name", ""))
                        if speaker_name in mic_name:
                            return mic
                    break
            except Exception:
                pass

            raise RuntimeError(
                f"Configured system audio device not found: {self.system_output_id}"
            )

        # Prefer loopback for the current default speaker when available.
        default_speaker = None
        try:
            default_speaker = soundcard.default_speaker()
        except Exception:
            default_speaker = None

        if default_speaker is not None:
            speaker_id = str(getattr(default_speaker, "id", ""))
            if speaker_id:
                try:
                    mic = soundcard.get_microphone(speaker_id, include_loopback=True)
                    if mic is not None:
                        return mic
                except Exception:
                    pass

            speaker_name = str(getattr(default_speaker, "name", ""))
            if speaker_name:
                for mic in loopbacks:
                    mic_name = str(getattr(mic, "name", ""))
                    if speaker_name in mic_name:
                        return mic

        # Final fallback: first available loopback device.
        return loopbacks[0]

    def _get_supported_channels(
        self, device_index: int | None, sample_rate: int
    ) -> int:
        """
        Get a supported channel count for the device.

        Tries mono first (preferred for Whisper), falls back to stereo.

        Args:
            device_index: Device index to check
            sample_rate: Sample rate to test with

        Returns:
            A supported channel count (1 or 2)
        """
        if self._audio is None:
            return self.channels

        # Try mono first (preferred)
        try:
            if self._audio.is_format_supported(
                sample_rate,
                input_device=device_index,
                input_channels=1,
                input_format=pyaudio.paInt16,
            ):
                return 1
        except Exception:
            logger.debug("Mono not supported, trying stereo")

        # Try stereo
        try:
            if self._audio.is_format_supported(
                sample_rate,
                input_device=device_index,
                input_channels=2,
                input_format=pyaudio.paInt16,
            ):
                logger.info("Using stereo recording (will convert to mono)")
                return 2
        except Exception:
            logger.debug("Stereo validation failed")

        # Last resort: return requested channels
        return self.channels

    def _get_supported_sample_rate(
        self, device_index: int | None, channels: int
    ) -> int:
        """
        Get a supported sample rate for the device.

        Tries to use the requested sample rate, falls back to device default,
        then tries common rates.

        Args:
            device_index: Device index to check
            channels: Number of channels to test with

        Returns:
            A supported sample rate
        """
        if self._audio is None:
            return self.sample_rate

        # Try the requested sample rate first
        try:
            if self._audio.is_format_supported(
                self.sample_rate,
                input_device=device_index,
                input_channels=channels,
                input_format=pyaudio.paInt16,
            ):
                return self.sample_rate
        except Exception:
            logger.debug(
                f"Failed to validate sample rate {self.sample_rate} for device"
            )

        # Get device's default sample rate
        try:
            if device_index is not None:
                device_info = self._audio.get_device_info_by_index(device_index)
            else:
                device_info = self._audio.get_default_input_device_info()

            default_rate = int(device_info.get("defaultSampleRate", 44100))
            logger.info(f"Device default sample rate: {default_rate} Hz")

            # Try the device's default rate
            try:
                if self._audio.is_format_supported(
                    default_rate,
                    input_device=device_index,
                    input_channels=channels,
                    input_format=pyaudio.paInt16,
                ):
                    logger.info(f"Using device default sample rate: {default_rate} Hz")
                    return default_rate
            except Exception:
                logger.debug("Failed to validate device default sample rate")
        except Exception as e:
            logger.warning(f"Could not get device info: {e}")

        # Try common sample rates
        common_rates = [48000, 44100, 32000, 24000, 22050, 16000, 8000]
        for rate in common_rates:
            try:
                if self._audio.is_format_supported(
                    rate,
                    input_device=device_index,
                    input_channels=channels,
                    input_format=pyaudio.paInt16,
                ):
                    logger.info(f"Using fallback sample rate: {rate} Hz")
                    return rate
            except Exception:
                continue

        # Last resort: return requested rate and hope for the best
        logger.warning(
            f"Could not find supported sample rate, using {self.sample_rate} Hz"
        )
        return self.sample_rate

    def start(self) -> bool:
        """Start recording audio."""
        if self._recording:
            logger.warning("Already recording")
            return False

        if self.source_type == "system_audio":
            return self._start_system_audio_recording()
        return self._start_microphone_recording()

    def _start_microphone_recording(self) -> bool:
        """Start microphone recording via PyAudio."""
        if not HAS_PYAUDIO:
            logger.error("PyAudio is not available")
            return False

        try:
            self._audio = pyaudio.PyAudio()
            device_index = self._get_device_index()

            # First, find supported channels (try mono, fallback to stereo)
            # Use device default sample rate for initial channel detection
            try:
                if device_index is not None:
                    device_info = self._audio.get_device_info_by_index(device_index)
                else:
                    device_info = self._audio.get_default_input_device_info()
                test_rate = int(device_info.get("defaultSampleRate", 44100))
            except Exception:
                test_rate = 44100

            actual_channels = self._get_supported_channels(device_index, test_rate)

            # Now get supported sample rate using the actual channels
            actual_rate = self._get_supported_sample_rate(device_index, actual_channels)

            # Store actual recording parameters for conversion later
            self._actual_sample_rate = actual_rate
            self._actual_channels = actual_channels
            self._needs_resampling = actual_rate != self.sample_rate
            self._needs_channel_conversion = actual_channels != self.channels

            if self._needs_resampling:
                logger.info(
                    f"Will resample from {actual_rate} Hz to {self.sample_rate} Hz after recording"
                )
            if self._needs_channel_conversion:
                logger.info(
                    f"Will convert from {actual_channels} channels to {self.channels} channel(s) after recording"
                )

            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=actual_channels,
                rate=actual_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                input_device_index=device_index,
            )

            self._recording = True
            self._frames = []

            # Start recording thread
            self._thread = threading.Thread(target=self._record_microphone_loop)
            self._thread.daemon = True
            self._thread.start()

            logger.info(f"Recording started at {actual_rate} Hz")
            return True

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self._cleanup()
            return False

    def _start_system_audio_recording(self) -> bool:
        """Start system audio loopback recording via soundcard."""
        if not HAS_SOUNDCARD:
            logger.error("soundcard is not available")
            return False

        try:
            loopback_mic = self._get_loopback_microphone()
            recorder_ctx = None
            for channels in (2, 1):
                try:
                    recorder_ctx = loopback_mic.recorder(
                        samplerate=self.sample_rate,
                        channels=channels,
                        blocksize=self.chunk_size,
                    )
                    break
                except Exception:
                    recorder_ctx = None
            if recorder_ctx is None:
                raise RuntimeError("No supported loopback recorder format found")

            self._system_recorder_ctx = recorder_ctx
            self._system_recorder = self._system_recorder_ctx.__enter__()
            self._recording = True
            self._frames = []
            self._actual_sample_rate = self.sample_rate
            self._actual_channels = 1
            self._needs_resampling = False
            self._needs_channel_conversion = False

            # Start recording thread
            self._thread = threading.Thread(target=self._record_system_audio_loop)
            self._thread.daemon = True
            self._thread.start()

            logger.info(
                "System audio recording started from %s",
                getattr(loopback_mic, "name", "default loopback device"),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to start system audio recording: {e}")
            self._cleanup()
            return False

    def _record_microphone_loop(self) -> None:
        """Microphone recording loop that runs in a separate thread."""
        while self._recording and self._stream:
            try:
                data = self._stream.read(self.chunk_size, exception_on_overflow=False)
                self._frames.append(data)

                if self.on_audio_chunk:
                    self.on_audio_chunk(data)

            except Exception as e:
                logger.error(f"Recording error: {e}")
                break

    def _record_system_audio_loop(self) -> None:
        """System audio recording loop that runs in a separate thread."""
        while self._recording and self._system_recorder is not None:
            try:
                frame = self._system_recorder.record(numframes=self.chunk_size)
                if frame is None:
                    continue

                audio_array = np.asarray(frame, dtype=np.float32)
                if audio_array.size == 0:
                    continue

                if audio_array.ndim == 2:
                    mono = audio_array.mean(axis=1)
                else:
                    mono = audio_array

                mono = np.clip(mono, -1.0, 1.0)
                data = (mono * 32767.0).astype(np.int16).tobytes()
                self._frames.append(data)

                if self.on_audio_chunk:
                    self.on_audio_chunk(data)

            except Exception as e:
                logger.error(f"System audio recording error: {e}")
                break

    def stop(self) -> bytes:
        """
        Stop recording and return the recorded audio as WAV bytes.

        Returns:
            WAV file content as bytes (16kHz, mono, 16-bit)
        """
        self._recording = False

        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

        frames = self._frames.copy()
        self._frames = []

        self._cleanup()

        if not frames:
            logger.warning("No audio recorded")
            return self._create_empty_wav()

        # Combine all frames
        audio_data = b"".join(frames)

        # Convert stereo to mono if needed (before resampling for efficiency)
        if self._needs_channel_conversion and self._actual_channels == 2:
            audio_data = self._stereo_to_mono(audio_data)

        # Resample if needed
        if self._needs_resampling:
            audio_data = self._resample_audio(
                audio_data, self._actual_sample_rate, self.sample_rate
            )

        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_data)

        wav_bytes = wav_buffer.getvalue()
        duration = len(audio_data) / (self.sample_rate * SAMPLE_WIDTH * self.channels)
        logger.info(f"Recording stopped: {duration:.1f}s")

        return wav_bytes

    def _resample_audio(self, audio_data: bytes, from_rate: int, to_rate: int) -> bytes:
        """
        Resample audio data from one sample rate to another.

        Args:
            audio_data: Raw audio bytes (int16, mono)
            from_rate: Source sample rate
            to_rate: Target sample rate

        Returns:
            Resampled audio bytes (int16)
        """
        # Convert bytes to numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        # Calculate the resampling ratio
        ratio = to_rate / from_rate

        # Calculate new length
        new_length = int(len(audio_array) * ratio)

        # Create indices for interpolation
        old_indices = np.arange(len(audio_array))
        new_indices = np.linspace(0, len(audio_array) - 1, new_length)

        # Perform linear interpolation
        resampled = np.interp(new_indices, old_indices, audio_array)

        # Convert back to int16
        resampled_int16 = resampled.astype(np.int16)

        logger.info(f"Resampled audio from {from_rate} Hz to {to_rate} Hz")

        return resampled_int16.tobytes()

    def _stereo_to_mono(self, audio_data: bytes) -> bytes:
        """
        Convert stereo audio to mono by averaging the channels.

        Args:
            audio_data: Raw stereo audio bytes (int16, interleaved L/R)

        Returns:
            Mono audio bytes (int16)
        """
        # Convert bytes to numpy array (stereo interleaved)
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        # Reshape to (samples, 2) for stereo
        stereo = audio_array.reshape(-1, 2)

        # Average the two channels (use int32 to avoid overflow)
        mono = (stereo[:, 0].astype(np.int32) + stereo[:, 1].astype(np.int32)) // 2

        # Convert back to int16
        mono_int16 = mono.astype(np.int16)

        logger.info(f"Converted stereo to mono ({len(stereo)} samples)")

        return mono_int16.tobytes()

    def _create_empty_wav(self) -> bytes:
        """Create an empty WAV file."""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b"")
        return wav_buffer.getvalue()

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
                logger.debug("Failed to stop/close audio stream during cleanup")
            self._stream = None

        if self._audio:
            try:
                self._audio.terminate()
            except Exception:
                logger.debug("Failed to terminate PyAudio during cleanup")
            self._audio = None

        if self._system_recorder_ctx is not None:
            try:
                self._system_recorder_ctx.__exit__(None, None, None)
            except Exception:
                logger.debug("Failed to close system audio recorder during cleanup")
            self._system_recorder_ctx = None
            self._system_recorder = None

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
    def list_input_devices() -> list[dict[str, Any]]:
        """List available microphone input devices."""
        if not HAS_PYAUDIO:
            return []

        devices: list[dict[str, Any]] = []
        try:
            audio = pyaudio.PyAudio()
            for i in range(audio.get_device_count()):
                try:
                    info = audio.get_device_info_by_index(i)
                    max_input_channels = int(info.get("maxInputChannels", 0))
                    if max_input_channels > 0:
                        devices.append(
                            {
                                "index": i,
                                "name": info.get("name", f"Device {i}"),
                                "channels": max_input_channels,
                                "sample_rate": info.get("defaultSampleRate"),
                            }
                        )
                except Exception:
                    continue
            audio.terminate()
        except Exception as e:
            logger.error(f"Error listing input devices: {e}")

        return devices

    @staticmethod
    def list_output_devices() -> list[dict[str, Any]]:
        """List available system output devices for loopback capture."""
        if not HAS_SOUNDCARD:
            return []

        devices: list[dict[str, Any]] = []
        try:
            for speaker in soundcard.all_speakers():
                speaker_id = str(getattr(speaker, "id", ""))
                speaker_name = str(getattr(speaker, "name", "Output device"))
                if not speaker_id:
                    continue
                try:
                    loopback = soundcard.get_microphone(
                        speaker_id, include_loopback=True
                    )
                except Exception:
                    loopback = None
                if loopback is None:
                    continue
                devices.append({"id": speaker_id, "name": speaker_name})

            # Fallback for environments where speaker->loopback mapping is unavailable.
            if not devices:
                try:
                    microphones = soundcard.all_microphones(include_loopback=True)
                except TypeError:
                    microphones = soundcard.all_microphones()
                for mic in microphones:
                    if not bool(getattr(mic, "isloopback", False)):
                        continue
                    mic_name = str(getattr(mic, "name", "Loopback device"))
                    mic_id = str(getattr(mic, "id", mic_name))
                    devices.append({"id": mic_id, "name": mic_name})
        except Exception as e:
            logger.error(f"Error listing output devices: {e}")

        return devices

    @staticmethod
    def list_devices() -> list[dict[str, Any]]:
        """Backward-compatible alias for microphone input devices."""
        return AudioRecorder.list_input_devices()
