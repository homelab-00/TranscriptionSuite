"""
Abstract base class for system tray implementations.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Optional


class TrayState(Enum):
    """Application states reflected in tray icon."""

    DISCONNECTED = "disconnected"  # Not connected to container
    CONNECTING = "connecting"  # Establishing connection
    STANDBY = "standby"  # Connected, ready
    RECORDING = "recording"  # Microphone active
    UPLOADING = "uploading"  # Sending audio to container
    TRANSCRIBING = "transcribing"  # Waiting for transcription
    ERROR = "error"  # Error state


class TrayAction(Enum):
    """Actions available from tray menu."""

    START_RECORDING = "start_recording"
    STOP_RECORDING = "stop_recording"
    OPEN_AUDIO_NOTEBOOK = "open_audio_notebook"
    OPEN_REMOTE_SERVER = "open_remote_server"
    TRANSCRIBE_FILE = "transcribe_file"
    SETTINGS = "settings"
    QUIT = "quit"


class AbstractTray(ABC):
    """Abstract system tray interface."""

    def __init__(self, app_name: str = "TranscriptionSuite"):
        self.app_name = app_name
        self.state = TrayState.DISCONNECTED
        self.callbacks: dict[TrayAction, Callable[[], None]] = {}

    def register_callback(self, action: TrayAction, callback: Callable[[], None]) -> None:
        """Register a callback for a tray action."""
        self.callbacks[action] = callback

    def _trigger_callback(self, action: TrayAction) -> None:
        """Trigger a registered callback."""
        if action in self.callbacks:
            self.callbacks[action]()

    @abstractmethod
    def set_state(self, state: TrayState) -> None:
        """Update the tray icon to reflect current state."""
        pass

    @abstractmethod
    def show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification."""
        pass

    @abstractmethod
    def run(self) -> None:
        """Start the tray icon event loop (blocking)."""
        pass

    @abstractmethod
    def quit(self) -> None:
        """Exit the tray application."""
        pass

    @abstractmethod
    def open_file_dialog(
        self, title: str, filetypes: list[tuple[str, str]]
    ) -> Optional[str]:
        """Open a file selection dialog."""
        pass

    def update_tooltip(self, text: str) -> None:
        """Update the tray icon tooltip. Override if supported."""
        pass
