"""
KDE Plasma system tray implementation using PyQt6.

Provides native system tray integration for KDE Plasma desktop.
Based on the architecture from NATIVE_CLIENT/tray/qt6_tray.py.
"""

import logging
import subprocess
import sys
from typing import TYPE_CHECKING, cast

from client.common.docker_manager import DockerManager, ServerMode, ServerStatus
from client.common.models import TrayAction, TrayState
from client.common.tray_base import AbstractTray

if TYPE_CHECKING:
    from client.common.config import ClientConfig

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


class Qt6Tray(AbstractTray):
    """PyQt6 system tray implementation for KDE Plasma."""

    # State colors (RGB)
    COLORS: dict[TrayState, tuple[int, int, int]] = {
        TrayState.DISCONNECTED: (128, 128, 128),  # Grey
        TrayState.CONNECTING: (255, 165, 0),  # Orange
        TrayState.STANDBY: (0, 255, 0),  # Green
        TrayState.RECORDING: (255, 255, 0),  # Yellow
        TrayState.UPLOADING: (0, 191, 255),  # Deep sky blue
        TrayState.TRANSCRIBING: (255, 128, 0),  # Orange
        TrayState.ERROR: (255, 0, 0),  # Red
    }

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

        # Setup menu and click handlers
        self._setup_menu()
        self._setup_click_handlers()

        # Set initial state
        self._do_set_state(TrayState.DISCONNECTED)

    def _setup_menu(self) -> None:
        """Create the context menu."""
        menu = QMenu()

        # Recording actions
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
        transcribe_action = QAction("Transcribe File...", menu)
        transcribe_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.TRANSCRIBE_FILE)
        )
        menu.addAction(transcribe_action)

        menu.addSeparator()

        # Web interface
        notebook_action = QAction("Open Audio Notebook", menu)
        notebook_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.OPEN_AUDIO_NOTEBOOK)
        )
        menu.addAction(notebook_action)

        menu.addSeparator()

        # Docker Server Control submenu
        server_menu = QMenu("Docker Server", menu)

        start_local_action = QAction("Start Server (Local)", server_menu)
        start_local_action.triggered.connect(self._on_server_start_local)
        server_menu.addAction(start_local_action)

        start_remote_action = QAction("Start Server (Remote)", server_menu)
        start_remote_action.triggered.connect(self._on_server_start_remote)
        server_menu.addAction(start_remote_action)

        stop_server_action = QAction("Stop Server", server_menu)
        stop_server_action.triggered.connect(self._on_server_stop)
        server_menu.addAction(stop_server_action)

        server_menu.addSeparator()

        server_status_action = QAction("Check Status", server_menu)
        server_status_action.triggered.connect(self._on_server_status)
        server_menu.addAction(server_status_action)

        server_menu.addSeparator()

        lazydocker_action = QAction("Open lazydocker", server_menu)
        lazydocker_action.triggered.connect(self._on_open_lazydocker)
        server_menu.addAction(lazydocker_action)

        menu.addMenu(server_menu)

        menu.addSeparator()

        # Reconnect
        self.reconnect_action = QAction("Reconnect", menu)
        self.reconnect_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.RECONNECT)
        )
        menu.addAction(self.reconnect_action)

        # Settings
        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self.show_settings_dialog)
        menu.addAction(settings_action)

        menu.addSeparator()

        # Quit
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)

    def _setup_click_handlers(self) -> None:
        """Setup click handlers for tray icon."""
        self.tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon clicks."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Left-click: Start recording (if in standby)
            if self.state == TrayState.STANDBY:
                self._trigger_callback(TrayAction.START_RECORDING)
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            # Middle-click: Stop recording and transcribe (if recording)
            if self.state == TrayState.RECORDING:
                self._trigger_callback(TrayAction.STOP_RECORDING)

    def _create_icon(self, color: tuple[int, int, int]) -> QIcon:
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
        color = self.COLORS.get(state, (128, 128, 128))
        self.tray.setIcon(self._create_icon(color))

        # Update tooltip
        self.tray.setToolTip(self.get_state_tooltip(state))

        # Update menu item states
        if self.start_action and self.stop_action:
            if state == TrayState.RECORDING:
                self.start_action.setEnabled(False)
                self.stop_action.setEnabled(True)
            else:
                self.start_action.setEnabled(state == TrayState.STANDBY)
                self.stop_action.setEnabled(False)

        # Cancel is enabled during recording, uploading, or transcribing
        if self.cancel_action:
            cancellable_states = {TrayState.RECORDING, TrayState.UPLOADING, TrayState.TRANSCRIBING}
            self.cancel_action.setEnabled(state in cancellable_states)

        # Update reconnect visibility
        if self.reconnect_action:
            self.reconnect_action.setVisible(state == TrayState.DISCONNECTED)

    def show_notification(self, title: str, message: str) -> None:
        """Show a system notification (thread-safe)."""
        self._signals.notification_requested.emit(title, message)

    def _do_show_notification(self, title: str, message: str) -> None:
        """Actually show the notification (must be called on main thread)."""
        self.tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 3000
        )

    def run(self) -> None:
        """Start the Qt event loop."""
        self.tray.show()
        self.app.exec()

    def quit(self) -> None:
        """Exit the application."""
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
                result = subprocess.run(
                    ["wl-copy"],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=2,
                )
                logger.info(f"Copied to clipboard via wl-copy: {len(text)} characters")
            except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as wl_err:
                logger.error(f"wl-copy fallback also failed: {wl_err}")

    def show_settings_dialog(self) -> None:
        """Show the settings dialog (thread-safe)."""
        self._signals.settings_dialog_requested.emit()

    def _do_show_settings_dialog(self) -> None:
        """Actually show the settings dialog (must be called on main thread)."""
        if self.config is None:
            logger.warning("Cannot show settings dialog: no config available")
            return

        from client.kde.settings_dialog import SettingsDialog

        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self.config)

        # Reload values in case config changed externally
        self._settings_dialog._load_values()
        self._settings_dialog.exec()

    def _on_server_start_local(self) -> None:
        """Start Docker server in local (HTTP) mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(
                mode=ServerMode.LOCAL,
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Starting server (local mode)...",
        )

    def _on_server_start_remote(self) -> None:
        """Start Docker server in remote (HTTPS) mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(
                mode=ServerMode.REMOTE,
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Starting server (remote mode)...",
        )

    def _on_server_stop(self) -> None:
        """Stop the Docker server."""
        self._run_server_operation(
            lambda: self._docker_manager.stop_server(
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Stopping server...",
        )

    def _on_server_status(self) -> None:
        """Check Docker server status."""
        try:
            available, docker_msg = self._docker_manager.is_docker_available()
            if not available:
                self.show_notification("Docker Server", docker_msg)
                return

            status = self._docker_manager.get_server_status()
            mode = self._docker_manager.get_current_mode()

            status_text = {
                ServerStatus.RUNNING: "Running",
                ServerStatus.STOPPED: "Stopped",
                ServerStatus.NOT_FOUND: "Not set up",
                ServerStatus.ERROR: "Error",
            }.get(status, "Unknown")

            mode_text = f" ({mode.value} mode)" if mode and status == ServerStatus.RUNNING else ""

            self.show_notification("Docker Server", f"Status: {status_text}{mode_text}")
        except Exception as e:
            logger.error(f"Failed to check server status: {e}")
            self.show_notification("Docker Server", f"Error: {e}")

    def _on_open_lazydocker(self) -> None:
        """Open lazydocker in a terminal."""
        import platform
        import shutil

        # Check if lazydocker is available
        lazydocker_path = shutil.which("lazydocker")
        if not lazydocker_path:
            system = platform.system()
            if system == "Windows":
                install_msg = "lazydocker not found. Install with: scoop install lazydocker"
            else:
                install_msg = "lazydocker not found. Install with: sudo pacman -S lazydocker"
            self.show_notification("lazydocker", install_msg)
            return

        # Platform-specific terminal commands
        system = platform.system()
        if system == "Windows":
            terminals = [
                ["wt.exe", "-w", "0", "nt", "lazydocker"],  # Windows Terminal (new tab)
                ["cmd.exe", "/c", "start", "lazydocker"],  # cmd fallback
            ]
        else:  # Linux
            terminals = [
                ["konsole", "-e", "lazydocker"],
                ["gnome-terminal", "--", "lazydocker"],
                ["xterm", "-e", "lazydocker"],
            ]

        for terminal_cmd in terminals:
            if shutil.which(terminal_cmd[0]):
                try:
                    subprocess.Popen(
                        terminal_cmd,
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    logger.info(f"Launched lazydocker with {terminal_cmd[0]}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to launch with {terminal_cmd[0]}: {e}")
                    continue

        if system == "Windows":
            error_msg = "No supported terminal found (Windows Terminal, cmd)"
        else:
            error_msg = "No supported terminal emulator found (konsole, gnome-terminal, xterm)"
        self.show_notification("lazydocker", error_msg)

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

                QTimer.singleShot(3000, lambda: self._trigger_callback(TrayAction.RECONNECT))
        except Exception as e:
            logger.error(f"Server operation failed: {e}")
            self.show_notification("Docker Server", f"Error: {e}")

    def cleanup(self) -> None:
        """Clean up resources before quitting."""
        if self._settings_dialog is not None:
            self._settings_dialog.close()
            self._settings_dialog = None


def run_tray(config) -> int:
    """
    Run the KDE Plasma tray application.

    Args:
        config: Client configuration

    Returns:
        Exit code
    """
    from client.common.orchestrator import ClientOrchestrator

    try:
        tray = Qt6Tray(config=config)
        orchestrator = ClientOrchestrator(
            config=config,
            auto_connect=True,
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
