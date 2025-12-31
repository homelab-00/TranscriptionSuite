"""
Mothership - Main control window for TranscriptionSuite.

The Mothership is the command center for managing both the Docker server
and the transcription client. It provides a unified GUI for:
- Starting/stopping the Docker server (local or remote mode)
- Starting/stopping the transcription client
- Configuring all settings
- Viewing server and client logs
"""

import logging
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QProcess, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.common.docker_manager import DockerManager, ServerMode, ServerStatus

if TYPE_CHECKING:
    from client.common.config import ClientConfig

logger = logging.getLogger(__name__)


class View(Enum):
    """Available views in the Mothership."""

    WELCOME = auto()
    SERVER = auto()
    CLIENT = auto()


class MothershipWindow(QMainWindow):
    """
    Main Mothership window - the command center for TranscriptionSuite.

    Provides navigation between:
    - Welcome screen (home)
    - Server management view
    - Client management view
    """

    # Signals for client operations
    start_client_requested = pyqtSignal(bool)  # True = remote, False = local
    stop_client_requested = pyqtSignal()
    show_settings_requested = pyqtSignal()

    def __init__(self, config: "ClientConfig", parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self._docker_manager = DockerManager()

        # View history for back navigation
        self._view_history: list[View] = []
        self._current_view: View = View.WELCOME

        # Log polling
        self._server_log_timer: QTimer | None = None
        self._client_log_timer: QTimer | None = None

        # Client state tracking
        self._client_running = False

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self) -> None:
        """Set up the main UI structure."""
        self.setWindowTitle("TranscriptionSuite")
        self.setMinimumSize(700, 500)

        # Set window icon
        icon = QIcon.fromTheme("audio-input-microphone")
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Navigation bar
        self._nav_bar = self._create_nav_bar()
        main_layout.addWidget(self._nav_bar)

        # Stacked widget for views
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        # Create views
        self._welcome_view = self._create_welcome_view()
        self._server_view = self._create_server_view()
        self._client_view = self._create_client_view()

        self._stack.addWidget(self._welcome_view)
        self._stack.addWidget(self._server_view)
        self._stack.addWidget(self._client_view)

        # Start on welcome view
        self._navigate_to(View.WELCOME, add_to_history=False)

    def _create_nav_bar(self) -> QWidget:
        """Create the navigation bar with back and home buttons."""
        nav = QFrame()
        nav.setObjectName("navBar")
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(10, 8, 10, 8)

        # Back button
        self._back_btn = QPushButton("← Back")
        self._back_btn.setObjectName("navButton")
        self._back_btn.clicked.connect(self._go_back)
        self._back_btn.setVisible(False)
        layout.addWidget(self._back_btn)

        # Home button
        self._home_btn = QPushButton("⌂ Home")
        self._home_btn.setObjectName("navButton")
        self._home_btn.clicked.connect(self._go_home)
        self._home_btn.setVisible(False)
        layout.addWidget(self._home_btn)

        layout.addStretch()

        # Title
        self._nav_title = QLabel("TranscriptionSuite")
        self._nav_title.setObjectName("navTitle")
        layout.addWidget(self._nav_title)

        layout.addStretch()

        return nav

    def _create_welcome_view(self) -> QWidget:
        """Create the welcome/home view."""
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(40, 40, 40, 40)

        # Welcome message
        welcome_label = QLabel("Welcome to TranscriptionSuite")
        welcome_label.setObjectName("welcomeTitle")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome_label)

        subtitle = QLabel("From here you can manage the Docker server and transcription client")
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(40)

        # Main buttons container
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setSpacing(20)

        # Server button
        server_btn = QPushButton("Manage\nDocker Server")
        server_btn.setObjectName("welcomeButton")
        server_btn.setMinimumSize(200, 100)
        server_btn.clicked.connect(lambda: self._navigate_to(View.SERVER))
        btn_layout.addWidget(server_btn)

        # Client button
        client_btn = QPushButton("Manage\nClient")
        client_btn.setObjectName("welcomeButton")
        client_btn.setMinimumSize(200, 100)
        client_btn.clicked.connect(lambda: self._navigate_to(View.CLIENT))
        btn_layout.addWidget(client_btn)

        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(20)

        # Web client button (smaller)
        web_btn = QPushButton("Open Web Client")
        web_btn.setObjectName("secondaryButton")
        web_btn.clicked.connect(self._on_open_web_client)
        layout.addWidget(web_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Note about web client
        web_note = QLabel("Web client URL is based on your client settings (local/remote)")
        web_note.setObjectName("noteLabel")
        web_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(web_note)

        layout.addStretch()

        return view

    def _on_open_web_client(self) -> None:
        """Open the web client in the default browser."""
        import webbrowser

        # Determine URL based on client configuration
        use_remote = self.config.get("server", "use_remote", default=False)
        use_https = self.config.get("server", "use_https", default=False)

        if use_remote:
            host = self.config.get("server", "remote_host", default="")
            port = self.config.get("server", "port", default=8443)
        else:
            host = "localhost"
            port = self.config.get("server", "port", default=8000)

        scheme = "https" if use_https else "http"
        url = f"{scheme}://{host}:{port}"

        logger.info(f"Opening web client: {url}")
        webbrowser.open(url)

    def _create_server_view(self) -> QWidget:
        """Create the server management view."""
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(30, 20, 30, 20)

        # Title
        title = QLabel("Docker Server")
        title.setObjectName("viewTitle")
        layout.addWidget(title)

        layout.addSpacing(10)

        # Status section
        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_layout = QVBoxLayout(status_frame)

        # Image status
        image_row = QHBoxLayout()
        image_row.addWidget(QLabel("Docker Image:"))
        self._image_status_label = QLabel("Checking...")
        self._image_status_label.setObjectName("statusValue")
        image_row.addWidget(self._image_status_label)
        image_row.addStretch()
        status_layout.addLayout(image_row)

        # Image date
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Image Date:"))
        self._image_date_label = QLabel("Checking...")
        self._image_date_label.setObjectName("statusValue")
        date_row.addWidget(self._image_date_label)
        date_row.addStretch()
        status_layout.addLayout(date_row)

        # Server status
        server_row = QHBoxLayout()
        server_row.addWidget(QLabel("Server Status:"))
        self._server_status_label = QLabel("Checking...")
        self._server_status_label.setObjectName("statusValue")
        server_row.addWidget(self._server_status_label)
        server_row.addStretch()
        status_layout.addLayout(server_row)

        layout.addWidget(status_frame)

        layout.addSpacing(20)

        # Control buttons
        btn_layout = QHBoxLayout()

        self._start_local_btn = QPushButton("Start Server (Local)")
        self._start_local_btn.clicked.connect(self._on_start_server_local)
        btn_layout.addWidget(self._start_local_btn)

        self._start_remote_btn = QPushButton("Start Server (Remote)")
        self._start_remote_btn.clicked.connect(self._on_start_server_remote)
        btn_layout.addWidget(self._start_remote_btn)

        self._stop_server_btn = QPushButton("Stop Server")
        self._stop_server_btn.clicked.connect(self._on_stop_server)
        btn_layout.addWidget(self._stop_server_btn)

        layout.addLayout(btn_layout)

        layout.addSpacing(10)

        # Secondary actions
        secondary_layout = QHBoxLayout()

        self._remove_container_btn = QPushButton("Remove Container")
        self._remove_container_btn.setObjectName("dangerButton")
        self._remove_container_btn.clicked.connect(self._on_remove_container)
        secondary_layout.addWidget(self._remove_container_btn)

        secondary_layout.addStretch()
        layout.addLayout(secondary_layout)

        layout.addSpacing(10)

        # Show logs toggle
        self._show_server_logs_btn = QPushButton("▼ Show Logs")
        self._show_server_logs_btn.setCheckable(True)
        self._show_server_logs_btn.toggled.connect(self._toggle_server_logs)
        layout.addWidget(self._show_server_logs_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Log viewer (hidden by default)
        self._server_log_view = QPlainTextEdit()
        self._server_log_view.setReadOnly(True)
        self._server_log_view.setObjectName("logView")
        self._server_log_view.setVisible(False)
        self._server_log_view.setMinimumHeight(200)
        layout.addWidget(self._server_log_view, 1)

        layout.addStretch()

        return view

    def _create_client_view(self) -> QWidget:
        """Create the client management view."""
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(30, 20, 30, 20)

        # Title
        title = QLabel("Transcription Client")
        title.setObjectName("viewTitle")
        layout.addWidget(title)

        layout.addSpacing(10)

        # Status section
        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_layout = QVBoxLayout(status_frame)

        # Client status
        client_row = QHBoxLayout()
        client_row.addWidget(QLabel("Client Status:"))
        self._client_status_label = QLabel("Stopped")
        self._client_status_label.setObjectName("statusValue")
        client_row.addWidget(self._client_status_label)
        client_row.addStretch()
        status_layout.addLayout(client_row)

        # Connection info
        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("Connection:"))
        self._connection_info_label = QLabel("Not connected")
        self._connection_info_label.setObjectName("statusValue")
        conn_row.addWidget(self._connection_info_label)
        conn_row.addStretch()
        status_layout.addLayout(conn_row)

        layout.addWidget(status_frame)

        layout.addSpacing(20)

        # Control buttons
        btn_layout = QHBoxLayout()

        self._start_client_local_btn = QPushButton("Start Client (Local)")
        self._start_client_local_btn.clicked.connect(self._on_start_client_local)
        btn_layout.addWidget(self._start_client_local_btn)

        self._start_client_remote_btn = QPushButton("Start Client (Remote)")
        self._start_client_remote_btn.clicked.connect(self._on_start_client_remote)
        btn_layout.addWidget(self._start_client_remote_btn)

        self._stop_client_btn = QPushButton("Stop Client")
        self._stop_client_btn.clicked.connect(self._on_stop_client)
        self._stop_client_btn.setEnabled(False)
        btn_layout.addWidget(self._stop_client_btn)

        layout.addLayout(btn_layout)

        layout.addSpacing(10)

        # Settings button
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(self._on_show_settings)
        layout.addWidget(settings_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addSpacing(10)

        # Show logs toggle
        self._show_client_logs_btn = QPushButton("▼ Show Logs")
        self._show_client_logs_btn.setCheckable(True)
        self._show_client_logs_btn.toggled.connect(self._toggle_client_logs)
        layout.addWidget(self._show_client_logs_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Log viewer (hidden by default)
        self._client_log_view = QPlainTextEdit()
        self._client_log_view.setReadOnly(True)
        self._client_log_view.setObjectName("logView")
        self._client_log_view.setVisible(False)
        self._client_log_view.setMinimumHeight(200)
        layout.addWidget(self._client_log_view, 1)

        layout.addStretch()

        return view

    def _apply_styles(self) -> None:
        """Apply stylesheet to the window."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            
            #navBar {
                background-color: #1e1e1e;
                border-bottom: 1px solid #3c3c3c;
            }
            
            #navButton {
                background-color: transparent;
                border: none;
                color: #a0a0a0;
                padding: 5px 10px;
                font-size: 13px;
            }
            
            #navButton:hover {
                color: #ffffff;
                background-color: #3c3c3c;
                border-radius: 4px;
            }
            
            #navTitle {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }
            
            #welcomeTitle {
                color: #ffffff;
                font-size: 24px;
                font-weight: bold;
            }
            
            #welcomeSubtitle {
                color: #a0a0a0;
                font-size: 14px;
            }
            
            #welcomeButton {
                background-color: #3c3c3c;
                border: 1px solid #4c4c4c;
                border-radius: 8px;
                color: #ffffff;
                font-size: 14px;
                padding: 20px;
            }
            
            #welcomeButton:hover {
                background-color: #4c4c4c;
                border-color: #5c5c5c;
            }
            
            #viewTitle {
                color: #ffffff;
                font-size: 20px;
                font-weight: bold;
            }
            
            #statusFrame {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 15px;
            }
            
            #statusFrame QLabel {
                color: #a0a0a0;
                font-size: 13px;
            }
            
            #statusValue {
                color: #ffffff;
                font-weight: bold;
            }
            
            QPushButton {
                background-color: #0d6efd;
                border: none;
                border-radius: 4px;
                color: white;
                padding: 8px 16px;
                font-size: 13px;
            }
            
            QPushButton:hover {
                background-color: #0b5ed7;
            }
            
            QPushButton:disabled {
                background-color: #4a4a4a;
                color: #808080;
            }
            
            QPushButton:checked {
                background-color: #198754;
            }
            
            #logView {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                color: #d4d4d4;
                font-family: monospace;
                font-size: 11px;
            }
            
            #secondaryButton {
                background-color: #6c757d;
                border: none;
                border-radius: 4px;
                color: white;
                padding: 10px 24px;
                font-size: 13px;
            }
            
            #secondaryButton:hover {
                background-color: #5c636a;
            }
            
            #noteLabel {
                color: #6c757d;
                font-size: 11px;
                font-style: italic;
            }
            
            #dangerButton {
                background-color: #dc3545;
                border: none;
                border-radius: 4px;
                color: white;
                padding: 8px 16px;
                font-size: 13px;
            }
            
            #dangerButton:hover {
                background-color: #bb2d3b;
            }
        """)

    # =========================================================================
    # Navigation
    # =========================================================================

    def _navigate_to(self, view: View, add_to_history: bool = True) -> None:
        """Navigate to a specific view."""
        if add_to_history and self._current_view != view:
            self._view_history.append(self._current_view)

        self._current_view = view

        # Update stack
        view_map = {
            View.WELCOME: 0,
            View.SERVER: 1,
            View.CLIENT: 2,
        }
        self._stack.setCurrentIndex(view_map[view])

        # Update nav buttons visibility
        is_home = view == View.WELCOME
        self._back_btn.setVisible(not is_home)
        self._home_btn.setVisible(not is_home)

        # Update title
        titles = {
            View.WELCOME: "Home",
            View.SERVER: "Docker Server",
            View.CLIENT: "Transcription Client",
        }
        self._nav_title.setText(titles[view])

        # Refresh view data
        if view == View.SERVER:
            self._refresh_server_status()
        elif view == View.CLIENT:
            self._refresh_client_status()

    def _go_back(self) -> None:
        """Navigate to the previous view."""
        if self._view_history:
            prev_view = self._view_history.pop()
            self._navigate_to(prev_view, add_to_history=False)

    def _go_home(self) -> None:
        """Navigate to the welcome/home view."""
        self._view_history.clear()
        self._navigate_to(View.WELCOME, add_to_history=False)

    # =========================================================================
    # Server Operations
    # =========================================================================

    def _refresh_server_status(self) -> None:
        """Refresh the server status display."""
        # Check image
        if self._docker_manager.image_exists_locally():
            self._image_status_label.setText("✓ Available")
            self._image_status_label.setStyleSheet("color: #198754;")

            # Get image date
            image_date = self._docker_manager.get_image_created_date()
            if image_date:
                self._image_date_label.setText(image_date)
                self._image_date_label.setStyleSheet("color: #a0a0a0;")
            else:
                self._image_date_label.setText("Unknown")
                self._image_date_label.setStyleSheet("color: #a0a0a0;")
        else:
            self._image_status_label.setText("✗ Not found")
            self._image_status_label.setStyleSheet("color: #dc3545;")
            self._image_date_label.setText("N/A")
            self._image_date_label.setStyleSheet("color: #6c757d;")

        # Check server status
        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()

        status_text = {
            ServerStatus.RUNNING: "Running",
            ServerStatus.STOPPED: "Stopped",
            ServerStatus.NOT_FOUND: "Not set up",
            ServerStatus.ERROR: "Error",
        }.get(status, "Unknown")

        if mode and status == ServerStatus.RUNNING:
            status_text += f" ({mode.value})"

        self._server_status_label.setText(status_text)

        # Update button states
        is_running = status == ServerStatus.RUNNING
        container_exists = status in (ServerStatus.RUNNING, ServerStatus.STOPPED)
        self._start_local_btn.setEnabled(not is_running)
        self._start_remote_btn.setEnabled(not is_running)
        self._stop_server_btn.setEnabled(is_running)
        self._remove_container_btn.setEnabled(container_exists and not is_running)

        # Style based on status
        if status == ServerStatus.RUNNING:
            self._server_status_label.setStyleSheet("color: #198754;")
        elif status == ServerStatus.STOPPED:
            self._server_status_label.setStyleSheet("color: #ffc107;")
        else:
            self._server_status_label.setStyleSheet("color: #dc3545;")

    def _on_start_server_local(self) -> None:
        """Start server in local mode."""
        self._start_server(ServerMode.LOCAL)

    def _on_start_server_remote(self) -> None:
        """Start server in remote mode."""
        self._start_server(ServerMode.REMOTE)

    def _start_server(self, mode: ServerMode) -> None:
        """Start the Docker server."""
        self._server_status_label.setText("Starting...")
        self._start_local_btn.setEnabled(False)
        self._start_remote_btn.setEnabled(False)

        # Log progress
        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.start_server(mode=mode, progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        # Refresh status after a short delay
        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_stop_server(self) -> None:
        """Stop the Docker server."""
        self._server_status_label.setText("Stopping...")
        self._stop_server_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.stop_server(progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_remove_container(self) -> None:
        """Remove the Docker container (for recreating from fresh image)."""
        from PyQt6.QtWidgets import QMessageBox

        # Confirm with user
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Container")
        msg_box.setText("Are you sure you want to remove the container?")
        msg_box.setInformativeText(
            "This will delete the container and its data. "
            "The Docker image will be kept. You can recreate the container by starting the server again."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._server_status_label.setText("Removing...")
        self._remove_container_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_container(progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _toggle_server_logs(self, checked: bool) -> None:
        """Toggle server log visibility."""
        self._server_log_view.setVisible(checked)
        self._show_server_logs_btn.setText("▲ Hide Logs" if checked else "▼ Show Logs")

        if checked:
            # Start log polling
            self._refresh_server_logs()
            self._server_log_timer = QTimer()
            self._server_log_timer.timeout.connect(self._refresh_server_logs)
            self._server_log_timer.start(3000)  # Poll every 3 seconds
        else:
            # Stop log polling
            if self._server_log_timer:
                self._server_log_timer.stop()
                self._server_log_timer = None

    def _refresh_server_logs(self) -> None:
        """Refresh server logs."""
        logs = self._docker_manager.get_logs(lines=100)
        self._server_log_view.setPlainText(logs)
        # Scroll to bottom
        scrollbar = self._server_log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # =========================================================================
    # Client Operations
    # =========================================================================

    def _refresh_client_status(self) -> None:
        """Refresh the client status display."""
        if self._client_running:
            self._client_status_label.setText("Running")
            self._client_status_label.setStyleSheet("color: #198754;")

            # Show connection info
            host = self.config.server_host
            port = self.config.server_port
            https = "HTTPS" if self.config.use_https else "HTTP"
            self._connection_info_label.setText(f"{https}://{host}:{port}")
        else:
            self._client_status_label.setText("Stopped")
            self._client_status_label.setStyleSheet("color: #ffc107;")
            self._connection_info_label.setText("Not connected")

        # Update button states
        self._start_client_local_btn.setEnabled(not self._client_running)
        self._start_client_remote_btn.setEnabled(not self._client_running)
        self._stop_client_btn.setEnabled(self._client_running)

    def _validate_remote_settings(self) -> tuple[bool, str]:
        """
        Validate settings for remote client connection.

        Returns:
            Tuple of (is_valid, error_message)
        """
        errors = []

        # Check remote host is set and contains .ts.net
        remote_host = self.config.get("server", "remote_host", default="")
        if not remote_host:
            errors.append("Remote host is not set")
        elif ".ts.net" not in remote_host:
            errors.append("Remote host should be a Tailscale hostname (*.ts.net)")

        # Check use_remote is enabled
        if not self.config.get("server", "use_remote", default=False):
            errors.append("'Use remote server' is not enabled")

        # Check HTTPS is enabled
        if not self.config.get("server", "use_https", default=False):
            errors.append("HTTPS is not enabled (required for remote)")

        # Check authentication token
        token = self.config.get("server", "token", default="")
        if not token or not token.strip():
            errors.append("Authentication token is not set")

        # Check port is appropriate for remote (should be 8443)
        port = self.config.get("server", "port", default=8000)
        # Note: We get the expected remote port from a constant or config
        # For now, we check for 8443 as the standard remote port
        expected_remote_port = 8443
        if port != expected_remote_port:
            errors.append(f"Port should be {expected_remote_port} for remote connection (currently {port})")

        if errors:
            return False, "\n".join(errors)
        return True, ""

    def _on_start_client_local(self) -> None:
        """Start client in local mode."""
        # Configure for local connection
        self.config.set("server", "use_remote", value=False)
        self.config.set("server", "use_https", value=False)
        self.config.set("server", "port", value=8000)
        self.config.save()

        self._client_running = True
        self._refresh_client_status()
        self.start_client_requested.emit(False)  # False = local

    def _on_start_client_remote(self) -> None:
        """Start client in remote mode."""
        # Validate settings first
        is_valid, error_msg = self._validate_remote_settings()

        if not is_valid:
            from PyQt6.QtWidgets import QMessageBox

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Invalid Settings")
            msg_box.setText("Please edit your settings before starting remote client.")
            msg_box.setDetailedText(error_msg)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()
            return

        self._client_running = True
        self._refresh_client_status()
        self.start_client_requested.emit(True)  # True = remote

    def _on_stop_client(self) -> None:
        """Stop the client."""
        self._client_running = False
        self._refresh_client_status()
        self.stop_client_requested.emit()

    def _on_show_settings(self) -> None:
        """Show settings dialog."""
        self.show_settings_requested.emit()

    def _toggle_client_logs(self, checked: bool) -> None:
        """Toggle client log visibility."""
        self._client_log_view.setVisible(checked)
        self._show_client_logs_btn.setText("▲ Hide Logs" if checked else "▼ Show Logs")

    def append_client_log(self, message: str) -> None:
        """Append a message to the client log view."""
        self._client_log_view.appendPlainText(message)

    def set_client_running(self, running: bool) -> None:
        """Update client running state (called from orchestrator)."""
        self._client_running = running
        if self._current_view == View.CLIENT:
            self._refresh_client_status()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        """Handle show event."""
        super().showEvent(event)
        # Refresh current view data
        if self._current_view == View.SERVER:
            self._refresh_server_status()
        elif self._current_view == View.CLIENT:
            self._refresh_client_status()

    def closeEvent(self, event) -> None:
        """Handle close event - hide window instead of closing."""
        # Stop log timers when hiding
        if self._server_log_timer:
            self._server_log_timer.stop()
            self._server_log_timer = None
        if self._client_log_timer:
            self._client_log_timer.stop()
            self._client_log_timer = None
        # Hide the window instead of closing - app continues in tray
        event.ignore()
        self.hide()

    def force_close(self) -> None:
        """Force close the window (called when quitting app)."""
        if self._server_log_timer:
            self._server_log_timer.stop()
        if self._client_log_timer:
            self._client_log_timer.stop()
        # Actually close the window
        self.deleteLater()
