"""
Search widget for Audio Notebook (GNOME/GTK4).

Provides full-text search across transcriptions with filtering options.
"""

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Callable

try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    HAS_GTK4 = True
except (ImportError, ValueError):
    HAS_GTK4 = False
    Gtk = None
    GLib = None

from dashboard.common.models import Recording, SearchResult

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class SearchWidget:
    """
    Search interface for Audio Notebook (GNOME).

    Provides full-text search with options for fuzzy matching
    and date range filtering.
    """

    def __init__(self, api_client: "APIClient | None"):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for SearchWidget")

        self._api_client = api_client
        self._recording_callback: Callable[[int], None] | None = None
        self._search_timeout_id: int | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the search widget UI."""
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.widget.set_margin_start(20)
        self.widget.set_margin_end(20)
        self.widget.set_margin_top(20)
        self.widget.set_margin_bottom(20)

        # Search input row
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search transcriptions...")
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", lambda _: self._perform_search())
        search_box.append(self._search_entry)

        search_btn = Gtk.Button(label="Search")
        search_btn.add_css_class("primary-button")
        search_btn.connect("clicked", lambda _: self._perform_search())
        search_box.append(search_btn)

        self.widget.append(search_box)

        # Filters section
        filters_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        filters_box.add_css_class("filters-box")
        filters_box.set_margin_start(16)
        filters_box.set_margin_end(16)
        filters_box.set_margin_top(12)
        filters_box.set_margin_bottom(12)

        self._fuzzy_switch = Gtk.CheckButton(label="Fuzzy matching")
        filters_box.append(self._fuzzy_switch)

        date_label = Gtk.Label(label="Date range:")
        date_label.add_css_class("filter-label")
        filters_box.append(date_label)

        # Note: GTK4 doesn't have a simple date picker like Qt's QDateEdit
        # We'll use entry fields with placeholder text
        self._from_date_entry = Gtk.Entry()
        self._from_date_entry.set_placeholder_text("YYYY-MM-DD")
        self._from_date_entry.set_max_width_chars(12)
        filters_box.append(self._from_date_entry)

        to_label = Gtk.Label(label="to")
        filters_box.append(to_label)

        self._to_date_entry = Gtk.Entry()
        self._to_date_entry.set_placeholder_text("YYYY-MM-DD")
        self._to_date_entry.set_max_width_chars(12)
        self._to_date_entry.set_text(date.today().isoformat())
        filters_box.append(self._to_date_entry)

        clear_btn = Gtk.Button(label="Clear dates")
        clear_btn.add_css_class("secondary-button")
        clear_btn.connect("clicked", lambda _: self._clear_date_filters())
        filters_box.append(clear_btn)

        self.widget.append(filters_box)

        # Results header
        self._results_label = Gtk.Label(label="Enter a search term to begin")
        self._results_label.add_css_class("results-label")
        self._results_label.set_xalign(0)
        self.widget.append(self._results_label)

        # Results list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._results_list = Gtk.ListBox()
        self._results_list.add_css_class("results-list")
        self._results_list.connect("row-activated", self._on_result_activated)
        scrolled.set_child(self._results_list)

        self.widget.append(scrolled)
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .filters-box {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }

            .filter-label {
                color: #a0a0a0;
            }

            .results-label {
                color: #a0a0a0;
                font-size: 13px;
            }

            .results-list {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }

            .results-list row {
                padding: 12px;
                border-bottom: 1px solid #2d2d2d;
            }

            .results-list row:selected {
                background-color: #2d4a6d;
            }

            .primary-button {
                background-color: #90caf9;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 10px 20px;
                font-weight: 500;
            }

            .primary-button:hover {
                background-color: #42a5f5;
            }

            .secondary-button {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
            }

            .match-type-badge {
                background-color: #2d4a6d;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.widget.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_search_changed(self, entry) -> None:
        """Handle search text changes with debouncing."""
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

        text = entry.get_text()
        if len(text) >= 2:
            self._search_timeout_id = GLib.timeout_add(300, self._perform_search)
        elif len(text) == 0:
            self._clear_results()
            self._results_label.set_label("Enter a search term to begin")

    def _perform_search(self) -> bool:
        """Execute the search."""
        self._search_timeout_id = None

        query = self._search_entry.get_text().strip()
        if len(query) < 2:
            return False

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._do_search(query))
            else:
                asyncio.run(self._do_search(query))
        except RuntimeError:
            pass

        return False

    async def _do_search(self, query: str) -> None:
        """Perform the actual search request."""
        if not self._api_client:
            return

        try:
            GLib.idle_add(lambda: self._results_label.set_label("Searching..."))
            GLib.idle_add(self._clear_results)

            fuzzy = self._fuzzy_switch.get_active()

            from_text = self._from_date_entry.get_text().strip()
            to_text = self._to_date_entry.get_text().strip()

            start_date = from_text if from_text else None
            end_date = to_text if to_text else None

            results_data = await self._api_client.search(
                query=query,
                fuzzy=fuzzy,
                start_date=start_date,
                end_date=end_date,
                limit=100,
            )

            results = results_data.get("results", [])

            def update_ui():
                if not results:
                    self._results_label.set_label(f"No results found for '{query}'")
                    return False

                self._results_label.set_label(f"Found {len(results)} result(s)")

                for result_data in results:
                    result = SearchResult.from_dict(result_data)
                    row = self._create_result_row(result)
                    self._results_list.append(row)

                return False

            GLib.idle_add(update_ui)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            GLib.idle_add(lambda: self._results_label.set_label(f"Search failed: {e}"))

    def _create_result_row(self, result: SearchResult) -> Gtk.ListBoxRow:
        """Create a list row for a search result."""
        row = Gtk.ListBoxRow()
        row.recording_id = result.recording_id
        row.start_time = result.start_time

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        recording = result.recording
        if recording:
            title = recording.title or recording.filename
            try:
                rec_datetime = datetime.fromisoformat(
                    recording.recorded_at.replace("Z", "+00:00")
                )
                date_str = rec_datetime.strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                date_str = "Unknown date"
        else:
            title = f"Recording #{result.recording_id}"
            date_str = "Unknown date"

        minutes = int(result.start_time // 60)
        seconds = int(result.start_time % 60)
        timestamp = f"{minutes}:{seconds:02d}"

        match_type_display = {
            "word": "[Word]",
            "filename": "[Filename]",
            "summary": "[Summary]",
        }.get(result.match_type, "[Match]")

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        badge = Gtk.Label(label=match_type_display)
        badge.add_css_class("match-type-badge")
        header_box.append(badge)

        title_label = Gtk.Label(label=title)
        title_label.set_xalign(0)
        header_box.append(title_label)

        box.append(header_box)

        details_label = Gtk.Label(label=f"{date_str}  •  at {timestamp}")
        details_label.set_xalign(0)
        details_label.add_css_class("result-details")
        box.append(details_label)

        if result.context:
            context = result.context
            if len(context) > 100:
                context = context[:97] + "..."

            context_label = Gtk.Label(label=f'"{context}"')
            context_label.set_xalign(0)
            context_label.add_css_class("result-context")
            context_label.set_wrap(True)
            box.append(context_label)

        row.set_child(box)
        return row

    def _clear_results(self) -> bool:
        """Clear all results from the list."""
        while True:
            row = self._results_list.get_first_child()
            if row is None:
                break
            self._results_list.remove(row)
        return False

    def _clear_date_filters(self) -> None:
        """Clear date filter inputs."""
        self._from_date_entry.set_text("")
        self._to_date_entry.set_text(date.today().isoformat())

    def _on_result_activated(self, listbox, row) -> None:
        """Handle activation of a search result."""
        if hasattr(row, "recording_id") and self._recording_callback:
            self._recording_callback(row.recording_id)

    def set_recording_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for recording requests."""
        self._recording_callback = callback

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
