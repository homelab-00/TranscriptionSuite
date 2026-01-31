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
    # Live Mode states
    LIVE_LISTENING = "live_listening"  # Live Mode active, microphone unmuted
    LIVE_MUTED = "live_muted"  # Live Mode active, microphone muted


class TrayAction(Enum):
    """Actions available from tray menu."""

    START_RECORDING = "start_recording"
    STOP_RECORDING = "stop_recording"
    CANCEL_RECORDING = "cancel_recording"
    OPEN_AUDIO_NOTEBOOK = "open_audio_notebook"
    TRANSCRIBE_FILE = "transcribe_file"
    TOGGLE_MODELS = "toggle_models"
    SETTINGS = "settings"
    RECONNECT = "reconnect"
    DISCONNECT = "disconnect"
    QUIT = "quit"
    # Live Mode actions
    START_LIVE_MODE = "start_live_mode"
    STOP_LIVE_MODE = "stop_live_mode"
    TOGGLE_LIVE_MUTE = "toggle_live_mute"
    # Docker server control actions
    SERVER_START_LOCAL = "server_start_local"
    SERVER_START_REMOTE = "server_start_remote"
    SERVER_STOP = "server_stop"
    SERVER_SETUP = "server_setup"


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


# =============================================================================
# Audio Notebook Data Models
# =============================================================================


@dataclass
class Recording:
    """Audio notebook recording metadata."""

    id: int
    filename: str
    filepath: str
    title: str | None
    recorded_at: str  # ISO datetime string
    imported_at: str  # ISO datetime string
    duration_seconds: float
    word_count: int
    has_diarization: bool
    summary: str | None = None
    summary_model: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recording":
        """Create from API response dict."""
        return cls(
            id=data.get("id", 0),
            filename=data.get("filename", ""),
            filepath=data.get("filepath", ""),
            title=data.get("title"),
            recorded_at=data.get("recorded_at", ""),
            imported_at=data.get("imported_at", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            word_count=data.get("word_count", 0),
            has_diarization=data.get("has_diarization", False),
            summary=data.get("summary"),
            summary_model=data.get("summary_model"),
        )


@dataclass
class Word:
    """Word-level transcription data with timestamps."""

    word: str
    start: float  # Start time in seconds
    end: float  # End time in seconds
    probability: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Word":
        """Create from API response dict."""
        return cls(
            word=data.get("word", ""),
            start=data.get("start", 0.0),
            end=data.get("end", 0.0),
            probability=data.get("probability"),
        )


@dataclass
class Segment:
    """Transcription segment with optional speaker and word-level data."""

    text: str
    start: float  # Start time in seconds
    end: float  # End time in seconds
    speaker: str | None = None
    words: list[Word] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Segment":
        """Create from API response dict."""
        words_data = data.get("words", [])
        words = [Word.from_dict(w) for w in words_data] if words_data else []
        return cls(
            text=data.get("text", ""),
            start=data.get("start", 0.0),
            end=data.get("end", 0.0),
            speaker=data.get("speaker"),
            words=words,
        )


@dataclass
class Transcription:
    """Full transcription with segments."""

    recording_id: int
    segments: list[Segment] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcription":
        """Create from API response dict."""
        segments_data = data.get("segments", [])
        segments = [Segment.from_dict(s) for s in segments_data]
        return cls(
            recording_id=data.get("recording_id", 0),
            segments=segments,
        )


@dataclass
class SearchResult:
    """Search result from full-text search."""

    recording_id: int
    recording: Recording | None
    word: str
    start_time: float
    end_time: float
    context: str
    match_type: str  # 'word', 'filename', 'summary'

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        """Create from API response dict."""
        recording_data = data.get("recording")
        recording = Recording.from_dict(recording_data) if recording_data else None
        return cls(
            recording_id=data.get("recording_id", 0),
            recording=recording,
            word=data.get("word", ""),
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            context=data.get("context", ""),
            match_type=data.get("match_type", "word"),
        )


@dataclass
class Conversation:
    """LLM conversation metadata."""

    id: int
    recording_id: int
    title: str
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        """Create from API response dict."""
        return cls(
            id=data.get("id", 0),
            recording_id=data.get("recording_id", 0),
            title=data.get("title", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class Message:
    """Chat message in a conversation."""

    id: int
    conversation_id: int
    role: str  # 'user', 'assistant', 'system'
    content: str
    created_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create from API response dict."""
        return cls(
            id=data.get("id", 0),
            conversation_id=data.get("conversation_id", 0),
            role=data.get("role", ""),
            content=data.get("content", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class ConversationWithMessages:
    """Conversation with full message history."""

    id: int
    recording_id: int
    title: str
    created_at: str
    updated_at: str
    messages: list[Message] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationWithMessages":
        """Create from API response dict."""
        messages_data = data.get("messages", [])
        messages = [Message.from_dict(m) for m in messages_data]
        return cls(
            id=data.get("id", 0),
            recording_id=data.get("recording_id", 0),
            title=data.get("title", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            messages=messages,
        )


@dataclass
class ImportJob:
    """Import job status for tracking file uploads."""

    id: int
    filename: str
    status: str  # 'pending', 'transcribing', 'completed', 'failed'
    progress: float | None = None
    message: str | None = None
    recording_id: int | None = None  # Set when completed

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportJob":
        """Create from API response dict."""
        return cls(
            id=data.get("id", 0),
            filename=data.get("filename", ""),
            status=data.get("status", "pending"),
            progress=data.get("progress"),
            message=data.get("message"),
            recording_id=data.get("recording_id"),
        )
