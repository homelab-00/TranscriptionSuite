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
    QLineEdit,
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

        self._server_health_timer: QTimer | None = None

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
        layout.setContentsMargins(40, 30, 40, 30)

        # Welcome message
        welcome_label = QLabel("Welcome to TranscriptionSuite")
        welcome_label.setObjectName("welcomeTitle")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome_label)

        subtitle = QLabel("Manage the Docker server and transcription client")
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(30)

        # Status indicators
        status_container = QWidget()
        status_container.setObjectName("homeStatusContainer")
        status_layout = QHBoxLayout(status_container)
        status_layout.setSpacing(20)

        # Server status indicator
        server_status_widget = QWidget()
        server_status_widget.setFixedWidth(180)
        server_status_layout = QVBoxLayout(server_status_widget)
        server_status_layout.setSpacing(4)
        server_status_layout.setContentsMargins(0, 0, 0, 0)
        
        server_label = QLabel("Server")
        server_label.setObjectName("homeStatusLabel")
        server_label.setProperty("accent", "server")
        server_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        server_status_layout.addWidget(server_label)
        
        self._home_server_status = QLabel("⬤ Checking...")
        self._home_server_status.setObjectName("homeStatusValue")
        self._home_server_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        server_status_layout.addWidget(self._home_server_status)
        
        status_layout.addWidget(server_status_widget)

        # Client status indicator
        client_status_widget = QWidget()
        client_status_widget.setFixedWidth(180)
        client_status_layout = QVBoxLayout(client_status_widget)
        client_status_layout.setSpacing(4)
        client_status_layout.setContentsMargins(0, 0, 0, 0)
        
        client_label = QLabel("Client")
        client_label.setObjectName("homeStatusLabel")
        client_label.setProperty("accent", "client")
        client_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        client_status_layout.addWidget(client_label)
        
        self._home_client_status = QLabel("⬤ Stopped")
        self._home_client_status.setObjectName("homeStatusValue")
        self._home_client_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        client_status_layout.addWidget(self._home_client_status)
        
        status_layout.addWidget(client_status_widget)

        layout.addWidget(status_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(12)

        # Main buttons container
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setSpacing(20)

        # Server button
        server_btn = QPushButton("Manage\nDocker Server")
        server_btn.setObjectName("welcomeButton")
        server_btn.setProperty("accent", "server")
        server_btn.setFixedSize(180, 90)
        server_btn.clicked.connect(lambda: self._navigate_to(View.SERVER))
        btn_layout.addWidget(server_btn)

        # Client button
        client_btn = QPushButton("Manage\nClient")
        client_btn.setObjectName("welcomeButton")
        client_btn.setProperty("accent", "client")
        client_btn.setFixedSize(180, 90)
        client_btn.clicked.connect(lambda: self._navigate_to(View.CLIENT))
        btn_layout.addWidget(client_btn)

        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(20)

        # Web client button (smaller)
        web_btn = QPushButton("Open Web Client")
        web_btn.setObjectName("secondaryButton")
        web_btn.setProperty("accent", "web")
        web_btn.clicked.connect(self._on_open_web_client)
        layout.addWidget(web_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Note about web client
        web_note = QLabel("Opens browser based on your client settings")
        web_note.setObjectName("noteLabel")
        web_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(web_note)

        layout.addStretch()

        return view

    def _refresh_home_status(self) -> None:
        """Refresh the status indicators on the home view."""
        # Server status
        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()
        
        if status == ServerStatus.RUNNING:
            mode_str = f" ({mode.value})" if mode else ""
            health = self._docker_manager.get_container_health()
            if health and health != "healthy":
                if health == "unhealthy":
                    self._home_server_status.setText(f"⬤ Unhealthy{mode_str}")
                    self._home_server_status.setStyleSheet("color: #dc3545;")
                else:
                    self._home_server_status.setText(f"⬤ Starting...{mode_str}")
                    self._home_server_status.setStyleSheet("color: #0d6efd;")
            else:
                self._home_server_status.setText(f"⬤ Running{mode_str}")
                self._home_server_status.setStyleSheet("color: #198754;")
        elif status == ServerStatus.STOPPED:
            self._home_server_status.setText("⬤ Stopped")
            self._home_server_status.setStyleSheet("color: #ffc107;")
        else:
            self._home_server_status.setText("⬤ Not set up")
            self._home_server_status.setStyleSheet("color: #6c757d;")

        # Client status
        if self._client_running:
            self._home_client_status.setText("⬤ Running")
            self._home_client_status.setStyleSheet("color: #198754;")
        else:
            self._home_client_status.setText("⬤ Stopped")
            self._home_client_status.setStyleSheet("color: #ffc107;")

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
        layout.setContentsMargins(40, 30, 40, 30)

        top_row = QHBoxLayout()
        top_row.addStretch()
        self._server_home_btn = QPushButton("⌂")
        self._server_home_btn.setObjectName("homeIconButton")
        self._server_home_btn.setFixedSize(36, 36)
        self._server_home_btn.clicked.connect(self._go_home)
        top_row.addWidget(self._server_home_btn)
        layout.addLayout(top_row)

        # Title section (centered like welcome)
        title = QLabel("Docker Server")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(20)

        # Status card
        status_frame = QFrame()
        status_frame.setObjectName("statusCard")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setSpacing(12)

        # Image status with inline date
        image_row = QHBoxLayout()
        image_label = QLabel("Docker Image:")
        image_label.setObjectName("statusLabel")
        image_row.addWidget(image_label)
        self._image_status_label = QLabel("Checking...")
        self._image_status_label.setObjectName("statusValue")
        image_row.addWidget(self._image_status_label)
        # Inline date (smaller)
        self._image_date_label = QLabel("")
        self._image_date_label.setObjectName("statusDateInline")
        image_row.addWidget(self._image_date_label)
        image_row.addStretch()
        status_layout.addLayout(image_row)

        # Server status
        server_row = QHBoxLayout()
        server_label = QLabel("Status:")
        server_label.setObjectName("statusLabel")
        server_row.addWidget(server_label)
        self._server_status_label = QLabel("Checking...")
        self._server_status_label.setObjectName("statusValue")
        server_row.addWidget(self._server_status_label)
        server_row.addStretch()
        status_layout.addLayout(server_row)

        layout.addWidget(status_frame)

        layout.addSpacing(25)

        # Control buttons (centered)
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setSpacing(12)

        self._start_local_btn = QPushButton("Start Local")
        self._start_local_btn.setObjectName("primaryButton")
        self._start_local_btn.clicked.connect(self._on_start_server_local)
        btn_layout.addWidget(self._start_local_btn)

        self._start_remote_btn = QPushButton("Start Remote")
        self._start_remote_btn.setObjectName("primaryButton")
        self._start_remote_btn.clicked.connect(self._on_start_server_remote)
        btn_layout.addWidget(self._start_remote_btn)

        self._stop_server_btn = QPushButton("Stop")
        self._stop_server_btn.setObjectName("stopButton")
        self._stop_server_btn.clicked.connect(self._on_stop_server)
        btn_layout.addWidget(self._stop_server_btn)

        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        # Secondary actions (centered)
        secondary_container = QWidget()
        secondary_layout = QHBoxLayout(secondary_container)
        secondary_layout.setSpacing(12)

        token_container = QWidget()
        token_layout = QHBoxLayout(token_container)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.setSpacing(8)

        token_label = QLabel("Auth Token:")
        token_label.setObjectName("statusLabel")
        token_layout.addWidget(token_label)

        self._auth_token_field = QLineEdit()
        self._auth_token_field.setObjectName("tokenField")
        self._auth_token_field.setReadOnly(True)
        self._auth_token_field.setPlaceholderText("Start Remote server to show token")
        self._auth_token_field.setMinimumWidth(320)
        token_layout.addWidget(self._auth_token_field, 1)

        secondary_layout.addWidget(token_container, 1)

        self._remove_container_btn = QPushButton("Remove Container")
        self._remove_container_btn.setObjectName("dangerButton")
        self._remove_container_btn.clicked.connect(self._on_remove_container)
        secondary_layout.addWidget(self._remove_container_btn)

        layout.addWidget(secondary_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        # Show logs toggle (centered)
        self._show_server_logs_btn = QPushButton("▼ Show Logs")
        self._show_server_logs_btn.setObjectName("toggleButton")
        self._show_server_logs_btn.setCheckable(True)
        self._show_server_logs_btn.toggled.connect(self._toggle_server_logs)
        layout.addWidget(self._show_server_logs_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Log viewer (hidden by default)
        self._server_log_view = QPlainTextEdit()
        self._server_log_view.setReadOnly(True)
        self._server_log_view.setObjectName("logView")
        self._server_log_view.setVisible(False)
        self._server_log_view.setMinimumHeight(150)
        layout.addWidget(self._server_log_view, 1)

        layout.addStretch()

        return view

    def _create_client_view(self) -> QWidget:
        """Create the client management view."""
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(40, 30, 40, 30)

        top_row = QHBoxLayout()
        top_row.addStretch()
        self._client_home_btn = QPushButton("⌂")
        self._client_home_btn.setObjectName("homeIconButton")
        self._client_home_btn.setFixedSize(36, 36)
        self._client_home_btn.clicked.connect(self._go_home)
        top_row.addWidget(self._client_home_btn)
        layout.addLayout(top_row)

        # Title section (centered like welcome)
        title = QLabel("Client")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(20)

        # Status card
        status_frame = QFrame()
        status_frame.setObjectName("statusCard")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setSpacing(12)

        # Client status
        client_row = QHBoxLayout()
        status_label = QLabel("Status:")
        status_label.setObjectName("statusLabel")
        client_row.addWidget(status_label)
        self._client_status_label = QLabel("Stopped")
        self._client_status_label.setObjectName("statusValue")
        client_row.addWidget(self._client_status_label)
        client_row.addStretch()
        status_layout.addLayout(client_row)

        # Connection info
        conn_row = QHBoxLayout()
        conn_label = QLabel("Connection:")
        conn_label.setObjectName("statusLabel")
        conn_row.addWidget(conn_label)
        self._connection_info_label = QLabel("Not connected")
        self._connection_info_label.setObjectName("statusValue")
        conn_row.addWidget(self._connection_info_label)
        conn_row.addStretch()
        status_layout.addLayout(conn_row)

        layout.addWidget(status_frame)

        layout.addSpacing(25)

        # Control buttons (centered)
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setSpacing(12)

        self._start_client_local_btn = QPushButton("Start Local")
        self._start_client_local_btn.setObjectName("primaryButton")
        self._start_client_local_btn.clicked.connect(self._on_start_client_local)
        btn_layout.addWidget(self._start_client_local_btn)

        self._start_client_remote_btn = QPushButton("Start Remote")
        self._start_client_remote_btn.setObjectName("primaryButton")
        self._start_client_remote_btn.clicked.connect(self._on_start_client_remote)
        btn_layout.addWidget(self._start_client_remote_btn)

        self._stop_client_btn = QPushButton("Stop")
        self._stop_client_btn.setObjectName("stopButton")
        self._stop_client_btn.clicked.connect(self._on_stop_client)
        self._stop_client_btn.setEnabled(False)
        btn_layout.addWidget(self._stop_client_btn)

        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        # Secondary actions (centered)
        secondary_container = QWidget()
        secondary_layout = QHBoxLayout(secondary_container)
        secondary_layout.setSpacing(12)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setObjectName("secondaryButton")
        settings_btn.clicked.connect(self._on_show_settings)
        secondary_layout.addWidget(settings_btn)

        layout.addWidget(secondary_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        # Show logs toggle (centered)
        self._show_client_logs_btn = QPushButton("▼ Show Logs")
        self._show_client_logs_btn.setObjectName("toggleButton")
        self._show_client_logs_btn.setCheckable(True)
        self._show_client_logs_btn.toggled.connect(self._toggle_client_logs)
        layout.addWidget(self._show_client_logs_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Log viewer (hidden by default)
        self._client_log_view = QPlainTextEdit()
        self._client_log_view.setReadOnly(True)
        self._client_log_view.setObjectName("logView")
        self._client_log_view.setVisible(False)
        self._client_log_view.setMinimumHeight(150)
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
            
            #homeStatusLabel {
                color: #a0a0a0;
                font-size: 12px;
            }
            
            #homeStatusValue {
                color: #ffffff;
                font-size: 13px;
            }
            
            #viewTitle {
                color: #ffffff;
                font-size: 22px;
                font-weight: bold;
            }
            
            #statusCard {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                padding: 20px;
            }
            
            #statusLabel {
                color: #a0a0a0;
                font-size: 13px;
                min-width: 100px;
            }
            
            #statusValue {
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
            }
            
            #statusDateInline {
                color: #6c757d;
                font-size: 11px;
                margin-left: 8px;
            }

            #tokenField {
                background-color: #1e1e1e;
                border: 1px solid #4c4c4c;
                border-radius: 6px;
                color: #ffffff;
                padding: 8px 10px;
                font-size: 12px;
                font-family: monospace;
            }

            #tokenField:focus {
                border-color: #0d6efd;
            }
            
            #primaryButton {
                background-color: #0d6efd;
                border: none;
                border-radius: 6px;
                color: white;
                padding: 10px 20px;
                font-size: 13px;
                min-width: 100px;
            }
            
            #primaryButton:hover {
                background-color: #0b5ed7;
            }
            
            #primaryButton:disabled {
                background-color: #4a4a4a;
                color: #808080;
            }
            
            #stopButton {
                background-color: #dc3545;
                border: none;
                border-radius: 6px;
                color: white;
                padding: 10px 20px;
                font-size: 13px;
                min-width: 80px;
            }
            
            #stopButton:hover {
                background-color: #bb2d3b;
            }
            
            #stopButton:disabled {
                background-color: #4a4a4a;
                color: #808080;
            }
            
            #secondaryButton {
                background-color: #3c3c3c;
                border: 1px solid #4c4c4c;
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
                font-size: 12px;
            }
            
            #secondaryButton:hover {
                background-color: #4c4c4c;
                border-color: #5c5c5c;
            }
            
            #toggleButton {
                background-color: transparent;
                border: 1px solid #4c4c4c;
                border-radius: 4px;
                color: #a0a0a0;
                padding: 6px 12px;
                font-size: 12px;
            }
            
            #toggleButton:hover {
                background-color: #3c3c3c;
                color: #ffffff;
            }
            
            #toggleButton:checked {
                background-color: #3c3c3c;
                color: #ffffff;
            }
            
            #logView {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                color: #d4d4d4;
                font-family: monospace;
                font-size: 11px;
            }
            
            QPushButton:disabled {
                background-color: #4a4a4a;
                color: #808080;
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

            #homeIconButton {
                background-color: #3c3c3c;
                border: 1px solid #4c4c4c;
                border-radius: 18px;
                color: #ffffff;
                font-size: 16px;
            }

            #homeIconButton:hover {
                background-color: #4c4c4c;
                border-color: #5c5c5c;
            }

            QLabel#homeStatusLabel[accent="server"] {
                color: #0d6efd;
            }

            QLabel#homeStatusLabel[accent="client"] {
                color: #fd7e14;
            }

            QPushButton#welcomeButton[accent="server"] {
                border: 2px solid #0d6efd;
            }

            QPushButton#welcomeButton[accent="server"]:hover {
                border-color: #0b5ed7;
            }

            QPushButton#welcomeButton[accent="client"] {
                border: 2px solid #fd7e14;
            }

            QPushButton#welcomeButton[accent="client"]:hover {
                border-color: #e8590c;
            }

            QPushButton#secondaryButton[accent="web"] {
                border: 1px solid #6f42c1;
            }

            QPushButton#secondaryButton[accent="web"]:hover {
                border-color: #845ef7;
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

        # Refresh view data
        if view == View.WELCOME:
            self._refresh_home_status()
        elif view == View.SERVER:
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

            # Get image date (inline, smaller)
            image_date = self._docker_manager.get_image_created_date()
            if image_date:
                self._image_date_label.setText(f"({image_date})")
            else:
                self._image_date_label.setText("")
        else:
            self._image_status_label.setText("✗ Not found")
            self._image_status_label.setStyleSheet("color: #dc3545;")
            self._image_date_label.setText("")

        # Check server status
        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()

        health: str | None = None
        mode_str = f" ({mode.value})" if mode else ""

        if status == ServerStatus.RUNNING:
            health = self._docker_manager.get_container_health()
            if health and health != "healthy":
                if health == "unhealthy":
                    status_text = f"Unhealthy{mode_str}"
                else:
                    status_text = f"Starting...{mode_str}"
            else:
                status_text = f"Running{mode_str}"
        elif status == ServerStatus.STOPPED:
            status_text = "Stopped"
        elif status == ServerStatus.NOT_FOUND:
            status_text = "Not set up"
        elif status == ServerStatus.ERROR:
            status_text = "Error"
        else:
            status_text = "Unknown"

        self._server_status_label.setText(status_text)

        if status == ServerStatus.RUNNING and mode == ServerMode.REMOTE:
            token = self._docker_manager.get_admin_token()
            if token:
                self._auth_token_field.setText(token)
                self._auth_token_field.setPlaceholderText("")
            else:
                self._auth_token_field.setText("")
                self._auth_token_field.setPlaceholderText("Token not found in logs yet")
        else:
            self._auth_token_field.setText("")
            if status == ServerStatus.RUNNING:
                self._auth_token_field.setPlaceholderText(
                    "Auth token is only used for remote mode"
                )
            else:
                self._auth_token_field.setPlaceholderText(
                    "Start Remote server to show token"
                )

        # Update button states
        is_running = status == ServerStatus.RUNNING
        container_exists = status in (ServerStatus.RUNNING, ServerStatus.STOPPED)
        self._start_local_btn.setEnabled(not is_running)
        self._start_remote_btn.setEnabled(not is_running)
        self._stop_server_btn.setEnabled(is_running)
        self._remove_container_btn.setEnabled(container_exists and not is_running)

        # Style based on status
        if status == ServerStatus.RUNNING:
            if health and health != "healthy":
                if health == "unhealthy":
                    self._server_status_label.setStyleSheet("color: #dc3545;")
                else:
                    self._server_status_label.setStyleSheet("color: #0d6efd;")
            else:
                self._server_status_label.setStyleSheet("color: #198754;")
        elif status == ServerStatus.STOPPED:
            self._server_status_label.setStyleSheet("color: #ffc107;")
        elif status == ServerStatus.NOT_FOUND:
            self._server_status_label.setStyleSheet("color: #6c757d;")
        else:
            self._server_status_label.setStyleSheet("color: #dc3545;")

        if self._server_health_timer:
            if status != ServerStatus.RUNNING or health in (None, "healthy"):
                self._server_health_timer.stop()
                self._server_health_timer = None

    def _on_start_server_local(self) -> None:
        """Start server in local mode."""
        self._start_server(ServerMode.LOCAL)

    def _on_start_server_remote(self) -> None:
        """Start server in remote mode."""
        self._start_server(ServerMode.REMOTE)

    def _start_server(self, mode: ServerMode) -> None:
        """Start the Docker server."""
        if self._server_health_timer:
            self._server_health_timer.stop()
            self._server_health_timer = None

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
            self._refresh_server_status()

            self._server_health_timer = QTimer(self)
            self._server_health_timer.timeout.connect(self._refresh_server_status)
            self._server_health_timer.start(1500)
        else:
            progress(f"Error: {result.message}")
            QTimer.singleShot(1000, self._refresh_server_status)

    def _on_stop_server(self) -> None:
        """Stop the Docker server."""
        if self._server_health_timer:
            self._server_health_timer.stop()
            self._server_health_timer = None

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

        if self._server_health_timer:
            self._server_health_timer.stop()
            self._server_health_timer = None

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
