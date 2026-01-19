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
import webbrowser
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.docker_manager import (
    DockerManager,
    DockerPullWorker,
    DockerResult,
    ServerMode,
    ServerStatus,
)
from dashboard.common.icon_loader import IconLoader

if TYPE_CHECKING:
    from dashboard.common.config import ClientConfig

logger = logging.getLogger(__name__)

# Constants for embedded resources
GITHUB_PROFILE_URL = "https://github.com/homelab-00"
GITHUB_REPO_URL = "https://github.com/homelab-00/TranscriptionSuite"


def _get_assets_path() -> Path:
    """Get the path to the assets directory, handling both dev and bundled modes."""
    import sys

    # Check if running as PyInstaller bundle
    if getattr(sys, "frozen", False):
        # Running as bundled app
        bundle_dir = Path(sys._MEIPASS)  # type: ignore
        return bundle_dir / "build" / "assets"
    else:
        # Running from source - find repo root
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "README.md").exists():
                return parent / "build" / "assets"
        # Fallback
        return Path(__file__).parent.parent.parent.parent.parent / "build" / "assets"


def _get_readme_path(dev: bool = False) -> Path | None:
    """Get the path to README.md or README_DEV.md.

    Handles multiple scenarios:
    - AppImage (looks in AppDir - checked even when not frozen)
    - PyInstaller bundle (looks in _MEIPASS)
    - Running from source (searches parent directories)
    - Current working directory (fallback)
    """
    import os
    import sys

    filename = "README_DEV.md" if dev else "README.md"

    # List of potential paths to check (in order of priority)
    paths_to_check: list[Path] = []

    # 1. AppImage root directory (APPDIR is set by AppImage runtime)
    if "APPDIR" in os.environ:
        appdir = Path(os.environ["APPDIR"])
        logger.debug(f"Checking AppImage APPDIR: {appdir}")
        paths_to_check.extend(
            [
                appdir / filename,
                appdir / "usr" / "share" / "transcriptionsuite" / filename,
            ]
        )

    # 2. PyInstaller bundle (_MEIPASS)
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)  # type: ignore
        logger.debug(f"Checking PyInstaller bundle: {bundle_dir}")
        paths_to_check.extend(
            [
                bundle_dir / filename,
                bundle_dir / "docs" / filename,
                bundle_dir / "src" / "dashboard" / filename,
            ]
        )

    # 3. Running from source - find repo root
    current = Path(__file__).resolve()
    logger.debug(f"Searching from module path: {current}")
    for parent in current.parents:
        if (parent / "README.md").exists():
            # Found project root
            paths_to_check.insert(0, parent / filename)
            logger.debug(f"Found project root at: {parent}")
            break
        paths_to_check.append(parent / filename)

    # 4. Current working directory (fallback)
    paths_to_check.append(Path.cwd() / filename)

    # Check all paths and return first existing one
    logger.debug(
        f"Searching for {filename} in paths: {[str(p) for p in paths_to_check[:5]]}..."
    )
    for path in paths_to_check:
        if path.exists():
            logger.info(f"Found {filename} at: {path}")
            return path

    logger.error(
        f"Could not find {filename} in any expected location. Searched {len(paths_to_check)} paths."
    )
    return None


class View(Enum):
    """Available views in the Dashboard."""

    WELCOME = auto()
    SERVER = auto()
    CLIENT = auto()


class LogSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for log messages with color-coded log levels."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Define text formats for different log levels
        self.formats = {}

        # DEBUG - Gray
        debug_format = QTextCharFormat()
        debug_format.setForeground(QColor("#808080"))
        self.formats["DEBUG"] = debug_format

        # INFO - Cyan
        info_format = QTextCharFormat()
        info_format.setForeground(QColor("#4EC9B0"))
        self.formats["INFO"] = info_format

        # WARNING - Yellow
        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor("#DCDCAA"))
        self.formats["WARNING"] = warning_format

        # ERROR - Red
        error_format = QTextCharFormat()
        error_format.setForeground(QColor("#F48771"))
        error_format.setFontWeight(QFont.Weight.Bold)
        self.formats["ERROR"] = error_format

        # CRITICAL - Bright Red + Bold
        critical_format = QTextCharFormat()
        critical_format.setForeground(QColor("#FF6B6B"))
        critical_format.setFontWeight(QFont.Weight.Bold)
        self.formats["CRITICAL"] = critical_format

        # Date format - Cyan
        self.date_format = QTextCharFormat()
        self.date_format.setForeground(QColor("#4EC9B0"))

        # Time format - Light blue
        self.time_format = QTextCharFormat()
        self.time_format.setForeground(QColor("#9CDCFE"))

        # Milliseconds format - Gray/blue
        self.milliseconds_format = QTextCharFormat()
        self.milliseconds_format.setForeground(QColor("#6A9FB5"))

        # Brackets format - Dim gray
        self.bracket_format = QTextCharFormat()
        self.bracket_format.setForeground(QColor("#808080"))

        # Module/file names - Light blue
        self.module_format = QTextCharFormat()
        self.module_format.setForeground(QColor("#9CDCFE"))

        # Separator (pipes, dashes) - Dim
        self.separator_format = QTextCharFormat()
        self.separator_format.setForeground(QColor("#6A6A6A"))

        # Container name - Purple
        self.container_format = QTextCharFormat()
        self.container_format.setForeground(QColor("#C586C0"))

    def highlightBlock(self, text):
        """Apply syntax highlighting to a block of text."""
        if not text:
            return

        import re

        # Highlight container name first (if present at start)
        # Server format: container-name | ...
        container_match = re.match(r"^([\w-]+)\s*(\|)", text)
        if container_match:
            # Container name
            self.setFormat(
                container_match.start(1),
                len(container_match.group(1)),
                self.container_format,
            )
            # First pipe
            self.setFormat(container_match.start(2), 1, self.separator_format)

        # Highlight timestamp patterns
        # Client format: [2026-01-07 15:35:24,321]
        # Server format: container | 2026-01-07 13:27:12 | INFO | main | ...

        # Pattern for bracketed timestamp with milliseconds [YYYY-MM-DD HH:MM:SS,mmm]
        bracket_ts_match = re.match(
            r"^(\[)(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(,\d{3})?(\])", text
        )
        if bracket_ts_match:
            # Opening bracket
            self.setFormat(bracket_ts_match.start(1), 1, self.bracket_format)
            # Date
            self.setFormat(
                bracket_ts_match.start(2),
                len(bracket_ts_match.group(2)),
                self.date_format,
            )
            # Time
            self.setFormat(
                bracket_ts_match.start(3),
                len(bracket_ts_match.group(3)),
                self.time_format,
            )
            # Milliseconds (if present)
            if bracket_ts_match.group(4):
                self.setFormat(
                    bracket_ts_match.start(4),
                    len(bracket_ts_match.group(4)),
                    self.milliseconds_format,
                )
            # Closing bracket
            self.setFormat(bracket_ts_match.start(5), 1, self.bracket_format)

        # Pattern for date/time in server logs: YYYY-MM-DD HH:MM:SS
        # This will match timestamps after the container name
        datetime_match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", text)
        if datetime_match:
            # Date
            self.setFormat(
                datetime_match.start(1),
                len(datetime_match.group(1)),
                self.date_format,
            )
            # Time
            self.setFormat(
                datetime_match.start(2),
                len(datetime_match.group(2)),
                self.time_format,
            )

        # Highlight all pipe separators
        for match in re.finditer(r"\|", text):
            self.setFormat(match.start(), 1, self.separator_format)

        # Highlight log level
        for level_name, level_format in self.formats.items():
            # Match level as a standalone word
            for match in re.finditer(rf"\b{level_name}\b", text):
                self.setFormat(match.start(), len(level_name), level_format)

        # Highlight module names (text after " - " before ":")
        # Pattern: [timestamp] LEVEL - module.name: message
        if " - " in text:
            parts = text.split(" - ")
            if len(parts) >= 2:
                module_part = parts[1]
                if ":" in module_part:
                    module_name = module_part.split(":")[0].strip()
                    module_idx = text.index(module_name)
                    self.setFormat(module_idx, len(module_name), self.module_format)


class LineNumberArea(QWidget):
    """Widget to display line numbers for a QPlainTextEdit."""

    def __init__(self, log_window):
        super().__init__(log_window._log_view)
        self.log_window = log_window

    def sizeHint(self):
        """Return the size hint for the line number area."""
        return self.log_window.lineNumberAreaWidth()

    def paintEvent(self, event):
        """Paint the line numbers."""
        self.log_window.lineNumberAreaPaintEvent(event)


