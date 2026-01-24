"""
Audio Notebook view for GNOME Dashboard.

Provides a tabbed interface with Calendar, Search, and Import sub-tabs
for managing audio recordings and transcriptions.
"""

import logging
from typing import TYPE_CHECKING, Any

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    HAS_GTK4 = True
except (ImportError, ValueError):
    HAS_GTK4 = False
    Gtk = None
    Adw = None
    GLib = None

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class NotebookView:
    """
    Main Audio Notebook view with tabbed interface for GNOME.

    Contains three sub-tabs:
    - Calendar: Browse recordings by date
    - Search: Full-text search across transcriptions
    - Import: Upload and transcribe audio files
    """

    def __init__(self, api_client: "APIClient | None"):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for NotebookView")

        self._api_client = api_client

        # Callbacks for recording requests
        self._recording_requested_callback: Any = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the notebook view UI."""
        # Main container
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header section
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.add_css_class("notebook-header")
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(15)
        header.set_margin_bottom(15)

        title = Gtk.Label(label="Audio Notebook")
        title.add_css_class("view-title")
        header.append(title)

        self.widget.append(header)

        # Tab widget (Gtk.Notebook)
        self._notebook = Gtk.Notebook()
        self._notebook.set_vexpand(True)
        self._notebook.add_css_class("notebook-tabs")

        # Create sub-tab widgets
        from dashboard.gnome.calendar_widget import CalendarWidget
        from dashboard.gnome.import_widget import ImportWidget
        from dashboard.gnome.search_widget import SearchWidget

        self._calendar_widget = CalendarWidget(self._api_client)
        self._search_widget = SearchWidget(self._api_client)
        self._import_widget = ImportWidget(self._api_client)

        # Add tabs
        calendar_label = Gtk.Label(label="Calendar")
        self._notebook.append_page(self._calendar_widget.widget, calendar_label)

        search_label = Gtk.Label(label="Search")
        self._notebook.append_page(self._search_widget.widget, search_label)

        import_label = Gtk.Label(label="Import")
        self._notebook.append_page(self._import_widget.widget, import_label)

        # Connect signals
        self._calendar_widget.set_recording_callback(self._on_recording_requested)
        self._search_widget.set_recording_callback(self._on_recording_requested)
        self._import_widget.set_recording_created_callback(self._on_import_complete)

        self.widget.append(self._notebook)

        # Apply styling
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .notebook-header {
                background-color: #1e1e1e;
                border-bottom: 1px solid #2d2d2d;
            }

            .view-title {
                color: #ffffff;
                font-size: 22px;
                font-weight: bold;
            }

            .notebook-tabs tab {
                background-color: #1e1e1e;
                color: #a0a0a0;
                padding: 10px 20px;
                border: none;
                border-bottom: 2px solid transparent;
            }

            .notebook-tabs tab:checked {
                color: #90caf9;
                border-bottom: 2px solid #90caf9;
            }

            .notebook-tabs tab:hover:not(:checked) {
                color: #ffffff;
                background-color: #2d2d2d;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.widget.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_recording_requested(self, recording_id: int) -> None:
        """Handle request to open a recording."""
        logger.debug(f"Recording requested: {recording_id}")
        if self._recording_requested_callback:
            self._recording_requested_callback(recording_id)

    def _on_import_complete(self, recording_id: int) -> None:
        """Handle import completion."""
        logger.info(f"Import complete, recording ID: {recording_id}")
        # Refresh calendar
        self._calendar_widget.refresh()
        # Open the recording
        if self._recording_requested_callback:
            self._recording_requested_callback(recording_id)

    def set_recording_callback(self, callback) -> None:
        """Set callback for recording requests."""
        self._recording_requested_callback = callback

    def refresh(self) -> None:
        """Refresh all notebook data."""
        current_page = self._notebook.get_current_page()
        if current_page == 0:
            self._calendar_widget.refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._calendar_widget.set_api_client(api_client)
        self._search_widget.set_api_client(api_client)
        self._import_widget.set_api_client(api_client)
