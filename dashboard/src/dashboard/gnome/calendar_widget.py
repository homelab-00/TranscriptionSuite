"""
Calendar widget for Audio Notebook (GNOME/GTK4).

Displays a monthly calendar view with recording counts per day.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    HAS_GTK4 = True
except (ImportError, ValueError):
    HAS_GTK4 = False
    Gtk = None
    GLib = None

from dashboard.common.models import Recording

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class CalendarWidget:
    """
    Calendar-based recording browser for GNOME.

    Shows a monthly calendar and a list of recordings for the selected day.
    """

    def __init__(self, api_client: "APIClient | None"):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for CalendarWidget")

        self._api_client = api_client
        self._recordings_cache: dict[str, list[Recording]] = {}
        self._recording_callback: Callable[[int], None] | None = None

        self._setup_ui()
        self._schedule_refresh()

    def _setup_ui(self) -> None:
        """Set up the calendar widget UI."""
        # Main container
        self.widget = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.widget.set_margin_start(20)
        self.widget.set_margin_end(20)
        self.widget.set_margin_top(20)
        self.widget.set_margin_bottom(20)

        # Left side: Calendar
        calendar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        # Navigation row
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        prev_btn = Gtk.Button(label="<")
        prev_btn.add_css_class("secondary-button")
        prev_btn.connect("clicked", lambda _: self._go_prev_month())
        nav_box.append(prev_btn)

        self._month_label = Gtk.Label()
        self._month_label.add_css_class("month-label")
        self._month_label.set_hexpand(True)
        nav_box.append(self._month_label)

        next_btn = Gtk.Button(label=">")
        next_btn.add_css_class("secondary-button")
        next_btn.connect("clicked", lambda _: self._go_next_month())
        self._next_btn = next_btn
        nav_box.append(next_btn)

        today_btn = Gtk.Button(label="Today")
        today_btn.add_css_class("secondary-button")
        today_btn.connect("clicked", lambda _: self._go_today())
        nav_box.append(today_btn)

        calendar_box.append(nav_box)

        # Calendar widget
        self._calendar = Gtk.Calendar()
        self._calendar.add_css_class("calendar-widget")
        self._calendar.connect("day-selected", self._on_date_selected)
        self._calendar.connect("next-month", lambda _: self._on_month_changed())
        self._calendar.connect("prev-month", lambda _: self._on_month_changed())
        calendar_box.append(self._calendar)

        self.widget.append(calendar_box)

        # Right side: Recordings list
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        list_box.set_hexpand(True)

        self._selected_date_label = Gtk.Label(label="Select a date")
        self._selected_date_label.add_css_class("selected-date-label")
        self._selected_date_label.set_xalign(0)
        list_box.append(self._selected_date_label)

        # Scrolled list of recordings
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._recordings_list = Gtk.ListBox()
        self._recordings_list.add_css_class("recordings-list")
        self._recordings_list.connect("row-activated", self._on_recording_activated)
        scrolled.set_child(self._recordings_list)

        list_box.append(scrolled)

        self._count_label = Gtk.Label()
        self._count_label.add_css_class("count-label")
        self._count_label.set_xalign(0)
        list_box.append(self._count_label)

        self.widget.append(list_box)

        self._update_month_label()
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .month-label {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }

            .selected-date-label {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }

            .count-label {
                color: #a0a0a0;
                font-size: 12px;
            }

            .recordings-list {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }

            .recordings-list row {
                padding: 10px;
                border-bottom: 1px solid #2d2d2d;
            }

            .recordings-list row:selected {
                background-color: #2d4a6d;
            }

            .calendar-widget {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }

            .secondary-button {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
            }

            .secondary-button:hover {
                background-color: #3d3d3d;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.widget.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _schedule_refresh(self) -> None:
        """Schedule an async refresh."""
        GLib.idle_add(self._trigger_refresh)

    def _trigger_refresh(self) -> bool:
        """Trigger the refresh in the main thread."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._load_month_recordings())
            else:
                asyncio.run(self._load_month_recordings())
        except RuntimeError:
            pass
        return False  # Don't repeat

    async def _load_month_recordings(self) -> None:
        """Load recordings for the current month."""
        if not self._api_client:
            return

        try:
            cal_date = self._calendar.get_date()
            year = cal_date.get_year()
            month = cal_date.get_month()

            first_of_month = date(year, month, 1)
            if month == 12:
                last_of_month = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_of_month = date(year, month + 1, 1) - timedelta(days=1)

            start_date = first_of_month - timedelta(days=7)
            end_date = last_of_month + timedelta(days=7)

            recordings_data = await self._api_client.get_recordings(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

            self._recordings_cache.clear()
            for rec_data in recordings_data:
                recording = Recording.from_dict(rec_data)
                rec_date = recording.recorded_at[:10]
                if rec_date not in self._recordings_cache:
                    self._recordings_cache[rec_date] = []
                self._recordings_cache[rec_date].append(recording)

            # Update UI in main thread
            GLib.idle_add(self._update_calendar_marks)
            GLib.idle_add(self._update_recordings_list)

        except Exception as e:
            logger.error(f"Failed to load recordings: {e}")

    def _update_calendar_marks(self) -> bool:
        """Update calendar to mark days with recordings."""
        self._calendar.clear_marks()
        for date_str in self._recordings_cache:
            try:
                year, month, day = map(int, date_str.split("-"))
                cal_date = self._calendar.get_date()
                if year == cal_date.get_year() and month == cal_date.get_month():
                    self._calendar.mark_day(day)
            except ValueError:
                continue
        return False

    def _update_recordings_list(self) -> bool:
        """Update the recordings list for the selected date."""
        # Clear existing items
        while True:
            row = self._recordings_list.get_first_child()
            if row is None:
                break
            self._recordings_list.remove(row)

        cal_date = self._calendar.get_date()
        selected_date = date(
            cal_date.get_year(), cal_date.get_month(), cal_date.get_day_of_month()
        )
        date_str = selected_date.isoformat()

        self._selected_date_label.set_label(selected_date.strftime("%A, %B %d, %Y"))

        recordings = self._recordings_cache.get(date_str, [])
        recordings.sort(key=lambda r: r.recorded_at)

        for recording in recordings:
            row = self._create_recording_row(recording)
            self._recordings_list.append(row)

        count = len(recordings)
        if count == 0:
            self._count_label.set_label("No recordings on this date")
        elif count == 1:
            self._count_label.set_label("1 recording")
        else:
            self._count_label.set_label(f"{count} recordings")

        return False

    def _create_recording_row(self, recording: Recording) -> Gtk.ListBoxRow:
        """Create a list row for a recording."""
        row = Gtk.ListBoxRow()
        row.recording_id = recording.id

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        try:
            rec_datetime = datetime.fromisoformat(
                recording.recorded_at.replace("Z", "+00:00")
            )
            time_str = rec_datetime.strftime("%H:%M")
        except (ValueError, AttributeError):
            time_str = "??:??"

        duration_mins = int(recording.duration_seconds // 60)
        duration_secs = int(recording.duration_seconds % 60)
        duration_str = f"{duration_mins}:{duration_secs:02d}"

        title = recording.title or recording.filename
        if len(title) > 50:
            title = title[:47] + "..."

        title_label = Gtk.Label(label=f"{time_str}  |  {title}")
        title_label.set_xalign(0)
        title_label.add_css_class("recording-title")
        box.append(title_label)

        details = f"Duration: {duration_str}  •  Words: {recording.word_count}"
        if recording.has_diarization:
            details += "  •  Diarized"

        details_label = Gtk.Label(label=details)
        details_label.set_xalign(0)
        details_label.add_css_class("recording-details")
        box.append(details_label)

        row.set_child(box)
        return row

    def _update_month_label(self) -> None:
        """Update the month navigation label."""
        cal_date = self._calendar.get_date()
        month_names = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        self._month_label.set_label(
            f"{month_names[cal_date.get_month() - 1]} {cal_date.get_year()}"
        )

        today = date.today()
        current_month = date(cal_date.get_year(), cal_date.get_month(), 1)
        today_month = date(today.year, today.month, 1)
        self._next_btn.set_sensitive(current_month < today_month)

    def _on_date_selected(self, calendar) -> None:
        """Handle date selection."""
        self._update_recordings_list()

    def _on_month_changed(self) -> None:
        """Handle month navigation."""
        self._update_month_label()
        self._schedule_refresh()

    def _go_prev_month(self) -> None:
        """Navigate to previous month."""
        cal_date = self._calendar.get_date()
        if cal_date.get_month() == 1:
            new_date = GLib.DateTime.new_local(cal_date.get_year() - 1, 12, 1, 0, 0, 0)
        else:
            new_date = GLib.DateTime.new_local(
                cal_date.get_year(), cal_date.get_month() - 1, 1, 0, 0, 0
            )
        self._calendar.select_day(new_date)
        self._on_month_changed()

    def _go_next_month(self) -> None:
        """Navigate to next month."""
        cal_date = self._calendar.get_date()
        today = date.today()

        if cal_date.get_month() == 12:
            new_year = cal_date.get_year() + 1
            new_month = 1
        else:
            new_year = cal_date.get_year()
            new_month = cal_date.get_month() + 1

        if new_year > today.year or (
            new_year == today.year and new_month > today.month
        ):
            return

        new_date = GLib.DateTime.new_local(new_year, new_month, 1, 0, 0, 0)
        self._calendar.select_day(new_date)
        self._on_month_changed()

    def _go_today(self) -> None:
        """Navigate to today's date."""
        today = date.today()
        new_date = GLib.DateTime.new_local(today.year, today.month, today.day, 0, 0, 0)
        self._calendar.select_day(new_date)
        self._on_month_changed()

    def _on_recording_activated(self, listbox, row) -> None:
        """Handle double-click on a recording."""
        if hasattr(row, "recording_id") and self._recording_callback:
            self._recording_callback(row.recording_id)

    def set_recording_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for recording requests."""
        self._recording_callback = callback

    def refresh(self) -> None:
        """Refresh the calendar data."""
        self._schedule_refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._schedule_refresh()