class LogWindow(QMainWindow):
    """
    Separate window for displaying logs.

    This window displays logs in a terminal-like view with CaskydiaCove Nerd Font,
    syntax highlighting, and line numbers.
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        """
        Initialize the log window.

        Args:
            title: Window title (e.g., "Server Logs" or "Client Logs")
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 600)

        # Track displayed content to avoid unnecessary redraws
        self._current_line_count = 0
        self._current_content_hash = 0

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Log view with line numbers
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        # Set font to CaskydiaCove Nerd Font 9pt
        font = QFont("CaskydiaCove Nerd Font", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._log_view.setFont(font)

        # Setup line number area
        self._line_number_area = LineNumberArea(self)

        # Connect signals for line number updates
        self._log_view.blockCountChanged.connect(self._update_line_number_area_width)
        self._log_view.updateRequest.connect(self._update_line_number_area)

        self._update_line_number_area_width(0)

        # Setup syntax highlighter
        self._highlighter = LogSyntaxHighlighter(self._log_view.document())

        layout.addWidget(self._log_view)

        # Apply dark theme styling
        self._apply_styles()

        # Update line number area geometry after everything is set up
        self._update_line_number_area_geometry()

    def lineNumberAreaWidth(self):
        """Calculate the width needed for the line number area."""
        digits = 1
        max_num = max(1, self._log_view.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1

        space = 10 + self._log_view.fontMetrics().horizontalAdvance("9") * digits
        return space

    def _update_line_number_area_width(self, _):
        """Update the viewport margins to make room for line numbers."""
        self._log_view.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        """Update the line number area when scrolling or text changes."""
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )

        if rect.contains(self._log_view.viewport().rect()):
            self._update_line_number_area_width(0)

        # Update geometry to ensure it stays aligned
        self._update_line_number_area_geometry()

    def _update_line_number_area_geometry(self):
        """Update the geometry of the line number area to match the text view."""
        cr = self._log_view.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height())
        )

    def lineNumberAreaPaintEvent(self, event):
        """Paint the line numbers in the line number area."""
        painter = QPainter(self._line_number_area)
        painter.fillRect(
            event.rect(), QColor("#252526")
        )  # Darker background for line numbers

        block = self._log_view.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(
            self._log_view.blockBoundingGeometry(block)
            .translated(self._log_view.contentOffset())
            .top()
        )
        bottom = top + int(self._log_view.blockBoundingRect(block).height())

        painter.setPen(QColor("#858585"))  # Gray color for line numbers

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 5,
                    self._log_view.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + int(self._log_view.blockBoundingRect(block).height())
            block_number += 1

    def resizeEvent(self, event):
        """Handle resize events to update line number area."""
        super().resizeEvent(event)
        self._update_line_number_area_geometry()

    def append_log(self, message: str) -> None:
        """Append a log message to the view while preserving scroll position."""
        # Save current scroll position
        scrollbar = self._log_view.verticalScrollBar()
        old_value = scrollbar.value()
        was_at_bottom = old_value == scrollbar.maximum()

        # Append the message
        self._log_view.appendPlainText(message)

        # Restore scroll position (unless user was at bottom)
        if not was_at_bottom:
            scrollbar.setValue(old_value)

    def set_logs(self, logs: str) -> None:
        """Set the entire log content, only updating if content changed."""
        # Check if content actually changed using hash
        new_hash = hash(logs)
        if new_hash == self._current_content_hash:
            return  # No change, skip update entirely

        # Split into lines for comparison
        new_lines = logs.rstrip("\n").split("\n") if logs.strip() else []
        new_line_count = len(new_lines)

        # If new content has more lines and starts with same content, just append
        if new_line_count > self._current_line_count and self._current_line_count > 0:
            current_text = self._log_view.toPlainText()
            current_lines = (
                current_text.rstrip("\n").split("\n") if current_text.strip() else []
            )

            # Check if current content matches the beginning of new content
            if new_lines[: len(current_lines)] == current_lines:
                # Just append the new lines
                lines_to_add = new_lines[len(current_lines) :]
                for line in lines_to_add:
                    self.append_log(line)
                self._current_line_count = new_line_count
                self._current_content_hash = new_hash
                return

        # Content changed significantly - need full replacement
        # Save scroll position
        scrollbar = self._log_view.verticalScrollBar()
        old_value = scrollbar.value()

        # Block signals to prevent unnecessary repaints during update
        self._log_view.blockSignals(True)
        self._log_view.setPlainText(logs)
        self._log_view.blockSignals(False)

        # Restore scroll position
        scrollbar.setValue(old_value)

        # Update tracking
        self._current_line_count = new_line_count
        self._current_content_hash = new_hash

        # Force single repaint of line numbers
        self._line_number_area.update()

    def clear_logs(self) -> None:
        """Clear all logs."""
        self._log_view.clear()
        self._current_line_count = 0
        self._current_content_hash = 0

    def _apply_styles(self) -> None:
        """Apply dark theme matching the Dashboard UI."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QPlainTextEdit {
                background-color: #1e1e1e;
                border: none;
                color: #d4d4d4;
            }
        """)


