"""
Dashboard - Main control window for TranscriptionSuite (GNOME GTK4 version).

The Dashboard is the command center for managing both the Docker server
and the transcription client. It provides a unified GUI for:
- Starting/stopping the Docker server (local or remote mode)
- Starting/stopping the transcription client
- Configuring all settings
- Viewing server and client logs

Uses GTK4 and libadwaita for native GNOME look and feel.
"""

from __future__ import annotations

import logging
import os
import subprocess
import webbrowser
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from dashboard.common.docker_manager import (
    DockerManager,
    DockerPullWorker,
    DockerResult,
    ServerMode,
    ServerStatus,
)

logger = logging.getLogger(__name__)

# Import GTK4 and Adwaita
HAS_GTK4 = False
HAS_GTKSOURCEVIEW = False
try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

    HAS_GTK4 = True

    # Try to import GtkSourceView for line numbers in log viewer
    try:
        gi.require_version("GtkSource", "5")
        from gi.repository import GtkSource

        HAS_GTKSOURCEVIEW = True
    except (ImportError, ValueError) as e:
        logger.debug(f"GtkSourceView not available, line numbers disabled: {e}")
        GtkSource = None  # type: ignore

except (ImportError, ValueError) as e:
    logger.warning(f"GTK4/Adwaita not available: {e}")
    Adw = None  # type: ignore
    Gdk = None  # type: ignore
    GdkPixbuf = None  # type: ignore
    Gio = None  # type: ignore
    GLib = None  # type: ignore
    Gtk = None  # type: ignore
    GtkSource = None  # type: ignore

if TYPE_CHECKING:
    from dashboard.common.config import ClientConfig

# Constants for embedded resources
GITHUB_PROFILE_URL = "https://github.com/homelab-00"
GITHUB_REPO_URL = "https://github.com/homelab-00/TranscriptionSuite"


def _get_assets_path() -> Path:
    """Get the path to the assets directory, handling dev, PyInstaller, and AppImage modes."""
    import sys

    # 1. PyInstaller bundle
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)  # type: ignore
        return bundle_dir / "build" / "assets"

    # 2. AppImage (APPDIR is set by AppImage runtime)
    if "APPDIR" in os.environ:
        appdir = Path(os.environ["APPDIR"])
        assets_path = appdir / "usr" / "share" / "transcriptionsuite" / "assets"
        if assets_path.exists():
            logger.debug(f"Using AppImage assets path: {assets_path}")
            return assets_path

    # 3. Running from source - find project root
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "README.md").exists():
            return parent / "build" / "assets"
    return Path(__file__).parent.parent.parent.parent.parent / "build" / "assets"


def _get_readme_path(dev: bool = False) -> Path | None:
    """Get the path to README.md or README_DEV.md.

    Handles multiple scenarios:
    - PyInstaller bundle (looks in _MEIPASS)
    - AppImage (looks in AppDir - checked even when not frozen)
    - Running from source (searches parent directories)
    - Current working directory (fallback)
    """
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

    # 5. XDG data directories (Linux)
    if "XDG_DATA_DIRS" in os.environ:
        for data_dir in os.environ["XDG_DATA_DIRS"].split(":"):
            if data_dir:  # Skip empty strings
                paths_to_check.append(Path(data_dir) / "transcriptionsuite" / filename)

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
    """Dashboard view types."""

    WELCOME = auto()
    SERVER = auto()
    CLIENT = auto()


# Use a factory function instead of conditional base class for type checker
def _get_log_window_base():
    """Get the base class for LogWindow."""
    if HAS_GTK4:
        return Adw.Window
    return object


