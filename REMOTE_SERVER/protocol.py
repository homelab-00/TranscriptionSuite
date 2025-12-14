"""
Audio and control protocol handlers for the remote transcription server.

Defines the binary and JSON message formats for:
- Audio streaming (16kHz mono PCM or Opus-compressed)
- Control commands (start/stop, config, status)
- Transcription results (realtime/final)
"""

import json
import logging
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import numpy as np

logger = logging.getLogger(__name__)

# Audio format constants
SAMPLE_RATE = 16000  # Whisper's native sample rate
CHANNELS = 1  # Mono
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
CHUNK_DURATION_MS = 40  # 40ms chunks (640 samples at 16kHz)
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 640 samples
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH  # 1280 bytes


class MessageType(str, Enum):
    """Types of control messages."""

    # Client -> Server
    AUTH = "auth"  # Authentication request
    START = "start"  # Start transcription session
    STOP = "stop"  # Stop transcription session
    CONFIG = "config"  # Update configuration
    PING = "ping"  # Heartbeat ping

    # Server -> Client
    AUTH_OK = "auth_ok"  # Authentication successful
    AUTH_FAIL = "auth_fail"  # Authentication failed
    SESSION_BUSY = "session_busy"  # Another user is active
    SESSION_STARTED = "session_started"  # Transcription session started
    SESSION_STOPPED = "session_stopped"  # Transcription session stopped
    REALTIME = "realtime"  # Real-time partial transcription
    FINAL = "final"  # Final transcription result
    PONG = "pong"  # Heartbeat response
    ERROR = "error"  # Error message
    STATUS = "status"  # Server status update