class DashboardWindow(QMainWindow):
    """
    Main Dashboard window - the command center for TranscriptionSuite.

    Provides navigation between:
    - Welcome screen (home)
    - Server management view
    - Client management view
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

    def __init__(self, config: "ClientConfig", parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self._docker_manager = DockerManager()

        # Initialize icon loader for cross-platform icon support
        self._icon_loader = IconLoader(self, assets_path=_get_assets_path())

        # View history for back navigation
        self._view_history: list[View] = []
        self._current_view: View = View.WELCOME

        # Log windows
        self._server_log_window: LogWindow | None = None
        self._client_log_window: LogWindow | None = None

        # Log polling timers
        self._server_log_timer: QTimer | None = None
        self._client_log_timer: QTimer | None = None

        self._server_health_timer: QTimer | None = None
        self._home_status_timer: QTimer | None = None

        # Client state tracking
        self._client_running = False

        # Model state tracking (assume loaded initially)
        self._models_loaded = True

        # Connection type tracking (assume local initially)
        self._is_local_connection = True

        # Docker pull worker for async image pulling
        self._pull_worker: "DockerPullWorker | None" = None

        # Tray reference for orchestrator access
        self.tray: Any = None

        self._setup_ui()
        self._apply_styles()

        # Connect Docker pull signals (thread-safe cross-thread communication)
        self._pull_progress_signal.connect(self._update_pull_progress)
        self._pull_complete_signal.connect(self._on_pull_complete)

        # Start home status auto-refresh timer
        self._start_home_status_timer()

    def _start_home_status_timer(self) -> None:
        """Start the timer for auto-refreshing home view status."""
        if self._home_status_timer is None:
            self._home_status_timer = QTimer()
            self._home_status_timer.timeout.connect(self._refresh_home_status)
            self._home_status_timer.start(3000)  # Refresh every 3 seconds
            logger.debug("Home status auto-refresh timer started")

        # Do an immediate refresh
        self._refresh_home_status()

    def _setup_ui(self) -> None:
        """Set up the main UI structure."""
        self.setWindowTitle("TranscriptionSuite")
        self.setMinimumSize(700, 500)

        # Set window icon from app logo
        logo_path = _get_assets_path() / "logo.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Add navigation bar
        nav_bar = self._create_nav_bar()
        main_layout.addWidget(nav_bar)

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
        """Create the navigation bar with Home, Server, Client buttons and Help/About."""
        nav = QFrame()
        nav.setObjectName("navBar")
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        # Home button with icon
        self._nav_home_btn = QPushButton("  Home")
        self._nav_home_btn.setObjectName("navButton")
        home_icon = self._icon_loader.get_icon("home")
        if not home_icon.isNull():
            self._nav_home_btn.setIcon(home_icon)
        self._nav_home_btn.clicked.connect(self._go_home)
        layout.addWidget(self._nav_home_btn)

        # Server button with icon
        self._nav_server_btn = QPushButton("  Server")
        self._nav_server_btn.setObjectName("navButton")
        server_icon = self._icon_loader.get_icon("server")
        if not server_icon.isNull():
            self._nav_server_btn.setIcon(server_icon)
        self._nav_server_btn.clicked.connect(lambda: self._navigate_to(View.SERVER))
        layout.addWidget(self._nav_server_btn)

        # Client button with icon
        self._nav_client_btn = QPushButton("  Client")
        self._nav_client_btn.setObjectName("navButton")
        client_icon = self._icon_loader.get_icon("client")
        if not client_icon.isNull():
            self._nav_client_btn.setIcon(client_icon)
        self._nav_client_btn.clicked.connect(lambda: self._navigate_to(View.CLIENT))
        layout.addWidget(self._nav_client_btn)

        layout.addStretch()

        # Hamburger menu button (☰)
        self._nav_menu_btn = QPushButton("  ☰")
        self._nav_menu_btn.setObjectName("navButton")
        menu_icon = self._icon_loader.get_icon("menu")
        if not menu_icon.isNull():
            self._nav_menu_btn.setIcon(menu_icon)
            self._nav_menu_btn.setText("")  # Remove text if icon is available
        self._nav_menu_btn.clicked.connect(self._show_hamburger_menu)
        layout.addWidget(self._nav_menu_btn)

        return nav

    def _create_welcome_view(self) -> QWidget:
        """Create the welcome/home view."""
        # Create scroll area for the view
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        view = QWidget()
        view.setMinimumWidth(450)  # Ensure minimum width for home view content
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

        # Server button with icon (same as navbar)
        server_btn = QPushButton("Manage\nDocker Server")
        server_btn.setObjectName("welcomeButton")
        server_btn.setProperty("accent", "server")
        server_btn.setFixedSize(180, 90)
        server_icon = self._icon_loader.get_icon("server")
        if not server_icon.isNull():
            server_btn.setIcon(server_icon)
            server_btn.setIconSize(server_btn.size() * 0.3)  # 30% of button size
        server_btn.clicked.connect(lambda: self._navigate_to(View.SERVER))
        btn_layout.addWidget(server_btn)

        # Client button with icon (same as navbar)
        client_btn = QPushButton("Manage\nClient")
        client_btn.setObjectName("welcomeButton")
        client_btn.setProperty("accent", "client")
        client_btn.setFixedSize(180, 90)
        client_icon = self._icon_loader.get_icon("client")
        if not client_icon.isNull():
            client_btn.setIcon(client_icon)
            client_btn.setIconSize(client_btn.size() * 0.3)  # 30% of button size
        client_btn.clicked.connect(lambda: self._navigate_to(View.CLIENT))
        btn_layout.addWidget(client_btn)

        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()

        scroll.setWidget(view)
        return scroll

    def _refresh_home_status(self) -> None:
        """Refresh the status indicators on the home view."""
        # Server status (using Web UI colors)
        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()

        if status == ServerStatus.RUNNING:
            mode_str = f" ({mode.value})" if mode else ""
            health = self._docker_manager.get_container_health()
            if health and health != "healthy":
                if health == "unhealthy":
                    self._home_server_status.setText(f"⬤ Unhealthy{mode_str}")
                    self._home_server_status.setStyleSheet("color: #f44336;")  # error
                else:
                    self._home_server_status.setText(f"⬤ Starting...{mode_str}")
                    self._home_server_status.setStyleSheet("color: #2196f3;")  # info
            else:
                self._home_server_status.setText(f"⬤ Running{mode_str}")
                self._home_server_status.setStyleSheet("color: #4caf50;")  # success
        elif status == ServerStatus.STOPPED:
            self._home_server_status.setText("⬤ Stopped")
            self._home_server_status.setStyleSheet("color: #ff9800;")  # warning
        else:
            self._home_server_status.setText("⬤ Not set up")
            self._home_server_status.setStyleSheet("color: #6c757d;")

        # Client status
        if self._client_running:
            self._home_client_status.setText("⬤ Running")
            self._home_client_status.setStyleSheet("color: #4caf50;")  # success
        else:
            self._home_client_status.setText("⬤ Stopped")
            self._home_client_status.setStyleSheet("color: #ff9800;")  # warning

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
        # Create scroll area for the view
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        view = QWidget()
        view.setMinimumWidth(550)  # Ensure minimum width for server view content
        layout = QVBoxLayout(view)
        layout.setContentsMargins(40, 30, 40, 30)

        # Title section (centered)
        title = QLabel("Docker Server")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(20)

        # Status card (compact)
        status_frame = QFrame()
        status_frame.setObjectName("statusCard")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setSpacing(8)

        # Container status row (FIRST)
        container_row = QHBoxLayout()
        container_label = QLabel("Container:")
        container_label.setObjectName("statusLabel")
        container_row.addWidget(container_label)
        self._server_status_label = QLabel("Checking...")
        self._server_status_label.setObjectName("statusValue")
        container_row.addWidget(self._server_status_label)
        container_row.addStretch()
        status_layout.addLayout(container_row)

        # Docker Image status row (SECOND)
        image_row = QHBoxLayout()
        image_label = QLabel("Docker Image:")
        image_label.setObjectName("statusLabel")
        image_row.addWidget(image_label)
        self._image_status_label = QLabel("Checking...")
        self._image_status_label.setObjectName("statusValue")
        image_row.addWidget(self._image_status_label)
        self._image_date_label = QLabel("")
        self._image_date_label.setObjectName("statusDateInline")
        image_row.addWidget(self._image_date_label)
        self._image_size_label = QLabel("")
        self._image_size_label.setObjectName("statusDateInline")
        image_row.addWidget(self._image_size_label)
        image_row.addStretch()
        status_layout.addLayout(image_row)

        # Separator line before Auth Token
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background-color: #2d2d2d; max-height: 1px;")
        status_layout.addWidget(separator)

        # Auth Token row (LAST, after separator)
        token_row = QHBoxLayout()
        token_label = QLabel("Auth Token:")
        token_label.setObjectName("statusLabel")
        token_row.addWidget(token_label)
        self._server_token_field = QLineEdit()
        self._server_token_field.setObjectName("tokenFieldInline")
        self._server_token_field.setReadOnly(True)
        self._server_token_field.setText("Not saved yet")
        self._server_token_field.setFrame(False)
        self._server_token_field.setStyleSheet(
            "background: transparent; border: none; font-family: monospace;"
        )
        # Set exact width for 32 characters (token length) - monospace font ~8.5px per char
        self._server_token_field.setFixedWidth(272)  # 32 chars * 8.5px ≈ 272px
        token_row.addWidget(self._server_token_field)
        token_row.setSpacing(0)  # Remove spacing between widgets
        token_note = QLabel(" (for remote)")  # Leading space for minimal separation
        token_note.setObjectName("statusDateInline")
        token_note.setStyleSheet("margin-left: 0px;")  # No margin - glued to token field
        token_row.addWidget(token_note)
        token_row.addStretch()
        status_layout.addLayout(token_row)

        layout.addWidget(status_frame)

        layout.addSpacing(20)

        # Primary control buttons (centered)
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

        layout.addSpacing(20)

        # Management section header
        mgmt_header = QLabel("Management")
        mgmt_header.setObjectName("sectionHeader")
        mgmt_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mgmt_header)

        layout.addSpacing(10)

        # 3-column management layout
        mgmt_container = QWidget()
        mgmt_grid = QHBoxLayout(mgmt_container)
        mgmt_grid.setSpacing(16)
        mgmt_grid.addStretch()

        # Column 1: Container Management
        container_col = QFrame()
        container_col.setObjectName("managementGroup")
        container_col_layout = QVBoxLayout(container_col)
        container_col_layout.setSpacing(8)
        container_col_layout.setContentsMargins(12, 12, 12, 12)

        container_col_header = QLabel("Container")
        container_col_header.setObjectName("columnHeader")
        container_col_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_col_layout.addWidget(container_col_header)

        self._remove_container_btn = QPushButton("Remove")
        self._remove_container_btn.setObjectName("dangerButton")
        self._remove_container_btn.setMinimumWidth(140)
        self._remove_container_btn.setToolTip("Remove the Docker container")
        self._remove_container_btn.clicked.connect(self._on_remove_container)
        container_col_layout.addWidget(self._remove_container_btn)

        mgmt_grid.addWidget(container_col)

        # Column 2: Image Management
        image_col = QFrame()
        image_col.setObjectName("managementGroup")
        image_col_layout = QVBoxLayout(image_col)
        image_col_layout.setSpacing(8)
        image_col_layout.setContentsMargins(12, 12, 12, 12)

        image_col_header = QLabel("Image")
        image_col_header.setObjectName("columnHeader")
        image_col_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_col_layout.addWidget(image_col_header)

        self._remove_image_btn = QPushButton("Remove")
        self._remove_image_btn.setObjectName("dangerButton")
        self._remove_image_btn.setMinimumWidth(140)
        self._remove_image_btn.clicked.connect(self._on_remove_image)
        image_col_layout.addWidget(self._remove_image_btn)

        self._pull_image_btn = QPushButton("Fetch Fresh")
        self._pull_image_btn.setObjectName("primaryButton")
        self._pull_image_btn.setMinimumWidth(140)
        self._pull_image_btn.clicked.connect(self._on_pull_fresh_image)
        image_col_layout.addWidget(self._pull_image_btn)

        # Cancel button for aborting image pull (initially hidden)
        self._pull_cancel_btn = QPushButton("Cancel Pull")
        self._pull_cancel_btn.setObjectName("dangerButton")
        self._pull_cancel_btn.setMinimumWidth(140)
        self._pull_cancel_btn.clicked.connect(self._on_cancel_pull)
        self._pull_cancel_btn.setVisible(False)
        image_col_layout.addWidget(self._pull_cancel_btn)

        mgmt_grid.addWidget(image_col)

        # Column 3: Volumes Management
        volumes_col = QFrame()
        volumes_col.setObjectName("managementGroup")
        volumes_col_layout = QVBoxLayout(volumes_col)
        volumes_col_layout.setSpacing(8)
        volumes_col_layout.setContentsMargins(12, 12, 12, 12)

        volumes_col_header = QLabel("Volumes")
        volumes_col_header.setObjectName("columnHeader")
        volumes_col_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        volumes_col_layout.addWidget(volumes_col_header)

        self._remove_data_volume_btn = QPushButton("Remove Data")
        self._remove_data_volume_btn.setObjectName("dangerButton")
        self._remove_data_volume_btn.setMinimumWidth(140)
        self._remove_data_volume_btn.clicked.connect(self._on_remove_data_volume)
        volumes_col_layout.addWidget(self._remove_data_volume_btn)

        self._remove_models_volume_btn = QPushButton("Remove Models")
        self._remove_models_volume_btn.setObjectName("dangerButton")
        self._remove_models_volume_btn.setMinimumWidth(140)
        self._remove_models_volume_btn.clicked.connect(self._on_remove_models_volume)
        volumes_col_layout.addWidget(self._remove_models_volume_btn)

        mgmt_grid.addWidget(volumes_col)
        mgmt_grid.addStretch()

        layout.addWidget(mgmt_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(20)

        # Volumes status panel
        volumes_frame = QFrame()
        volumes_frame.setObjectName("volumesStatusCard")
        volumes_layout = QVBoxLayout(volumes_frame)
        volumes_layout.setSpacing(10)
        volumes_layout.setContentsMargins(16, 12, 16, 12)

        # Data volume row
        data_volume_row = QHBoxLayout()
        data_volume_label = QLabel("Data Volume:")
        data_volume_label.setObjectName("statusLabel")
        data_volume_label.setMinimumWidth(110)
        data_volume_row.addWidget(data_volume_label)

        self._data_volume_status = QLabel("Not found")
        self._data_volume_status.setObjectName("statusValue")
        data_volume_row.addWidget(self._data_volume_status)

        self._data_volume_size = QLabel("")
        self._data_volume_size.setObjectName("statusDateInline")
        data_volume_row.addWidget(self._data_volume_size)

        data_volume_row.addStretch()
        volumes_layout.addLayout(data_volume_row)

        # Models volume row
        models_volume_row = QHBoxLayout()
        models_volume_label = QLabel("Models Volume:")
        models_volume_label.setObjectName("statusLabel")
        models_volume_label.setMinimumWidth(110)
        models_volume_row.addWidget(models_volume_label)

        self._models_volume_status = QLabel("Not found")
        self._models_volume_status.setObjectName("statusValue")
        models_volume_row.addWidget(self._models_volume_status)

        self._models_volume_size = QLabel("")
        self._models_volume_size.setObjectName("statusDateInline")
        models_volume_row.addWidget(self._models_volume_size)

        models_volume_row.addStretch()
        volumes_layout.addLayout(models_volume_row)

        # Models list (shown when container is running)
        self._models_list_label = QLabel("")
        self._models_list_label.setObjectName("modelsListLabel")
        self._models_list_label.setWordWrap(True)
        self._models_list_label.setStyleSheet(
            "color: #a0a0a0; font-size: 11px; margin-left: 110px;"
        )
        self._models_list_label.setVisible(False)
        volumes_layout.addWidget(self._models_list_label)

        # Volume path info
        volumes_path = self._docker_manager.get_volumes_base_path()
        path_label = QLabel(f"Path: {volumes_path}")
        path_label.setObjectName("volumePathLabel")
        path_label.setStyleSheet("color: #6c757d; font-size: 10px; margin-top: 4px;")
        volumes_layout.addWidget(path_label)

        layout.addWidget(volumes_frame)

        layout.addSpacing(15)

        # Show logs button (centered)
        self._show_server_logs_btn = QPushButton("Show Logs")
        self._show_server_logs_btn.setObjectName("secondaryButton")
        logs_icon = self._icon_loader.get_icon("logs")
        if not logs_icon.isNull():
            self._show_server_logs_btn.setIcon(logs_icon)
        self._show_server_logs_btn.clicked.connect(self._toggle_server_logs)
        layout.addWidget(
            self._show_server_logs_btn, alignment=Qt.AlignmentFlag.AlignCenter
        )

        layout.addStretch()

        scroll.setWidget(view)
        return scroll

    def _create_client_view(self) -> QWidget:
        """Create the client management view."""
        # Create scroll area for the view
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        view = QWidget()
        view.setMinimumWidth(450)  # Ensure minimum width for client view content
        layout = QVBoxLayout(view)
        layout.setContentsMargins(40, 30, 40, 30)

        # Title section (centered)
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

        # Web client button
        web_btn = QPushButton("Open Web Client")
        web_btn.setObjectName("secondaryButton")
        web_btn.setProperty("accent", "web")
        web_btn.clicked.connect(self._on_open_web_client)
        layout.addWidget(web_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        # Show logs button (centered)
        self._show_client_logs_btn = QPushButton("Show Logs")
        self._show_client_logs_btn.setObjectName("secondaryButton")
        logs_icon = self._icon_loader.get_icon("logs")
        if not logs_icon.isNull():
            self._show_client_logs_btn.setIcon(logs_icon)
        self._show_client_logs_btn.clicked.connect(self._toggle_client_logs)
        layout.addWidget(
            self._show_client_logs_btn, alignment=Qt.AlignmentFlag.AlignCenter
        )

        layout.addSpacing(15)

        # Model management button (unload/reload)
        self._unload_models_btn = QPushButton("Unload All Models")
        self._unload_models_btn.setObjectName("secondaryButton")
        self._unload_models_btn.setToolTip(
            "Unload transcription models to free GPU memory"
        )
        # Start disabled (gray) until server is healthy
        self._unload_models_btn.setEnabled(False)
        # Use dark gray disabled state
        self._unload_models_btn.setStyleSheet(
            "QPushButton { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
            "border-radius: 6px; color: #606060; padding: 10px 20px; }"
            "QPushButton:disabled { background-color: #2d2d2d; border-color: #3d3d3d; color: #606060; }"
        )
        self._unload_models_btn.clicked.connect(self._on_toggle_models)
        layout.addWidget(self._unload_models_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(20)

        # Auto-add to Audio Notebook toggle
        notebook_frame = QFrame()
        notebook_frame.setObjectName("statusCard")
        notebook_frame.setStyleSheet(
            "QFrame#statusCard { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
            "border-radius: 8px; padding: 12px; }"
        )
        notebook_layout = QHBoxLayout(notebook_frame)
        notebook_layout.setContentsMargins(16, 12, 16, 12)

        notebook_label = QLabel("Auto-add to Audio Notebook:")
        notebook_label.setObjectName("statusLabel")
        notebook_label.setStyleSheet("color: #e0e0e0;")
        notebook_layout.addWidget(notebook_label)

        notebook_layout.addStretch()

        self._notebook_toggle_btn = QPushButton("Disabled")
        self._notebook_toggle_btn.setCheckable(True)
        auto_notebook = self.config.get_server_config(
            "longform_recording", "auto_add_to_audio_notebook", default=False
        )
        self._notebook_toggle_btn.setChecked(auto_notebook)
        self._notebook_toggle_btn.setText("Enabled" if auto_notebook else "Disabled")
        self._notebook_toggle_btn.setToolTip(
            "When enabled, recordings are saved to Audio Notebook with diarization\\n"
            "instead of copying transcription to clipboard.\\n"
            "Can only be changed when both server and client are stopped."
        )
        self._notebook_toggle_btn.clicked.connect(self._on_notebook_toggle)
        self._update_notebook_toggle_style()
        notebook_layout.addWidget(self._notebook_toggle_btn)

        layout.addWidget(notebook_frame)

        layout.addSpacing(15)

        # Preview Transcription toggle
        preview_toggle_frame = QFrame()
        preview_toggle_frame.setObjectName("statusCard")
        preview_toggle_frame.setStyleSheet(
            "QFrame#statusCard { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
            "border-radius: 8px; padding: 12px; }"
        )
        preview_toggle_layout = QHBoxLayout(preview_toggle_frame)
        preview_toggle_layout.setContentsMargins(16, 12, 16, 12)

        preview_label = QLabel("Live Transcriber:")
        preview_label.setObjectName("statusLabel")
        preview_label.setStyleSheet("color: #e0e0e0;")
        preview_toggle_layout.addWidget(preview_label)

        preview_toggle_layout.addStretch()

        self._preview_toggle_btn = QPushButton("Disabled")
        self._preview_toggle_btn.setCheckable(True)
        # Read live transcriber enabled setting
        live_transcriber_enabled = self.config.get_server_config(
            "transcription_options", "enable_live_transcriber", default=False
        )
        self._preview_toggle_btn.setChecked(live_transcriber_enabled)
        self._preview_toggle_btn.setText(
            "Enabled" if live_transcriber_enabled else "Disabled"
        )
        self._preview_toggle_btn.setToolTip(
            "Enable live transcriber during recording.\n"
            "Uses a faster model for real-time feedback.\n"
            "Only editable when server is stopped."
        )
        self._preview_toggle_btn.clicked.connect(self._on_live_transcriber_toggle)
        self._update_live_transcriber_toggle_style()
        preview_toggle_layout.addWidget(self._preview_toggle_btn)

        layout.addWidget(preview_toggle_frame)

        # Live Mode Language selector
        language_frame = QFrame()
        language_frame.setObjectName("statusCard")
        language_frame.setStyleSheet(
            "QFrame#statusCard { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
            "border-radius: 8px; padding: 12px; }"
        )
        language_layout = QHBoxLayout(language_frame)
        language_layout.setContentsMargins(16, 12, 16, 12)

        language_label = QLabel("Live Mode Language:")
        language_label.setObjectName("statusLabel")
        language_label.setStyleSheet("color: #e0e0e0;")
        language_layout.addWidget(language_label)

        language_layout.addStretch()

        # Language combo box
        self._live_language_combo = QComboBox()
        self._live_language_combo.setMinimumWidth(180)
        self._live_language_combo.setStyleSheet(
            "QComboBox { background-color: #252526; border: 1px solid #3d3d3d; "
            "border-radius: 4px; padding: 6px 12px; color: #e0e0e0; font-size: 12px; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
            "QComboBox::down-arrow { image: none; border-left: 5px solid transparent; "
            "border-right: 5px solid transparent; border-top: 6px solid #a0a0a0; margin-right: 8px; }"
            "QComboBox QAbstractItemView { background-color: #252526; border: 1px solid #3d3d3d; "
            "color: #e0e0e0; selection-background-color: #3d3d3d; }"
        )
        # Add language options (Whisper-supported languages)
        languages = [
            ("Auto-detect", ""),
            ("English", "en"),
            ("Greek", "el"),
            ("German", "de"),
            ("French", "fr"),
            ("Spanish", "es"),
            ("Italian", "it"),
            ("Portuguese", "pt"),
            ("Russian", "ru"),
            ("Japanese", "ja"),
            ("Korean", "ko"),
            ("Chinese", "zh"),
            ("Arabic", "ar"),
            ("Hindi", "hi"),
            ("Dutch", "nl"),
            ("Polish", "pl"),
            ("Turkish", "tr"),
            ("Ukrainian", "uk"),
            ("Vietnamese", "vi"),
            ("Thai", "th"),
        ]
        for name, code in languages:
            self._live_language_combo.addItem(name, code)

        # Load saved value
        saved_language = self.config.get_server_config(
            "live_transcriber", "live_language", default="en"
        )
        for i in range(self._live_language_combo.count()):
            if self._live_language_combo.itemData(i) == saved_language:
                self._live_language_combo.setCurrentIndex(i)
                break

        self._live_language_combo.setToolTip(
            "Force a specific language for Live Mode.\\n"
            "Recommended: Select your language for better accuracy.\\n"
            "Auto-detect works poorly with short utterances.\\n"
            "Only editable when server is stopped."
        )
        self._live_language_combo.currentIndexChanged.connect(
            self._on_live_language_changed
        )
        language_layout.addWidget(self._live_language_combo)

        layout.addWidget(language_frame)

        layout.addSpacing(10)

        # Collapsible preview display section (Live Mode)
        preview_display_frame = QFrame()
        preview_display_frame.setObjectName("previewCard")
        preview_display_frame.setStyleSheet(
            "QFrame#previewCard { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
            "border-radius: 8px; padding: 8px; }"
        )
        preview_display_layout = QVBoxLayout(preview_display_frame)
        preview_display_layout.setContentsMargins(12, 8, 12, 8)
        preview_display_layout.setSpacing(8)

        # Header with collapse toggle
        preview_header = QHBoxLayout()
        self._preview_collapse_btn = QPushButton("\u25bc")  # Down arrow (expanded)
        self._preview_collapse_btn.setFixedSize(24, 24)
        self._preview_collapse_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; "
            "color: #808080; font-size: 12px; }"
            "QPushButton:hover { color: #e0e0e0; }"
        )
        self._preview_collapse_btn.clicked.connect(self._toggle_live_preview_collapse)
        preview_header.addWidget(self._preview_collapse_btn)

        preview_title = QLabel("Live Preview")
        preview_title.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_display_layout.addLayout(preview_header)

        # Collapsible content
        self._preview_content = QWidget()
        preview_content_layout = QVBoxLayout(self._preview_content)
        preview_content_layout.setContentsMargins(0, 4, 0, 0)
        preview_content_layout.setSpacing(8)

        # Scrollable text area for live transcription history (~10 lines)
        self._live_transcription_text_edit = QPlainTextEdit()
        self._live_transcription_text_edit.setReadOnly(True)
        self._live_transcription_text_edit.setPlaceholderText(
            "Start Live Mode to see transcription..."
        )
        self._live_transcription_text_edit.setMinimumHeight(
            180
        )  # ~10 lines at standard font
        self._live_transcription_text_edit.setMaximumHeight(250)
        self._live_transcription_text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #252526; border-radius: 4px; "
            "padding: 8px; color: #e0e0e0; font-family: 'Inter', sans-serif; "
            "font-size: 13px; border: none; }"
            "QPlainTextEdit::placeholder { color: #808080; }"
        )
        # Store history of transcription lines
        self._live_transcription_history: list[str] = []
        preview_content_layout.addWidget(self._live_transcription_text_edit)

        preview_display_layout.addWidget(self._preview_content)

        layout.addWidget(preview_display_frame)

        layout.addStretch()

        scroll.setWidget(view)
        return scroll

    def _apply_styles(self) -> None:
        """Apply stylesheet to the window - matching Web UI colors."""
        # Web UI color palette:
        # background: #0a0a0a (darker), surface: #1e1e1e, surface-light: #2d2d2d
        # primary: #90caf9, primary-dark: #42a5f5
        # error: #f44336, success: #4caf50, warning: #ff9800, info: #2196f3
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0a0a0a;
            }

            QScrollArea {
                background-color: #0a0a0a;
                border: none;
            }

            QScrollBar:vertical {
                background-color: #1e1e1e;
                width: 10px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background-color: #3d3d3d;
                min-height: 30px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #4d4d4d;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }

            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }

            QScrollBar:horizontal {
                background-color: #1e1e1e;
                height: 10px;
                margin: 0;
            }

            QScrollBar::handle:horizontal {
                background-color: #3d3d3d;
                min-width: 30px;
                border-radius: 5px;
            }

            QScrollBar::handle:horizontal:hover {
                background-color: #4d4d4d;
            }

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }

            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }

            #navBar {
                background-color: #1e1e1e;
                border-bottom: 1px solid #2d2d2d;
            }

            #navButton {
                background-color: transparent;
                border: none;
                color: #a0a0a0;
                padding: 5px 10px;
                font-size: 13px;
            }

            #navButton:hover {
                color: #90caf9;
                background-color: #2d2d2d;
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
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                color: #ffffff;
                font-size: 14px;
                padding: 20px;
            }

            #welcomeButton:hover {
                background-color: #2d2d2d;
                border-color: #3d3d3d;
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
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                padding: 20px;
            }

            #managementGroup {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }

            #columnHeader {
                color: #90caf9;
                font-size: 13px;
                font-weight: bold;
                margin-bottom: 6px;
            }

            #volumesStatusCard {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
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
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                padding: 8px 10px;
                font-size: 12px;
                font-family: monospace;
            }

            #tokenField:focus {
                border-color: #90caf9;
            }

            #primaryButton {
                background-color: #90caf9;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 10px 20px;
                font-size: 13px;
                min-width: 100px;
                font-weight: 500;
            }

            #primaryButton:hover {
                background-color: #42a5f5;
            }

            #primaryButton:disabled {
                background-color: #2d2d2d;
                color: #606060;
            }

            #stopButton {
                background-color: #f44336;
                border: none;
                border-radius: 6px;
                color: white;
                padding: 10px 20px;
                font-size: 13px;
                min-width: 80px;
            }

            #stopButton:hover {
                background-color: #d32f2f;
            }

            #stopButton:disabled {
                background-color: #2d2d2d;
                color: #606060;
            }

            #secondaryButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
                font-size: 12px;
            }

            #secondaryButton:hover {
                background-color: #3d3d3d;
                border-color: #4d4d4d;
            }

            #toggleButton {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #a0a0a0;
                padding: 6px 12px;
                font-size: 12px;
            }

            #toggleButton:hover {
                background-color: #2d2d2d;
                color: #ffffff;
            }

            #toggleButton:checked {
                background-color: #2d2d2d;
                color: #ffffff;
            }

            #logView {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
                color: #d4d4d4;
                font-family: monospace;
                font-size: 11px;
            }

            QPushButton:disabled {
                background-color: #2d2d2d;
                color: #606060;
            }

            #noteLabel {
                color: #6c757d;
                font-size: 11px;
                font-style: italic;
            }

            #webNoteLabel {
                color: #808080;
                font-size: 11px;
                font-style: italic;
            }

            #dangerButton {
                background-color: #f44336;
                border: none;
                border-radius: 4px;
                color: white;
                padding: 8px 16px;
                font-size: 13px;
            }

            #dangerButton:hover {
                background-color: #d32f2f;
            }

            #dangerButton:disabled {
                background-color: #2d2d2d;
                color: #606060;
            }

            #homeIconButton {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 18px;
                color: #ffffff;
                font-size: 16px;
            }

            #homeIconButton:hover {
                background-color: #2d2d2d;
                border-color: #3d3d3d;
            }

            QLabel#homeStatusLabel[accent="server"] {
                color: #6B8DD9;
            }

            QLabel#homeStatusLabel[accent="client"] {
                color: #D070D0;
            }

            QPushButton#welcomeButton[accent="server"] {
                border: 2px solid #7BA9F5;
            }

            QPushButton#welcomeButton[accent="server"]:hover {
                border-color: #A0C5FF;
            }

            QPushButton#welcomeButton[accent="client"] {
                border: 2px solid #E78FF5;
            }

            QPushButton#welcomeButton[accent="client"]:hover {
                border-color: #F5B3FF;
            }

            QPushButton#secondaryButton[accent="web"] {
                border: 1px solid #4DD0E1;
            }

            QPushButton#secondaryButton[accent="web"]:hover {
                border-color: #80DEEA;
            }

            #sectionHeader {
                color: #a0a0a0;
                font-size: 14px;
                font-weight: bold;
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
        # Check image (using Web UI colors)
        if self._docker_manager.image_exists_locally():
            self._image_status_label.setText("✓ Available")
            self._image_status_label.setStyleSheet("color: #4caf50;")  # success

            # Get image date (inline, smaller)
            image_date = self._docker_manager.get_image_created_date()
            if image_date:
                self._image_date_label.setText(f"({image_date})")
            else:
                self._image_date_label.setText("")

            # Get image size (inline, smaller)
            image_size = self._docker_manager.get_image_size()
            if image_size:
                self._image_size_label.setText(f"{image_size}")
            else:
                self._image_size_label.setText("")
        else:
            self._image_status_label.setText("✗ Not found")
            self._image_status_label.setStyleSheet("color: #f44336;")  # error
            self._image_date_label.setText("")
            self._image_size_label.setText("")

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

        # Update auth token display - always check logs when running to catch new tokens
        if status == ServerStatus.RUNNING:
            # Force check logs for latest token (clears cache first)
            import re

            logs = self._docker_manager.get_logs(lines=1000)
            new_token = None
            for line in logs.split("\n"):
                if "Admin Token:" in line:
                    match = re.search(r"Admin Token:\s*(\S+)", line)
                    if match:
                        new_token = match.group(1)
                        # Update cache if token changed
                        if new_token != self._docker_manager._cached_auth_token:
                            self._docker_manager._cached_auth_token = new_token
                            self._docker_manager.save_server_auth_token(new_token)
                            logger.info("Detected new admin token from logs")

            # Display the token (either new or cached)
            token = new_token or self._docker_manager.get_admin_token(check_logs=False)
        else:
            # When not running, just use cached token
            token = self._docker_manager.get_admin_token(check_logs=False)

        if token:
            self._server_token_field.setText(token)
            self._server_token_field.setStyleSheet(
                "background: transparent; border: none; color: #4caf50;"
            )  # success
        else:
            self._server_token_field.setText("Not saved yet")
            self._server_token_field.setStyleSheet(
                "background: transparent; border: none; color: #6c757d;"
            )

        # Update button states
        is_running = status == ServerStatus.RUNNING
        container_exists = status in (ServerStatus.RUNNING, ServerStatus.STOPPED)
        image_exists = self._docker_manager.image_exists_locally()

        self._start_local_btn.setEnabled(not is_running)
        self._start_remote_btn.setEnabled(not is_running)
        self._stop_server_btn.setEnabled(is_running)
        self._remove_container_btn.setEnabled(container_exists and not is_running)

        # Docker management buttons with tooltips
        self._remove_image_btn.setEnabled(not container_exists and image_exists)
        if container_exists:
            self._remove_image_btn.setToolTip(
                "Remove container first before removing image"
            )
        else:
            self._remove_image_btn.setToolTip("Remove the Docker image")

        if is_running:
            self._remove_container_btn.setToolTip("Stop container first before removing")
        else:
            self._remove_container_btn.setToolTip("Remove the Docker container")

        self._pull_image_btn.setEnabled(True)  # Can always pull
        self._remove_data_volume_btn.setEnabled(not is_running)
        self._remove_models_volume_btn.setEnabled(not is_running)

        # Style based on status (using Web UI colors)
        if status == ServerStatus.RUNNING:
            if health and health != "healthy":
                if health == "unhealthy":
                    self._server_status_label.setStyleSheet("color: #f44336;")  # error
                else:
                    self._server_status_label.setStyleSheet("color: #2196f3;")  # info
            else:
                self._server_status_label.setStyleSheet("color: #4caf50;")  # success
        elif status == ServerStatus.STOPPED:
            self._server_status_label.setStyleSheet("color: #ff9800;")  # warning
        elif status == ServerStatus.NOT_FOUND:
            self._server_status_label.setStyleSheet("color: #6c757d;")
        else:
            self._server_status_label.setStyleSheet("color: #f44336;")  # error

        if self._server_health_timer:
            if status != ServerStatus.RUNNING or health in (None, "healthy"):
                self._server_health_timer.stop()
                self._server_health_timer = None

        # Update models button state when server status changes
        self._update_models_button_state()

        # Update notebook toggle state when server status changes
        server_stopped = status != ServerStatus.RUNNING
        self._notebook_toggle_btn.setEnabled(not self._client_running and server_stopped)
        self._update_notebook_toggle_style()

        # Update live transcriber toggle state when server status changes
        if hasattr(self, "_preview_toggle_btn"):
            self._preview_toggle_btn.setEnabled(server_stopped)
            self._update_live_transcriber_toggle_style()

        # Update live mode language dropdown state when server status changes
        if hasattr(self, "_live_language_combo"):
            self._live_language_combo.setEnabled(server_stopped)

        # Update volumes status
        data_volume_exists = self._docker_manager.volume_exists(
            "transcription-suite-data"
        )
        models_volume_exists = self._docker_manager.volume_exists(
            "transcription-suite-models"
        )

        if data_volume_exists:
            self._data_volume_status.setText("✓ Exists")
            self._data_volume_status.setStyleSheet("color: #4caf50;")  # success
            # Get volume size
            size = self._docker_manager.get_volume_size("transcription-suite-data")
            if size:
                self._data_volume_size.setText(f"({size})")
            else:
                self._data_volume_size.setText("")
        else:
            self._data_volume_status.setText("✗ Not found")
            self._data_volume_status.setStyleSheet("color: #6c757d;")
            self._data_volume_size.setText("")

        if models_volume_exists:
            self._models_volume_status.setText("✓ Exists")
            self._models_volume_status.setStyleSheet("color: #4caf50;")  # success
            # Get volume size
            size = self._docker_manager.get_volume_size("transcription-suite-models")
            if size:
                self._models_volume_size.setText(f"({size})")
            else:
                self._models_volume_size.setText("")

            # Update models list (only when container is running)
            if is_running:
                models = self._docker_manager.list_downloaded_models()
                if models:
                    models_lines = [f"  • {m['name']} ({m['size']})" for m in models]
                    models_text = "Downloaded:\n" + "\n".join(models_lines)
                    self._models_list_label.setText(models_text)
                    self._models_list_label.setVisible(True)
                else:
                    self._models_list_label.setText("No models downloaded yet")
                    self._models_list_label.setVisible(True)
            else:
                self._models_list_label.setText("Start container to view models")
                self._models_list_label.setVisible(True)
        else:
            self._models_volume_status.setText("✗ Not found")
            self._models_volume_status.setStyleSheet("color: #6c757d;")
            self._models_volume_size.setText("")
            self._models_list_label.setVisible(False)

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
            # Force refresh token from logs for new/restarted container
            QTimer.singleShot(2000, self._docker_manager.refresh_admin_token)
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
            # Clear server logs window when server is stopped
            if self._server_log_window is not None:
                self._server_log_window.clear_logs()
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
            # Clear server logs window when container is removed
            if self._server_log_window is not None:
                self._server_log_window.clear_logs()
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_remove_image(self) -> None:
        """Remove the Docker server image."""
        from PyQt6.QtWidgets import QMessageBox

        # Confirm with user
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Docker Image")
        msg_box.setText("Are you sure you want to remove the Docker image?")
        msg_box.setInformativeText(
            "This will delete the server Docker image from your system. "
            "The container must be removed first. "
            "You can re-download the image using 'Fetch Fresh Image'."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._image_status_label.setText("Removing...")
        self._remove_image_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_image(progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_pull_fresh_image(self) -> None:
        """Pull a fresh copy of the Docker server image (async, non-blocking)."""
        from PyQt6.QtWidgets import QMessageBox

        # Prevent starting another pull if one is already in progress
        if self._pull_worker is not None and self._pull_worker.is_alive():
            logger.warning("Docker pull already in progress")
            return

        # Inform user this may take time
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Fetch Fresh Image")
        msg_box.setText("Pull a fresh copy of the Docker image?")
        msg_box.setInformativeText(
            "This will download the latest server image (~15GB). "
            "This may take several minutes to hours depending on your connection speed.\n\n"
            "The download runs in the background - you can continue using the app."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        msg_box.setIcon(QMessageBox.Icon.Information)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        # Update UI for pull in progress
        self._image_status_label.setText("Pulling...")
        self._pull_image_btn.setEnabled(False)
        self._pull_cancel_btn.setVisible(True)

        def on_progress(msg: str) -> None:
            """Called from worker thread - emit signal for thread-safe UI update."""
            self._pull_progress_signal.emit(msg)

        def on_complete(result: DockerResult) -> None:
            """Called from worker thread - emit signal for thread-safe UI update."""
            logger.debug(f"Emitting pull complete signal: {result.message}")
            self._pull_complete_signal.emit(result)

        # Start async pull
        self._pull_worker = self._docker_manager.start_pull_worker(
            progress_callback=on_progress,
            complete_callback=on_complete,
        )
        logger.info("Started async Docker image pull")

    def _update_pull_progress(self, msg: str) -> None:
        """Update UI with pull progress (called on main thread)."""
        logger.info(msg)
        # Update status label with latest message
        self._image_status_label.setText(f"Pulling: {msg[:50]}...")

    def _on_pull_complete(self, result: DockerResult) -> None:
        """Handle pull completion (called on main thread)."""
        logger.info(
            f"Pull complete callback: success={result.success}, message={result.message}"
        )
        self._pull_worker = None

        # Reset UI state - ALWAYS do this regardless of result
        self._pull_image_btn.setEnabled(True)
        self._pull_cancel_btn.setVisible(False)
        self._pull_cancel_btn.setEnabled(True)  # Re-enable for next time

        if result.success:
            self._image_status_label.setText("Pull complete!")
            logger.info("Docker image pull completed successfully")
        else:
            # Show more specific message for cancellation
            if "cancelled" in result.message.lower():
                self._image_status_label.setText("Pull cancelled")
                logger.info(f"Docker image pull cancelled: {result.message}")
            else:
                self._image_status_label.setText("Pull failed")
                logger.error(f"Docker image pull failed: {result.message}")

        # Refresh status to update image info
        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_cancel_pull(self) -> None:
        """Cancel the in-progress Docker pull."""
        if self._pull_worker is not None:
            logger.info("User requested to cancel Docker pull")
            self._image_status_label.setText("Cancelling...")
            self._pull_cancel_btn.setEnabled(False)

            # Cancel in a separate thread to avoid blocking UI if it takes time
            import threading

            def cancel_worker():
                try:
                    if self._pull_worker:
                        self._pull_worker.cancel()
                        # Wait for worker thread to finish (with timeout)
                        self._pull_worker.join(timeout=10)
                        if self._pull_worker.is_alive():
                            logger.warning("Docker pull worker still alive after cancel")
                        else:
                            logger.info("Docker pull worker terminated successfully")
                except Exception as e:
                    logger.error(f"Error during cancel: {e}")

            cancel_thread = threading.Thread(target=cancel_worker, daemon=True)
            cancel_thread.start()

    def _on_remove_data_volume(self) -> None:
        """Remove the data volume."""
        from PyQt6.QtWidgets import QCheckBox, QMessageBox

        # Check if container exists first
        from dashboard.common.docker_manager import ServerStatus

        status = self._docker_manager.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Cannot Remove Volume")
            msg_box.setText("Container must be removed first")
            msg_box.setInformativeText(
                "Docker volumes cannot be removed while the container exists.\n\n"
                "Please remove the container first, then try removing the volume again."
            )
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()
            return

        # Confirm with user - this is destructive!
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Data Volume")
        msg_box.setText("WARNING: This will DELETE ALL SERVER DATA!")
        msg_box.setInformativeText(
            "This will permanently delete:\n"
            "• The SQLite database\n"
            "• All user data and transcription history\n"
            "• Server authentication token\n\n"
            "This action cannot be undone!"
        )

        # Add checkbox for also removing config directory
        config_checkbox = QCheckBox("Also remove config directory")
        config_checkbox.setToolTip(
            f"Remove {self._docker_manager.config_dir}\n"
            "(contains dashboard.yaml, docker-compose.yml, etc.)"
        )
        msg_box.setCheckBox(config_checkbox)

        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Critical)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        also_remove_config = config_checkbox.isChecked()
        self._remove_data_volume_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_data_volume(
            progress_callback=progress,
            also_remove_config=also_remove_config,
        )

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_remove_models_volume(self) -> None:
        """Remove the models volume."""
        from PyQt6.QtWidgets import QMessageBox

        # Check if container exists first
        from dashboard.common.docker_manager import ServerStatus

        status = self._docker_manager.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Cannot Remove Volume")
            msg_box.setText("Container must be removed first")
            msg_box.setInformativeText(
                "Docker volumes cannot be removed while the container exists.\n\n"
                "Please remove the container first, then try removing the volume again."
            )
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()
            return

        # Confirm with user
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Models Volume")
        msg_box.setText("WARNING: This will DELETE ALL DOWNLOADED MODELS!")
        msg_box.setInformativeText(
            "This will permanently delete all downloaded Whisper models. "
            "Models will need to be re-downloaded when needed (may take time)."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._remove_models_volume_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_models_volume(progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _toggle_server_logs(self) -> None:
        """Open server logs in a separate window."""
        if self._server_log_window is None:
            self._server_log_window = LogWindow("Server Logs", self)

        # Start log polling if not already running
        if self._server_log_timer is None:
            self._refresh_server_logs()
            self._server_log_timer = QTimer()
            self._server_log_timer.timeout.connect(self._refresh_server_logs)
            self._server_log_timer.start(3000)  # Poll every 3 seconds

        self._server_log_window.show()
        self._server_log_window.raise_()
        self._server_log_window.activateWindow()

    def _refresh_server_logs(self) -> None:
        """Refresh server logs."""
        if self._server_log_window is None:
            return
        logs = self._docker_manager.get_logs(lines=300)
        self._server_log_window.set_logs(logs)

    # =========================================================================
    # Client Operations
    # =========================================================================

    def _refresh_client_status(self) -> None:
        """Refresh the client status display."""
        if self._client_running:
            self._client_status_label.setText("Running")
            self._client_status_label.setStyleSheet("color: #4caf50;")  # success

            # Show connection info
            host = self.config.server_host
            port = self.config.server_port
            https = "HTTPS" if self.config.use_https else "HTTP"
            self._connection_info_label.setText(f"{https}://{host}:{port}")
        else:
            self._client_status_label.setText("Stopped")
            self._client_status_label.setStyleSheet("color: #ff9800;")  # warning
            self._connection_info_label.setText("Not connected")

        # Update button states
        self._start_client_local_btn.setEnabled(not self._client_running)
        self._start_client_remote_btn.setEnabled(not self._client_running)
        self._stop_client_btn.setEnabled(self._client_running)

        # Notebook toggle only allowed when both server and client are stopped
        # (setting takes effect on next client start)
        server_status = self._docker_manager.get_server_status()
        server_stopped = server_status != ServerStatus.RUNNING
        self._notebook_toggle_btn.setEnabled(not self._client_running and server_stopped)
        self._update_notebook_toggle_style()

        # Update models button based on server health
        self._update_models_button_state()

    def _update_models_button_state(self) -> None:
        """Update the models button state based on server health and connection type."""
        # Check if server is running and healthy
        status = self._docker_manager.get_server_status()
        health = self._docker_manager.get_container_health()

        is_healthy = status == ServerStatus.RUNNING and (
            health is None or health == "healthy"
        )

        # Only enable if healthy AND connected locally (model management unavailable for remote)
        if is_healthy and self._is_local_connection:
            # Server is healthy and local, enable button with appropriate color
            self._unload_models_btn.setEnabled(True)
            if self._models_loaded:
                # Light blue (models loaded, ready to unload) - color 2
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #90caf9; border: none; border-radius: 6px; color: #121212; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #42a5f5; }"
                )
            else:
                # Red (models unloaded, ready to reload) - color 3
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #d32f2f; }"
                )
        else:
            # Server not healthy, disable button with dark gray style
            self._unload_models_btn.setEnabled(False)
            self._unload_models_btn.setStyleSheet(
                "QPushButton { background-color: #2d2d2d; border: 1px solid #3d3d3d; border-radius: 6px; color: #606060; padding: 10px 20px; }"
                "QPushButton:disabled { background-color: #2d2d2d; border-color: #3d3d3d; color: #606060; }"
            )

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
            errors.append(
                f"Port should be {expected_remote_port} for remote connection (currently {port})"
            )

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

    def _toggle_client_logs(self) -> None:
        """Open client logs in a separate window."""
        if self._client_log_window is None:
            self._client_log_window = LogWindow("Client Logs", self)

        # Read client logs from the unified log file
        try:
            from dashboard.common.logging_config import get_log_file

            log_file = get_log_file()
            if log_file.exists():
                # Read last 200 lines
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    last_lines = lines[-200:] if len(lines) > 200 else lines
                    logs = "".join(last_lines)
            else:
                logs = "No log file found"
        except Exception as e:
            logger.error(f"Failed to read client logs: {e}")
            logs = f"Error reading logs: {e}"

        self._client_log_window.set_logs(logs)
        self._client_log_window.show()
        self._client_log_window.raise_()
        self._client_log_window.activateWindow()

    def append_client_log(self, message: str) -> None:
        """Append a message to the client log view."""
        if self._client_log_window is None:
            self._client_log_window = LogWindow("Client Logs", self)
        self._client_log_window.append_log(message)

    def set_client_running(self, running: bool) -> None:
        """Update client running state (called from orchestrator)."""
        self._client_running = running
        if self._current_view == View.CLIENT:
            self._refresh_client_status()

    def set_models_loaded(self, loaded: bool) -> None:
        """
        Update models loaded state (called from tray when changed via menu).

        Args:
            loaded: True if models are loaded, False if unloaded
        """
        self._models_loaded = loaded
        if self._current_view == View.CLIENT and self._unload_models_btn:
            if loaded:
                self._unload_models_btn.setText("Unload All Models")
                self._unload_models_btn.setToolTip(
                    "Unload transcription models to free GPU memory"
                )
                # Light blue background (models loaded) - color 2
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #90caf9; border: none; border-radius: 6px; color: #121212; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #42a5f5; }"
                )
            else:
                self._unload_models_btn.setText("Reload Models")
                self._unload_models_btn.setToolTip("Reload transcription models for use")
                # Red background (models unloaded) - color 3
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #d32f2f; }"
                )

    def set_connection_local(self, is_local: bool) -> None:
        """
        Update connection type (called from tray when connection changes).

        Args:
            is_local: True if connected to localhost, False if remote
        """
        self._is_local_connection = is_local
        # Refresh button state with new connection type
        if self._current_view == View.CLIENT:
            self._update_models_button_state()

    def _on_toggle_models(self) -> None:
        """Toggle model loading state - unload to free GPU memory or reload."""
        import asyncio

        from dashboard.common.api_client import APIClient

        # Get server connection settings
        use_remote = self.config.get("server", "use_remote", default=False)
        use_https = self.config.get("server", "use_https", default=False)

        if use_remote:
            host = self.config.get("server", "remote_host", default="")
            port = self.config.get("server", "port", default=8443)
        else:
            host = "localhost"
            port = self.config.get("server", "port", default=8000)

        token = self.config.get("server", "token", default="")
        tls_verify = self.config.get("server", "tls_verify", default=True)

        if not host:
            self._show_notification("Error", "No server host configured")
            return

        # Create temporary API client for this operation
        api_client = APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token if token else None,
            tls_verify=tls_verify,
        )

        async def do_toggle():
            try:
                if self._models_loaded:
                    result = await api_client.unload_models()
                else:
                    result = await api_client.reload_models()
                return result
            finally:
                await api_client.close()

        # Run async operation
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(do_toggle())
            loop.close()

            if result.get("success"):
                self._models_loaded = not self._models_loaded
                # Emit signal to notify tray of state change
                self.models_state_changed.emit(self._models_loaded)
                if self._models_loaded:
                    self._unload_models_btn.setText("Unload All Models")
                    self._unload_models_btn.setToolTip(
                        "Unload transcription models to free GPU memory"
                    )
                    # Light blue background (models loaded) - color 2
                    self._unload_models_btn.setStyleSheet(
                        "QPushButton { background-color: #90caf9; border: none; border-radius: 6px; color: #121212; padding: 10px 20px; font-weight: 500; }"
                        "QPushButton:hover { background-color: #42a5f5; }"
                    )
                    self._show_notification(
                        "Models Loaded", "Models ready for transcription"
                    )
                else:
                    self._unload_models_btn.setText("Reload Models")
                    self._unload_models_btn.setToolTip(
                        "Reload transcription models for use"
                    )
                    # Red background (models unloaded) - color 3
                    self._unload_models_btn.setStyleSheet(
                        "QPushButton { background-color: #f44336; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
                        "QPushButton:hover { background-color: #d32f2f; }"
                    )
                    self._show_notification(
                        "Models Unloaded",
                        "GPU memory freed. Click 'Reload Models' to restore.",
                    )
            else:
                self._show_notification(
                    "Operation Failed", result.get("message", "Unknown error")
                )
        except Exception as e:
            logger.error(f"Model toggle failed: {e}")
            self._show_notification("Error", f"Failed to toggle models: {e}")

    def _show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification."""
        # Check if notifications are enabled in settings
        if not self.config.get("ui", "notifications", default=True):
            logger.debug("Notifications disabled in settings")
            return

        try:
            import subprocess

            subprocess.run(
                ["notify-send", "-a", "TranscriptionSuite", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            logger.debug("notify-send not found - cannot show desktop notifications")

    def _on_notebook_toggle(self) -> None:
        """Handle notebook toggle button click."""
        is_enabled = self._notebook_toggle_btn.isChecked()
        self._notebook_toggle_btn.setText("Enabled" if is_enabled else "Disabled")
        self._update_notebook_toggle_style()

        # Save to server config - orchestrator will read this on next startup
        self.config.set_server_config(
            "longform_recording", "auto_add_to_audio_notebook", value=is_enabled
        )

        logger.info(f"Auto-add to notebook: {'enabled' if is_enabled else 'disabled'}")

    def _update_notebook_toggle_style(self) -> None:
        """Update notebook toggle button style based on state and editability."""
        is_checked = self._notebook_toggle_btn.isChecked()
        is_editable = self._notebook_toggle_btn.isEnabled()

        if is_checked:
            # Enabled state - green (or desaturated green if not editable)
            if is_editable:
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #4caf50; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #43a047; }"
                )
            else:
                # Desaturated green when not editable
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #3d5d3d; border: none; border-radius: 4px; "
                    "color: #7a9a7a; padding: 6px 12px; min-width: 70px; }"
                )
        else:
            # Disabled state - red (or desaturated red if not editable)
            if is_editable:
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #e53935; }"
                )
            else:
                # Desaturated red when not editable
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #5d3d3d; border: none; border-radius: 4px; "
                    "color: #9a7a7a; padding: 6px 12px; min-width: 70px; }"
                )

    def _on_live_transcriber_toggle(self) -> None:
        """Handle live transcriber toggle button click."""
        is_enabled = self._preview_toggle_btn.isChecked()
        self._preview_toggle_btn.setText("Enabled" if is_enabled else "Disabled")
        self._update_live_transcriber_toggle_style()

        # Save to server config - requires server restart to take effect
        self.config.set_server_config(
            "transcription_options", "enable_live_transcriber", value=is_enabled
        )
        self.config.set_server_config("live_transcriber", "enabled", value=is_enabled)

        logger.info(f"Live transcriber: {'enabled' if is_enabled else 'disabled'}")

    def _on_live_language_changed(self) -> None:
        """Handle Live Mode language dropdown change."""
        language_code = self._live_language_combo.currentData()
        language_name = self._live_language_combo.currentText()

        # Save to server config - takes effect on next Live Mode start
        self.config.set_server_config(
            "live_transcriber", "live_language", value=language_code
        )

        logger.info(
            f"Live Mode language set to: {language_name} ({language_code or 'auto'})"
        )

    def _toggle_live_preview_collapse(self) -> None:
        """Toggle live preview section collapse."""
        is_visible = self._preview_content.isVisible()
        self._preview_content.setVisible(not is_visible)
        self._preview_collapse_btn.setText("\u25b6" if is_visible else "\u25bc")


    def update_live_transcription_text(self, text: str, append: bool = False) -> None:
        """
        Update live transcription text display (called from orchestrator via tray).

        Args:
            text: The text to display
            append: If True, append to history. If False, replace current line.
        """
        if (
            not hasattr(self, "_live_transcription_text_edit")
            or not self._live_transcription_text_edit
        ):
            return

        if not text:
            # Clear or show placeholder
            self._live_transcription_text_edit.clear()
            return

        if append:
            # Append text as a new line in history
            self._live_transcription_history.append(text)
            # Keep last 1000 lines
            if len(self._live_transcription_history) > 1000:
                self._live_transcription_history = self._live_transcription_history[
                    -1000:
                ]
            # Update display - join with spaces for continuous text wrapping
            self._live_transcription_text_edit.setPlainText(
                " ".join(self._live_transcription_history)
            )
        else:
            # Real-time update: show history + current partial text
            if self._live_transcription_history:
                display_text = " ".join(self._live_transcription_history) + " " + text
            else:
                display_text = text
            self._live_transcription_text_edit.setPlainText(display_text)

        # Auto-scroll to bottom
        scrollbar = self._live_transcription_text_edit.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def clear_live_transcription_history(self) -> None:
        """Clear the live transcription text history."""
        if hasattr(self, "_live_transcription_history"):
            self._live_transcription_history.clear()
        if (
            hasattr(self, "_live_transcription_text_edit")
            and self._live_transcription_text_edit
        ):
            self._live_transcription_text_edit.clear()

    def _update_live_transcriber_toggle_style(self) -> None:
        """Update live transcriber toggle button style based on state and editability."""
        if not hasattr(self, "_preview_toggle_btn"):
            return

        is_checked = self._preview_toggle_btn.isChecked()
        is_editable = self._preview_toggle_btn.isEnabled()

        if is_checked:
            # Enabled state - green (or desaturated green if not editable)
            if is_editable:
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #4caf50; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #43a047; }"
                )
            else:
                # Desaturated green when not editable
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #3d5d3d; border: none; border-radius: 4px; "
                    "color: #7a9a7a; padding: 6px 12px; min-width: 70px; }"
                )
        else:
            # Disabled state - red (or desaturated red if not editable)
            if is_editable:
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #e53935; }"
                )
            else:
                # Desaturated red when not editable
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #5d3d3d; border: none; border-radius: 4px; "
                    "color: #9a7a7a; padding: 6px 12px; min-width: 70px; }"
                )

    # =========================================================================
    # Hamburger Menu, Help and About
    # =========================================================================

    def _show_hamburger_menu(self) -> None:
        """Show hamburger menu with Settings, Help, and About options."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #ffffff;
                padding: 8px 12px 8px 8px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2d2d2d;
            }
            QMenu::separator {
                height: 1px;
                background-color: #2d2d2d;
                margin: 4px 8px;
            }
            QMenu::icon {
                padding-left: 20px;
                padding-right: -6px;
            }
        """)

        # Settings action with white icon (symbolic only for monochrome appearance)
        settings_icon = self._icon_loader.get_icon("settings")
        settings_action = menu.addAction(settings_icon, "Settings")
        settings_action.triggered.connect(self._on_show_settings)

        menu.addSeparator()

        # Help submenu
        help_icon = self._icon_loader.get_icon("help")
        help_menu = menu.addMenu(help_icon, "Help")
        help_menu.setStyleSheet(menu.styleSheet())

        # User Guide
        user_guide_icon = self._icon_loader.get_icon("document")
        readme_action = help_menu.addAction(user_guide_icon, "User Guide (README)")
        readme_action.triggered.connect(lambda: self._show_readme_viewer(dev=False))

        # Developer Guide
        dev_guide_icon = self._icon_loader.get_icon("script")
        readme_dev_action = help_menu.addAction(
            dev_guide_icon, "Developer Guide (README_DEV)"
        )
        readme_dev_action.triggered.connect(lambda: self._show_readme_viewer(dev=True))

        # About action
        about_icon = self._icon_loader.get_icon("about")
        about_action = menu.addAction(about_icon, "About")
        about_action.triggered.connect(self._show_about_dialog)

        # Show menu below the hamburger button
        menu.exec(self._nav_menu_btn.mapToGlobal(self._nav_menu_btn.rect().bottomLeft()))

    def _show_help_menu(self) -> None:
        """Show help menu with README options."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #ffffff;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2d2d2d;
            }
        """)

        # User Guide icon - use document-properties or x-office-document for documentation
        user_guide_icon = QIcon.fromTheme("x-office-document")
        if user_guide_icon.isNull():
            user_guide_icon = QIcon.fromTheme("document-properties")
        if user_guide_icon.isNull():
            user_guide_icon = QIcon.fromTheme("text-x-generic")
        readme_action = menu.addAction(user_guide_icon, "User Guide (README)")
        readme_action.triggered.connect(lambda: self._show_readme_viewer(dev=False))

        # Developer Guide icon - use text-x-script or application-x-executable for code/dev docs
        dev_guide_icon = QIcon.fromTheme("text-x-script")
        if dev_guide_icon.isNull():
            dev_guide_icon = QIcon.fromTheme("text-x-source")
        if dev_guide_icon.isNull():
            dev_guide_icon = QIcon.fromTheme("application-x-executable")
        readme_dev_action = menu.addAction(dev_guide_icon, "Developer Guide (README_DEV)")
        readme_dev_action.triggered.connect(lambda: self._show_readme_viewer(dev=True))

        # Show menu below the help button
        menu.exec(self._nav_help_btn.mapToGlobal(self._nav_help_btn.rect().bottomLeft()))

    def _show_readme_viewer(self, dev: bool = False) -> None:
        """Show a README file in a markdown viewer dialog with dark theme."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtWidgets import QTextBrowser

        readme_path = _get_readme_path(dev=dev)
        title = "Developer Guide" if dev else "User Guide"

        if readme_path is None or not readme_path.exists():
            from PyQt6.QtWidgets import QMessageBox

            msg = QMessageBox(self)
            msg.setWindowTitle("File Not Found")
            msg.setText(f"Could not find {'README_DEV.md' if dev else 'README.md'}")
            msg.setInformativeText(
                "This file should be bundled with the application. "
                "If running from source, ensure you're in the repository root."
            )
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.exec()
            return

        # Create viewer dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"TranscriptionSuite - {title}")
        dialog.resize(950, 750)
        dialog.setModal(False)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        # Markdown content viewer with HTML rendering
        from PyQt6.QtGui import QColor, QPalette

        text_browser = QTextBrowser()
        text_browser.setReadOnly(True)
        # Disable automatic link handling - we'll handle anchors manually
        text_browser.setOpenLinks(False)
        text_browser.setOpenExternalLinks(False)

        def handle_anchor_click(url: QUrl) -> None:
            """Handle anchor clicks - internal anchors scroll, external open browser."""
            url_str = url.toString()
            if url_str.startswith("#"):
                # Internal anchor - scroll to it
                anchor_name = url_str[1:]  # Remove the # prefix
                text_browser.scrollToAnchor(anchor_name)
            elif url_str.startswith("http://") or url_str.startswith("https://"):
                # External link - open in browser
                webbrowser.open(url_str)
            # Ignore other URL schemes (file://, etc.)

        text_browser.anchorClicked.connect(handle_anchor_click)

        # Apply dark theme styling
        text_browser.setStyleSheet("""
            QTextBrowser {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                padding: 20px;
                font-size: 14px;
                selection-background-color: #3d3d3d;
                selection-color: #ffffff;
            }
        """)

        # Set custom colors for links
        palette = text_browser.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#d4d4d4"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#90caf9"))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#81d4fa"))
        text_browser.setPalette(palette)

        try:
            content = readme_path.read_text(encoding="utf-8")

            # Pre-process markdown content to handle HTML img tags and embedded HTML
            # The markdown library with extra extension handles inline HTML better
            import re

            # Remove HTML img tags and replace with text description
            # QTextBrowser has limited HTML support
            content = re.sub(
                r'<img[^>]*alt=["\']([^"\']*)["\'][^>]*>',
                r"[Image: \1]",
                content,
                flags=re.IGNORECASE,
            )
            content = re.sub(
                r'<img[^>]*src=["\']([^"\']*)["\'][^>]*>',
                r"[Image]",
                content,
                flags=re.IGNORECASE,
            )

            # Convert <pre> tags to fenced code blocks for better handling
            content = re.sub(r"<pre>\s*", "\n```\n", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*</pre>", "\n```\n", content, flags=re.IGNORECASE)

            # Try using markdown library to convert to HTML
            try:
                import markdown

                # Convert markdown to HTML with extensions
                # Using toc extension with slugify for consistent anchor IDs
                html_body = markdown.markdown(
                    content,
                    extensions=[
                        "fenced_code",
                        "tables",
                        "toc",
                        "sane_lists",
                        "attr_list",
                    ],
                    extension_configs={
                        "toc": {
                            "permalink": False,
                            "toc_depth": 4,
                        }
                    },
                )

                # Wrap in HTML with inline dark theme CSS
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{
                            color: #d4d4d4;
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            font-size: 14px;
                            line-height: 1.6;
                            margin: 0;
                            padding: 0;
                        }}
                        h1 {{ color: #90caf9; font-size: 28px; margin-top: 24px; border-bottom: 1px solid #3d3d3d; padding-bottom: 8px; }}
                        h2 {{ color: #81d4fa; font-size: 22px; margin-top: 20px; border-bottom: 1px solid #2d2d2d; padding-bottom: 6px; }}
                        h3 {{ color: #b3e5fc; font-size: 18px; margin-top: 16px; }}
                        h4, h5, h6 {{ color: #e1f5fe; margin-top: 12px; }}
                        a {{ color: #90caf9; text-decoration: none; }}
                        a:hover {{ text-decoration: underline; }}
                        code {{
                            background-color: #2d2d2d;
                            color: #ce93d8;
                            padding: 2px 6px;
                            border-radius: 4px;
                            font-family: 'CaskaydiaCove Nerd Font', 'Fira Code', 'Consolas', monospace;
                            font-size: 13px;
                        }}
                        pre {{
                            background-color: #1a1a1a;
                            border: 1px solid #3d3d3d;
                            border-radius: 6px;
                            padding: 12px;
                            overflow-x: auto;
                            font-family: 'CaskaydiaCove Nerd Font', 'Fira Code', 'Consolas', monospace;
                            font-size: 13px;
                        }}
                        pre code {{
                            background-color: transparent;
                            padding: 0;
                            color: #d4d4d4;
                        }}
                        blockquote {{
                            border-left: 4px solid #90caf9;
                            margin: 16px 0;
                            padding: 8px 16px;
                            background-color: #252525;
                            color: #b0b0b0;
                        }}
                        table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
                        th, td {{ border: 1px solid #3d3d3d; padding: 10px; text-align: left; }}
                        th {{ background-color: #2d2d2d; color: #90caf9; font-weight: 600; }}
                        tr:nth-child(even) {{ background-color: #252525; }}
                        ul, ol {{ padding-left: 24px; margin: 12px 0; }}
                        li {{ margin: 6px 0; }}
                        hr {{ border: none; border-top: 1px solid #3d3d3d; margin: 24px 0; }}
                        strong {{ color: #ffffff; }}
                        em {{ color: #b0b0b0; }}
                    </style>
                </head>
                <body>
                    {html_body}
                </body>
                </html>
                """
                text_browser.setHtml(html)

            except ImportError:
                # Fallback: use Qt's built-in setMarkdown
                text_browser.setMarkdown(content)

        except Exception as e:
            text_browser.setPlainText(f"Error reading file: {e}")

        layout.addWidget(text_browser)

        # Style the dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            QTextBrowser {
                background-color: #1e1e1e;
                border: none;
            }
        """)

        dialog.show()

    def _show_about_dialog(self) -> None:
        """Show the About dialog with author info and links."""
        dialog = QDialog(self)
        dialog.setWindowTitle("About TranscriptionSuite")
        dialog.setFixedSize(480, 620)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)

        # Profile picture with proper centering and clipping
        profile_container = QWidget()
        profile_container.setFixedSize(120, 120)
        profile_container_layout = QVBoxLayout(profile_container)
        profile_container_layout.setContentsMargins(0, 0, 0, 0)
        profile_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        profile_label = QLabel()
        profile_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        profile_label.setFixedSize(110, 110)

        profile_pixmap = self._load_profile_picture()
        if profile_pixmap:
            # Create circular mask for the profile picture
            scaled_pixmap = profile_pixmap.scaled(
                100,
                100,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

            # Create a rounded pixmap
            rounded = QPixmap(100, 100)
            rounded.fill(Qt.GlobalColor.transparent)

            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, 100, 100)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled_pixmap)
            painter.end()

            profile_label.setPixmap(rounded)
        else:
            # Fallback: use a placeholder
            profile_label.setText("👤")

        profile_container_layout.addWidget(profile_label)
        layout.addWidget(profile_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # App name
        app_name = QLabel("TranscriptionSuite")
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_name.setStyleSheet("color: #ffffff; font-size: 20px; font-weight: bold;")
        layout.addWidget(app_name)

        # Version info - always display (use shared version utility)
        from dashboard.common.version import __version__

        version_label = QLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        layout.addWidget(version_label)

        layout.addSpacing(4)

        # Description
        description = QLabel("Speech-to-Text Transcription Suite")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        layout.addWidget(description)

        # Copyright notice
        copyright_label = QLabel("© 2025-2026 homelab-00 • MIT License")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        layout.addWidget(copyright_label)

        layout.addSpacing(12)

        # Links section
        links_frame = QFrame()
        links_frame.setObjectName("linksFrame")
        links_layout = QVBoxLayout(links_frame)
        links_layout.setSpacing(10)
        links_layout.setContentsMargins(20, 20, 20, 20)

        # Author section header
        author_header = QLabel("Author")
        author_header.setStyleSheet(
            "color: #90caf9; font-size: 13px; font-weight: bold; margin-bottom: 4px;"
        )
        links_layout.addWidget(author_header)

        # GitHub profile
        github_btn = QPushButton("  GitHub Profile")
        github_icon = QIcon.fromTheme("user-identity")
        if github_icon.isNull():
            github_icon = QIcon.fromTheme("contact-new")
        github_btn.setIcon(github_icon)
        github_btn.setObjectName("linkButton")
        github_btn.clicked.connect(lambda: webbrowser.open(GITHUB_PROFILE_URL))
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        links_layout.addWidget(github_btn)

        links_layout.addSpacing(12)

        # Repository section header
        repo_header = QLabel("Repository")
        repo_header.setStyleSheet(
            "color: #90caf9; font-size: 13px; font-weight: bold; margin-bottom: 4px;"
        )
        links_layout.addWidget(repo_header)

        # GitHub repo
        github_repo_btn = QPushButton("  GitHub Repository")
        repo_icon = QIcon.fromTheme("folder-git")
        if repo_icon.isNull():
            repo_icon = QIcon.fromTheme("folder-development")
        if repo_icon.isNull():
            repo_icon = QIcon.fromTheme("folder")
        github_repo_btn.setIcon(repo_icon)
        github_repo_btn.setObjectName("linkButton")
        github_repo_btn.clicked.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        github_repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        links_layout.addWidget(github_repo_btn)

        layout.addWidget(links_frame)

        layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Style the dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            #linksFrame {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }
            #linkButton {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: #ffffff;
                padding: 10px 16px;
                padding-left: 12px;
                text-align: left;
                font-size: 13px;
                min-width: 200px;
                min-height: 20px;
            }
            #linkButton:hover {
                background-color: #2d2d2d;
                border-color: #90caf9;
            }
            #primaryButton {
                background-color: #90caf9;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 10px 32px;
                font-size: 13px;
                font-weight: 500;
            }
            #primaryButton:hover {
                background-color: #42a5f5;
            }
        """)

        dialog.exec()

    def _load_profile_picture(self) -> QPixmap | None:
        """Load the profile picture from bundled assets."""
        assets_path = _get_assets_path()
        profile_path = assets_path / "profile.png"

        if profile_path.exists():
            pixmap = QPixmap(str(profile_path))
            if not pixmap.isNull():
                return pixmap

        # Try loading from logo as fallback
        logo_path = assets_path / "logo.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                return pixmap

        return None

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