class LogWindow(_get_log_window_base()):
    """Separate window for displaying logs with syntax highlighting and line numbers."""

    def __init__(self, title: str, app: Any = None):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for LogWindow")

        super().__init__(title=title)
        if app:
            self.set_application(app)
        self.set_default_size(800, 600)

        # Track displayed content to avoid unnecessary redraws
        self._current_line_count = 0
        self._current_content_hash = 0

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=title))
        content.append(header)

        # Log view in a scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # Use GtkSourceView if available (for line numbers), otherwise fallback to TextView
        if HAS_GTKSOURCEVIEW and GtkSource:
            self._text_view = GtkSource.View()
            self._text_view.set_show_line_numbers(True)
            self._text_view.set_background_pattern(GtkSource.BackgroundPatternType.NONE)
            # Get buffer from source view
            self._buffer = self._text_view.get_buffer()
        else:
            self._text_view = Gtk.TextView()
            self._buffer = self._text_view.get_buffer()

        self._text_view.set_editable(False)
        self._text_view.set_monospace(True)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.add_css_class("log-view")

        # Setup text tags for syntax highlighting
        self._setup_text_tags()

        scrolled.set_child(self._text_view)
        content.append(scrolled)

        self.set_content(content)
        self._apply_styles()

    def _setup_text_tags(self) -> None:
        """Create text tags for syntax highlighting."""
        tag_table = self._buffer.get_tag_table()

        # DEBUG - Gray
        debug_tag = self._buffer.create_tag("DEBUG", foreground="#808080")

        # INFO - Cyan
        info_tag = self._buffer.create_tag("INFO", foreground="#4EC9B0")

        # WARNING - Yellow
        warning_tag = self._buffer.create_tag("WARNING", foreground="#DCDCAA")

        # ERROR - Red + Bold
        error_tag = self._buffer.create_tag("ERROR", foreground="#F48771", weight=700)

        # CRITICAL - Bright Red + Bold
        critical_tag = self._buffer.create_tag(
            "CRITICAL", foreground="#FF6B6B", weight=700
        )

        # Date format - Cyan
        date_tag = self._buffer.create_tag("date", foreground="#4EC9B0")

        # Time format - Light blue
        time_tag = self._buffer.create_tag("time", foreground="#9CDCFE")

        # Milliseconds format - Gray/blue
        milliseconds_tag = self._buffer.create_tag("milliseconds", foreground="#6A9FB5")

        # Brackets format - Dim gray
        bracket_tag = self._buffer.create_tag("bracket", foreground="#808080")

        # Module names - Light blue
        module_tag = self._buffer.create_tag("module", foreground="#9CDCFE")

        # Separator (pipes) - Dim
        separator_tag = self._buffer.create_tag("separator", foreground="#6A6A6A")

        # Container name - Purple
        container_tag = self._buffer.create_tag("container", foreground="#C586C0")

    def _apply_highlighting(self, start_iter, text: str) -> None:
        """Apply syntax highlighting to newly added text."""
        if not text:
            return

        import re

        # Helper to apply tag at specific position
        def apply_tag(tag_name: str, start_pos: int, length: int) -> None:
            tag_start = start_iter.copy()
            tag_start.forward_chars(start_pos)
            tag_end = tag_start.copy()
            tag_end.forward_chars(length)
            self._buffer.apply_tag_by_name(tag_name, tag_start, tag_end)

        # Highlight container name first (if present at start)
        # Server format: container-name | ...
        container_match = re.match(r"^([\w-]+)\s*(\|)", text)
        if container_match:
            # Container name
            apply_tag(
                "container", container_match.start(1), len(container_match.group(1))
            )
            # First pipe
            apply_tag("separator", container_match.start(2), 1)

        # Pattern for bracketed timestamp with milliseconds [YYYY-MM-DD HH:MM:SS,mmm]
        bracket_ts_match = re.match(
            r"^(\[)(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(,\d{3})?(\])", text
        )
        if bracket_ts_match:
            # Opening bracket
            apply_tag("bracket", bracket_ts_match.start(1), 1)
            # Date
            apply_tag("date", bracket_ts_match.start(2), len(bracket_ts_match.group(2)))
            # Time
            apply_tag("time", bracket_ts_match.start(3), len(bracket_ts_match.group(3)))
            # Milliseconds (if present)
            if bracket_ts_match.group(4):
                apply_tag(
                    "milliseconds",
                    bracket_ts_match.start(4),
                    len(bracket_ts_match.group(4)),
                )
            # Closing bracket
            apply_tag("bracket", bracket_ts_match.start(5), 1)

        # Pattern for date/time in server logs: YYYY-MM-DD HH:MM:SS
        # This will match timestamps after the container name
        datetime_match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", text)
        if datetime_match:
            # Date
            apply_tag("date", datetime_match.start(1), len(datetime_match.group(1)))
            # Time
            apply_tag("time", datetime_match.start(2), len(datetime_match.group(2)))

        # Highlight all pipe separators
        for match in re.finditer(r"\|", text):
            apply_tag("separator", match.start(), 1)

        # Highlight log level
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            for match in re.finditer(rf"\b{level}\b", text):
                apply_tag(level, match.start(), len(level))

        # Highlight module names (text after " - ", before ":")
        if " - " in text:
            parts = text.split(" - ")
            if len(parts) >= 2:
                module_part = parts[1]
                if ":" in module_part:
                    module_name = module_part.split(":")[0].strip()
                    module_idx = text.index(module_name)
                    apply_tag("module", module_idx, len(module_name))

    def append_log(self, message: str) -> None:
        """Append a log message to the view with syntax highlighting while preserving scroll position."""
        # Get scroll position
        vadj = self._text_view.get_vadjustment()
        old_value = vadj.get_value()
        old_upper = vadj.get_upper()
        was_at_bottom = old_value >= (old_upper - vadj.get_page_size() - 1)

        # Insert text
        end_iter = self._buffer.get_end_iter()
        start_offset = end_iter.get_offset()
        self._buffer.insert(end_iter, message + "\n")

        # Apply highlighting to the newly added text
        start_iter = self._buffer.get_iter_at_offset(start_offset)
        self._apply_highlighting(start_iter, message)

        # Restore scroll position (unless user was at bottom)
        if not was_at_bottom:
            vadj.set_value(old_value)

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
            current_text = self._buffer.get_text(
                self._buffer.get_start_iter(), self._buffer.get_end_iter(), False
            )
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
        vadj = self._text_view.get_vadjustment()
        old_value = vadj.get_value()

        # Clear and set new content
        self._buffer.set_text("")

        # Split by lines and apply highlighting to each
        for line in logs.split("\n"):
            if line:
                end_iter = self._buffer.get_end_iter()
                start_offset = end_iter.get_offset()
                self._buffer.insert(end_iter, line + "\n")
                start_iter = self._buffer.get_iter_at_offset(start_offset)
                self._apply_highlighting(start_iter, line)

        # Restore scroll position
        vadj.set_value(old_value)

        # Update tracking
        self._current_line_count = new_line_count
        self._current_content_hash = new_hash

    def clear_logs(self) -> None:
        """Clear all logs."""
        self._buffer.set_text("")
        self._current_line_count = 0
        self._current_content_hash = 0

    def _apply_styles(self) -> None:
        """Apply dark theme styling."""
        css = b"""
        .log-view {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: "CaskaydiaCove Nerd Font", monospace;
            font-size: 9pt;
        }
        .log-view:selected {
            background-color: #264f78;
        }
        .log-view text {
            background-color: #1e1e1e;
        }
        .log-view border {
            background-color: #252526;
        }
        .log-view .line-numbers {
            background-color: #252526;
            color: #858585;
            padding-left: 4px;
            padding-right: 8px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def _get_dashboard_base():
    """Get the base class for DashboardWindow."""
    if HAS_GTK4:
        return Adw.ApplicationWindow
    return object


class DashboardWindow(_get_dashboard_base()):
    """
    Main Dashboard window - the command center for TranscriptionSuite.

    Uses GTK4 and libadwaita for native GNOME integration.
    """

    def __init__(
        self,
        config: ClientConfig,
        app: Any = None,
        on_start_client: Callable[[bool], None] | None = None,
        on_stop_client: Callable[[], None] | None = None,
        on_show_settings: Callable[[], None] | None = None,
    ):
        if not HAS_GTK4:
            raise ImportError("GTK4 and libadwaita are required for GNOME Dashboard")

        super().__init__()
        if app:
            self.set_application(app)

        self.config = config
        self._docker_manager = DockerManager()

        # Callbacks for client operations
        self._start_client_callback = on_start_client
        self._stop_client_callback = on_stop_client
        self._show_settings_callback = on_show_settings

        # View history for navigation
        self._view_history: list[View] = []
        self._current_view: View = View.WELCOME

        # Log windows
        self._server_log_window: LogWindow | None = None
        self._client_log_window: LogWindow | None = None

        # Client state tracking
        self._client_running = False

        # Model state tracking (assume loaded initially)
        self._models_loaded = True

        # Connection type tracking (assume local initially)
        self._is_local_connection = True

        # Status update timers
        self._status_timer_id: int | None = None

        # Docker pull worker for async image pulling
        self._pull_worker: DockerPullWorker | None = None

        # UI references (typed as Any since GTK types are dynamic)
        self._stack: Any = None
        self._home_server_status: Any = None
        self._home_client_status: Any = None
        self._server_status_label: Any = None
        self._image_status_label: Any = None
        self._image_date_label: Any = None
        self._image_size_label: Any = None
        self._server_token_entry: Any = None
        self._data_volume_status: Any = None
        self._data_volume_size: Any = None
        self._models_volume_status: Any = None
        self._models_volume_size: Any = None
        self._models_list_label: Any = None
        self._client_status_label: Any = None
        self._connection_info_label: Any = None

        # Button references
        self._start_local_btn: Any = None
        self._start_remote_btn: Any = None
        self._stop_server_btn: Any = None
        self._start_client_local_btn: Any = None
        self._start_client_remote_btn: Any = None
        self._stop_client_btn: Any = None
        self._unload_models_btn: Any = None
        self._notebook_toggle_btn: Any = None

        self._setup_ui()
        self._apply_styles()

        # Start status refresh timer
        self._start_status_timer()

    def _setup_ui(self) -> None:
        """Set up the main UI structure."""
        self.set_title("TranscriptionSuite")
        self.set_default_size(750, 600)

        # Set window icon from app logo
        self._set_window_icon()

        # Force dark theme
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        # Main content box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Navigation header bar
        header = self._create_header_bar()
        main_box.append(header)

        # Stack for views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(200)
        self._stack.set_vexpand(True)

        # Create views
        welcome_view = self._create_welcome_view()
        server_view = self._create_server_view()
        client_view = self._create_client_view()

        self._stack.add_named(welcome_view, "welcome")
        self._stack.add_named(server_view, "server")
        self._stack.add_named(client_view, "client")

        main_box.append(self._stack)

        self.set_content(main_box)

        # Start on welcome view
        self._navigate_to(View.WELCOME, add_to_history=False)

        # Connect close request
        self.connect("close-request", self._on_close_request)

    def _set_window_icon(self) -> None:
        """Set the window icon from the app logo.

        In GTK4/Wayland, window icons are typically determined by the .desktop file.
        However, we can add our assets directory to the icon theme search path
        so the icon can be found.
        """
        try:
            assets_path = _get_assets_path()

            # Add the assets directory to icon theme search path
            icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            icon_theme.add_search_path(str(assets_path))

            # Also add parent directories that might contain icons
            # AppImage structure: usr/share/icons/...
            if "APPDIR" in os.environ:
                appdir = Path(os.environ["APPDIR"])
                icon_dirs = [
                    appdir / "usr" / "share" / "icons",
                    appdir / "usr" / "share" / "pixmaps",
                ]
                for icon_dir in icon_dirs:
                    if icon_dir.exists():
                        icon_theme.add_search_path(str(icon_dir))
                        logger.debug(f"Added icon search path: {icon_dir}")

            logger.debug(f"Added icon search path: {assets_path}")
        except Exception as e:
            logger.warning(f"Failed to configure icon theme: {e}")

    def _create_header_bar(self) -> Any:
        """Create the navigation header bar."""
        header = Adw.HeaderBar()

        # Left side: Home, Server, Client buttons
        home_btn = Gtk.Button(label="Home")
        home_btn.set_icon_name("go-home-symbolic")
        home_btn.add_css_class("nav-button")
        home_btn.connect("clicked", lambda _: self._go_home())
        header.pack_start(home_btn)

        server_btn = Gtk.Button(label="Server")
        server_btn.set_icon_name("network-server-symbolic")
        server_btn.add_css_class("nav-button")
        server_btn.connect("clicked", lambda _: self._navigate_to(View.SERVER))
        header.pack_start(server_btn)

        client_btn = Gtk.Button(label="Client")
        client_btn.set_icon_name("audio-input-microphone-symbolic")
        client_btn.add_css_class("nav-button")
        client_btn.connect("clicked", lambda _: self._navigate_to(View.CLIENT))
        header.pack_start(client_btn)

        # Right side: Hamburger menu button (☰) with Settings, Help, About
        self._menu_btn = Gtk.MenuButton()
        self._menu_btn.set_icon_name("open-menu-symbolic")
        self._menu_btn.set_tooltip_text("Menu")
        self._menu_btn.add_css_class("nav-button")

        # Create menu model
        menu = Gio.Menu()

        # Settings item
        menu.append("Settings", "win.show-settings")

        # Separator
        help_section = Gio.Menu()

        # Help submenu
        help_submenu = Gio.Menu()
        help_submenu.append("User Guide (README)", "win.help-user")
        help_submenu.append("Developer Guide (README_DEV)", "win.help-dev")
        help_section.append_submenu("Help", help_submenu)

        # About item
        help_section.append("About", "win.show-about")

        menu.append_section(None, help_section)

        # Create popover menu
        popover = Gtk.PopoverMenu.new_from_model(menu)
        self._menu_btn.set_popover(popover)

        # Add actions
        settings_action = Gio.SimpleAction.new("show-settings", None)
        settings_action.connect("activate", lambda a, p: self._trigger_show_settings())
        self.add_action(settings_action)

        help_user_action = Gio.SimpleAction.new("help-user", None)
        help_user_action.connect("activate", lambda a, p: self._show_readme(dev=False))
        self.add_action(help_user_action)

        help_dev_action = Gio.SimpleAction.new("help-dev", None)
        help_dev_action.connect("activate", lambda a, p: self._show_readme(dev=True))
        self.add_action(help_dev_action)

        about_action = Gio.SimpleAction.new("show-about", None)
        about_action.connect("activate", lambda a, p: self._show_about_dialog())
        self.add_action(about_action)

        header.pack_end(self._menu_btn)

        return header

    def _create_welcome_view(self) -> Any:
        """Create the welcome/home view."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(40)
        box.set_margin_end(40)
        box.set_size_request(450, -1)  # Minimum width for home view

        # Welcome title
        title = Gtk.Label(label="Welcome to TranscriptionSuite")
        title.add_css_class("title-1")
        box.append(title)

        # Subtitle
        subtitle = Gtk.Label(label="Manage the Docker server and transcription client")
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        # Status indicators
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=40)
        status_box.set_halign(Gtk.Align.CENTER)
        status_box.set_margin_top(20)

        # Server status
        server_status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        server_label = Gtk.Label(label="Server")
        server_label.add_css_class("server-accent")
        server_status_box.append(server_label)

        self._home_server_status = Gtk.Label(label="⬤ Checking...")
        self._home_server_status.add_css_class("status-label")
        server_status_box.append(self._home_server_status)
        status_box.append(server_status_box)

        # Client status
        client_status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        client_label = Gtk.Label(label="Client")
        client_label.add_css_class("client-accent")
        client_status_box.append(client_label)

        self._home_client_status = Gtk.Label(label="⬤ Stopped")
        self._home_client_status.add_css_class("status-label")
        client_status_box.append(self._home_client_status)
        status_box.append(client_status_box)

        box.append(status_box)

        # Main action buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(30)

        # Server button with icon
        server_btn = Gtk.Button()
        server_btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        server_btn_box.set_halign(Gtk.Align.CENTER)
        server_btn_box.set_valign(Gtk.Align.CENTER)
        server_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
        server_icon.set_pixel_size(24)
        server_btn_box.append(server_icon)
        server_btn_label = Gtk.Label(label="Manage\nDocker Server")
        server_btn_label.set_justify(Gtk.Justification.CENTER)
        server_btn_box.append(server_btn_label)
        server_btn.set_child(server_btn_box)
        server_btn.add_css_class("welcome-button")
        server_btn.add_css_class("server-accent")
        server_btn.set_size_request(180, 90)
        server_btn.connect("clicked", lambda _: self._navigate_to(View.SERVER))
        btn_box.append(server_btn)

        # Client button with icon
        client_btn = Gtk.Button()
        client_btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        client_btn_box.set_halign(Gtk.Align.CENTER)
        client_btn_box.set_valign(Gtk.Align.CENTER)
        client_icon = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")
        client_icon.set_pixel_size(24)
        client_btn_box.append(client_icon)
        client_btn_label = Gtk.Label(label="Manage\nClient")
        client_btn_label.set_justify(Gtk.Justification.CENTER)
        client_btn_box.append(client_btn_label)
        client_btn.set_child(client_btn_box)
        client_btn.add_css_class("welcome-button")
        client_btn.add_css_class("client-accent")
        client_btn.set_size_request(180, 90)
        client_btn.connect("clicked", lambda _: self._navigate_to(View.CLIENT))
        btn_box.append(client_btn)

        box.append(btn_box)

        scrolled.set_child(box)
        return scrolled

    def _create_server_view(self) -> Any:
        """Create the server management view."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(40)
        box.set_margin_end(40)
        box.set_size_request(550, -1)  # Minimum width for server view

        # Title
        title = Gtk.Label(label="Docker Server")
        title.add_css_class("title-1")
        box.append(title)

        # Status card
        status_frame = Gtk.Frame()
        status_frame.add_css_class("card")
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.set_margin_top(12)
        status_box.set_margin_bottom(12)
        status_box.set_margin_start(16)
        status_box.set_margin_end(16)

        # Container status row
        container_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container_label = Gtk.Label(label="Container:")
        container_label.add_css_class("dim-label")
        container_row.append(container_label)
        self._server_status_label = Gtk.Label(label="Checking...")
        container_row.append(self._server_status_label)
        status_box.append(container_row)

        # Image status row
        image_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        image_label = Gtk.Label(label="Docker Image:")
        image_label.add_css_class("dim-label")
        image_row.append(image_label)
        self._image_status_label = Gtk.Label(label="Checking...")
        image_row.append(self._image_status_label)
        self._image_date_label = Gtk.Label(label="")
        self._image_date_label.add_css_class("dim-label")
        self._image_date_label.add_css_class("caption")
        image_row.append(self._image_date_label)
        self._image_size_label = Gtk.Label(label="")
        self._image_size_label.add_css_class("dim-label")
        self._image_size_label.add_css_class("caption")
        image_row.append(self._image_size_label)
        status_box.append(image_row)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        status_box.append(separator)

        # Auth token row
        token_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        token_label = Gtk.Label(label="Auth Token:")
        token_label.add_css_class("dim-label")
        token_row.append(token_label)
        self._server_token_entry = Gtk.Entry()
        self._server_token_entry.set_editable(False)
        self._server_token_entry.set_text("Not saved yet")
        self._server_token_entry.set_hexpand(True)
        self._server_token_entry.add_css_class("flat")
        token_row.append(self._server_token_entry)
        token_note = Gtk.Label(label="(for remote)")
        token_note.add_css_class("dim-label")
        token_note.add_css_class("caption")
        token_row.append(token_note)
        status_box.append(token_row)

        status_frame.set_child(status_box)
        box.append(status_frame)

        # Control buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(16)

        self._start_local_btn = Gtk.Button(label="Start Local")
        self._start_local_btn.add_css_class("suggested-action")
        self._start_local_btn.connect("clicked", lambda _: self._on_start_server_local())
        btn_box.append(self._start_local_btn)

        self._start_remote_btn = Gtk.Button(label="Start Remote")
        self._start_remote_btn.add_css_class("suggested-action")
        self._start_remote_btn.connect(
            "clicked", lambda _: self._on_start_server_remote()
        )
        btn_box.append(self._start_remote_btn)

        self._stop_server_btn = Gtk.Button(label="Stop")
        self._stop_server_btn.add_css_class("destructive-action")
        self._stop_server_btn.connect("clicked", lambda _: self._on_stop_server())
        btn_box.append(self._stop_server_btn)

        # Model management button (unload/reload)
        self._unload_models_btn = Gtk.Button(label="Unload All Models")
        self._unload_models_btn.add_css_class("secondary-button")
        # Start disabled (gray) until server is healthy
        self._unload_models_btn.set_sensitive(False)
        self._unload_models_btn.set_tooltip_text(
            "Unload transcription models to free GPU memory"
        )
        self._unload_models_btn.connect("clicked", lambda _: self._on_toggle_models())
        btn_box.append(self._unload_models_btn)

        box.append(btn_box)

        # Management section
        mgmt_label = Gtk.Label(label="Management")
        mgmt_label.add_css_class("heading")
        mgmt_label.set_margin_top(20)
        box.append(mgmt_label)

        # Management buttons in a grid
        mgmt_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        mgmt_grid.set_halign(Gtk.Align.CENTER)

        # Container column
        container_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        container_col.add_css_class("card")
        container_col.set_margin_top(8)
        container_col.set_margin_bottom(8)
        container_col.set_margin_start(12)
        container_col.set_margin_end(12)

        container_header = Gtk.Label(label="Container")
        container_header.add_css_class("heading")
        container_col.append(container_header)

        remove_container_btn = Gtk.Button(label="Remove")
        remove_container_btn.add_css_class("destructive-action")
        remove_container_btn.connect("clicked", lambda _: self._on_remove_container())
        container_col.append(remove_container_btn)
        mgmt_grid.append(container_col)

        # Image column
        image_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        image_col.add_css_class("card")
        image_col.set_margin_top(8)
        image_col.set_margin_bottom(8)
        image_col.set_margin_start(12)
        image_col.set_margin_end(12)

        image_header = Gtk.Label(label="Image")
        image_header.add_css_class("heading")
        image_col.append(image_header)

        remove_image_btn = Gtk.Button(label="Remove")
        remove_image_btn.add_css_class("destructive-action")
        remove_image_btn.connect("clicked", lambda _: self._on_remove_image())
        image_col.append(remove_image_btn)

        fetch_image_btn = Gtk.Button(label="Fetch Fresh")
        fetch_image_btn.add_css_class("suggested-action")
        fetch_image_btn.connect("clicked", lambda _: self._on_pull_fresh_image())
        image_col.append(fetch_image_btn)
        mgmt_grid.append(image_col)

        # Volumes column
        volumes_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        volumes_col.add_css_class("card")
        volumes_col.set_margin_top(8)
        volumes_col.set_margin_bottom(8)
        volumes_col.set_margin_start(12)
        volumes_col.set_margin_end(12)

        volumes_header = Gtk.Label(label="Volumes")
        volumes_header.add_css_class("heading")
        volumes_col.append(volumes_header)

        remove_data_btn = Gtk.Button(label="Remove Data")
        remove_data_btn.add_css_class("destructive-action")
        remove_data_btn.connect("clicked", lambda _: self._on_remove_data_volume())
        volumes_col.append(remove_data_btn)

        remove_models_btn = Gtk.Button(label="Remove Models")
        remove_models_btn.add_css_class("destructive-action")
        remove_models_btn.connect("clicked", lambda _: self._on_remove_models_volume())
        volumes_col.append(remove_models_btn)
        mgmt_grid.append(volumes_col)

        box.append(mgmt_grid)

        # Volumes status
        volumes_frame = Gtk.Frame()
        volumes_frame.add_css_class("card")
        volumes_frame.set_margin_top(16)
        volumes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        volumes_box.set_margin_top(12)
        volumes_box.set_margin_bottom(12)
        volumes_box.set_margin_start(16)
        volumes_box.set_margin_end(16)

        # Data volume
        data_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        data_label = Gtk.Label(label="Data Volume:")
        data_label.add_css_class("dim-label")
        data_row.append(data_label)
        self._data_volume_status = Gtk.Label(label="Not found")
        data_row.append(self._data_volume_status)
        self._data_volume_size = Gtk.Label(label="")
        self._data_volume_size.add_css_class("dim-label")
        self._data_volume_size.add_css_class("caption")
        data_row.append(self._data_volume_size)
        volumes_box.append(data_row)

        # Models volume
        models_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        models_label = Gtk.Label(label="Models Volume:")
        models_label.add_css_class("dim-label")
        models_row.append(models_label)
        self._models_volume_status = Gtk.Label(label="Not found")
        models_row.append(self._models_volume_status)
        self._models_volume_size = Gtk.Label(label="")
        self._models_volume_size.add_css_class("dim-label")
        self._models_volume_size.add_css_class("caption")
        models_row.append(self._models_volume_size)
        volumes_box.append(models_row)

        # Models list
        self._models_list_label = Gtk.Label(label="")
        self._models_list_label.add_css_class("dim-label")
        self._models_list_label.add_css_class("caption")
        self._models_list_label.set_wrap(True)
        self._models_list_label.set_visible(False)
        volumes_box.append(self._models_list_label)

        # Volume path
        volumes_path = self._docker_manager.get_volumes_base_path()
        path_label = Gtk.Label(label=f"Path: {volumes_path}")
        path_label.add_css_class("dim-label")
        path_label.add_css_class("caption")
        volumes_box.append(path_label)

        volumes_frame.set_child(volumes_box)
        box.append(volumes_frame)

        # Show logs button with icon and text
        logs_btn = Gtk.Button()
        logs_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        logs_btn_icon = Gtk.Image.new_from_icon_name("utilities-log-viewer-symbolic")
        logs_btn_box.append(logs_btn_icon)
        logs_btn_label = Gtk.Label(label="Show Logs")
        logs_btn_box.append(logs_btn_label)
        logs_btn.set_child(logs_btn_box)
        logs_btn.add_css_class("secondary-button")
        logs_btn.set_halign(Gtk.Align.CENTER)
        logs_btn.set_margin_top(8)
        logs_btn.connect("clicked", lambda _: self._toggle_server_logs())
        box.append(logs_btn)

        scrolled.set_child(box)
        return scrolled

    def _create_client_view(self) -> Any:
        """Create the client management view."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(40)
        box.set_margin_end(40)
        box.set_size_request(450, -1)  # Minimum width for client view

        # Title
        title = Gtk.Label(label="Client")
        title.add_css_class("title-1")
        box.append(title)

        # Status card
        status_frame = Gtk.Frame()
        status_frame.add_css_class("card")
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.set_margin_top(12)
        status_box.set_margin_bottom(12)
        status_box.set_margin_start(16)
        status_box.set_margin_end(16)

        # Status row
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_label = Gtk.Label(label="Status:")
        status_label.add_css_class("dim-label")
        status_row.append(status_label)
        self._client_status_label = Gtk.Label(label="Stopped")
        status_row.append(self._client_status_label)
        status_box.append(status_row)

        # Connection row
        conn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        conn_label = Gtk.Label(label="Connection:")
        conn_label.add_css_class("dim-label")
        conn_row.append(conn_label)
        self._connection_info_label = Gtk.Label(label="Not connected")
        conn_row.append(self._connection_info_label)
        status_box.append(conn_row)

        status_frame.set_child(status_box)
        box.append(status_frame)

        # Control buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(20)

        self._start_client_local_btn = Gtk.Button(label="Start Local")
        self._start_client_local_btn.add_css_class("suggested-action")
        self._start_client_local_btn.connect(
            "clicked", lambda _: self._on_start_client_local()
        )
        btn_box.append(self._start_client_local_btn)

        self._start_client_remote_btn = Gtk.Button(label="Start Remote")
        self._start_client_remote_btn.add_css_class("suggested-action")
        self._start_client_remote_btn.connect(
            "clicked", lambda _: self._on_start_client_remote()
        )
        btn_box.append(self._start_client_remote_btn)

        self._stop_client_btn = Gtk.Button(label="Stop")
        self._stop_client_btn.add_css_class("destructive-action")
        self._stop_client_btn.set_sensitive(False)
        self._stop_client_btn.connect("clicked", lambda _: self._on_stop_client())
        btn_box.append(self._stop_client_btn)

        box.append(btn_box)

        # Web client button
        web_btn = Gtk.Button(label="Open Web Client")
        web_btn.add_css_class("secondary-button")
        web_btn.add_css_class("web-accent")
        web_btn.set_margin_top(12)
        web_btn.set_halign(Gtk.Align.CENTER)
        web_btn.connect("clicked", lambda _: self._on_open_web_client())
        box.append(web_btn)

        # Show logs button with icon and text
        logs_btn = Gtk.Button()
        logs_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        logs_btn_icon = Gtk.Image.new_from_icon_name("utilities-log-viewer-symbolic")
        logs_btn_box.append(logs_btn_icon)
        logs_btn_label = Gtk.Label(label="Show Logs")
        logs_btn_box.append(logs_btn_label)
        logs_btn.set_child(logs_btn_box)
        logs_btn.add_css_class("secondary-button")
        logs_btn.set_halign(Gtk.Align.CENTER)
        logs_btn.set_margin_top(8)
        logs_btn.connect("clicked", lambda _: self._toggle_client_logs())
        box.append(logs_btn)

        # Auto-add to Audio Notebook toggle
        notebook_frame = Gtk.Frame()
        notebook_frame.add_css_class("card")
        notebook_frame.set_margin_top(20)
        notebook_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        notebook_box.set_margin_top(12)
        notebook_box.set_margin_bottom(12)
        notebook_box.set_margin_start(16)
        notebook_box.set_margin_end(16)

        notebook_label = Gtk.Label(label="Auto-add to Audio Notebook:")
        notebook_label.add_css_class("dim-label")
        notebook_box.append(notebook_label)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        notebook_box.append(spacer)

        self._notebook_toggle_btn = Gtk.ToggleButton(label="Disabled")
        auto_notebook = self.config.get_server_config(
            "longform_recording", "auto_add_to_audio_notebook", default=False
        )
        self._notebook_toggle_btn.set_active(auto_notebook)
        self._notebook_toggle_btn.set_label("Enabled" if auto_notebook else "Disabled")
        self._notebook_toggle_btn.set_tooltip_text(
            "When enabled, recordings are saved to Audio Notebook with diarization\n"
            "instead of copying transcription to clipboard.\n"
            "Can only be changed when both server and client are stopped."
        )
        self._notebook_toggle_btn.connect("toggled", self._on_notebook_toggle)
        self._update_notebook_toggle_style()
        notebook_box.append(self._notebook_toggle_btn)

        notebook_frame.set_child(notebook_box)
        box.append(notebook_frame)

        # Live Transcription section
        preview_frame = Gtk.Frame()
        preview_frame.add_css_class("card")
        preview_frame.set_margin_top(16)
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_box.set_margin_top(12)
        preview_box.set_margin_bottom(12)
        preview_box.set_margin_start(16)
        preview_box.set_margin_end(16)

        # Live transcription header
        preview_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preview_title = Gtk.Label(label="Live Transcription")
        preview_title.add_css_class("dim-label")
        preview_header.append(preview_title)
        preview_box.append(preview_header)

        # Scrollable text view for live transcription history (~10 lines)
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        preview_scroll.set_min_content_height(180)
        preview_scroll.set_max_content_height(250)

        self._live_transcription_text_view = Gtk.TextView()
        self._live_transcription_text_view.set_editable(False)
        self._live_transcription_text_view.set_cursor_visible(False)
        self._live_transcription_text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._live_transcription_text_view.add_css_class("preview-text")
        self._live_transcription_text_buffer = (
            self._live_transcription_text_view.get_buffer()
        )
        self._live_transcription_text_buffer.set_text(
            "Start Live Mode to see transcription..."
        )
        preview_scroll.set_child(self._live_transcription_text_view)
        preview_box.append(preview_scroll)

        # Store history of transcription lines
        self._live_transcription_history: list[str] = []

        # Auto-paste toggle row
        paste_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        paste_row.set_margin_top(8)
        paste_label = Gtk.Label(label="Auto-paste to cursor:")
        paste_label.add_css_class("dim-label")
        paste_row.append(paste_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        paste_row.append(spacer)

        self._auto_paste_toggle_btn = Gtk.ToggleButton(label="Disabled")
        self._auto_paste_toggle_btn.set_active(False)
        self._auto_paste_toggle_btn.add_css_class("paste-disabled")
        self._auto_paste_toggle_btn.set_tooltip_text(
            "When enabled, completed sentences will be\n"
            "automatically pasted at the system cursor position."
        )
        self._auto_paste_toggle_btn.connect("toggled", self._on_auto_paste_toggle)
        paste_row.append(self._auto_paste_toggle_btn)
        preview_box.append(paste_row)

        preview_frame.set_child(preview_box)
        box.append(preview_frame)

        scrolled.set_child(box)
        return scrolled

    def _apply_styles(self) -> None:
        """Apply custom CSS styling matching KDE color scheme."""
        css = b"""
        /* Color scheme matching KDE Dashboard:
           - Background: #0a0a0a (darker)
           - Surface: #1e1e1e, #2d2d2d
           - Primary: #90caf9, #42a5f5
           - Error: #f44336, Success: #4caf50, Warning: #ff9800, Info: #2196f3
           - Server: #6B8DD9, Client: #D070D0, Web: #4DD0E1
        */

        /* Window background */
        window {
            background-color: #0a0a0a;
        }

        /* Accent colors */
        .server-accent {
            color: #6B8DD9;
        }
        .client-accent {
            color: #D070D0;
        }
        .web-accent {
            color: #4DD0E1;
        }

        /* Welcome buttons */
        .welcome-button {
            background: #1e1e1e;
            border: 1px solid #3d3d3d;
            border-radius: 8px;
            padding: 20px;
        }
        .welcome-button:hover {
            background: #3d3d3d;
            border-color: #4d4d4d;
        }
        .welcome-button.server-accent:hover {
            border-color: #6B8DD9;
        }
        .welcome-button.client-accent:hover {
            border-color: #D070D0;
        }

        /* Secondary button */
        .secondary-button {
            background: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 10px 24px;
            color: #ffffff;
        }
        .secondary-button:hover {
            background: #3d3d3d;
            border-color: #4d4d4d;
        }
        .secondary-button:disabled {
            background: #1e3a5f;
            border-color: #2d4d6f;
            color: #7090b0;
        }

        /* Web button with green-aquamarine accent */
        .secondary-button.web-accent {
            border-color: #4DD0E1;
        }
        .secondary-button.web-accent:hover {
            border-color: #80DEEA;
        }

        /* Model management button states */
        .models-loaded {
            background: #1e3a5f;
            border-color: #90caf9;
        }
        .models-loaded:hover {
            background: #2e4a6f;
        }
        .models-unloaded {
            background: #5d1f1f;
            border-color: #f44336;
        }
        .models-unloaded:hover {
            background: #6d2f2f;
        }

        /* Primary button (suggested-action style) */
        button.suggested-action {
            background: #90caf9;
            color: #121212;
            border-radius: 6px;
            padding: 10px 32px;
        }
        button.suggested-action:hover {
            background: #42a5f5;
        }

        /* Card styling */
        .card {
            background: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
            padding: 12px;
        }

        /* Status colors */
        .status-running {
            color: #4caf50;
        }
        .status-stopped {
            color: #6c757d;
        }
        .status-error {
            color: #f44336;
        }
        .status-starting {
            color: #2196f3;
        }
        .status-warning {
            color: #ff9800;
        }

        /* Nav button */
        .nav-button {
            background: transparent;
            border: none;
            padding: 5px 10px;
        }
        .nav-button:hover {
            background: #2d2d2d;
            border-radius: 4px;
            color: #90caf9;
        }

        /* Log view */
        .log-view {
            font-family: "CaskaydiaCove Nerd Font", "Cascadia Code", monospace;
            background: #1e1e1e;
            color: #d4d4d4;
        }

        /* Text labels */
        .dim-label {
            color: #a0a0a0;
        }

        /* Notebook toggle button states */
        .notebook-enabled {
            background: #4caf50;
            color: white;
            border-radius: 4px;
            padding: 6px 12px;
            min-width: 70px;
        }
        .notebook-enabled:hover {
            background: #43a047;
        }
        .notebook-enabled:disabled {
            background: #3d5d3d;
            color: #7a9a7a;
        }
        .notebook-disabled {
            background: #f44336;
            color: white;
            border-radius: 4px;
            padding: 6px 12px;
            min-width: 70px;
        }
        .notebook-disabled:hover {
            background: #e53935;
        }
        .notebook-disabled:disabled {
            background: #5d3d3d;
            color: #9a7a7a;
        }

        /* Preview text view */
        .preview-text {
            background: #252526;
            color: #e0e0e0;
            font-family: "Inter", sans-serif;
            font-size: 13px;
            padding: 8px;
        }

        /* Auto-paste toggle button states */
        .paste-enabled {
            background: #4caf50;
            color: white;
            border-radius: 4px;
            padding: 4px 10px;
            font-size: 11px;
            min-width: 60px;
        }
        .paste-enabled:hover {
            background: #43a047;
        }
        .paste-disabled {
            background: #f44336;
            color: white;
            border-radius: 4px;
            padding: 4px 10px;
            font-size: 11px;
            min-width: 60px;
        }
        .paste-disabled:hover {
            background: #e53935;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    # =========================================================================
    # Navigation
    # =========================================================================

    def _navigate_to(self, view: View, add_to_history: bool = True) -> None:
        """Navigate to a specific view."""
        if add_to_history and self._current_view != view:
            self._view_history.append(self._current_view)

        self._current_view = view

        view_names = {
            View.WELCOME: "welcome",
            View.SERVER: "server",
            View.CLIENT: "client",
        }

        if self._stack:
            self._stack.set_visible_child_name(view_names[view])

        # Refresh status when navigating to views
        if view == View.WELCOME:
            self._refresh_home_status()
        elif view == View.SERVER:
            self._refresh_server_status()
        elif view == View.CLIENT:
            self._refresh_client_status()

    def _go_home(self) -> None:
        """Navigate to home view."""
        self._navigate_to(View.WELCOME)

    def _on_close_request(self, window) -> bool:
        """Handle window close - hide to tray instead of quitting."""
        self.hide()
        return True  # Prevent default close

    def force_close(self) -> None:
        """Force close the window (when quitting app)."""
        self._stop_status_timer()
        self.destroy()

    # =========================================================================
    # Status Updates
    # =========================================================================

    def _start_status_timer(self) -> None:
        """Start periodic status updates."""
        self._status_timer_id = GLib.timeout_add_seconds(5, self._on_status_tick)
        # Initial refresh
        self._refresh_home_status()
        self._refresh_server_status()

    def _stop_status_timer(self) -> None:
        """Stop status update timer."""
        if self._status_timer_id:
            GLib.source_remove(self._status_timer_id)
            self._status_timer_id = None

    def _on_status_tick(self) -> bool:
        """Called periodically to refresh status."""
        self._refresh_home_status()
        if self._current_view == View.SERVER:
            self._refresh_server_status()
        return True  # Continue timer

    def _refresh_home_status(self) -> None:
        """Refresh home view status indicators."""
        if not self._home_server_status:
            return

        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()

        if status == ServerStatus.RUNNING:
            mode_str = f" ({mode.value})" if mode else ""
            health = self._docker_manager.get_container_health()
            if health and health != "healthy":
                if health == "unhealthy":
                    self._home_server_status.set_text(f"⬤ Unhealthy{mode_str}")
                    self._home_server_status.remove_css_class("status-running")
                    self._home_server_status.add_css_class("status-error")
                else:
                    self._home_server_status.set_text(f"⬤ Starting...{mode_str}")
                    self._home_server_status.remove_css_class("status-running")
                    self._home_server_status.add_css_class("status-starting")
            else:
                self._home_server_status.set_text(f"⬤ Running{mode_str}")
                self._home_server_status.remove_css_class("status-error")
                self._home_server_status.remove_css_class("status-starting")
                self._home_server_status.add_css_class("status-running")
        elif status == ServerStatus.STOPPED:
            self._home_server_status.set_text("⬤ Stopped")
            self._home_server_status.remove_css_class("status-running")
            self._home_server_status.remove_css_class("status-error")
            self._home_server_status.add_css_class("status-stopped")
        else:
            self._home_server_status.set_text("⬤ Not set up")
            self._home_server_status.add_css_class("status-stopped")

        # Client status
        if self._home_client_status:
            if self._client_running:
                self._home_client_status.set_text("⬤ Running")
                self._home_client_status.add_css_class("status-running")
            else:
                self._home_client_status.set_text("⬤ Stopped")
                self._home_client_status.remove_css_class("status-running")
                self._home_client_status.add_css_class("status-stopped")

    def _refresh_server_status(self) -> None:
        """Refresh server view status."""
        if not self._server_status_label:
            return

        status = self._docker_manager.get_server_status()

        if status == ServerStatus.RUNNING:
            self._server_status_label.set_text("Running")
            self._server_status_label.add_css_class("status-running")
        elif status == ServerStatus.STOPPED:
            self._server_status_label.set_text("Stopped")
            self._server_status_label.add_css_class("status-stopped")
        else:
            self._server_status_label.set_text("Not set up")

        # Image status
        if self._image_status_label:
            if self._docker_manager.image_exists_locally():
                self._image_status_label.set_text("Available")
                # Get image date
                image_date = self._docker_manager.get_image_created_date()
                if self._image_date_label and image_date:
                    self._image_date_label.set_text(f"  ({image_date})")
                else:
                    self._image_date_label.set_text("")
                # Get image size
                image_size = self._docker_manager.get_image_size()
                if self._image_size_label and image_size:
                    self._image_size_label.set_text(f"  [{image_size}]")
                else:
                    self._image_size_label.set_text("")
            else:
                self._image_status_label.set_text("Not found")
                if self._image_date_label:
                    self._image_date_label.set_text("")
                if self._image_size_label:
                    self._image_size_label.set_text("")

        # Volume status
        data_volume_exists = self._docker_manager.volume_exists(
            "transcription-suite-data"
        )
        models_volume_exists = self._docker_manager.volume_exists(
            "transcription-suite-models"
        )

        if self._data_volume_status:
            if data_volume_exists:
                self._data_volume_status.set_text("Available")
                size = self._docker_manager.get_volume_size("transcription-suite-data")
                if self._data_volume_size and size:
                    self._data_volume_size.set_text(f"  ({size})")
                else:
                    self._data_volume_size.set_text("")
            else:
                self._data_volume_status.set_text("Not found")
                if self._data_volume_size:
                    self._data_volume_size.set_text("")

        if self._models_volume_status:
            if models_volume_exists:
                self._models_volume_status.set_text("Available")
                size = self._docker_manager.get_volume_size("transcription-suite-models")
                if self._models_volume_size and size:
                    self._models_volume_size.set_text(f"  ({size})")
                else:
                    self._models_volume_size.set_text("")
            else:
                self._models_volume_status.set_text("Not found")
                if self._models_volume_size:
                    self._models_volume_size.set_text("")

        # Update models list
        if self._models_list_label:
            if models_volume_exists and status == ServerStatus.RUNNING:
                models = self._docker_manager.list_downloaded_models()
                if models:
                    models_lines = [f"  • {m['name']} ({m['size']})" for m in models]
                    models_text = "Downloaded:\n" + "\n".join(models_lines)
                    self._models_list_label.set_text(models_text)
                    self._models_list_label.set_visible(True)
                else:
                    self._models_list_label.set_text("No models downloaded yet")
                    self._models_list_label.set_visible(True)
            elif models_volume_exists:
                self._models_list_label.set_text("(Start server to view models)")
                self._models_list_label.set_visible(True)
            else:
                self._models_list_label.set_visible(False)

        # Load auth token - check logs when running to catch new tokens
        if self._server_token_entry:
            if status == ServerStatus.RUNNING:
                # Force check logs for latest token
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
                token = new_token or self._docker_manager.get_admin_token(
                    check_logs=False
                )
            else:
                # When not running, just use cached token
                token = self._docker_manager.get_admin_token(check_logs=False)

            if token:
                self._server_token_entry.set_text(token)
            else:
                self._server_token_entry.set_text("Not saved yet")

        # Update models button state when server status changes
        self._update_models_button_state()

        # Update notebook toggle state when server status changes
        if self._notebook_toggle_btn:
            server_stopped = status != ServerStatus.RUNNING
            self._notebook_toggle_btn.set_sensitive(
                not self._client_running and server_stopped
            )

    def _refresh_client_status(self) -> None:
        """Refresh client view status."""
        if self._client_status_label:
            if self._client_running:
                self._client_status_label.set_text("Running")
                self._client_status_label.add_css_class("status-running")
            else:
                self._client_status_label.set_text("Stopped")
                self._client_status_label.add_css_class("status-stopped")

        if self._connection_info_label:
            use_remote = self.config.get("server", "use_remote", default=False)
            if use_remote:
                host = self.config.get("server", "remote_host", default="")
                port = self.config.get("server", "port", default=8443)
                self._connection_info_label.set_text(f"{host}:{port} (HTTPS)")
            else:
                port = self.config.get("server", "port", default=8000)
                self._connection_info_label.set_text(f"localhost:{port}")

        # Update models button based on server health
        self._update_models_button_state()

        # Update models button based on server health
        self._update_models_button_state()

    def _update_models_button_state(self) -> None:
        """Update the models button state based on server health and connection type."""
        if not self._unload_models_btn:
            return

        # Check if server is running and healthy
        status = self._docker_manager.get_server_status()
        health = self._docker_manager.get_container_health()

        is_healthy = status == ServerStatus.RUNNING and (
            health is None or health == "healthy"
        )

        # Only enable if healthy AND connected locally (model management unavailable for remote)
        if is_healthy and self._is_local_connection:
            # Server is healthy and local, enable button with appropriate color
            self._unload_models_btn.set_sensitive(True)
            if self._models_loaded:
                # Light blue (models loaded, ready to unload)
                self._unload_models_btn.remove_css_class("models-unloaded")
                self._unload_models_btn.add_css_class("models-loaded")
            else:
                # Red (models unloaded, ready to reload)
                self._unload_models_btn.remove_css_class("models-loaded")
                self._unload_models_btn.add_css_class("models-unloaded")
        else:
            # Server not healthy, disable button (gray)
            self._unload_models_btn.set_sensitive(False)
            self._unload_models_btn.remove_css_class("models-loaded")
            self._unload_models_btn.remove_css_class("models-unloaded")

    def set_connection_local(self, is_local: bool) -> None:
        """
        Update connection type.

        Args:
            is_local: True if connected to localhost, False if remote
        """
        self._is_local_connection = is_local
        # Refresh button state with new connection type
        self._update_models_button_state()

    def set_client_running(self, running: bool) -> None:
        """Update client running state."""
        self._client_running = running
        self._refresh_home_status()
        self._refresh_client_status()

        if self._stop_client_btn:
            self._stop_client_btn.set_sensitive(running)
        if self._start_client_local_btn:
            self._start_client_local_btn.set_sensitive(not running)
        if self._start_client_remote_btn:
            self._start_client_remote_btn.set_sensitive(not running)
        if self._notebook_toggle_btn:
            # Notebook toggle only allowed when both server and client are stopped
            server_status = self._docker_manager.get_server_status()
            server_stopped = server_status != ServerStatus.RUNNING
            self._notebook_toggle_btn.set_sensitive(not running and server_stopped)

    # =========================================================================
    # Server Operations
    # =========================================================================

    def _on_start_server_local(self) -> None:
        """Start server in local mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(ServerMode.LOCAL),
            "Starting server (local mode)...",
        )

    def _on_start_server_remote(self) -> None:
        """Start server in remote mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(ServerMode.REMOTE),
            "Starting server (remote mode)...",
        )

    def _on_stop_server(self) -> None:
        """Stop the server."""
        self._run_server_operation(
            lambda: self._docker_manager.stop_server(),
            "Stopping server...",
        )
        # Clear server logs when server is stopped
        if self._server_log_window is not None:
            self._server_log_window.clear_logs()

    def _on_remove_container(self) -> None:
        """Remove the Docker container."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_container(),
            "Removing container...",
        )
        # Clear server logs when container is removed
        if self._server_log_window is not None:
            self._server_log_window.clear_logs()

    def _on_remove_image(self) -> None:
        """Remove the Docker image."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_image(),
            "Removing image...",
        )

    def _on_pull_fresh_image(self) -> None:
        """Pull fresh Docker image (async, non-blocking)."""
        # Prevent starting another pull if one is already in progress
        if self._pull_worker is not None and self._pull_worker.is_alive():
            logger.warning("Docker pull already in progress")
            self._show_notification("Docker Server", "Image download already in progress")
            return

        self._show_notification(
            "Docker Server",
            "Starting image download (~15GB). This may take a while...",
        )

        def on_progress(msg: str) -> None:
            """Called from worker thread - schedule UI update on main thread."""
            GLib.idle_add(self._update_pull_progress, msg)

        def on_complete(result: DockerResult) -> None:
            """Called from worker thread - schedule UI update on main thread."""
            GLib.idle_add(self._on_pull_complete, result)

        # Start async pull
        self._pull_worker = self._docker_manager.start_pull_worker(
            progress_callback=on_progress,
            complete_callback=on_complete,
        )
        logger.info("Started async Docker image pull")

    def _update_pull_progress(self, msg: str) -> bool:
        """Update UI with pull progress (called on main thread via GLib.idle_add)."""
        logger.info(msg)
        # For GNOME, we just log progress - notifications would be too spammy
        return False  # Return False to remove from idle queue

    def _on_pull_complete(self, result: DockerResult) -> bool:
        """Handle pull completion (called on main thread via GLib.idle_add)."""
        self._pull_worker = None

        if result.success:
            self._show_notification("Docker Server", result.message)
            logger.info("Docker image pull completed successfully")
        else:
            self._show_notification("Docker Server", f"Error: {result.message}")
            logger.error(f"Docker image pull failed: {result.message}")

        # Refresh status
        self._refresh_server_status()
        self._refresh_home_status()
        return False  # Return False to remove from idle queue

    def _on_remove_data_volume(self) -> None:
        """Remove data volume with confirmation dialog."""
        # Check if container exists first
        status = self._docker_manager.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            self._show_notification(
                "Cannot Remove Volume",
                "Container must be removed first. Remove the container, then try again.",
            )
            return

        # Show confirmation dialog with checkbox for config removal
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Remove Data Volume",
            body=(
                "WARNING: This will DELETE ALL SERVER DATA!\n\n"
                "This will permanently delete:\n"
                "• The SQLite database\n"
                "• All user data and transcription history\n"
                "• Server authentication token\n\n"
                "This action cannot be undone!"
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        # Add checkbox for config directory removal
        checkbox = Gtk.CheckButton(label="Also remove config directory")
        checkbox.set_tooltip_text(
            f"Remove {self._docker_manager.config_dir}\n"
            "(contains dashboard.yaml, docker-compose.yml, etc.)"
        )
        dialog.set_extra_child(checkbox)

        def on_response(dialog: Adw.MessageDialog, response: str) -> None:
            if response == "delete":
                also_remove_config = checkbox.get_active()
                self._run_server_operation(
                    lambda: self._docker_manager.remove_data_volume(
                        also_remove_config=also_remove_config
                    ),
                    "Removing data volume...",
                )

        dialog.connect("response", on_response)
        dialog.present()

    def _on_remove_models_volume(self) -> None:
        """Remove models volume."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_models_volume(),
            "Removing models volume...",
        )

    def _run_server_operation(self, operation, progress_msg: str) -> None:
        """Run a Docker operation with notification."""
        try:
            self._show_notification("Docker Server", progress_msg)
            result = operation()
            self._show_notification("Docker Server", result.message)
            self._refresh_server_status()
            self._refresh_home_status()
        except Exception as e:
            logger.error(f"Server operation failed: {e}")
            self._show_notification("Docker Server", f"Error: {e}")

    def _toggle_server_logs(self) -> None:
        """Toggle server log window."""
        if self._server_log_window is None:
            self._server_log_window = LogWindow("Server Logs")

        logs = self._docker_manager.get_logs(lines=300)
        self._server_log_window.set_logs(logs)
        self._server_log_window.present()

    # =========================================================================
    # Client Operations
    # =========================================================================

    def _on_start_client_local(self) -> None:
        """Start client in local mode."""
        self.config.set("server", "use_remote", value=False)
        self.config.set("server", "use_https", value=False)
        self.config.set("server", "port", value=8000)
        self.config.save()

        if self._start_client_callback:
            self._start_client_callback(False)
        self.set_client_running(True)

    def _on_start_client_remote(self) -> None:
        """Start client in remote mode."""
        self.config.set("server", "use_remote", value=True)
        self.config.set("server", "use_https", value=True)
        self.config.set("server", "port", value=8443)
        self.config.save()

        if self._start_client_callback:
            self._start_client_callback(True)
        self.set_client_running(True)

    def _on_stop_client(self) -> None:
        """Stop the client."""
        if self._stop_client_callback:
            self._stop_client_callback()
        self.set_client_running(False)

    def _toggle_client_logs(self) -> None:
        """Toggle client log window."""
        if self._client_log_window is None:
            self._client_log_window = LogWindow("Client Logs")

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
        self._client_log_window.present()

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
                if self._models_loaded:
                    if self._unload_models_btn:
                        self._unload_models_btn.set_label("Unload All Models")
                        self._unload_models_btn.set_tooltip_text(
                            "Unload transcription models to free GPU memory"
                        )
                        # Change to light blue styling (models loaded)
                        self._unload_models_btn.remove_css_class("models-unloaded")
                        self._unload_models_btn.add_css_class("models-loaded")
                    self._show_notification(
                        "Models Loaded", "Models ready for transcription"
                    )
                else:
                    if self._unload_models_btn:
                        self._unload_models_btn.set_label("Reload Models")
                        self._unload_models_btn.set_tooltip_text(
                            "Reload transcription models for use"
                        )
                        # Change to red styling (models unloaded)
                        self._unload_models_btn.remove_css_class("models-loaded")
                        self._unload_models_btn.add_css_class("models-unloaded")
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

    def _on_notebook_toggle(self, button: Any) -> None:
        """Handle notebook toggle button click."""
        is_enabled = button.get_active()
        button.set_label("Enabled" if is_enabled else "Disabled")
        self._update_notebook_toggle_style()

        # Save to server config - orchestrator will read this on next startup
        self.config.set_server_config(
            "longform_recording", "auto_add_to_audio_notebook", value=is_enabled
        )

        logger.info(f"Auto-add to notebook: {'enabled' if is_enabled else 'disabled'}")

    def _update_notebook_toggle_style(self) -> None:
        """Update notebook toggle button style based on state."""
        if not self._notebook_toggle_btn:
            return

        if self._notebook_toggle_btn.get_active():
            # Enabled state - green
            self._notebook_toggle_btn.remove_css_class("notebook-disabled")
            self._notebook_toggle_btn.add_css_class("notebook-enabled")
        else:
            # Disabled state - gray
            self._notebook_toggle_btn.remove_css_class("notebook-enabled")
            self._notebook_toggle_btn.add_css_class("notebook-disabled")

    def _on_auto_paste_toggle(self, button: Any) -> None:
        """Handle auto-paste toggle button click."""
        is_enabled = button.get_active()
        button.set_label("Enabled" if is_enabled else "Disabled")

        if is_enabled:
            button.remove_css_class("paste-disabled")
            button.add_css_class("paste-enabled")
        else:
            button.remove_css_class("paste-enabled")
            button.add_css_class("paste-disabled")

        # Save to config
        self.config.set("preview", "auto_paste_to_cursor", value=is_enabled)

        # Update orchestrator for Live Mode auto-paste
        if self._dbus_service and self._dbus_service.orchestrator:
            self._dbus_service.orchestrator.set_live_mode_auto_paste(is_enabled)

        logger.info(f"Auto-paste to cursor: {'enabled' if is_enabled else 'disabled'}")

    def update_live_transcription_text(self, text: str, append: bool = False) -> None:
        """
        Update live transcription text display.

        Args:
            text: The text to display
            append: If True, append to history. If False, replace current line.
        """
        if (
            not hasattr(self, "_live_transcription_text_buffer")
            or not self._live_transcription_text_buffer
        ):
            return

        if not text:
            self._live_transcription_text_buffer.set_text("")
            return

        if append:
            # Append text as a new line in history
            self._live_transcription_history.append(text)
            # Keep only last ~20 lines to prevent memory bloat
            if len(self._live_transcription_history) > 20:
                self._live_transcription_history = self._live_transcription_history[-20:]
            # Update display
            self._live_transcription_text_buffer.set_text(
                "\n".join(self._live_transcription_history)
            )
        else:
            # Real-time update: show history + current partial text
            if self._live_transcription_history:
                display_text = "\n".join(self._live_transcription_history) + "\n" + text
            else:
                display_text = text
            self._live_transcription_text_buffer.set_text(display_text)

        # Auto-scroll to bottom - schedule on idle to ensure layout is updated
        if hasattr(self, "_live_transcription_text_view"):
            from gi.repository import GLib

            GLib.idle_add(self._scroll_live_transcription_to_bottom)

    def _scroll_live_transcription_to_bottom(self) -> bool:
        """Scroll live transcription text view to bottom."""
        if (
            hasattr(self, "_live_transcription_text_view")
            and self._live_transcription_text_view
        ):
            adj = self._live_transcription_text_view.get_parent().get_vadjustment()
            if adj:
                adj.set_value(adj.get_upper() - adj.get_page_size())
        return False  # Don't repeat

    def clear_live_transcription_history(self) -> None:
        """Clear the live transcription text history."""
        if hasattr(self, "_live_transcription_history"):
            self._live_transcription_history.clear()
        if (
            hasattr(self, "_live_transcription_text_buffer")
            and self._live_transcription_text_buffer
        ):
            self._live_transcription_text_buffer.set_text("")

    # =========================================================================
    # Web Client
    # =========================================================================

    def _on_open_web_client(self) -> None:
        """Open web client in browser."""
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

    # =========================================================================
    # Help & About
    # =========================================================================

    def _trigger_show_settings(self) -> None:
        """Trigger the settings callback if set."""
        if self._show_settings_callback:
            self._show_settings_callback()

    def _show_readme(self, dev: bool = False) -> None:
        """Show README in a dialog with plain text display.

        Note: WebKit 6.0 crashes with SIGTRAP on Ubuntu 24.04.
        Displaying as plain text for maximum compatibility.
        """
        readme_path = _get_readme_path(dev=dev)
        if not readme_path:
            self._show_notification(
                "Help",
                "Documentation not found",
            )
            return

        try:
            content = readme_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read readme: {e}")
            return

        # Create dialog
        dialog = Adw.Window()
        dialog.set_title("User Guide" if not dev else "Developer Guide")
        dialog.set_default_size(900, 700)
        dialog.set_transient_for(self)
        dialog.set_modal(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        box.append(header)

        # Plain text view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        text_view.set_left_margin(20)
        text_view.set_right_margin(20)
        text_view.set_top_margin(20)
        text_view.set_bottom_margin(20)
        text_view.add_css_class("readme-view")

        # Apply dark theme styling
        css = b"""
        .readme-view {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: "CaskaydiaCove Nerd Font", monospace;
            font-size: 10pt;
        }
        .readme-view text {
            background-color: #1e1e1e;
            color: #d4d4d4;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Set plain text content
        buffer = text_view.get_buffer()
        buffer.set_text(content)

        scrolled.set_child(text_view)
        box.append(scrolled)

        dialog.set_content(box)
        dialog.present()

    def _show_about_dialog(self) -> None:
        """Show the About dialog with author info and links, matching KDE layout."""
        # Create custom dialog window
        dialog = Adw.Window()
        dialog.set_title("About TranscriptionSuite")
        dialog.set_default_size(480, 620)
        dialog.set_transient_for(self)
        dialog.set_modal(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        main_box.append(header)

        # Content box with padding
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_top(24)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(32)
        content_box.set_margin_end(32)

        # Profile picture
        profile_pixbuf = self._load_profile_picture()
        if profile_pixbuf:
            # Create circular image using Adw.Avatar
            avatar = Adw.Avatar()
            avatar.set_size(100)
            avatar.set_custom_image(Gdk.Texture.new_for_pixbuf(profile_pixbuf))
            avatar.set_halign(Gtk.Align.CENTER)
            content_box.append(avatar)
        else:
            # Fallback placeholder
            placeholder = Gtk.Label(label="👤")
            placeholder.add_css_class("title-1")
            placeholder.set_halign(Gtk.Align.CENTER)
            content_box.append(placeholder)

        # App name
        app_name = Gtk.Label(label="TranscriptionSuite")
        app_name.add_css_class("title-1")
        app_name.set_halign(Gtk.Align.CENTER)
        content_box.append(app_name)

        # Version info
        app_version = self._get_app_version()
        version_label = Gtk.Label(label=f"v{app_version}")
        version_label.add_css_class("dim-label")
        version_label.set_halign(Gtk.Align.CENTER)
        content_box.append(version_label)

        # Description
        description = Gtk.Label(label="Speech-to-Text Transcription Suite")
        description.add_css_class("dim-label")
        description.set_halign(Gtk.Align.CENTER)
        content_box.append(description)

        # Copyright notice
        copyright_label = Gtk.Label(label="© 2025-2026 homelab-00 • MIT License")
        copyright_label.add_css_class("dim-label")
        copyright_label.add_css_class("caption")
        copyright_label.set_halign(Gtk.Align.CENTER)
        content_box.append(copyright_label)

        # Links section in a card
        links_frame = Gtk.Frame()
        links_frame.add_css_class("card")
        links_frame.set_margin_top(16)
        links_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        links_box.set_margin_top(16)
        links_box.set_margin_bottom(16)
        links_box.set_margin_start(16)
        links_box.set_margin_end(16)

        # Author section
        author_header = Gtk.Label(label="Author")
        author_header.add_css_class("heading")
        author_header.set_halign(Gtk.Align.START)
        links_box.append(author_header)

        # GitHub Profile button with icon and proper styling
        github_profile_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        github_profile_icon = Gtk.Image.new_from_icon_name("user-info-symbolic")
        github_profile_box.append(github_profile_icon)
        github_profile_label = Gtk.Label(label="GitHub Profile")
        github_profile_box.append(github_profile_label)

        github_profile_btn = Gtk.Button()
        github_profile_btn.set_child(github_profile_box)
        github_profile_btn.set_has_frame(True)
        github_profile_btn.set_halign(Gtk.Align.FILL)
        github_profile_btn.connect(
            "clicked", lambda _: webbrowser.open(GITHUB_PROFILE_URL)
        )
        links_box.append(github_profile_btn)

        # Repository section
        repo_header = Gtk.Label(label="Repository")
        repo_header.add_css_class("heading")
        repo_header.set_halign(Gtk.Align.START)
        repo_header.set_margin_top(12)
        links_box.append(repo_header)

        # GitHub Repository button with icon and proper styling
        github_repo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        github_repo_icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        github_repo_box.append(github_repo_icon)
        github_repo_label = Gtk.Label(label="GitHub Repository")
        github_repo_box.append(github_repo_label)

        github_repo_btn = Gtk.Button()
        github_repo_btn.set_child(github_repo_box)
        github_repo_btn.set_has_frame(True)
        github_repo_btn.set_halign(Gtk.Align.FILL)
        github_repo_btn.connect("clicked", lambda _: webbrowser.open(GITHUB_REPO_URL))
        links_box.append(github_repo_btn)

        links_frame.set_child(links_box)
        content_box.append(links_frame)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        content_box.append(spacer)

        # Close button
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("suggested-action")
        close_btn.set_halign(Gtk.Align.CENTER)
        close_btn.connect("clicked", lambda _: dialog.close())
        content_box.append(close_btn)

        main_box.append(content_box)
        dialog.set_content(main_box)
        dialog.present()

    def _load_profile_picture(self):
        """Load the profile picture from bundled assets. Returns GdkPixbuf or None."""
        if GdkPixbuf is None:
            logger.warning("GdkPixbuf not available")
            return None

        assets_path = _get_assets_path()
        logger.info(f"Loading profile picture from assets path: {assets_path}")

        profile_path = assets_path / "profile.png"
        logger.info(
            f"Checking profile picture at: {profile_path} (exists: {profile_path.exists()})"
        )

        if profile_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(profile_path))
                # Scale to appropriate size
                pixbuf = pixbuf.scale_simple(100, 100, GdkPixbuf.InterpType.BILINEAR)
                logger.info("Successfully loaded profile picture")
                return pixbuf
            except Exception as e:
                logger.error(f"Failed to load profile picture: {e}", exc_info=True)

        # Fallback to logo
        logo_path = assets_path / "logo.png"
        logger.info(f"Checking logo at: {logo_path} (exists: {logo_path.exists()})")
        if logo_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(logo_path))
                pixbuf = pixbuf.scale_simple(100, 100, GdkPixbuf.InterpType.BILINEAR)
                logger.info("Successfully loaded logo as fallback")
                return pixbuf
            except Exception as e:
                logger.error(f"Failed to load logo: {e}", exc_info=True)

        logger.warning("No profile picture or logo found")
        return None

    def _get_app_version(self) -> str:
        """Get the application version using shared version utility."""
        from dashboard.common.version import __version__

        return __version__

    # =========================================================================
    # Notifications
    # =========================================================================

    def _show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification."""
        # Check if notifications are enabled in settings
        if not self._config.get("ui", "notifications", default=True):
            logger.debug("Notifications disabled in settings")
            return

        try:
            subprocess.run(
                ["notify-send", "-a", "TranscriptionSuite", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            logger.debug("notify-send not found - cannot show desktop notifications")


# =============================================================================
# Standalone Entry Point
# =============================================================================


def run_dashboard(config_path: Path | None = None) -> int:
    """
    Run the Dashboard as a standalone GTK4 application.

    This function is called from dashboard_main.py when the Dashboard is
    spawned as a separate process from the tray.

    Args:
        config_path: Optional path to client config file

    Returns:
        Exit code (0 for success)
    """
    import sys

    if not HAS_GTK4:
        print(
            "Error: GTK4 and libadwaita are required.\n"
            "Install with:\n"
            "  Arch Linux: sudo pacman -S gtk4 libadwaita\n"
            "  Ubuntu/Debian: sudo apt install gir1.2-adw-1 gir1.2-gtk-4.0",
            file=sys.stderr,
        )
        return 1

    # Load config
    from dashboard.common.config import ClientConfig

    if config_path:
        config = ClientConfig(config_path)
    else:
        config = ClientConfig()

    # Create D-Bus client for communicating with tray process
    from dashboard.gnome.dbus_service import DashboardDBusClient

    dbus_client = DashboardDBusClient()
    tray_connected = dbus_client.is_connected()

    if not tray_connected:
        logger.warning(
            "D-Bus connection to tray not available. "
            "Client control will be disabled. Start the tray first."
        )

    # Create and run the application
    # GApplication with a unique application_id provides single-instance behavior:
    # When a second instance tries to start, the existing instance receives
    # an "activate" signal instead of a new instance starting.
    app = Adw.Application(
        application_id="com.transcriptionsuite.dashboard",
        flags=Gio.ApplicationFlags.FLAGS_NONE,
    )

    # Store the window reference to reuse on subsequent activations
    main_window: DashboardWindow | None = None

    def on_activate(application: Adw.Application) -> None:
        """Create and present the main window, or present existing window."""
        nonlocal main_window

        # If window already exists, just present it (handles single-instance)
        if main_window is not None:
            main_window.present()
            return

        # Wrap D-Bus client methods for use as callbacks
        def on_start_client(use_remote: bool) -> None:
            if tray_connected:
                success, message = dbus_client.start_client(use_remote)
                if not success:
                    logger.error(f"Failed to start client: {message}")
            else:
                logger.warning("Cannot start client: tray not connected")

        def on_stop_client() -> None:
            if tray_connected:
                success, message = dbus_client.stop_client()
                if not success:
                    logger.error(f"Failed to stop client: {message}")
            else:
                logger.warning("Cannot stop client: tray not connected")

        def on_show_settings() -> None:
            # Always show settings directly from Dashboard (GTK4)
            # No need to go through D-Bus/tray
            from dashboard.gnome.settings_dialog import SettingsDialog

            dialog = SettingsDialog(config, parent=None)
            dialog.show()

        main_window = DashboardWindow(
            config=config,
            app=application,
            on_start_client=on_start_client if tray_connected else None,
            on_stop_client=on_stop_client if tray_connected else None,
            on_show_settings=on_show_settings,
        )

        # Connect live transcription updates
        if tray_connected:
            dbus_client.connect_live_transcription_text(
                lambda text, append: GLib.idle_add(
                    main_window.update_live_transcription_text, text, append
                )
            )

        # If tray not connected, show a warning banner
        if not tray_connected:
            main_window._show_notification(
                "Limited Mode",
                "Client control unavailable. Start the tray first for full functionality.",
            )

        main_window.present()

    app.connect("activate", on_activate)
    return app.run(sys.argv)
