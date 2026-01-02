"""
Shared data models for TranscriptionSuite client.

Defines state enums, actions, and data classes used across all client components.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrayState(Enum):
    """Application states reflected in tray icon."""

    IDLE = "idle"  # Client not running (shows app logo)
    DISCONNECTED = "disconnected"  # Client running but not connected to server
    CONNECTING = "connecting"  # Establishing connection
    STANDBY = "standby"  # Connected, ready
    RECORDING = "recording"  # Microphone active
    UPLOADING = "uploading"  # Sending audio to server
    TRANSCRIBING = "transcribing"  # Waiting for transcription
    ERROR = "error"  # Error state


class TrayAction(Enum):
    """Actions available from tray menu."""

    START_RECORDING = "start_recording"
    STOP_RECORDING = "stop_recording"
    CANCEL_RECORDING = "cancel_recording"
    OPEN_AUDIO_NOTEBOOK = "open_audio_notebook"
    TRANSCRIBE_FILE = "transcribe_file"
    SETTINGS = "settings"
    RECONNECT = "reconnect"
    QUIT = "quit"
    # Docker server control actions
    SERVER_START_LOCAL = "server_start_local"
    SERVER_START_REMOTE = "server_start_remote"
    SERVER_STOP = "server_stop"
    SERVER_SETUP = "server_setup"
    # Tools
    OPEN_LAZYDOCKER = "open_lazydocker"


class TranscriptionMode(Enum):
    """Transcription modes supported by the client."""

    LONG_FORM = "long_form"  # Long-form dictation
    STATIC = "static"  # Static file transcription
    NOTEBOOK = "notebook"  # Audio notebook mode


@dataclass
class TranscriptionResult:
    """Result of a transcription request."""

    text: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0
    num_speakers: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptionResult":
        """Create from API response dict."""
        return cls(
            text=data.get("text", ""),
            segments=data.get("segments", []),
            words=data.get("words", []),
            language=data.get("language", ""),
            language_probability=data.get("language_probability", 0.0),
            duration=data.get("duration", 0.0),
            num_speakers=data.get("num_speakers", 0),
        )


@dataclass
class ServerStatus:
    """Server status information."""

    connected: bool = False
    status: str = "disconnected"
    version: str = ""
    gpu_available: bool = False
    model_loaded: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerStatus":
        """Create from API response dict."""
        models = data.get("models", {})
        transcription = models.get("transcription", {})

        return cls(
            connected=True,
            status=data.get("status", "unknown"),
            version=data.get("version", ""),
            gpu_available=models.get("gpu_available", False),
            model_loaded=transcription.get("loaded", False),
        )


# Type aliases for callbacks
StateCallback = Callable[[TrayState], None]
ActionCallback = Callable[[], None]
ProgressCallback = Callable[[str], None]
TranscriptionCallback = Callable[[TranscriptionResult], None]
ErrorCallback = Callable[[str], None]
