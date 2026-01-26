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
    DockerServerWorker,
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

# Import from modular files
from dashboard.gnome.utils import (
    GITHUB_PROFILE_URL,
    GITHUB_REPO_URL,
    get_assets_path as _get_assets_path,
    get_readme_path as _get_readme_path,
)
from dashboard.gnome.log_window import LogWindow


class View(Enum):
    """Dashboard view types."""

    WELCOME = auto()
    SERVER = auto()
    CLIENT = auto()
    NOTEBOOK = auto()


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
        self._dbus_service: Any = None

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

        # Docker server start worker for async server start
        self._server_worker: DockerServerWorker | None = None

        # UI references (typed as Any since GTK types are dynamic)
        self._stack: Any = None
        self._home_server_status: Any = None
        self._home_client_status: Any = None
        self._server_status_label: Any = None
        self._image_status_label: Any = None
        self._image_date_label: Any = None
        self._image_size_label: Any = None
        self._image_selector: Any = None
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
        """Set up the main UI structure with sidebar navigation."""
        self.set_title("TranscriptionSuite")
        self.set_default_size(850, 600)

        # Set window icon from app logo
        self._set_window_icon()

        # Force dark theme
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        # Main horizontal box (sidebar | content)
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Create sidebar
        sidebar = self._create_sidebar()
        main_box.append(sidebar)

        # Content area with header
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_hexpand(True)

        # Minimal header bar for window controls
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        # Menu button in header
        self._menu_btn = Gtk.MenuButton()
        self._menu_btn.set_icon_name("open-menu-symbolic")
        self._menu_btn.set_tooltip_text("Menu")
        self._setup_menu_button()
        header.pack_end(self._menu_btn)

        content_box.append(header)

        # Stack for views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(200)
        self._stack.set_vexpand(True)

        # Create views
        welcome_view = self._create_welcome_view()
        server_view = self._create_server_view()
        client_view = self._create_client_view()
        notebook_view = self._create_notebook_view()

        self._stack.add_named(welcome_view, "welcome")
        self._stack.add_named(server_view, "server")
        self._stack.add_named(client_view, "client")
        self._stack.add_named(notebook_view, "notebook")

        content_box.append(self._stack)
        main_box.append(content_box)

        self.set_content(main_box)

        # Start on home view by default
        self._navigate_to(View.WELCOME, add_to_history=False)

        # Connect close request
        self.connect("close-request", self._on_close_request)

    def _create_sidebar(self) -> Any:
        """Create the vertical sidebar navigation with status lights."""
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.set_size_request(200, -1)
        sidebar.add_css_class("sidebar")

        # Header with title
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.set_margin_top(20)
        header.set_margin_bottom(16)
        header.set_margin_start(16)
        header.set_margin_end(16)
        header.add_css_class("sidebar-header")

        title = Gtk.Label(label="Transcription")
        title.add_css_class("sidebar-title")
        title.set_halign(Gtk.Align.START)
        header.append(title)

        subtitle = Gtk.Label(label="Suite")
        subtitle.add_css_class("sidebar-subtitle")
        subtitle.set_halign(Gtk.Align.START)
        header.append(subtitle)

        sidebar.append(header)

        # Navigation buttons container
        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        nav_box.set_margin_start(8)
        nav_box.set_margin_end(8)
        nav_box.set_vexpand(True)

        # Home button
        home_btn = Gtk.Button(label="  Home")
        home_btn.set_icon_name("go-home-symbolic")
        home_btn.add_css_class("sidebar-button")
        home_btn.connect("clicked", lambda _: self._go_home())
        nav_box.append(home_btn)

        # Server button with status light
        server_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        server_btn = Gtk.Button(label="  Docker Server")
        server_btn.set_icon_name("network-server-symbolic")
        server_btn.add_css_class("sidebar-button")
        server_btn.set_hexpand(True)
        server_btn.connect("clicked", lambda _: self._navigate_to(View.SERVER))
        server_box.append(server_btn)

        self._server_status_light = Gtk.Label(label="⬤")
        self._server_status_light.add_css_class("status-light-gray")
        self._server_status_light.set_margin_end(8)
        server_box.append(self._server_status_light)
        nav_box.append(server_box)

        # Client button with status light
        client_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        client_btn = Gtk.Button(label="  Client")
        client_btn.set_icon_name("audio-input-microphone-symbolic")
        client_btn.add_css_class("sidebar-button")
        client_btn.set_hexpand(True)
        client_btn.connect("clicked", lambda _: self._navigate_to(View.CLIENT))
        client_box.append(client_btn)

        self._client_status_light = Gtk.Label(label="⬤")
        self._client_status_light.add_css_class("status-light-orange")
        self._client_status_light.set_margin_end(8)
        client_box.append(self._client_status_light)
        nav_box.append(client_box)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        nav_box.append(sep)

        # Notebook button
        notebook_btn = Gtk.Button(label="  Notebook")
        notebook_btn.set_icon_name("accessories-text-editor-symbolic")
        notebook_btn.add_css_class("sidebar-button")
        notebook_btn.connect("clicked", lambda _: self._navigate_to(View.NOTEBOOK))
        nav_box.append(notebook_btn)

        sidebar.append(nav_box)

        return sidebar

    def _setup_menu_button(self) -> None:
        """Set up the hamburger menu button."""
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

    def _update_sidebar_status_lights(self) -> None:
        """Update the status light indicators in the sidebar."""
        # Server status light
        if hasattr(self, "_server_status_light") and self._server_status_light:
            status = self._docker_manager.get_server_status()
            # Remove old classes
            for cls in [
                "status-light-green",
                "status-light-red",
                "status-light-blue",
                "status-light-orange",
                "status-light-gray",
            ]:
                self._server_status_light.remove_css_class(cls)

            if status == ServerStatus.RUNNING:
                health = self._docker_manager.get_container_health()
                if health == "unhealthy":
                    self._server_status_light.add_css_class("status-light-red")
                elif health and health != "healthy":
                    self._server_status_light.add_css_class("status-light-blue")
                else:
                    self._server_status_light.add_css_class("status-light-green")
            elif status == ServerStatus.STOPPED:
                self._server_status_light.add_css_class("status-light-gray")
            else:
                self._server_status_light.add_css_class("status-light-red")

        # Client status light
        if hasattr(self, "_client_status_light") and self._client_status_light:
            # Remove old classes
            for cls in ["status-light-green", "status-light-orange"]:
                self._client_status_light.remove_css_class(cls)

            if self._client_running:
                self._client_status_light.add_css_class("status-light-green")
            else:
                self._client_status_light.add_css_class("status-light-gray")

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

        # Add logo
        logo_path = _get_assets_path() / "logo_wide.png"
        if logo_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(logo_path))
                # Scale to specified dimensions (350 x 193)
                orig_width = pixbuf.get_width()
                orig_height = pixbuf.get_height()
                # Calculate aspect ratio
                aspect = orig_width / orig_height if orig_height > 0 else 1
                # Scale to fit within 350 x 193 while maintaining aspect ratio
                target_width = 350
                target_height = int(target_width / aspect)
                if target_height > 193:
                    target_height = 193
                    target_width = int(target_height * aspect)
                scaled_pixbuf = pixbuf.scale_simple(
                    target_width, target_height, GdkPixbuf.InterpType.BILINEAR
                )
                logo_image = Gtk.Image.new_from_pixbuf(scaled_pixbuf)
                logo_image.set_halign(Gtk.Align.CENTER)
                box.append(logo_image)
            except Exception as e:
                logger.debug(f"Failed to load logo: {e}")

        # Status indicators
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=40)
        status_box.set_halign(Gtk.Align.CENTER)
        status_box.set_margin_top(30)

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

        # Image selector row
        image_selector_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        selector_label = Gtk.Label(label="Select Image:")
        selector_label.add_css_class("dim-label")
        image_selector_row.append(selector_label)
        self._image_selector = Gtk.ComboBoxText()
        self._image_selector.set_tooltip_text(
            "Select which Docker image to use when starting the server.\n"
            "'Most Recent (auto)' automatically selects the newest image by build date."
        )
        self._image_selector.connect("changed", self._on_image_selection_changed)
        image_selector_row.append(self._image_selector)
        status_box.append(image_selector_row)

        # Populate image selector
        self._populate_image_selector()

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

        # Live Mode Language selector
        language_frame = Gtk.Frame()
        language_frame.add_css_class("card")
        language_frame.set_margin_top(16)
        language_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        language_box.set_margin_top(12)
        language_box.set_margin_bottom(12)
        language_box.set_margin_start(16)
        language_box.set_margin_end(16)

        language_label = Gtk.Label(label="Live Mode Language:")
        language_label.add_css_class("dim-label")
        language_box.append(language_label)

        # Spacer
        language_spacer = Gtk.Box()
        language_spacer.set_hexpand(True)
        language_box.append(language_spacer)

        # Language dropdown
        self._live_language_combo = Gtk.ComboBoxText()
        # Full Whisper language list (99 languages)
        languages = [
            ("Auto-detect", ""),
            ("Afrikaans", "af"),
            ("Amharic", "am"),
            ("Arabic", "ar"),
            ("Assamese", "as"),
            ("Azerbaijani", "az"),
            ("Bashkir", "ba"),
            ("Belarusian", "be"),
            ("Bulgarian", "bg"),
            ("Bengali", "bn"),
            ("Tibetan", "bo"),
            ("Breton", "br"),
            ("Bosnian", "bs"),
            ("Catalan", "ca"),
            ("Czech", "cs"),
            ("Welsh", "cy"),
            ("Danish", "da"),
            ("German", "de"),
            ("Greek", "el"),
            ("English", "en"),
            ("Spanish", "es"),
            ("Estonian", "et"),
            ("Basque", "eu"),
            ("Persian", "fa"),
            ("Finnish", "fi"),
            ("Faroese", "fo"),
            ("French", "fr"),
            ("Galician", "gl"),
            ("Gujarati", "gu"),
            ("Hausa", "ha"),
            ("Hawaiian", "haw"),
            ("Hebrew", "he"),
            ("Hindi", "hi"),
            ("Croatian", "hr"),
            ("Haitian Creole", "ht"),
            ("Hungarian", "hu"),
            ("Armenian", "hy"),
            ("Indonesian", "id"),
            ("Icelandic", "is"),
            ("Italian", "it"),
            ("Japanese", "ja"),
            ("Javanese", "jw"),
            ("Georgian", "ka"),
            ("Kazakh", "kk"),
            ("Khmer", "km"),
            ("Kannada", "kn"),
            ("Korean", "ko"),
            ("Latin", "la"),
            ("Luxembourgish", "lb"),
            ("Lingala", "ln"),
            ("Lao", "lo"),
            ("Lithuanian", "lt"),
            ("Latvian", "lv"),
            ("Malagasy", "mg"),
            ("Maori", "mi"),
            ("Macedonian", "mk"),
            ("Malayalam", "ml"),
            ("Mongolian", "mn"),
            ("Marathi", "mr"),
            ("Malay", "ms"),
            ("Maltese", "mt"),
            ("Burmese", "my"),
            ("Nepali", "ne"),
            ("Dutch", "nl"),
            ("Norwegian Nynorsk", "nn"),
            ("Norwegian", "no"),
            ("Occitan", "oc"),
            ("Punjabi", "pa"),
            ("Polish", "pl"),
            ("Pashto", "ps"),
            ("Portuguese", "pt"),
            ("Romanian", "ro"),
            ("Russian", "ru"),
            ("Sanskrit", "sa"),
            ("Sindhi", "sd"),
            ("Sinhala", "si"),
            ("Slovak", "sk"),
            ("Slovenian", "sl"),
            ("Shona", "sn"),
            ("Somali", "so"),
            ("Albanian", "sq"),
            ("Serbian", "sr"),
            ("Sundanese", "su"),
            ("Swedish", "sv"),
            ("Swahili", "sw"),
            ("Tamil", "ta"),
            ("Telugu", "te"),
            ("Tajik", "tg"),
            ("Thai", "th"),
            ("Turkmen", "tk"),
            ("Tagalog", "tl"),
            ("Turkish", "tr"),
            ("Tatar", "tt"),
            ("Ukrainian", "uk"),
            ("Urdu", "ur"),
            ("Uzbek", "uz"),
            ("Vietnamese", "vi"),
            ("Yiddish", "yi"),
            ("Yoruba", "yo"),
            ("Chinese", "zh"),
            ("Cantonese", "yue"),
        ]
        for name, code in languages:
            self._live_language_combo.append(code, name)

        # Load saved value
        saved_language = self.config.get_server_config(
            "live_transcriber", "live_language", default="en"
        )
        self._live_language_combo.set_active_id(saved_language)

        self._live_language_combo.set_tooltip_text(
            "Force a specific language for Live Mode.\n"
            "Recommended: Select your language for better accuracy.\n"
            "Auto-detect works poorly with short utterances.\n"
            "Only editable when server is stopped."
        )
        self._live_language_combo.connect("changed", self._on_live_language_changed)
        language_box.append(self._live_language_combo)

        language_frame.set_child(language_box)
        box.append(language_frame)

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

        # Spacer to push button to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        preview_header.append(spacer)

        # Copy and Clear button (upper right)
        self._copy_clear_btn = Gtk.Button(label="Copy and Clear")
        self._copy_clear_btn.add_css_class("copy-clear-btn")
        self._copy_clear_btn.set_size_request(120, 24)
        self._copy_clear_btn.connect("clicked", self._on_copy_and_clear_live_preview)
        preview_header.append(self._copy_clear_btn)

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

        preview_frame.set_child(preview_box)
        box.append(preview_frame)

        scrolled.set_child(box)
        return scrolled

    def _get_api_client(self) -> "APIClient | None":
        """Create an API client from current config settings for notebook operations.

        GNOME Dashboard runs in a separate process from the tray, so it cannot
        access the tray's orchestrator directly. This method creates an API client
        from the current config settings when the server is running.
        """
        from dashboard.common.api_client import APIClient

        server_status = self._docker_manager.get_server_status()
        if server_status != ServerStatus.RUNNING:
            logger.debug("Server not running, cannot create API client")
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
        tls_verify = self.config.get("server", "tls_verify", default=True)

        if not host:
            logger.debug("No host configured, cannot create API client")
            return None

        return APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token if token else None,
            tls_verify=tls_verify,
        )

    def _create_notebook_view(self) -> Any:
        """Create the Audio Notebook view."""
        from dashboard.gnome.notebook_view import NotebookView

        # Create API client from config settings (GNOME runs in separate process, no tray access)
        api_client = self._get_api_client()

        self._notebook_widget = NotebookView(api_client)
        self._notebook_widget.recording_requested.connect(self._open_recording_dialog)
        return self._notebook_widget

    def _refresh_notebook_view(self) -> None:
        """Refresh the notebook view data."""
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            # Update API client reference in case connection changed
            api_client = self._get_api_client()
            if api_client:
                self._notebook_widget.set_api_client(api_client)
            self._notebook_widget.refresh()

    def _update_notebook_api_client(self) -> bool:
        """Update notebook widgets with current API client (called after connection)."""
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            api_client = self._get_api_client()
            if api_client:
                self._notebook_widget.set_api_client(api_client)
                logger.debug("Notebook API client updated after connection")
        return False  # Don't repeat

    def _open_recording_dialog(self, recording_id: int) -> None:
        """Open a recording dialog for the given recording ID."""
        from dashboard.gnome.recording_dialog import RecordingDialog

        # Create API client from config settings
        api_client = self._get_api_client()

        if not api_client:
            logger.error(
                "Cannot open recording: API client not available (server not running?)"
            )
            self._show_notification(
                "Error", "Cannot open recording: Server not running"
            )
            return

        dialog = RecordingDialog(
            api_client=api_client,
            recording_id=recording_id,
            parent=self,
        )
        dialog.connect_recording_deleted(self._on_recording_deleted)
        dialog.connect_recording_updated(self._on_recording_updated)
        dialog.present()

    def _on_recording_deleted(self, recording_id: int) -> None:
        """Handle recording deletion - refresh notebook view."""
        logger.info(f"Recording {recording_id} deleted, refreshing notebook")
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            self._notebook_widget.remove_recording_from_cache(recording_id)
        self._refresh_notebook_view()

    def _on_recording_updated(self, recording_id: int, title: str) -> None:
        """Handle recording update - update cache and refresh notebook view."""
        logger.info(f"Recording {recording_id} updated with title: {title}")
        if hasattr(self, "_notebook_widget") and self._notebook_widget:
            self._notebook_widget.update_recording_in_cache(recording_id, title)
        self._refresh_notebook_view()

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
            color: #ff007a;
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
        .welcome-button.client-accent {
            border-color: #ff007a;
        }
        .welcome-button.client-accent:hover {
            border-color: #ff007a;
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
        .status-not-setup {
            color: #5d0000;
        }
        .status-error {
            color: #f44336;
        }
        .status-starting {
            color: #2196f3;
        }
        .status-warning {
            color: #f44336;
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

        /* Sidebar styles */
        .sidebar {
            background-color: #1a1a2e;
            border-right: 1px solid #2d2d2d;
        }
        .sidebar-header {
            border-bottom: 1px solid #2d2d2d;
        }
        .sidebar-title {
            color: #90caf9;
            font-size: 20px;
            font-weight: bold;
        }
        .sidebar-subtitle {
            color: #606080;
            font-size: 16px;
        }
        .sidebar-button {
            background: transparent;
            border: none;
            border-radius: 6px;
            padding: 10px 12px;
            color: #a0a0a0;
        }
        .sidebar-button:hover {
            background: #2d2d3d;
            color: #ffffff;
        }
        .sidebar-button:checked {
            background: #2d4a6d;
            color: #90caf9;
        }

        /* Status light colors */
        .status-light-green {
            color: #4caf50;
            font-size: 8px;
        }
        .status-light-red {
            color: #f44336;
            font-size: 8px;
        }
        .status-light-blue {
            color: #2196f3;
            font-size: 8px;
        }
        .status-light-orange {
            color: #f44336;
            font-size: 8px;
        }
        .status-light-gray {
            color: #6c757d;
            font-size: 8px;
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

        /* Copy and Clear button */
        .copy-clear-btn {
            background: #2d2d2d;
            color: #e0e0e0;
            border: 1px solid #404040;
            border-radius: 4px;
            font-size: 11px;
            padding: 0 8px;
            min-height: 24px;
        }
        .copy-clear-btn:hover {
            background: #3d3d3d;
            border-color: #505050;
        }
        .copy-clear-btn:active {
            background: #1e1e1e;
        }

        /* Combobox styling to match Client view dropdown */
        combobox button {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            color: #e0e0e0;
            padding: 6px 10px;
            font-size: 12px;
        }
        combobox button:hover {
            border-color: #505050;
        }
        combobox button:focus {
            border-color: #0AFCCF;
        }
        combobox popover {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            color: #e0e0e0;
        }
        combobox list {
            background-color: #2d2d2d;
            color: #e0e0e0;
        }
        combobox row {
            padding: 4px;
        }
        combobox row:selected {
            background-color: #404040;
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
            View.NOTEBOOK: "notebook",
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
        elif view == View.NOTEBOOK:
            self._refresh_notebook_view()

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
        self._status_timer_id = GLib.timeout_add_seconds(1, self._on_status_tick)
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
            self._home_server_status.add_css_class("status-not-setup")

        # Client status
        if self._home_client_status:
            if self._client_running:
                self._home_client_status.set_text("⬤ Running")
                self._home_client_status.add_css_class("status-running")
            else:
                self._home_client_status.set_text("⬤ Stopped")
                self._home_client_status.remove_css_class("status-running")
                self._home_client_status.add_css_class("status-stopped")

        # Update sidebar status lights
        self._update_sidebar_status_lights()

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
            "transcriptionsuite-data"
        )
        models_volume_exists = self._docker_manager.volume_exists(
            "transcriptionsuite-models"
        )

        if self._data_volume_status:
            if data_volume_exists:
                self._data_volume_status.set_text("Available")
                size = self._docker_manager.get_volume_size("transcriptionsuite-data")
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
                size = self._docker_manager.get_volume_size("transcriptionsuite-models")
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

        # Update live mode language dropdown state when server status changes
        if hasattr(self, "_live_language_combo"):
            self._live_language_combo.set_sensitive(server_stopped)

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

        # Update notebook API client when client starts
        if running:
            GLib.timeout_add(2000, self._update_notebook_api_client)

    # =========================================================================
    # Server Operations
    # =========================================================================

    def _populate_image_selector(self) -> None:
        """Populate the image selector dropdown with available local images."""
        if not self._image_selector:
            return

        self._image_selector.remove_all()

        # Add "Most Recent (auto)" as first option
        self._image_selector.append("auto", "Most Recent (auto)")

        # Get list of local images
        images = self._docker_manager.list_local_images()

        for img in images:
            display_text = img.display_name()
            self._image_selector.append(img.tag, display_text)

        # Set default selection to "auto"
        self._image_selector.set_active_id("auto")

        # If no images found, show a placeholder tooltip
        if not images:
            self._image_selector.set_tooltip_text(
                "No local images found.\n"
                "Use 'Fetch Fresh' to pull the latest image from the registry."
            )

    def _on_image_selection_changed(self, combo: Any) -> None:
        """Handle image selection change."""
        tag = combo.get_active_id()
        if tag == "auto":
            logger.debug("Image selection: auto (most recent)")
        else:
            logger.debug(f"Image selection: {tag}")

    def _get_selected_image_tag(self) -> str:
        """Get the currently selected image tag."""
        if not self._image_selector:
            return "auto"
        tag = self._image_selector.get_active_id()
        return tag if tag else "auto"

    def _on_start_server_local(self) -> None:
        """Start server in local mode (async, non-blocking)."""
        self._start_server_async(ServerMode.LOCAL)

    def _on_start_server_remote(self) -> None:
        """Start server in remote mode (async, non-blocking)."""
        self._start_server_async(ServerMode.REMOTE)

    def _start_server_async(self, mode: ServerMode) -> None:
        """Start the Docker server asynchronously."""
        # Prevent starting another server start if one is already in progress
        if self._server_worker is not None and self._server_worker.is_alive():
            logger.warning("Server start already in progress")
            self._show_notification("Docker Server", "Server start already in progress")
            return

        image_selection = self._get_selected_image_tag()
        self._show_notification(
            "Docker Server", f"Starting server ({mode.value} mode)..."
        )

        def on_progress(msg: str) -> None:
            """Called from worker thread - schedule UI update on main thread."""
            GLib.idle_add(self._update_server_start_progress, msg)

        def on_complete(result: DockerResult) -> None:
            """Called from worker thread - schedule UI update on main thread."""
            GLib.idle_add(self._on_server_start_complete, result)

        # Start the server asynchronously
        result = self._docker_manager.start_server_async(
            mode=mode,
            progress_callback=on_progress,
            complete_callback=on_complete,
            image_selection=image_selection,
        )

        # Check if pre-flight validation failed (returns DockerResult instead of worker)
        if isinstance(result, DockerResult):
            # Validation failed - handle synchronously
            self._show_notification("Docker Server", f"Error: {result.message}")
            self._refresh_server_status()
            self._refresh_home_status()
        else:
            # Got a worker - store reference
            self._server_worker = result
            logger.info(f"Started async server start ({mode.value} mode)")

    def _update_server_start_progress(self, msg: str) -> bool:
        """Update with server start progress (main thread via GLib.idle_add)."""
        logger.info(msg)
        return False  # Remove from idle queue

    def _on_server_start_complete(self, result: DockerResult) -> bool:
        """Handle server start completion (main thread via GLib.idle_add)."""
        self._server_worker = None
        self._show_notification("Docker Server", result.message)
        self._refresh_server_status()
        self._refresh_home_status()

        # Update notebook API client when server starts successfully
        # (user may use notebook without explicitly starting client)
        if result.success:
            GLib.timeout_add(2000, self._update_notebook_api_client)

        return False  # Remove from idle queue

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
            self._show_notification(
                "Docker Server", "Image download already in progress"
            )
            return

        self._show_notification(
            "Docker Server",
            "Starting image download (~17GB). This may take a while...",
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

        # Schedule notebook API client update after connection establishes
        GLib.timeout_add(2000, self._update_notebook_api_client)

    def _on_start_client_remote(self) -> None:
        """Start client in remote mode."""
        self.config.set("server", "use_remote", value=True)
        self.config.set("server", "use_https", value=True)
        self.config.set("server", "port", value=8443)
        self.config.save()

        if self._start_client_callback:
            self._start_client_callback(True)
        self.set_client_running(True)

        # Schedule notebook API client update after connection establishes
        GLib.timeout_add(2000, self._update_notebook_api_client)

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

    def _on_live_language_changed(self, combo: Any) -> None:
        """Handle Live Mode language dropdown change."""
        language_code = combo.get_active_id()
        language_name = combo.get_active_text()

        # Save to server config - takes effect on next Live Mode start
        self.config.set_server_config(
            "live_transcriber", "live_language", value=language_code
        )

        logger.info(
            f"Live Mode language set to: {language_name} ({language_code or 'auto'})"
        )

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

    def _on_copy_and_clear_live_preview(self, _button: Gtk.Button) -> None:
        """Copy all text from live preview to clipboard and clear the field."""
        if (
            not hasattr(self, "_live_transcription_text_buffer")
            or not self._live_transcription_text_buffer
        ):
            return

        # Get all text from the buffer
        start = self._live_transcription_text_buffer.get_start_iter()
        end = self._live_transcription_text_buffer.get_end_iter()
        text = self._live_transcription_text_buffer.get_text(start, end, False)

        if text:
            # Copy to clipboard
            clipboard = Gdk.Display.get_default().get_clipboard()
            if clipboard:
                clipboard.set(text)
                logger.debug("Copied live preview text to clipboard")

        # Clear the buffer and history
        self._live_transcription_text_buffer.set_text("")
        self._live_transcription_history.clear()
        logger.debug("Cleared live preview text and history")

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
            # Keep only last 1000 lines to prevent memory bloat
            if len(self._live_transcription_history) > 1000:
                self._live_transcription_history = self._live_transcription_history[
                    -1000:
                ]
            # Update display - join with spaces for continuous text wrapping
            self._live_transcription_text_buffer.set_text(
                " ".join(self._live_transcription_history)
            )
        else:
            # Real-time update: show history + current partial text
            if self._live_transcription_history:
                display_text = " ".join(self._live_transcription_history) + " " + text
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
