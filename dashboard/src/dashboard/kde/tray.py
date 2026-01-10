"""
KDE Plasma system tray implementation using PyQt6.

Provides native system tray integration for KDE Plasma desktop.
Based on the architecture from NATIVE_CLIENT/tray/qt6_tray.py.

The Dashboard window is the main command center for the application,
providing a GUI to manage both the Docker server and the transcription client.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from dashboard.common.docker_manager import DockerManager, ServerStatus
from dashboard.common.models import TrayAction, TrayState
from dashboard.common.server_control_mixin import ServerControlMixin
from dashboard.common.tray_base import AbstractTray

if TYPE_CHECKING:
    from dashboard.common.config import ClientConfig

logger = logging.getLogger(__name__)

# Import PyQt6 - required at runtime, but handle import errors gracefully
HAS_PYQT6 = False
try:
    from PyQt6.QtCore import QObject, Qt, pyqtSignal
    from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

    HAS_PYQT6 = True

    class TraySignals(QObject):
        """Signals for thread-safe tray updates."""

        state_changed = pyqtSignal(object)  # TrayState
        notification_requested = pyqtSignal(str, str)  # title, message
        clipboard_requested = pyqtSignal(str)  # text to copy
        settings_dialog_requested = pyqtSignal()  # show settings dialog

except ImportError:
    # Provide stub for type checking only
    TraySignals = None  # type: ignore


class Qt6Tray(ServerControlMixin, AbstractTray):
    """PyQt6 system tray implementation for KDE Plasma."""

    # State colors (RGB) - used when client is running
    COLORS: dict[TrayState, tuple[int, int, int]] = {
        TrayState.IDLE: (128, 128, 128),  # Grey (fallback, normally uses logo)
        TrayState.DISCONNECTED: (128, 128, 128),  # Grey
        TrayState.CONNECTING: (255, 165, 0),  # Orange
        TrayState.STANDBY: (0, 255, 0),  # Green
        TrayState.RECORDING: (255, 255, 0),  # Yellow
        TrayState.UPLOADING: (0, 191, 255),  # Deep sky blue
        TrayState.TRANSCRIBING: (255, 128, 0),  # Orange
        TrayState.ERROR: (255, 0, 0),  # Red
    }

    # Path to app logo (relative to project root)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        LOGO_PATH = Path(sys._MEIPASS) / "build" / "assets" / "logo.png"
    else:
        LOGO_PATH = (
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "build"
            / "assets"
            / "logo.png"
        )

    def __init__(
        self, app_name: str = "TranscriptionSuite", config: "ClientConfig | None" = None
    ):
        if not HAS_PYQT6:
            raise ImportError(
                "PyQt6 is required for KDE tray. Install with: pip install PyQt6"
            )

        super().__init__(app_name)
        self.config = config

        # Initialize Qt application
        self.app = QApplication.instance()
        if not self.app:
            self.app = QApplication(sys.argv)
        self.app = cast(QApplication, self.app)
        self.app.setQuitOnLastWindowClosed(False)

        # Check system tray availability
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError(
                "System tray is not available. On KDE Wayland, ensure the system tray "
                "plasmoid is added to your panel."
            )

        # Create tray icon
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip(app_name)

        # Menu actions (stored for state updates)
        self.start_action: QAction | None = None
        self.stop_action: QAction | None = None
        self.cancel_action: QAction | None = None
        self.transcribe_action: QAction | None = None
        self.reconnect_action: QAction | None = None

        # Docker manager for server control
        self._docker_manager = DockerManager()

        # Thread-safe signals for GUI updates from async thread
        self._signals = TraySignals()
        self._signals.state_changed.connect(self._do_set_state)
        self._signals.notification_requested.connect(self._do_show_notification)
        self._signals.clipboard_requested.connect(self._do_copy_to_clipboard)
        self._signals.settings_dialog_requested.connect(self._do_show_settings_dialog)

        # Dialog instances (created lazily)
        self._settings_dialog = None

        # Dashboard window (command center)
        self._dashboard_window = None

        # Setup menu and click handlers
        self._setup_menu()
        self._setup_click_handlers()

        # Set initial state - IDLE until client is started
        self._do_set_state(TrayState.IDLE)

    def _setup_menu(self) -> None:
        """Create the context menu."""
        menu = QMenu()

        # Recording actions (only enabled when client is running)
        self.start_action = QAction("Start Recording", menu)
        self.start_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.START_RECORDING)
        )
        menu.addAction(self.start_action)

        self.stop_action = QAction("Stop Recording", menu)
        self.stop_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.STOP_RECORDING)
        )
        self.stop_action.setEnabled(False)
        menu.addAction(self.stop_action)

        self.cancel_action = QAction("Cancel", menu)
        self.cancel_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.CANCEL_RECORDING)
        )
        self.cancel_action.setEnabled(False)
        menu.addAction(self.cancel_action)

        menu.addSeparator()

        # File transcription
        self.transcribe_action = QAction("Transcribe File...", menu)
        self.transcribe_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.TRANSCRIBE_FILE)
        )
        self.transcribe_action.setEnabled(False)
        menu.addAction(self.transcribe_action)

        menu.addSeparator()

        # Show app window
        show_app_action = QAction("Show App", menu)
        show_app_action.triggered.connect(self.show_dashboard_window)
        menu.addAction(show_app_action)

        menu.addSeparator()

        # Quit
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)

    def _setup_click_handlers(self) -> None:
        """Setup click handlers for tray icon."""
        self.tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason: "QSystemTrayIcon.ActivationReason") -> None:
        """Handle tray icon clicks."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Left-click: Start recording (if in standby)
            if self.state == TrayState.STANDBY:
                self._trigger_callback(TrayAction.START_RECORDING)
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            # Middle-click: Stop recording and transcribe (if recording)
            # Note: Windows often doesn't emit MiddleClick for system tray icons
            if self.state == TrayState.RECORDING:
                self._trigger_callback(TrayAction.STOP_RECORDING)
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # Double-click: Stop recording (primary method for Windows)
            # On Windows, middle-click events are unreliable/unsupported for system
            # tray icons, so double-click is the standard alternative
            if self.state == TrayState.RECORDING:
                self._trigger_callback(TrayAction.STOP_RECORDING)

    def _create_icon(self, color: tuple[int, int, int]) -> "QIcon":
        """Create a colored circle icon."""
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(*color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, size - 8, size - 8)
        painter.end()

        return QIcon(pixmap)

    def set_state(self, state: TrayState) -> None:
        """Update tray icon color based on state (thread-safe)."""
        self._signals.state_changed.emit(state)

    def _do_set_state(self, state: TrayState) -> None:
        """Actually update the tray state (must be called on main thread)."""
        self.state = state

        # Use app logo for IDLE state, colored circles for running client
        if state == TrayState.IDLE:
            self.tray.setIcon(self._get_logo_icon())
        else:
            color = self.COLORS.get(state, (128, 128, 128))
            self.tray.setIcon(self._create_icon(color))

        # Update tooltip
        self.tray.setToolTip(self.get_state_tooltip(state))

        # Update menu item states - recording only when client is running (not IDLE)
        if self.start_action and self.stop_action:
            if state == TrayState.IDLE:
                self.start_action.setEnabled(False)
                self.stop_action.setEnabled(False)
            elif state == TrayState.RECORDING:
                self.start_action.setEnabled(False)
                self.stop_action.setEnabled(True)
            else:
                self.start_action.setEnabled(state == TrayState.STANDBY)
                self.stop_action.setEnabled(False)

        # Cancel is enabled during recording, uploading, or transcribing
        if self.cancel_action:
            cancellable_states = {
                TrayState.RECORDING,
                TrayState.UPLOADING,
                TrayState.TRANSCRIBING,
            }
            self.cancel_action.setEnabled(state in cancellable_states)

        # Transcribe File is only enabled when server is connected and ready (STANDBY)
        if self.transcribe_action:
            self.transcribe_action.setEnabled(state == TrayState.STANDBY)

    def _get_logo_icon(self) -> "QIcon":
        """Get the app logo icon for IDLE state."""
        if self.LOGO_PATH.exists():
            return QIcon(str(self.LOGO_PATH))
        else:
            # Fallback to a grey circle if logo not found
            logger.warning(f"App logo not found at {self.LOGO_PATH}")
            return self._create_icon((128, 128, 128))

    def show_notification(self, title: str, message: str) -> None:
        """Show a system notification (thread-safe)."""
        # Check if notifications are enabled
        if self.config and not self.config.get("ui", "notifications", default=True):
            return
        self._signals.notification_requested.emit(title, message)

    def _do_show_notification(self, title: str, message: str) -> None:
        """Actually show the notification (must be called on main thread)."""
        self.tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 3000
        )

    def run(self) -> None:
        """Start the Qt event loop."""
        self.tray.show()
        # Show Dashboard window on startup
        self.show_dashboard_window()
        self.app.exec()

    def quit(self) -> None:
        """Exit the application."""
        # Stop Docker server if running and setting enabled
        if self.config and self.config.get(
            "dashboard", "stop_server_on_quit", default=True
        ):
            if self._docker_manager.get_server_status() == ServerStatus.RUNNING:
                logger.info("Stopping Docker server on quit")
                self._docker_manager.stop_server()

        self._trigger_callback(TrayAction.QUIT)
        self.cleanup()
        self.tray.hide()
        self.app.quit()

    def open_file_dialog(
        self, title: str, filetypes: list[tuple[str, str]]
    ) -> str | None:
        """Open a file selection dialog."""
        filter_str = ";;".join(f"{name} ({ext})" for name, ext in filetypes)
        path, _ = QFileDialog.getOpenFileName(None, title, "", filter_str)
        return path if path else None

    def update_tooltip(self, text: str) -> None:
        """Update the tray icon tooltip."""
        self.tray.setToolTip(text)

    def update_models_menu_state(self, models_loaded: bool) -> None:
        """
        Update the toggle models menu item text based on current state.

        Note: Menu item removed; button now in Dashboard Server view.
        Method kept for interface compatibility.
        """
        pass

    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text to clipboard (thread-safe)."""
        self._signals.clipboard_requested.emit(text)
        return True

    def _do_copy_to_clipboard(self, text: str) -> None:
        """Actually copy to clipboard (must be called on main thread)."""
        try:
            clipboard = self.app.clipboard()
            clipboard.setText(text)
            # Process events to ensure clipboard is committed (critical for Wayland)
            self.app.processEvents()
            logger.debug(f"Copied to clipboard via Qt: {len(text)} characters")
        except Exception as e:
            logger.warning(f"Qt clipboard copy failed: {e}")
            # Try wl-copy fallback on Wayland
            try:
                subprocess.run(
                    ["wl-copy"],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=2,
                )
                logger.info(f"Copied to clipboard via wl-copy: {len(text)} characters")
            except (
                FileNotFoundError,
                subprocess.TimeoutExpired,
                subprocess.CalledProcessError,
            ) as wl_err:
                logger.error(f"wl-copy fallback also failed: {wl_err}")

    def show_settings_dialog(self) -> None:
        """Show the settings dialog (thread-safe)."""
        self._signals.settings_dialog_requested.emit()

    def _do_show_settings_dialog(self) -> None:
        """Actually show the settings dialog (must be called on main thread)."""
        if self.config is None:
            logger.warning("Cannot show settings dialog: no config available")
            return

        from dashboard.kde.settings_dialog import SettingsDialog

        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self.config)

        # Reload values in case config changed externally
        self._settings_dialog._load_values()
        self._settings_dialog.exec()

    def show_dashboard_window(self) -> None:
        """Show the Dashboard command center window."""
        if self.config is None:
            logger.warning("Cannot show Dashboard: no config available")
            return

        from dashboard.kde.dashboard import DashboardWindow

        if self._dashboard_window is None:
            self._dashboard_window = DashboardWindow(self.config)
            # Connect Dashboard signals
            self._dashboard_window.start_client_requested.connect(
                self._on_dashboard_start_client
            )
            self._dashboard_window.stop_client_requested.connect(
                self._on_dashboard_stop_client
            )
            self._dashboard_window.show_settings_requested.connect(
                self.show_settings_dialog
            )

        self._dashboard_window.show()
        self._dashboard_window.raise_()
        self._dashboard_window.activateWindow()

    def _on_dashboard_start_client(self, remote: bool) -> None:
        """Handle start client request from Dashboard."""
        logger.info(f"Dashboard requested client start (remote={remote})")
        # Trigger reconnect to apply new settings and connect
        self._trigger_callback(TrayAction.RECONNECT)
        # Update Dashboard with running state
        if self._dashboard_window:
            self._dashboard_window.set_client_running(True)

    def _on_dashboard_stop_client(self) -> None:
        """Handle stop client request from Dashboard."""
        logger.info("Dashboard requested client stop")
        # Disconnect from server to properly clean up resources
        self._trigger_callback(TrayAction.DISCONNECT)
        # Set tray state to IDLE (client not running)
        self.set_state(TrayState.IDLE)
        # Update Dashboard
        if self._dashboard_window:
            self._dashboard_window.set_client_running(False)

    # Server control methods are provided by ServerControlMixin
    # (_on_server_start_local, _on_server_start_remote, _on_server_stop,
    #  _on_server_status)

    def _run_server_operation(self, operation, progress_msg: str) -> None:
        """Run a Docker server operation with notification feedback."""
        try:
            self.show_notification("Docker Server", progress_msg)
            result = operation()
            self.show_notification("Docker Server", result.message)

            # Trigger reconnect if server started successfully
            if result.success and result.status == ServerStatus.RUNNING:
                # Give server time to start, then reconnect
                from PyQt6.QtCore import QTimer

                QTimer.singleShot(
                    3000, lambda: self._trigger_callback(TrayAction.RECONNECT)
                )
        except Exception as e:
            logger.error(f"Server operation failed: {e}")
            self.show_notification("Docker Server", f"Error: {e}")

    def cleanup(self) -> None:
        """Clean up resources before quitting."""
        if self._settings_dialog is not None:
            self._settings_dialog.close()
            self._settings_dialog = None
        if self._dashboard_window is not None:
            self._dashboard_window.force_close()
            self._dashboard_window = None


def run_tray(config) -> int:
    """
    Run the KDE Plasma tray application.

    Args:
        config: Client configuration

    Returns:
        Exit code
    """
    from dashboard.common.orchestrator import ClientOrchestrator

    try:
        tray = Qt6Tray(config=config)
        # Check if user wants to auto-start client when app launches
        auto_start = config.get("behavior", "auto_start_client", default=False)
        orchestrator = ClientOrchestrator(
            config=config,
            auto_connect=auto_start,
            auto_copy_clipboard=config.get("clipboard", "auto_copy", default=True),
        )
        orchestrator.start(tray)
        return 0

    except ImportError as e:
        logger.error(f"PyQt6 not available: {e}")
        print("Error: PyQt6 is required for KDE tray. Install with: pip install PyQt6")
        return 1

    except RuntimeError as e:
        logger.error(f"Tray initialization failed: {e}")
        print(f"Error: {e}")
        return 1

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1
