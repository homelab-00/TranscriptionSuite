"""
Abstract base class for system tray implementations.

Defines the interface that all platform-specific tray implementations must follow.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from dashboard.common.models import TrayAction, TrayState

if TYPE_CHECKING:
    from dashboard.common.orchestrator import (  # lgtm [py/unsafe-cyclic-import]
        ClientOrchestrator,  # lgtm [py/unused-import]
    )


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
        self.orchestrator: "ClientOrchestrator | None" = (
            None  # Set by orchestrator for state sync
        )

    def register_callback(
        self, action: TrayAction, callback: Callable[[], None]
    ) -> None:
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

    def flash_then_set_state(
        self, target_state: TrayState, flash_duration_ms: int = 250
    ) -> None:
        """
        Flash icon to light gray, then transition to target state.

        Override with platform-specific implementation for visual feedback.
        Default implementation just calls set_state directly.

        Args:
            target_state: State to transition to after flash
            flash_duration_ms: Duration of flash in milliseconds
        """
        self.set_state(target_state)

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

    def update_live_transcription_text(self, text: str, append: bool = False) -> None:
        """
        Update the live transcription text display.

        Override with platform-specific implementation to forward
        live transcription text to the dashboard UI.

        Args:
            text: Live transcription text to display
            append: If True, append to history. If False, replace current line.
        """
        pass

    def get_state_tooltip(self, state: TrayState) -> str:
        """Get tooltip text for a state."""
        state_names = {
            TrayState.IDLE: "Client not running",
            TrayState.DISCONNECTED: "Disconnected",
            TrayState.CONNECTING: "Connecting...",
            TrayState.STANDBY: "Ready",
            TrayState.RECORDING: "Recording...",
            TrayState.UPLOADING: "Uploading...",
            TrayState.TRANSCRIBING: "Transcribing...",
            TrayState.ERROR: "Error",
            TrayState.LIVE_LISTENING: "Live Mode - Listening",
            TrayState.LIVE_MUTED: "Live Mode - Muted",
        }
        return f"{self.app_name} - {state_names.get(state, 'Unknown')}"

    def update_connection_type(self, is_local: bool) -> None:
        """
        Update the tray to reflect whether the connection is local or remote.

        This affects which menu items are enabled (e.g., model management
        only available for local connections).

        Override with platform-specific implementation.

        Args:
            is_local: True if connected to localhost, False if remote
        """
        pass

    def set_live_mode_active(self, active: bool) -> None:
        """
        Set Live Mode active state and update menu items.

        Override with platform-specific implementation.

        Args:
            active: True if Live Mode is active, False otherwise
        """
        pass

    def update_models_menu_state(self, models_loaded: bool) -> None:
        """
        Update the toggle models menu item text based on current state.

        Override with platform-specific implementation.

        Args:
            models_loaded: True if models are loaded, False if unloaded
        """
        pass
