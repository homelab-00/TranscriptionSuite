"""
PyQt6-based system tray for KDE Wayland and Windows.
"""

import sys
from typing import Optional, cast

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from .base import AbstractTray, TrayAction, TrayState


class Qt6Tray(AbstractTray):
    """PyQt6 system tray implementation."""

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

    def __init__(self, app_name: str = "TranscriptionSuite"):
        super().__init__(app_name)

        # Initialize Qt application
        self.app = QApplication.instance()
        if not self.app:
            self.app = QApplication(sys.argv)
        self.app = cast(QApplication, self.app)
        self.app.setQuitOnLastWindowClosed(False)

        # Create tray icon
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip(app_name)

        # Menu actions (stored for state updates)
        self.start_action: Optional[QAction] = None
        self.stop_action: Optional[QAction] = None

        # Setup menu
        self._setup_menu()

        # Set initial state
        self.set_state(TrayState.DISCONNECTED)

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

        menu.addSeparator()

        # File transcription
        transcribe_action = QAction("Transcribe File...", menu)
        transcribe_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.TRANSCRIBE_FILE)
        )
        menu.addAction(transcribe_action)

        menu.addSeparator()

        # Web interfaces
        notebook_action = QAction("Open Audio Notebook", menu)
        notebook_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.OPEN_AUDIO_NOTEBOOK)
        )
        menu.addAction(notebook_action)

        remote_action = QAction("Open Remote Server", menu)
        remote_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.OPEN_REMOTE_SERVER)
        )
        menu.addAction(remote_action)

        menu.addSeparator()

        # Settings & Quit
        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(
            lambda: self._trigger_callback(TrayAction.SETTINGS)
        )
        menu.addAction(settings_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)

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
        """Update tray icon color based on state."""
        self.state = state
        color = self.COLORS.get(state, (128, 128, 128))
        self.tray.setIcon(self._create_icon(color))

        # Update tooltip
        state_names = {
            TrayState.DISCONNECTED: "Disconnected",
            TrayState.CONNECTING: "Connecting...",
            TrayState.STANDBY: "Ready",
            TrayState.RECORDING: "Recording...",
            TrayState.UPLOADING: "Uploading...",
            TrayState.TRANSCRIBING: "Transcribing...",
            TrayState.ERROR: "Error",
        }
        self.tray.setToolTip(f"{self.app_name} - {state_names.get(state, 'Unknown')}")

        # Update menu item states
        if self.start_action and self.stop_action:
            if state == TrayState.RECORDING:
                self.start_action.setEnabled(False)
                self.stop_action.setEnabled(True)
            else:
                self.start_action.setEnabled(state == TrayState.STANDBY)
                self.stop_action.setEnabled(False)

    def show_notification(self, title: str, message: str) -> None:
        """Show a system notification."""
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
        self.tray.hide()
        self.app.quit()

    def open_file_dialog(
        self, title: str, filetypes: list[tuple[str, str]]
    ) -> Optional[str]:
        """Open a file selection dialog."""
        filter_str = ";;".join(f"{name} ({ext})" for name, ext in filetypes)
        path, _ = QFileDialog.getOpenFileName(None, title, "", filter_str)
        return path if path else None

    def update_tooltip(self, text: str) -> None:
        """Update the tray icon tooltip."""
        self.tray.setToolTip(text)
