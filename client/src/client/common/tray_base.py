"""
Abstract base class for system tray implementations.

Defines the interface that all platform-specific tray implementations must follow.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable

from client.common.models import TrayAction, TrayState


class AbstractTray(ABC):
    """
    Abstract system tray interface.

    All platform-specific tray implementations (KDE, GNOME, Windows) must
    inherit from this class and implement the abstract methods.
    """

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
        """
        Update the tray icon to reflect current state.

        Args:
            state: New application state
        """
        pass

    @abstractmethod
    def show_notification(self, title: str, message: str) -> None:
        """
        Show a desktop notification.

        Args:
            title: Notification title
            message: Notification message body
        """
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
    ) -> str | None:
        """
        Open a file selection dialog.

        Args:
            title: Dialog title
            filetypes: List of (description, pattern) tuples
                       e.g., [("Audio Files", "*.wav *.mp3"), ("All Files", "*.*")]

        Returns:
            Selected file path, or None if cancelled
        """
        pass

    def update_tooltip(self, text: str) -> None:
        """
        Update the tray icon tooltip.

        Override if supported by the platform.

        Args:
            text: New tooltip text
        """
        pass

    def copy_to_clipboard(self, text: str) -> bool:
        """
        Copy text to system clipboard.

        Override with platform-specific implementation.

        Args:
            text: Text to copy

        Returns:
            True if successful, False otherwise
        """
        return False

    def show_settings_dialog(self) -> None:
        """
        Show the settings dialog.

        Override with platform-specific implementation.
        """
        pass

    def get_state_tooltip(self, state: TrayState) -> str:
        """Get tooltip text for a state."""
        state_names = {
            TrayState.DISCONNECTED: "Disconnected",
            TrayState.CONNECTING: "Connecting...",
            TrayState.STANDBY: "Ready",
            TrayState.RECORDING: "Recording...",
            TrayState.UPLOADING: "Uploading...",
            TrayState.TRANSCRIBING: "Transcribing...",
            TrayState.ERROR: "Error",
        }
        return f"{self.app_name} - {state_names.get(state, 'Unknown')}"
