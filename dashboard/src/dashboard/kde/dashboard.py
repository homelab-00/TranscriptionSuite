"""
Dashboard - Main control window for TranscriptionSuite.

The Dashboard is the command center for managing both the Docker server
and the transcription client. It provides a unified GUI for:
- Starting/stopping the Docker server (local or remote mode)
- Starting/stopping the transcription client
- Configuring all settings
- Viewing server and client logs
"""

import logging
import asyncio
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.docker_manager import DockerManager, DockerResult, ServerStatus
from dashboard.common.icon_loader import IconLoader
from dashboard.kde.client_mixin import ClientControlMixin
from dashboard.kde.dialogs import DialogsMixin
from dashboard.kde.log_window import LogWindow
from dashboard.kde.server_mixin import ServerControlMixin
from dashboard.kde.styles import get_dashboard_stylesheet
from dashboard.kde.utils import get_assets_path

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient
    from dashboard.common.config import ClientConfig
    from dashboard.common.docker_manager import DockerPullWorker, DockerServerWorker

logger = logging.getLogger(__name__)


class View(Enum):
    """Available views in the Dashboard."""

    WELCOME = auto()
    SERVER = auto()
    CLIENT = auto()
    NOTEBOOK = auto()


class DashboardWindow(
    ServerControlMixin, ClientControlMixin, DialogsMixin, QMainWindow
):
    """
    Main Dashboard window - the command center for TranscriptionSuite.

    Provides navigation between:
    - Welcome screen (home)
    - Server management view
    - Client management view
    - Notebook view
    """

    # Signals for client operations
    start_client_requested = pyqtSignal(bool)  # True = remote, False = local
    stop_client_requested = pyqtSignal()
    show_settings_requested = pyqtSignal()

    # Signal for model state changes
    models_state_changed = pyqtSignal(bool)  # True = loaded, False = unloaded

    # Signals for Docker pull progress (thread-safe cross-thread communication)
    _pull_progress_signal = pyqtSignal(str)
    _pull_complete_signal = pyqtSignal(object)  # DockerResult

    # Signals for Docker server start progress
    _server_start_progress_signal = pyqtSignal(str)
    _server_start_complete_signal = pyqtSignal(object)  # DockerResult

    # Expose View enum for mixins
    _View = View
    _VIEWPORT_MIN_WIDTH = 650
    _SIDEBAR_EXPANDED_WIDTH = 200
    _SIDEBAR_COLLAPSED_WIDTH = 56

    def __init__(
        self,
        config: "ClientConfig",
        parent: QWidget | None = None,
        *,
        hide_on_close: bool = True,
    ):
        super().__init__(parent)
        self.config = config
        self._hide_on_close = hide_on_close
        self._docker_manager = DockerManager()
        self._icon_loader = IconLoader(self, assets_path=get_assets_path())

        # View history for back navigation
        self._view_history: list[View] = []
        self._current_view: View = View.WELCOME

        # Log windows and timers
        self._server_log_window: LogWindow | None = None
        self._client_log_window: LogWindow | None = None
        self._server_log_timer: QTimer | None = None
        self._client_log_timer: QTimer | None = None
        self._server_health_timer: QTimer | None = None
        self._home_status_timer: QTimer | None = None

        # State tracking
        self._client_running = False
        self._models_loaded = True
        self._is_local_connection = True

        # Workers for async operations
        self._pull_worker: "DockerPullWorker | None" = None
        self._server_worker: "DockerServerWorker | None" = None

        # Tray reference for orchestrator access
        self.tray: Any = None

        # Recording view (embedded)
        self._recording_view: QWidget | None = None
        # Shared API client for Notebook/Recording views (avoid leaking aiohttp sessions).
        self._notebook_api_client: "APIClient | None" = None
        self._notebook_api_client_key: tuple[Any, ...] | None = None

        self._setup_ui()
        self._apply_styles()

        # Connect signals
        self._pull_progress_signal.connect(self._update_pull_progress)
        self._pull_complete_signal.connect(self._on_pull_complete)
        self._server_start_progress_signal.connect(self._update_server_start_progress)
        self._server_start_complete_signal.connect(self._on_server_start_complete)

        # Start home status auto-refresh timer
        self._start_home_status_timer()

    def _start_home_status_timer(self) -> None:
        """Start the timer for auto-refreshing home view status."""
        if self._home_status_timer is None:
            self._home_status_timer = QTimer()
            self._home_status_timer.timeout.connect(self._refresh_home_status)
            self._home_status_timer.start(1000)
            logger.debug("Home status auto-refresh timer started")
        self._refresh_home_status()

    def _setup_ui(self) -> None:
        """Set up the main UI structure with sidebar navigation."""
        self.setWindowTitle("TranscriptionSuite")
        self.setMinimumHeight(550)

        logo_path = get_assets_path() / "logo.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        self._welcome_view = self._create_welcome_view()
        self._server_view = self._create_server_view()
        self._client_view = self._create_client_view()
        self._notebook_view = self._create_notebook_view()

        self._stack.addWidget(self._welcome_view)
        self._stack.addWidget(self._server_view)
        self._stack.addWidget(self._client_view)
        self._stack.addWidget(self._notebook_view)

        self._navigate_to(View.WELCOME, add_to_history=False)
        self._update_minimum_width()

    def _apply_styles(self) -> None:
        """Apply stylesheet to the window."""
        self.setStyleSheet(get_dashboard_stylesheet())

    def _create_sidebar(self) -> QWidget:
        """Create the vertical sidebar navigation with status lights."""
        self._sidebar = QFrame()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(self._SIDEBAR_EXPANDED_WIDTH)
        self._sidebar_expanded = True
        layout = QVBoxLayout(self._sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with collapse button
        header = QFrame()
        header.setObjectName("sidebarHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 8, 16)
        header_layout.setSpacing(4)
        self._sidebar_header_layout = header_layout

        # Title container (for collapse/expand)
        self._sidebar_title_container = QWidget()
        self._sidebar_title_container.setObjectName("sidebarTitleContainer")
        title_inner = QVBoxLayout(self._sidebar_title_container)
        title_inner.setContentsMargins(0, 0, 0, 0)
        title_inner.setSpacing(2)

        self._sidebar_title = QLabel("Transcription")
        self._sidebar_title.setObjectName("sidebarTitle")
        title_inner.addWidget(self._sidebar_title)

        self._sidebar_subtitle = QLabel("Suite")
        self._sidebar_subtitle.setObjectName("sidebarSubtitle")
        title_inner.addWidget(self._sidebar_subtitle)

        header_layout.addWidget(self._sidebar_title_container, 1)

        # Collapse toggle button
        self._collapse_btn = QPushButton("«")
        self._collapse_btn.setObjectName("collapseButton")
        self._collapse_btn.setFixedSize(24, 24)
        self._collapse_btn.setToolTip("Collapse sidebar")
        self._collapse_btn.clicked.connect(self._toggle_sidebar)
        header_layout.addWidget(
            self._collapse_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )

        layout.addWidget(header)

        # Navigation - reordered: Home, Docker Server, Client | separator | Notebook
        nav_container = QWidget()
        self._nav_container = nav_container
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(8, 8, 8, 8)
        nav_layout.setSpacing(4)

        self._nav_home_btn = self._create_sidebar_button("Home", "home")
        self._nav_home_btn.clicked.connect(self._go_home)
        nav_layout.addWidget(self._nav_home_btn)

        self._nav_server_btn = self._create_sidebar_button_with_status(
            "Docker Server", "server"
        )
        self._server_nav_btn.clicked.connect(lambda: self._navigate_to(View.SERVER))
        nav_layout.addWidget(self._nav_server_btn)

        self._nav_client_btn = self._create_sidebar_button_with_status(
            "Client", "client"
        )
        self._client_nav_btn.clicked.connect(lambda: self._navigate_to(View.CLIENT))
        nav_layout.addWidget(self._nav_client_btn)

        nav_layout.addSpacing(8)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("background-color: #2d2d2d; max-height: 1px;")
        nav_layout.addWidget(sep1)

        nav_layout.addSpacing(8)

        self._nav_notebook_btn = self._create_sidebar_button("Notebook", "notebook")
        self._nav_notebook_btn.clicked.connect(self._toggle_notebook_submenu)
        nav_layout.addWidget(self._nav_notebook_btn)

        # Notebook sub-menu (collapsible)
        self._notebook_submenu = QWidget()
        self._notebook_submenu.setObjectName("notebookSubmenu")
        submenu_layout = QVBoxLayout(self._notebook_submenu)
        submenu_layout.setContentsMargins(24, 0, 8, 0)
        submenu_layout.setSpacing(2)

        self._nav_calendar_btn = self._create_sidebar_subbutton("Calendar")
        self._nav_calendar_btn.clicked.connect(
            lambda: self._navigate_to_notebook_tab(0)
        )
        submenu_layout.addWidget(self._nav_calendar_btn)

        self._nav_search_btn = self._create_sidebar_subbutton("Search")
        self._nav_search_btn.clicked.connect(lambda: self._navigate_to_notebook_tab(1))
        submenu_layout.addWidget(self._nav_search_btn)

        self._nav_import_btn = self._create_sidebar_subbutton("Import")
        self._nav_import_btn.clicked.connect(lambda: self._navigate_to_notebook_tab(2))
        submenu_layout.addWidget(self._nav_import_btn)

        self._notebook_submenu.hide()
        nav_layout.addWidget(self._notebook_submenu)

        nav_layout.addStretch()
        layout.addWidget(nav_container, 1)

        # Bottom
        bottom = QFrame()
        bottom.setObjectName("sidebarBottom")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(8, 8, 8, 12)
        bottom_layout.setSpacing(4)

        self._nav_menu_btn = self._create_sidebar_button("Menu", "menu")
        self._nav_menu_btn.clicked.connect(self._show_hamburger_menu)
        bottom_layout.addWidget(self._nav_menu_btn)

        layout.addWidget(bottom)
        return self._sidebar

    def _toggle_sidebar(self) -> None:
        """Toggle sidebar between expanded and collapsed state."""
        self._sidebar_expanded = not self._sidebar_expanded
        if self._sidebar_expanded:
            self._sidebar.setFixedWidth(self._SIDEBAR_EXPANDED_WIDTH)
            self._collapse_btn.setText("«")
            self._collapse_btn.setToolTip("Collapse sidebar")
            self._sidebar_title_container.show()
            self._sidebar_header_layout.setContentsMargins(16, 16, 8, 16)
            self._sidebar_header_layout.setAlignment(
                self._collapse_btn,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            self._sidebar_title.show()
            self._sidebar_subtitle.show()
            # Show text on buttons
            self._nav_home_btn.setText("  Home")
            self._nav_notebook_btn.setText("  Notebook")
            self._nav_menu_btn.setText("  Menu")
            self._server_nav_btn.setText("  Docker Server")
            self._client_nav_btn.setText("  Client")
            # Show status lights
            self._server_status_light.show()
            self._client_status_light.show()
        else:
            self._sidebar.setFixedWidth(self._SIDEBAR_COLLAPSED_WIDTH)
            self._collapse_btn.setText("»")
            self._collapse_btn.setToolTip("Expand sidebar")
            self._sidebar_title_container.hide()
            self._sidebar_header_layout.setContentsMargins(0, 16, 0, 16)
            self._sidebar_header_layout.setAlignment(
                self._collapse_btn, Qt.AlignmentFlag.AlignCenter
            )
            self._sidebar_title.hide()
            self._sidebar_subtitle.hide()
            # Hide text on buttons, keep only icons
            self._nav_home_btn.setText("")
            self._nav_notebook_btn.setText("")
            self._nav_menu_btn.setText("")
            self._server_nav_btn.setText("")
            self._client_nav_btn.setText("")
            # Hide status lights when collapsed (they break the icon layout)
            self._server_status_light.hide()
            self._client_status_light.hide()
            # Hide notebook submenu when collapsed
            self._notebook_submenu.hide()
        self._update_minimum_width()

    def _update_minimum_width(self) -> None:
        """Ensure the main content viewport stays at least the minimum width."""
        self._stack.setMinimumWidth(self._VIEWPORT_MIN_WIDTH)
        sidebar_width = (
            self._SIDEBAR_EXPANDED_WIDTH
            if self._sidebar_expanded
            else self._SIDEBAR_COLLAPSED_WIDTH
        )
        self.setMinimumWidth(sidebar_width + self._VIEWPORT_MIN_WIDTH)

    def _create_sidebar_button(self, text: str, icon_name: str) -> QPushButton:
        """Create a sidebar navigation button."""
        btn = QPushButton(f"  {text}")
        btn.setObjectName("sidebarButton")
        btn.setCheckable(True)
        btn.setAutoExclusive(False)
        icon = self._icon_loader.get_icon(icon_name)
        if not icon.isNull():
            btn.setIcon(icon)
        return btn

    def _create_sidebar_subbutton(self, text: str) -> QPushButton:
        """Create a sidebar sub-navigation button (for notebook submenu)."""
        btn = QPushButton(text)
        btn.setObjectName("sidebarSubButton")
        btn.setCheckable(True)
        btn.setAutoExclusive(False)
        return btn

    def _toggle_notebook_submenu(self) -> None:
        """Toggle the notebook sub-menu visibility and navigate to notebook."""
        if self._notebook_submenu.isVisible():
            self._notebook_submenu.hide()
        else:
            self._notebook_submenu.show()
        self._navigate_to(View.NOTEBOOK)

    def _navigate_to_notebook_tab(self, tab_index: int) -> None:
        """Navigate to a specific notebook tab."""
        self._navigate_to(View.NOTEBOOK)
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            self._notebook_widget.set_tab(tab_index)
        # Update sub-button checked states
        self._nav_calendar_btn.setChecked(tab_index == 0)
        self._nav_search_btn.setChecked(tab_index == 1)
        self._nav_import_btn.setChecked(tab_index == 2)

    def _create_sidebar_button_with_status(self, text: str, icon_name: str) -> QWidget:
        """Create a sidebar navigation button with a status light indicator."""
        container = QWidget()
        container.setObjectName("sidebarButtonContainer")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(0)

        btn = QPushButton(f"  {text}")
        btn.setObjectName("sidebarButton")
        btn.setCheckable(True)
        btn.setAutoExclusive(False)
        icon = self._icon_loader.get_icon(icon_name)
        if not icon.isNull():
            btn.setIcon(icon)
        layout.addWidget(btn, 1)

        status_light = QLabel("⚪")
        status_light.setObjectName(f"{icon_name}StatusLight")
        status_light.setFixedWidth(16)
        status_light.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_light.setStyleSheet("font-size: 10px;")
        layout.addWidget(status_light)

        if icon_name == "server":
            self._server_status_light = status_light
            self._server_nav_btn = btn
        elif icon_name == "client":
            self._client_status_light = status_light
            self._client_nav_btn = btn

        container.mousePressEvent = lambda e: btn.click()
        container.setCursor(Qt.CursorShape.PointingHandCursor)
        return container

    def _update_sidebar_status_lights(self) -> None:
        """Update the status light indicators in the sidebar."""
        light_style = "font-size: 10px; color: {color};"
        if hasattr(self, "_server_status_light"):
            status = self._docker_manager.get_server_status()
            if status == ServerStatus.RUNNING:
                health = self._docker_manager.get_container_health()
                if health == "unhealthy":
                    self._server_status_light.setText("●")
                    self._server_status_light.setStyleSheet(
                        light_style.format(color="#f44336")
                    )
                elif health and health != "healthy":
                    self._server_status_light.setText("●")
                    self._server_status_light.setStyleSheet(
                        light_style.format(color="#2196f3")
                    )
                else:
                    self._server_status_light.setText("●")
                    self._server_status_light.setStyleSheet(
                        light_style.format(color="#4caf50")
                    )
            elif status == ServerStatus.STOPPED:
                self._server_status_light.setText("●")
                self._server_status_light.setStyleSheet(
                    light_style.format(color="#ff9800")
                )
            elif status == ServerStatus.NOT_FOUND:
                self._server_status_light.setText("●")
                self._server_status_light.setStyleSheet(
                    light_style.format(color="#6c757d")
                )
            else:
                self._server_status_light.setText("●")
                self._server_status_light.setStyleSheet(
                    light_style.format(color="#f44336")
                )

        if hasattr(self, "_client_status_light"):
            if self._client_running:
                self._client_status_light.setText("●")
                self._client_status_light.setStyleSheet(
                    light_style.format(color="#4caf50")
                )
            else:
                self._client_status_light.setText("●")
                self._client_status_light.setStyleSheet(
                    light_style.format(color="#ff9800")
                )

    # =========================================================================
    # Welcome View
    # =========================================================================

    def _create_welcome_view(self) -> QWidget:
        """Create the welcome/home view."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        view = QWidget()
        view.setMinimumWidth(450)
        layout = QVBoxLayout(view)
        layout.setContentsMargins(40, 30, 40, 30)

        welcome_label = QLabel("Welcome to TranscriptionSuite")
        welcome_label.setObjectName("welcomeTitle")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome_label)

        subtitle = QLabel("Manage the Docker server and transcription client")
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        logo_path = get_assets_path() / "logo_wide.png"
        if logo_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaledToWidth(
                    350, Qt.TransformationMode.SmoothTransformation
                )
                if scaled_pixmap.height() > 193:
                    scaled_pixmap = pixmap.scaledToHeight(
                        193, Qt.TransformationMode.SmoothTransformation
                    )
                logo_label.setPixmap(scaled_pixmap)
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(20)

        # Status indicators
        status_container = QWidget()
        status_container.setObjectName("homeStatusContainer")
        status_layout = QHBoxLayout(status_container)
        status_layout.setSpacing(20)

        # Server status
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

        self._home_server_status = QLabel("● Checking...")
        self._home_server_status.setObjectName("homeStatusValue")
        self._home_server_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._home_server_status.setStyleSheet("color: #6c757d;")
        server_status_layout.addWidget(self._home_server_status)

        status_layout.addWidget(server_status_widget)

        # Client status
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

        self._home_client_status = QLabel("● Stopped")
        self._home_client_status.setObjectName("homeStatusValue")
        self._home_client_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._home_client_status.setStyleSheet("color: #ff9800;")
        client_status_layout.addWidget(self._home_client_status)

        status_layout.addWidget(client_status_widget)
        layout.addWidget(status_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(12)

        # Main buttons
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setSpacing(20)

        server_btn = QPushButton("Manage\nDocker Server")
        server_btn.setObjectName("welcomeButton")
        server_btn.setProperty("accent", "server")
        server_btn.setFixedSize(180, 90)
        server_icon = self._icon_loader.get_icon("server")
        if not server_icon.isNull():
            server_btn.setIcon(server_icon)
            server_btn.setIconSize(server_btn.size() * 0.3)
        server_btn.clicked.connect(lambda: self._navigate_to(View.SERVER))
        btn_layout.addWidget(server_btn)

        client_btn = QPushButton("Manage\nClient")
        client_btn.setObjectName("welcomeButton")
        client_btn.setProperty("accent", "client")
        client_btn.setFixedSize(180, 90)
        client_icon = self._icon_loader.get_icon("client")
        if not client_icon.isNull():
            client_btn.setIcon(client_icon)
            client_btn.setIconSize(client_btn.size() * 0.3)
        client_btn.clicked.connect(lambda: self._navigate_to(View.CLIENT))
        btn_layout.addWidget(client_btn)

        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        scroll.setWidget(view)
        return scroll

    def _refresh_home_status(self) -> None:
        """Refresh the status indicators on the home view."""
        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()

        if status == ServerStatus.RUNNING:
            mode_str = f" ({mode.value})" if mode else ""
            health = self._docker_manager.get_container_health()
            if health and health != "healthy":
                if health == "unhealthy":
                    self._home_server_status.setText(f"● Unhealthy{mode_str}")
                    self._home_server_status.setStyleSheet("color: #f44336;")
                else:
                    self._home_server_status.setText(f"● Starting...{mode_str}")
                    self._home_server_status.setStyleSheet("color: #2196f3;")
            else:
                self._home_server_status.setText(f"● Running{mode_str}")
                self._home_server_status.setStyleSheet("color: #4caf50;")
        elif status == ServerStatus.STOPPED:
            self._home_server_status.setText("● Stopped")
            self._home_server_status.setStyleSheet("color: #ff9800;")
        else:
            self._home_server_status.setText("● Not set up")
            self._home_server_status.setStyleSheet("color: #6c757d;")

        if self._client_running:
            self._home_client_status.setText("● Running")
            self._home_client_status.setStyleSheet("color: #4caf50;")
        else:
            self._home_client_status.setText("● Stopped")
            self._home_client_status.setStyleSheet("color: #ff9800;")

        self._update_sidebar_status_lights()

    # =========================================================================
    # Server View
    # =========================================================================

    def _create_server_view(self) -> QWidget:
        """Create the server management view."""
        from dashboard.kde.views.server_view import create_server_view

        return create_server_view(self)

    # =========================================================================
    # Client View
    # =========================================================================

    def _create_client_view(self) -> QWidget:
        """Create the client management view."""
        from dashboard.kde.views.client_view import create_client_view

        return create_client_view(self)

    # =========================================================================
    # Notebook View
    # =========================================================================

    def _create_notebook_view(self) -> QWidget:
        """Create the Audio Notebook view."""
        from dashboard.kde.notebook_view import NotebookView

        api_client = self._get_api_client()
        self._notebook_widget = NotebookView(api_client)
        self._notebook_widget.recording_requested.connect(self._open_recording_dialog)
        return self._notebook_widget

    def _refresh_notebook_view(self) -> None:
        """Refresh the notebook view data."""
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            api_client = self._get_api_client()
            if api_client:
                self._notebook_widget.set_api_client(api_client)
            self._notebook_widget.refresh()

    def _update_notebook_api_client(self) -> None:
        """Update notebook widgets with current API client (called after connection)."""
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            api_client = self._get_api_client()
            if api_client:
                self._notebook_widget.set_api_client(api_client)
                logger.debug("Notebook API client updated after connection")

    def _open_recording_dialog(self, recording_id: int) -> None:
        """Open the recording view for a specific recording (embedded)."""
        from dashboard.kde.recording_dialog import RecordingDialog

        api_client = self._get_api_client()
        if not api_client:
            logger.error("Cannot open recording: API client not available")
            return

        # Remove existing recording view if present
        if self._recording_view is not None:
            self._stack.removeWidget(self._recording_view)
            self._recording_view.deleteLater()
            self._recording_view = None

        view = RecordingDialog(api_client, recording_id, self)
        view.recording_deleted.connect(self._on_recording_deleted)
        view.recording_updated.connect(self._on_recording_updated)
        view.close_requested.connect(self._close_recording_view)

        self._recording_view = view
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)

    def _close_recording_view(self) -> None:
        """Close the embedded recording view and return to notebook."""
        if self._recording_view is not None:
            self._stack.removeWidget(self._recording_view)
            self._recording_view.deleteLater()
            self._recording_view = None
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            self._stack.setCurrentWidget(self._notebook_view)

    def _on_recording_deleted(self, recording_id: int) -> None:
        """Handle recording deletion - refresh notebook view."""
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            self._notebook_widget.remove_recording_from_cache(recording_id)
            self._notebook_widget.refresh()

    def _on_recording_updated(self, recording_id: int, title: str) -> None:
        """Handle recording update - update cache and refresh notebook view."""
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            self._notebook_widget.update_recording_in_cache(recording_id, title)
            self._notebook_widget.refresh()

    def _get_api_client(self) -> "APIClient | None":
        """Create an API client from current config settings for notebook operations."""
        from dashboard.common.api_client import APIClient

        server_status = self._docker_manager.get_server_status()
        if server_status != ServerStatus.RUNNING:
            logger.debug("Server not running, cannot create API client")
            if self._notebook_api_client is not None:
                self._close_api_client(self._notebook_api_client)
                self._notebook_api_client = None
                self._notebook_api_client_key = None
            return None

        use_remote = self.config.get("server", "use_remote", default=False)
        use_https = self.config.get("server", "use_https", default=False)

        if use_remote:
            host = self.config.get("server", "remote_host", default="")
            port = self.config.get("server", "port", default=8443)
        else:
            host = "localhost"
            port = self.config.get("server", "port", default=8000)

        token = self.config.get("server", "token", default="")

        if not host:
            logger.debug("No host configured, cannot create API client")
            return None

        token_value = token if token else None
        key = (host, port, use_https, token_value)
        if (
            self._notebook_api_client is not None
            and self._notebook_api_client_key == key
        ):
            return self._notebook_api_client

        if self._notebook_api_client is not None:
            self._close_api_client(self._notebook_api_client)

        self._notebook_api_client = APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token_value,
        )
        self._notebook_api_client_key = key
        return self._notebook_api_client

    def _close_api_client(self, api_client: "APIClient") -> None:
        """Close an APIClient session safely from the Qt thread."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(api_client.close())
            else:
                loop.run_until_complete(api_client.close())
        except RuntimeError:
            asyncio.run(api_client.close())

    # =========================================================================
    # Navigation
    # =========================================================================

    def _navigate_to(self, view: View, add_to_history: bool = True) -> None:
        """Navigate to a specific view."""
        if add_to_history and self._current_view != view:
            self._view_history.append(self._current_view)

        self._current_view = view

        view_map = {
            View.WELCOME: 0,
            View.SERVER: 1,
            View.CLIENT: 2,
            View.NOTEBOOK: 3,
        }
        self._stack.setCurrentIndex(view_map[view])

        # Update sidebar button checked states
        self._nav_home_btn.setChecked(view == View.WELCOME)
        self._server_nav_btn.setChecked(view == View.SERVER)
        self._client_nav_btn.setChecked(view == View.CLIENT)
        self._nav_notebook_btn.setChecked(view == View.NOTEBOOK)

        if view == View.WELCOME:
            self._refresh_home_status()
        elif view == View.SERVER:
            self._refresh_server_status()
        elif view == View.CLIENT:
            self._refresh_client_status()
        elif view == View.NOTEBOOK:
            self._refresh_notebook_view()

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
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        """Handle show event."""
        super().showEvent(event)
        if self._current_view == View.SERVER:
            self._refresh_server_status()
        elif self._current_view == View.CLIENT:
            self._refresh_client_status()

    def closeEvent(self, event) -> None:
        """Handle close event - hide window instead of closing."""
        if self._hide_on_close:
            if self._server_log_timer:
                self._server_log_timer.stop()
                self._server_log_timer = None
            if self._client_log_timer:
                self._client_log_timer.stop()
                self._client_log_timer = None
            event.ignore()
            self.hide()
            return

        self.force_close()
        event.accept()

    def force_close(self) -> None:
        """Force close the window (called when quitting app)."""
        if self._server_log_timer:
            self._server_log_timer.stop()
        if self._client_log_timer:
            self._client_log_timer.stop()
        self.deleteLater()
