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

from client.common.docker_manager import DockerManager, ServerMode, ServerStatus

logger = logging.getLogger(__name__)

# Import GTK4 and Adwaita
HAS_GTK4 = False
try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

    HAS_GTK4 = True

except (ImportError, ValueError) as e:
    logger.warning(f"GTK4/Adwaita not available: {e}")
    Adw = None  # type: ignore
    Gdk = None  # type: ignore
    GdkPixbuf = None  # type: ignore
    Gio = None  # type: ignore
    GLib = None  # type: ignore
    Gtk = None  # type: ignore

if TYPE_CHECKING:
    from client.common.config import ClientConfig

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
                bundle_dir / "src" / "client" / filename,
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
    """Separate window for displaying logs."""

    def __init__(self, title: str, app: Any = None):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for LogWindow")

        super().__init__(title=title)
        if app:
            self.set_application(app)
        self.set_default_size(800, 600)

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

        self._text_view = Gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_monospace(True)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.add_css_class("log-view")

        scrolled.set_child(self._text_view)
        content.append(scrolled)

        self.set_content(content)
        self._apply_styles()

    def append_log(self, message: str) -> None:
        """Append a log message to the view."""
        buffer = self._text_view.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, message + "\n")
        # Auto-scroll to bottom
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self._text_view.scroll_to_mark(mark, 0, False, 0, 0)

    def set_logs(self, logs: str) -> None:
        """Set the entire log content."""
        buffer = self._text_view.get_buffer()
        buffer.set_text(logs)
        # Auto-scroll to bottom
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self._text_view.scroll_to_mark(mark, 0, False, 0, 0)

    def clear_logs(self) -> None:
        """Clear all logs."""
        buffer = self._text_view.get_buffer()
        buffer.set_text("")

    def _apply_styles(self) -> None:
        """Apply dark theme styling."""
        css = b"""
        .log-view {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: "CaskaydiaCove Nerd Font", monospace;
            font-size: 12pt;
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
        self._on_start_client = on_start_client
        self._on_stop_client = on_stop_client
        self._on_show_settings = on_show_settings

        # View history for navigation
        self._view_history: list[View] = []
        self._current_view: View = View.WELCOME

        # Log windows
        self._server_log_window: LogWindow | None = None
        self._client_log_window: LogWindow | None = None

        # Client state tracking
        self._client_running = False

        # Status update timers
        self._status_timer_id: int | None = None

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

        # Right side: Help, About buttons
        help_btn = Gtk.Button()
        help_btn.set_icon_name("help-contents-symbolic")
        help_btn.set_tooltip_text("Help")
        help_btn.add_css_class("nav-button")
        help_btn.connect("clicked", self._show_help_menu)
        header.pack_end(help_btn)

        about_btn = Gtk.Button()
        about_btn.set_icon_name("help-about-symbolic")
        about_btn.set_tooltip_text("About")
        about_btn.add_css_class("nav-button")
        about_btn.connect("clicked", lambda _: self._show_about_dialog())
        header.pack_end(about_btn)

        return header

    def _create_welcome_view(self) -> Any:
        """Create the welcome/home view."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(40)
        box.set_margin_end(40)

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

        # Web client button
        web_btn = Gtk.Button(label="Open Web Client")
        web_btn.add_css_class("secondary-button")
        web_btn.set_margin_top(20)
        web_btn.set_halign(Gtk.Align.CENTER)
        web_btn.connect("clicked", lambda _: self._on_open_web_client())
        box.append(web_btn)

        # Web note
        web_note = Gtk.Label(label="Opens browser based on your client settings")
        web_note.add_css_class("dim-label")
        web_note.add_css_class("caption")
        box.append(web_note)

        scrolled.set_child(box)
        return scrolled

    def _create_server_view(self) -> Any:
        """Create the server management view."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(40)
        box.set_margin_end(40)

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
        self._start_local_btn.connect(
            "clicked", lambda _: self._on_start_server_local()
        )
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

        # Settings button
        settings_btn = Gtk.Button(label="Settings")
        settings_btn.add_css_class("secondary-button")
        settings_btn.set_halign(Gtk.Align.CENTER)
        settings_btn.set_margin_top(16)
        settings_btn.connect("clicked", lambda _: self._on_open_server_settings())
        box.append(settings_btn)

        # Show logs button
        logs_btn = Gtk.Button(label="Show Logs")
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
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(40)
        box.set_margin_end(40)

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

        # Settings button
        settings_btn = Gtk.Button(label="⚙ Settings")
        settings_btn.add_css_class("secondary-button")
        settings_btn.set_halign(Gtk.Align.CENTER)
        settings_btn.set_margin_top(16)
        settings_btn.connect("clicked", lambda _: self._on_show_client_settings())
        box.append(settings_btn)

        # Show logs button
        logs_btn = Gtk.Button(label="Show Logs")
        logs_btn.add_css_class("secondary-button")
        logs_btn.set_halign(Gtk.Align.CENTER)
        logs_btn.set_margin_top(8)
        logs_btn.connect("clicked", lambda _: self._toggle_client_logs())
        box.append(logs_btn)

        scrolled.set_child(box)
        return scrolled

    def _apply_styles(self) -> None:
        """Apply custom CSS styling matching KDE color scheme."""
        css = b"""
        /* Color scheme matching KDE Dashboard:
           - Background: #121212
           - Surface: #1e1e1e, #2d2d2d
           - Primary: #90caf9, #42a5f5
           - Error: #f44336, Success: #4caf50, Warning: #ff9800, Info: #2196f3
           - Server: #6B8DD9, Client: #D070D0
        */

        /* Accent colors */
        .server-accent {
            color: #6B8DD9;
        }
        .client-accent {
            color: #D070D0;
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
                size = self._docker_manager.get_volume_size(
                    "transcription-suite-models"
                )
                if self._models_volume_size and size:
                    self._models_volume_size.set_text(f"  ({size})")
                else:
                    self._models_volume_size.set_text("")
            else:
                self._models_volume_status.set_text("Not found")
                if self._models_volume_size:
                    self._models_volume_size.set_text("")

        # Load auth token
        if self._server_token_entry:
            token = self.config.get("server", "token", default="")
            if token:
                self._server_token_entry.set_text(token)
            else:
                self._server_token_entry.set_text("Not saved yet")

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

    def _on_remove_container(self) -> None:
        """Remove the Docker container."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_container(),
            "Removing container...",
        )

    def _on_remove_image(self) -> None:
        """Remove the Docker image."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_image(),
            "Removing image...",
        )

    def _on_pull_fresh_image(self) -> None:
        """Pull fresh Docker image."""
        self._run_server_operation(
            lambda: self._docker_manager.pull_image(),
            "Pulling fresh image...",
        )

    def _on_remove_data_volume(self) -> None:
        """Remove data volume."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_volume("data"),
            "Removing data volume...",
        )

    def _on_remove_models_volume(self) -> None:
        """Remove models volume."""
        self._run_server_operation(
            lambda: self._docker_manager.remove_volume("models"),
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

    def _on_open_server_settings(self) -> None:
        """Open server settings file."""
        try:
            from client.common.config import get_config_dir

            config_dir = get_config_dir()
            config_file = config_dir / "config.yaml"
            if config_file.exists():
                subprocess.run(["xdg-open", str(config_file)], check=False)
        except Exception as e:
            logger.error(f"Failed to open server settings: {e}")

    def _toggle_server_logs(self) -> None:
        """Toggle server log window."""
        if self._server_log_window is None:
            self._server_log_window = LogWindow("Server Logs")

        logs = self._docker_manager.get_logs(lines=200)
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

        if self._on_start_client:
            self._on_start_client(False)
        self.set_client_running(True)

    def _on_start_client_remote(self) -> None:
        """Start client in remote mode."""
        self.config.set("server", "use_remote", value=True)
        self.config.set("server", "use_https", value=True)
        self.config.set("server", "port", value=8443)
        self.config.save()

        if self._on_start_client:
            self._on_start_client(True)
        self.set_client_running(True)

    def _on_stop_client(self) -> None:
        """Stop the client."""
        if self._on_stop_client:
            self._on_stop_client()
        self.set_client_running(False)

    def _on_show_client_settings(self) -> None:
        """Show client settings dialog."""
        if self._on_show_settings:
            self._on_show_settings()

    def _toggle_client_logs(self) -> None:
        """Toggle client log window."""
        if self._client_log_window is None:
            self._client_log_window = LogWindow("Client Logs")

        # Read client logs from the unified log file
        try:
            from client.common.logging_config import get_log_file

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

    def _show_help_menu(self, button) -> None:
        """Show help menu."""
        menu = Gio.Menu()
        menu.append("User Guide", "win.help-user")
        menu.append("Developer Guide", "win.help-dev")

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(button)

        # Add actions
        action_user = Gio.SimpleAction.new("help-user", None)
        action_user.connect("activate", lambda a, p: self._show_readme(dev=False))
        self.add_action(action_user)

        action_dev = Gio.SimpleAction.new("help-dev", None)
        action_dev.connect("activate", lambda a, p: self._show_readme(dev=True))
        self.add_action(action_dev)

        popover.popup()

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
        """Get the application version."""
        try:
            from importlib.metadata import version

            return version("transcription-suite-client")
        except Exception:
            # When running from source or PyInstaller bundle
            try:
                import sys
                import tomllib

                if getattr(sys, "frozen", False):
                    bundle_dir = Path(sys._MEIPASS)  # type: ignore
                    pyproject_path = bundle_dir / "client" / "pyproject.toml"
                else:
                    current = Path(__file__).resolve()
                    pyproject_path = None
                    for parent in current.parents:
                        potential_path = parent / "pyproject.toml"
                        if potential_path.exists():
                            pyproject_path = potential_path
                            break

                if pyproject_path and pyproject_path.exists():
                    with open(pyproject_path, "rb") as f:
                        data = tomllib.load(f)
                    return data.get("project", {}).get("version", "dev")
            except Exception:
                pass
        return "dev"

    # =========================================================================
    # Notifications
    # =========================================================================

    def _show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification."""
        try:
            subprocess.run(
                ["notify-send", "-a", "TranscriptionSuite", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass


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
    from client.common.config import ClientConfig

    if config_path:
        config = ClientConfig(config_path)
    else:
        config = ClientConfig()

    # Create D-Bus client for communicating with tray process
    from client.gnome.dbus_service import DashboardDBusClient

    dbus_client = DashboardDBusClient()
    tray_connected = dbus_client.is_connected()

    if not tray_connected:
        logger.warning(
            "D-Bus connection to tray not available. "
            "Client control will be disabled. Start the tray first."
        )

    # Create and run the application
    app = Adw.Application(application_id="com.transcriptionsuite.dashboard")

    def on_activate(application: Adw.Application) -> None:
        """Create and present the main window."""

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
            if tray_connected:
                dbus_client.show_settings()
            else:
                logger.warning("Cannot show settings: tray not connected")

        window = DashboardWindow(
            config=config,
            app=application,
            on_start_client=on_start_client if tray_connected else None,
            on_stop_client=on_stop_client if tray_connected else None,
            on_show_settings=on_show_settings if tray_connected else None,
        )

        # If tray not connected, show a warning banner
        if not tray_connected:
            window._show_notification(
                "Limited Mode",
                "Client control unavailable. Start the tray first for full functionality.",
            )

        window.present()

    app.connect("activate", on_activate)
    return app.run(sys.argv)