@dataclass
class ControlMessage:
    """Represents a control channel message."""

    type: MessageType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(
            {
                "type": self.type.value,
                "data": self.data,
                "timestamp": self.timestamp,
            }
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ControlMessage":
        """Deserialize from JSON string."""
        try:
            obj = json.loads(json_str)
            return cls(
                type=MessageType(obj["type"]),
                data=obj.get("data", {}),
                timestamp=obj.get("timestamp", time.time()),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse control message: {e}")
            raise ValueError(f"Invalid control message: {e}")


@dataclass
class AudioChunk:
    """
    Represents an audio data chunk.

    Binary format:
    - 4 bytes: payload length (little-endian uint32)
    - N bytes: JSON metadata (sample_rate, timestamp, etc.)
    - M bytes: raw PCM audio data (16-bit signed, mono)
    """

    audio_data: bytes  # Raw PCM bytes
    sample_rate: int = SAMPLE_RATE
    timestamp_ns: int = 0  # Nanosecond timestamp for synchronization
    sequence: int = 0  # Sequence number for ordering

    def to_bytes(self) -> bytes:
        """Serialize to binary format for transmission."""
        metadata = json.dumps(
            {
                "sample_rate": self.sample_rate,
                "timestamp_ns": self.timestamp_ns,
                "sequence": self.sequence,
            }
        ).encode("utf-8")

        # Format: [4 bytes metadata length][metadata JSON][audio PCM data]
        header = struct.pack("<I", len(metadata))
        return header + metadata + self.audio_data

    @classmethod
    def from_bytes(cls, data: bytes) -> "AudioChunk":
        """Deserialize from binary format."""
        if len(data) < 4:
            raise ValueError("Data too short for audio chunk header")

        # Read metadata length
        metadata_len = struct.unpack("<I", data[:4])[0]

        if len(data) < 4 + metadata_len:
            raise ValueError("Data too short for metadata")

        # Parse metadata
        metadata_bytes = data[4 : 4 + metadata_len]
        metadata = json.loads(metadata_bytes.decode("utf-8"))

        # Extract audio data
        audio_data = data[4 + metadata_len :]

        return cls(
            audio_data=audio_data,
            sample_rate=metadata.get("sample_rate", SAMPLE_RATE),
            timestamp_ns=metadata.get("timestamp_ns", 0),
            sequence=metadata.get("sequence", 0),
        )


@dataclass
class TranscriptionResult:
    """Represents a transcription result."""

    text: str
    is_final: bool
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None
    language: Optional[str] = None
    words: Optional[List[Dict[str, Any]]] = None  # Word-level timestamps

    def to_control_message(self) -> ControlMessage:
        """Convert to a control message for transmission."""
        msg_type = MessageType.FINAL if self.is_final else MessageType.REALTIME
        return ControlMessage(
            type=msg_type,
            data={
                "text": self.text,
                "is_final": self.is_final,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "confidence": self.confidence,
                "language": self.language,
                "words": self.words,
            },
        )


class ControlProtocol:
    """
    Handles control channel protocol operations.

    The control channel uses JSON messages for:
    - Authentication
    - Session management (start/stop)
    - Configuration
    - Heartbeats
    """

    @staticmethod
    def create_auth_request(token: str) -> ControlMessage:
        """Create an authentication request message."""
        return ControlMessage(type=MessageType.AUTH, data={"token": token})

    @staticmethod
    def create_auth_response(success: bool, message: str = "") -> ControlMessage:
        """Create an authentication response message."""
        msg_type = MessageType.AUTH_OK if success else MessageType.AUTH_FAIL
        return ControlMessage(type=msg_type, data={"message": message})

    @staticmethod
    def create_session_busy_response(active_client: str) -> ControlMessage:
        """Create a session busy response."""
        return ControlMessage(
            type=MessageType.SESSION_BUSY,
            data={
                "message": "Another user is using the server",
                "active_client": active_client,
            },
        )

    @staticmethod
    def create_start_request(
        language: Optional[str] = None,
        enable_realtime: bool = True,
        word_timestamps: bool = False,
    ) -> ControlMessage:
        """Create a start transcription request."""
        return ControlMessage(
            type=MessageType.START,
            data={
                "language": language,
                "enable_realtime": enable_realtime,
                "word_timestamps": word_timestamps,
            },
        )

    @staticmethod
    def create_stop_request() -> ControlMessage:
        """Create a stop transcription request."""
        return ControlMessage(type=MessageType.STOP)

    @staticmethod
    def create_ping() -> ControlMessage:
        """Create a ping message."""
        return ControlMessage(type=MessageType.PING)

    @staticmethod
    def create_pong() -> ControlMessage:
        """Create a pong response."""
        return ControlMessage(type=MessageType.PONG)

    @staticmethod
    def create_error(message: str, code: str = "error") -> ControlMessage:
        """Create an error message."""
        return ControlMessage(
            type=MessageType.ERROR,
            data={"message": message, "code": code},
        )

    @staticmethod
    def create_status(
        is_transcribing: bool,
        models_loaded: bool,
        session_active: bool,
    ) -> ControlMessage:
        """Create a status message."""
        return ControlMessage(
            type=MessageType.STATUS,
            data={
                "is_transcribing": is_transcribing,
                "models_loaded": models_loaded,
                "session_active": session_active,
            },
        )


class AudioProtocol:
    """
    Handles audio data channel protocol operations.

    The audio channel uses binary messages for:
    - Audio data streaming (PCM)
    - Transcription results (as binary-wrapped JSON)
    """

    def __init__(self, target_sample_rate: int = SAMPLE_RATE):
        """
        Initialize audio protocol handler.

        Args:
            target_sample_rate: Target sample rate for transcription (default 16kHz)
        """
        self.target_sample_rate = target_sample_rate
        self._sequence_counter = 0
        self._audio_buffer = bytearray()

    def create_audio_chunk(
        self,
        audio_data: Union[bytes, np.ndarray],
        source_sample_rate: int = SAMPLE_RATE,
    ) -> AudioChunk:
        """
        Create an audio chunk for transmission.

        Args:
            audio_data: Raw PCM data (bytes) or numpy array
            source_sample_rate: Sample rate of the input audio

        Returns:
            AudioChunk ready for transmission
        """
        # Convert numpy array to bytes if needed
        if isinstance(audio_data, np.ndarray):
            # Ensure it's 16-bit signed
            if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
                audio_data = (audio_data * 32767).astype(np.int16)
            elif audio_data.dtype != np.int16:
                audio_data = audio_data.astype(np.int16)
            audio_bytes = audio_data.tobytes()
        else:
            audio_bytes = audio_data

        self._sequence_counter += 1

        return AudioChunk(
            audio_data=audio_bytes,
            sample_rate=source_sample_rate,
            timestamp_ns=time.time_ns(),
            sequence=self._sequence_counter,
        )

    def process_incoming_audio(self, chunk: AudioChunk) -> np.ndarray:
        """
        Process an incoming audio chunk.

        Handles resampling if the source sample rate differs from target.

        Args:
            chunk: The received audio chunk

        Returns:
            Numpy array of audio samples (float32, normalized to [-1, 1])
        """
        # Convert bytes to numpy array
        audio_int16 = np.frombuffer(chunk.audio_data, dtype=np.int16)

        # Normalize to float32 [-1, 1]
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Resample if needed
        if chunk.sample_rate != self.target_sample_rate:
            from scipy.signal import resample

            num_samples = int(
                len(audio_float) * self.target_sample_rate / chunk.sample_rate
            )
            audio_float = resample(audio_float, num_samples).astype(np.float32)

        return audio_float

    def buffer_audio(self, audio: np.ndarray) -> None:
        """Add audio to the internal buffer."""
        # Convert to bytes for buffering
        audio_int16 = (audio * 32767).astype(np.int16)
        self._audio_buffer.extend(audio_int16.tobytes())

    def get_buffered_audio(self, clear: bool = True) -> np.ndarray:
        """
        Get all buffered audio.

        Args:
            clear: Whether to clear the buffer after retrieval

        Returns:
            Numpy array of buffered audio (float32)
        """
        audio_int16 = np.frombuffer(bytes(self._audio_buffer), dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0

        if clear:
            self._audio_buffer.clear()

        return audio_float

    def clear_buffer(self) -> None:
        """Clear the audio buffer."""
        self._audio_buffer.clear()

    def reset(self) -> None:
        """Reset the protocol state."""
        self._sequence_counter = 0
        self._audio_buffer.clear()
