"""
Calendar widget for Audio Notebook (GNOME/GTK4).

Displays a monthly calendar grid view with recording indicators,
and a day view with hourly time slots matching the web UI design.
"""

import asyncio
import calendar
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    HAS_GTK4 = True
except (ImportError, ValueError):
    HAS_GTK4 = False
    Gtk = None
    GLib = None
    Gdk = None
    Gio = None

from dashboard.common.models import Recording

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


# Supported audio formats (same as ImportWidget)
AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
    ".aac",
    ".aiff",
    ".webm",
    ".mp4",
}


class DayViewImportDialog:
    """
    Import dialog for adding audio entries from the day view.

    This dialog provides a simplified import experience without the queue UI,
    allowing users to select a single file and set transcription options.
    """

    def __init__(
        self,
        api_client: "APIClient | None",
        target_date: date,
        hour: int,
        parent_window: Gtk.Window | None = None,
        on_complete: Callable[[int], None] | None = None,
    ):
        self._api_client = api_client
        self._target_date = target_date
        self._hour = hour
        self._on_complete = on_complete
        self._is_transcribing = False
        self._file_path: Path | None = None

        self._setup_dialog(parent_window)

    def _setup_dialog(self, parent_window: Gtk.Window | None) -> None:
        """Set up the dialog UI."""
        self.dialog = Gtk.Window(title="Add Audio Entry")
        self.dialog.set_default_size(450, 380)
        self.dialog.set_modal(True)
        if parent_window:
            self.dialog.set_transient_for(parent_window)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        main_box.set_margin_top(24)
        main_box.set_margin_bottom(24)

        # Header
        time_str = self._format_time(self._hour)
        date_str = self._target_date.strftime("%B %d, %Y")
        header_label = Gtk.Label(label=f"Adding entry for {date_str} at {time_str}")
        header_label.add_css_class("dialog-header")
        header_label.set_xalign(0)
        main_box.append(header_label)

        # Drop zone
        self._drop_zone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._drop_zone.add_css_class("day-view-drop-zone")
        self._drop_zone.set_valign(Gtk.Align.CENTER)
        self._drop_zone.set_halign(Gtk.Align.FILL)
        self._drop_zone.set_size_request(-1, 140)

        self._icon_label = Gtk.Label(label="⬆")
        self._icon_label.add_css_class("drop-icon")
        self._drop_zone.append(self._icon_label)

        self._text_label = Gtk.Label(label="Drag audio file here")
        self._text_label.add_css_class("drop-text")
        self._drop_zone.append(self._text_label)

        self._formats_label = Gtk.Label(
            label="Supported: MP3, WAV, M4A, FLAC, OGG, and more"
        )
        self._formats_label.add_css_class("drop-formats")
        self._drop_zone.append(self._formats_label)

        # Set up drag-and-drop
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        drop_target.connect("enter", self._on_drag_enter)
        drop_target.connect("leave", self._on_drag_leave)
        self._drop_zone.add_controller(drop_target)

        # Click to browse
        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", lambda *_: self._open_file_browser())
        self._drop_zone.add_controller(click_controller)

        main_box.append(self._drop_zone)

        # Options section
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        options_box.add_css_class("options-card")
        options_box.set_margin_top(8)
        options_box.set_margin_bottom(8)

        options_label = Gtk.Label(label="Transcription Options:")
        options_label.add_css_class("options-label")
        options_label.set_xalign(0)
        options_box.append(options_label)

        checkboxes_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)

        self._diarization_check = Gtk.CheckButton(label="Speaker diarization")
        self._diarization_check.set_active(True)
        checkboxes_box.append(self._diarization_check)

        self._word_timestamps_check = Gtk.CheckButton(label="Word-level timestamps")
        self._word_timestamps_check.set_active(True)
        checkboxes_box.append(self._word_timestamps_check)

        options_box.append(checkboxes_box)
        main_box.append(options_box)

        # Progress section (hidden by default)
        self._progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._progress_box.set_visible(False)

        self._status_label = Gtk.Label()
        self._status_label.add_css_class("status-label")
        self._status_label.set_xalign(0)
        self._progress_box.append(self._status_label)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.add_css_class("import-progress")
        self._progress_box.append(self._progress_bar)

        main_box.append(self._progress_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        main_box.append(spacer)

        # Button row
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.add_css_class("secondary-button")
        self._cancel_btn.connect("clicked", lambda _: self.dialog.close())
        button_box.append(self._cancel_btn)

        spacer2 = Gtk.Box()
        spacer2.set_hexpand(True)
        button_box.append(spacer2)

        self._transcribe_btn = Gtk.Button(label="Transcribe")
        self._transcribe_btn.add_css_class("primary-button")
        self._transcribe_btn.set_sensitive(False)
        self._transcribe_btn.connect("clicked", lambda _: self._start_transcription())
        button_box.append(self._transcribe_btn)

        main_box.append(button_box)

        self.dialog.set_child(main_box)
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .dialog-header {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }

            .day-view-drop-zone {
                background-color: #1e1e1e;
                border: 2px dashed #3d3d3d;
                border-radius: 12px;
                padding: 20px;
            }

            .day-view-drop-zone.drag-over {
                border-color: #90caf9;
                background-color: #1e2a3a;
            }

            .drop-icon {
                font-size: 36px;
                color: #ffffff;
            }

            .drop-text {
                color: #a0a0a0;
                font-size: 13px;
            }

            .drop-formats {
                color: #606060;
                font-size: 11px;
            }

            .options-card {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                padding: 12px 16px;
            }

            .options-label {
                color: #a0a0a0;
                font-size: 13px;
                font-weight: bold;
            }

            .status-label {
                color: #a0a0a0;
                font-size: 13px;
            }

            .primary-button {
                background-color: #1e88e5;
                border: none;
                border-radius: 6px;
                color: white;
                padding: 10px 24px;
                font-weight: bold;
            }

            .primary-button:hover {
                background-color: #2196f3;
            }

            .primary-button:disabled {
                background-color: #2d2d2d;
                color: #606060;
            }

            .secondary-button {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: white;
                padding: 10px 24px;
            }

            .secondary-button:hover {
                background-color: #3d3d3d;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.dialog.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _format_time(self, hour: int) -> str:
        """Format hour to 12-hour time string."""
        if hour == 0:
            return "12:00 AM"
        elif hour < 12:
            return f"{hour}:00 AM"
        elif hour == 12:
            return "12:00 PM"
        else:
            return f"{hour - 12}:00 PM"

    def _on_drag_enter(self, drop_target, x, y) -> Gdk.DragAction:
        """Handle drag enter."""
        self._drop_zone.add_css_class("drag-over")
        return Gdk.DragAction.COPY

    def _on_drag_leave(self, drop_target) -> None:
        """Handle drag leave."""
        self._drop_zone.remove_css_class("drag-over")

    def _on_drop(self, drop_target, value, x, y) -> bool:
        """Handle file drop."""
        self._drop_zone.remove_css_class("drag-over")

        if isinstance(value, Gio.File):
            file_path = Path(value.get_path())
            if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                self._file_path = file_path
                self._update_display()
                self._transcribe_btn.set_sensitive(True)
                return True
        return False

    def _open_file_browser(self) -> None:
        """Open file browser dialog."""
        dialog = Gtk.FileChooserDialog(
            title="Select Audio File",
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Open", Gtk.ResponseType.ACCEPT)
        dialog.set_transient_for(self.dialog)
        dialog.set_modal(True)

        filter_audio = Gtk.FileFilter()
        filter_audio.set_name("Audio files")
        for ext in AUDIO_EXTENSIONS:
            filter_audio.add_pattern(f"*{ext}")
        dialog.add_filter(filter_audio)

        dialog.connect("response", self._on_file_chooser_response)
        dialog.present()

    def _on_file_chooser_response(self, dialog, response) -> None:
        """Handle file chooser response."""
        if response == Gtk.ResponseType.ACCEPT:
            gfile = dialog.get_file()
            if gfile:
                file_path = Path(gfile.get_path())
                if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                    self._file_path = file_path
                    self._update_display()
                    self._transcribe_btn.set_sensitive(True)
        dialog.destroy()

    def _update_display(self) -> None:
        """Update display to show selected file."""
        if self._file_path:
            self._icon_label.set_label("🎵")
            self._text_label.set_label(self._file_path.name)
            self._formats_label.set_label("Drop another file to replace")

    def _start_transcription(self) -> None:
        """Start the transcription process."""
        if not self._file_path:
            return

        self._is_transcribing = True
        self._transcribe_btn.set_sensitive(False)
        self._cancel_btn.set_label("Close")
        self._progress_box.set_visible(True)
        self._status_label.set_label("Starting transcription...")
        self._progress_bar.set_fraction(0)

        target_datetime = datetime(
            self._target_date.year,
            self._target_date.month,
            self._target_date.day,
            self._hour,
            0,
            0,
        ).isoformat()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._upload_file(self._file_path, target_datetime))
            else:
                asyncio.run(self._upload_file(self._file_path, target_datetime))
        except RuntimeError:
            pass

    async def _upload_file(self, file_path: Path, recorded_at: str) -> None:
        """Upload and transcribe the file."""
        if self._api_client is None:
            GLib.idle_add(
                lambda: self._status_label.set_label("Error: Not connected to server")
            )
            self._is_transcribing = False
            return

        try:

            def on_progress(message: str) -> None:
                def update():
                    self._status_label.set_label(message)
                    if "uploading" in message.lower():
                        self._progress_bar.set_fraction(0.2)
                    elif "transcribing" in message.lower():
                        self._progress_bar.set_fraction(0.5)
                    elif "complete" in message.lower():
                        self._progress_bar.set_fraction(1.0)
                    return False

                GLib.idle_add(update)

            result = await self._api_client.upload_file_to_notebook(
                file_path=file_path,
                diarization=self._diarization_check.get_active(),
                word_timestamps=self._word_timestamps_check.get_active(),
                recorded_at=recorded_at,
                on_progress=on_progress,
            )

            recording_id = result.get("id") or result.get("recording_id")

            def finish():
                self._progress_bar.set_fraction(1.0)
                self._status_label.set_label("Transcription complete!")
                if recording_id and self._on_complete:
                    self._on_complete(recording_id)
                GLib.timeout_add(1000, lambda: self.dialog.close() or False)
                return False

            GLib.idle_add(finish)
            logger.info(
                f"Day view import complete: {file_path.name} -> ID {recording_id}"
            )

        except Exception as e:
            logger.error(f"Day view import failed for {file_path.name}: {e}")
            GLib.idle_add(lambda: self._status_label.set_label(f"Error: {e}"))
            self._is_transcribing = False

    def present(self) -> None:
        """Show the dialog."""
        self.dialog.present()


class CalendarWidget:
    """
    Calendar-based recording browser with month and day views.

    Shows a monthly calendar grid with visual indicators for days that have recordings,
    and a day view with hourly time slots when a date is selected.
    """

    def __init__(self, api_client: "APIClient | None"):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for CalendarWidget")

        self._api_client = api_client
        self._recordings_cache: dict[str, list[Recording]] = {}
        self._recording_callback: Callable[[int], None] | None = None
        self._delete_callback: Callable[[int], None] | None = None
        self._change_date_callback: Callable[[int], None] | None = None
        self._export_callback: Callable[[int], None] | None = None

        # State
        self._current_year = date.today().year
        self._current_month = date.today().month
        self._selected_date: date | None = date.today()
        self._day_cells: list[Gtk.Button] = []
        self._time_slots: dict[int, dict] = {}
        self._view_mode = "month"

        self._setup_ui()
        self._schedule_refresh()

    def _setup_ui(self) -> None:
        """Set up the calendar widget UI."""
        # Main container
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.widget.set_margin_start(24)
        self.widget.set_margin_end(24)
        self.widget.set_margin_top(24)
        self.widget.set_margin_bottom(24)

        # Header with navigation
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        # Back button (hidden in month view)
        self._back_btn = Gtk.Button(label="← Month")
        self._back_btn.add_css_class("secondary-button")
        self._back_btn.connect("clicked", lambda _: self._show_month_view())
        self._back_btn.set_visible(False)
        header_box.append(self._back_btn)

        # Title
        self._title_label = Gtk.Label()
        self._title_label.add_css_class("calendar-title")
        self._title_label.set_hexpand(True)
        self._title_label.set_xalign(0)
        header_box.append(self._title_label)

        # Navigation buttons
        self._prev_btn = Gtk.Button(label="←")
        self._prev_btn.add_css_class("nav-button")
        self._prev_btn.connect("clicked", lambda _: self._go_prev())
        header_box.append(self._prev_btn)

        self._next_btn = Gtk.Button(label="→")
        self._next_btn.add_css_class("nav-button")
        self._next_btn.connect("clicked", lambda _: self._go_next())
        header_box.append(self._next_btn)

        self.widget.append(header_box)

        # Stack for month/day views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_vexpand(True)

        # Month view
        self._month_view = self._create_month_view()
        self._stack.add_named(self._month_view, "month")

        # Day view
        self._day_view = self._create_day_view()
        self._stack.add_named(self._day_view, "day")

        self.widget.append(self._stack)

        self._update_title()
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .calendar-title {
                color: #ffffff;
                font-size: 24px;
                font-weight: bold;
            }

            .nav-button, .secondary-button {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
            }

            .nav-button:hover, .secondary-button:hover {
                background-color: #3d3d3d;
            }

            .day-header {
                color: #808080;
                font-size: 12px;
                font-weight: 500;
            }

            .day-cell {
                background-color: #1a1a2e;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
                min-height: 70px;
                padding: 8px;
            }

            .day-cell:hover {
                background-color: #252540;
                border-color: #3d3d3d;
            }

            .day-cell.selected {
                background-color: #2d4a6d;
                border: 2px solid #90caf9;
            }

            .day-cell.today {
                background-color: #1e3a5f;
                border: 2px solid #90caf9;
            }

            .day-cell.other-month {
                background-color: #0d0d1a;
            }

            .day-cell.other-month .day-number {
                color: #404040;
            }

            .day-cell.future {
                background-color: #0d0d1a;
            }

            .day-cell.future .day-number {
                color: #404040;
            }

            .day-cell.has-recordings {
                background-color: #1e2a3a;
            }

            .day-number {
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
            }

            .recording-indicator {
                color: #90caf9;
                font-size: 10px;
            }

            .time-slot {
                border-bottom: 1px solid #2d2d2d;
                padding: 8px 12px;
                min-height: 60px;
            }

            .time-slot:hover {
                background-color: #1e1e2e;
            }

            .time-label {
                color: #808080;
                font-size: 12px;
            }

            .section-title-morning {
                color: #90caf9;
                font-size: 16px;
                font-weight: bold;
            }

            .section-title-afternoon {
                color: #f48fb1;
                font-size: 16px;
                font-weight: bold;
            }

            .add-button {
                background-color: transparent;
                border: 1px dashed #3d3d3d;
                border-radius: 4px;
                color: #606060;
                min-width: 28px;
                min-height: 28px;
            }

            .add-button:hover {
                background-color: #2d2d2d;
                border-color: #90caf9;
                color: #90caf9;
            }

            .recording-card {
                background-color: #1e2a3a;
                border: 1px solid #2d4a6d;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 180px;
            }

            .recording-card:hover {
                background-color: #263a4f;
                border-color: #90caf9;
            }

            .card-title {
                color: #ffffff;
                font-size: 13px;
                font-weight: 500;
            }

            .card-info {
                color: #808080;
                font-size: 11px;
            }

            .card-duration {
                color: #a0a0a0;
                font-size: 11px;
            }

            .diarization-badge {
                background-color: #1e3a5f;
                border: 1px solid #4a90d9;
                border-radius: 4px;
                color: #90caf9;
                font-size: 10px;
                padding: 2px 6px;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.widget.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _create_month_view(self) -> Gtk.Widget:
        """Create the month grid view."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        # Day of week headers
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        header.set_margin_bottom(8)

        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for day in days:
            lbl = Gtk.Label(label=day)
            lbl.add_css_class("day-header")
            lbl.set_hexpand(True)
            header.append(lbl)

        container.append(header)

        # Calendar grid
        self._grid = Gtk.Grid()
        self._grid.set_row_homogeneous(True)
        self._grid.set_column_homogeneous(True)
        self._grid.set_row_spacing(2)
        self._grid.set_column_spacing(2)
        self._grid.set_vexpand(True)

        container.append(self._grid)
        self._rebuild_calendar_grid()

        return container

    def _create_day_view(self) -> Gtk.Widget:
        """Create the day view with hourly time slots."""
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)

        # Morning section (12 AM - 11 AM)
        morning = self._create_time_section("Morning", range(0, 12))
        morning.set_hexpand(True)
        container.append(morning)

        # Afternoon section (12 PM - 11 PM)
        afternoon = self._create_time_section("Afternoon", range(12, 24))
        afternoon.set_hexpand(True)
        container.append(afternoon)

        return container

    def _create_time_section(self, title: str, hours: range) -> Gtk.Widget:
        """Create a time section (morning or afternoon)."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        # Section title
        title_label = Gtk.Label(label=title)
        if "Morning" in title:
            title_label.add_css_class("section-title-morning")
        else:
            title_label.add_css_class("section-title-afternoon")
        title_label.set_xalign(0)
        container.append(title_label)

        # Scrollable time slots
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        slots_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        for hour in hours:
            slot = self._create_time_slot(hour)
            slots_box.append(slot)

        scrolled.set_child(slots_box)
        container.append(scrolled)

        return container

    def _create_time_slot(self, hour: int) -> Gtk.Widget:
        """Create a single time slot row."""
        slot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        slot.add_css_class("time-slot")

        # Time label
        if hour == 0:
            time_str = "12 AM"
        elif hour < 12:
            time_str = f"{hour} AM"
        elif hour == 12:
            time_str = "12 PM"
        else:
            time_str = f"{hour - 12} PM"

        time_label = Gtk.Label(label=time_str)
        time_label.add_css_class("time-label")
        time_label.set_size_request(50, -1)
        time_label.set_xalign(0)
        slot.append(time_label)

        # Recordings container (scrollable horizontally)
        recordings_scroll = Gtk.ScrolledWindow()
        recordings_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        recordings_scroll.set_hexpand(True)
        recordings_scroll.set_size_request(-1, 56)

        recordings_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        recordings_scroll.set_child(recordings_box)
        slot.append(recordings_scroll)

        # Add button
        add_btn = Gtk.Button(label="+")
        add_btn.add_css_class("add-button")
        add_btn.set_visible(False)  # Hidden by default, shown on hover
        add_btn.connect("clicked", lambda _, h=hour: self._on_add_clicked(h))
        slot.append(add_btn)

        # Hover detection for showing add button
        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect("enter", lambda *_, h=hour: self._on_slot_enter(h))
        motion_controller.connect("leave", lambda *_, h=hour: self._on_slot_leave(h))
        slot.add_controller(motion_controller)

        # Store references
        self._time_slots[hour] = {
            "slot": slot,
            "add_btn": add_btn,
            "recordings_box": recordings_box,
            "recording_widgets": [],
        }

        return slot

    def _on_slot_enter(self, hour: int) -> None:
        """Show add button when mouse enters time slot."""
        slot_info = self._time_slots.get(hour)
        if slot_info and slot_info["add_btn"].get_sensitive():
            slot_info["add_btn"].set_visible(True)

    def _on_slot_leave(self, hour: int) -> None:
        """Hide add button when mouse leaves time slot."""
        slot_info = self._time_slots.get(hour)
        if slot_info:
            slot_info["add_btn"].set_visible(False)

    def _on_add_clicked(self, hour: int) -> None:
        """Handle add button click for a time slot."""
        if self._selected_date:
            dialog = DayViewImportDialog(
                api_client=self._api_client,
                target_date=self._selected_date,
                hour=hour,
                parent_window=None,
                on_complete=self._on_day_view_import_complete,
            )
            dialog.present()

    def _on_day_view_import_complete(self, recording_id: int) -> None:
        """Handle completion of a day view import."""
        logger.info(f"Day view import complete, recording ID: {recording_id}")
        self.refresh()

    def _rebuild_calendar_grid(self) -> None:
        """Rebuild the calendar grid for the current month."""
        # Clear existing cells
        for cell in self._day_cells:
            self._grid.remove(cell)
        self._day_cells.clear()

        # Get calendar data for the month
        cal = calendar.Calendar(firstweekday=6)  # Sunday first
        month_days = cal.monthdatescalendar(self._current_year, self._current_month)

        # Build grid
        for row, week in enumerate(month_days):
            for col, day_date in enumerate(week):
                cell = self._create_day_cell(day_date)
                self._grid.attach(cell, col, row, 1, 1)
                self._day_cells.append(cell)

    def _create_day_cell(self, day_date: date) -> Gtk.Button:
        """Create a single day cell."""
        is_current_month = day_date.month == self._current_month
        is_today = day_date == date.today()
        is_future = day_date > date.today()
        is_selected = self._selected_date and day_date == self._selected_date

        cell = Gtk.Button()
        cell.add_css_class("day-cell")
        cell.set_hexpand(True)
        cell.set_vexpand(True)
        cell.day_date = day_date

        if is_future:
            cell.add_css_class("future")
            cell.set_sensitive(False)
        elif is_selected:
            cell.add_css_class("selected")
        elif is_today:
            cell.add_css_class("today")
        elif not is_current_month:
            cell.add_css_class("other-month")

        # Cell content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.set_halign(Gtk.Align.START)
        content.set_valign(Gtk.Align.START)

        day_label = Gtk.Label(label=str(day_date.day))
        day_label.add_css_class("day-number")
        content.append(day_label)

        # Recording indicator (updated later)
        indicator = Gtk.Label()
        indicator.add_css_class("recording-indicator")
        indicator.set_visible(False)
        content.append(indicator)
        cell.indicator = indicator

        cell.set_child(content)

        if not is_future:
            cell.connect("clicked", self._on_day_clicked)

        return cell

    def _on_day_clicked(self, button) -> None:
        """Handle day cell click."""
        clicked_date = button.day_date

        # Update selection styling
        for cell in self._day_cells:
            cell.remove_css_class("selected")
            if cell.day_date == clicked_date:
                cell.add_css_class("selected")

        self._selected_date = clicked_date
        self._show_day_view()

    def _show_month_view(self) -> None:
        """Switch to month view."""
        self._view_mode = "month"
        self._stack.set_visible_child_name("month")
        self._back_btn.set_visible(False)
        self._update_title()

    def _show_day_view(self) -> None:
        """Switch to day view for selected date."""
        self._view_mode = "day"
        self._stack.set_visible_child_name("day")
        self._back_btn.set_visible(True)
        self._update_title()
        self._update_day_view()

    def _update_title(self) -> None:
        """Update the title based on current view mode."""
        if self._view_mode == "month":
            month_name = calendar.month_name[self._current_month]
            self._title_label.set_label(f"{month_name} {self._current_year}")
        else:
            if self._selected_date:
                self._title_label.set_label(self._selected_date.strftime("%A, %b %d"))

    def _update_day_view(self) -> None:
        """Update day view with recordings for the selected date."""
        if not self._selected_date:
            return

        date_str = self._selected_date.isoformat()
        recordings = self._recordings_cache.get(date_str, [])
        today = date.today()
        now = datetime.now()

        # Group recordings by hour
        recordings_by_hour: dict[int, list[Recording]] = {}
        for rec in recordings:
            try:
                rec_dt = datetime.fromisoformat(rec.recorded_at.replace("Z", "+00:00"))
                hour = rec_dt.hour
                if hour not in recordings_by_hour:
                    recordings_by_hour[hour] = []
                recordings_by_hour[hour].append(rec)
            except (ValueError, AttributeError):
                pass

        # Update time slot widgets
        for hour, slot_info in self._time_slots.items():
            add_btn = slot_info["add_btn"]
            recordings_box = slot_info["recordings_box"]

            # Clear existing recording widgets
            for widget in slot_info["recording_widgets"]:
                recordings_box.remove(widget)
            slot_info["recording_widgets"] = []

            # Add recording cards for this hour
            hour_recordings = recordings_by_hour.get(hour, [])
            for rec in hour_recordings:
                card = self._create_recording_card(rec)
                recordings_box.append(card)
                slot_info["recording_widgets"].append(card)

            # Disable add button for future time slots
            is_future = self._selected_date > today or (
                self._selected_date == today and hour > now.hour
            )
            add_btn.set_sensitive(not is_future)

    def _create_recording_card(self, rec: Recording) -> Gtk.Button:
        """Create a card widget for a recording entry."""
        card = Gtk.Button()
        card.add_css_class("recording-card")
        card.recording_id = rec.id

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Top row: title + diarization badge
        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        title = rec.title or rec.filename or "Recording"
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("card-title")
        title_label.set_xalign(0)
        title_label.set_hexpand(True)
        title_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        title_label.set_max_width_chars(20)
        top_box.append(title_label)

        if rec.has_diarization:
            diar_badge = Gtk.Label(label="Diarization")
            diar_badge.add_css_class("diarization-badge")
            top_box.append(diar_badge)

        layout.append(top_box)

        # Bottom row: time and duration
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        try:
            rec_dt = datetime.fromisoformat(rec.recorded_at.replace("Z", "+00:00"))
            time_str = rec_dt.strftime("%I:%M %p").lstrip("0")
        except (ValueError, AttributeError):
            time_str = ""

        time_label = Gtk.Label(label=f"● {time_str}")
        time_label.add_css_class("card-info")
        time_label.set_xalign(0)
        info_box.append(time_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        info_box.append(spacer)

        duration = rec.duration_seconds
        if duration < 60:
            duration_str = f"{int(duration)}s"
        elif duration < 3600:
            mins = int(duration // 60)
            secs = int(duration % 60)
            duration_str = f"{mins}m {secs}s" if secs else f"{mins}m"
        else:
            hours = int(duration // 3600)
            mins = int((duration % 3600) // 60)
            duration_str = f"{hours}h {mins}m"

        duration_label = Gtk.Label(label=duration_str)
        duration_label.add_css_class("card-duration")
        info_box.append(duration_label)

        layout.append(info_box)

        card.set_child(layout)

        # Click handlers
        card.connect("clicked", self._on_card_clicked)

        # Right-click menu
        gesture = Gtk.GestureClick()
        gesture.set_button(3)  # Right button
        gesture.connect("pressed", lambda g, n, x, y, r=rec: self._show_card_menu(g, r))
        card.add_controller(gesture)

        return card

    def _on_card_clicked(self, button) -> None:
        """Handle card click."""
        if hasattr(button, "recording_id") and self._recording_callback:
            self._recording_callback(button.recording_id)

    def _show_card_menu(self, gesture, rec: Recording) -> None:
        """Show context menu for a recording card."""
        menu = Gtk.PopoverMenu()
        menu_model = Gio.Menu()

        menu_model.append("Change date & time", f"card.change_date::{rec.id}")
        menu_model.append("Delete note", f"card.delete::{rec.id}")

        menu.set_menu_model(menu_model)

        # For now, use callbacks directly since action setup is complex
        # We'll trigger callbacks via simple button approach
        widget = gesture.get_widget()

        popover = Gtk.Popover()
        popover.set_parent(widget)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        export_btn = Gtk.Button(label="Export transcription")
        export_btn.add_css_class("flat")
        export_btn.connect(
            "clicked", lambda _, rid=rec.id: self._request_export(rid, popover)
        )
        box.append(export_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        box.append(sep)

        change_btn = Gtk.Button(label="Change date & time")
        change_btn.add_css_class("flat")
        change_btn.connect(
            "clicked", lambda _, rid=rec.id: self._request_change_date(rid, popover)
        )
        box.append(change_btn)

        delete_btn = Gtk.Button(label="Delete note")
        delete_btn.add_css_class("flat")
        delete_btn.connect(
            "clicked", lambda _, rid=rec.id: self._request_delete(rid, popover)
        )
        box.append(delete_btn)

        popover.set_child(box)
        popover.popup()

    def _request_change_date(self, recording_id: int, popover: Gtk.Popover) -> None:
        """Request date change for a recording."""
        popover.popdown()
        if self._change_date_callback:
            self._change_date_callback(recording_id)

    def _request_delete(self, recording_id: int, popover: Gtk.Popover) -> None:
        """Request deletion of a recording."""
        popover.popdown()
        if self._delete_callback:
            self._delete_callback(recording_id)

    def _request_export(self, recording_id: int, popover: Gtk.Popover) -> None:
        """Request export of a recording."""
        popover.popdown()
        if self._export_callback:
            self._export_callback(recording_id)

    def _go_prev(self) -> None:
        """Navigate to previous month/day."""
        if self._view_mode == "month":
            if self._current_month == 1:
                self._current_month = 12
                self._current_year -= 1
            else:
                self._current_month -= 1
            self._rebuild_calendar_grid()
            self._update_title()
            self._schedule_refresh()
        else:
            if self._selected_date:
                self._selected_date -= timedelta(days=1)
                self._update_title()
                self._update_day_view()

    def _go_next(self) -> None:
        """Navigate to next month/day."""
        today = date.today()

        if self._view_mode == "month":
            next_month = self._current_month + 1 if self._current_month < 12 else 1
            next_year = (
                self._current_year
                if self._current_month < 12
                else self._current_year + 1
            )
            if date(next_year, next_month, 1) > date(today.year, today.month, 1):
                return

            self._current_month = next_month
            self._current_year = next_year
            self._rebuild_calendar_grid()
            self._update_title()
            self._schedule_refresh()
        else:
            if self._selected_date and self._selected_date < today:
                self._selected_date += timedelta(days=1)
                self._update_title()
                self._update_day_view()

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
        return False

    async def _load_month_recordings(self) -> None:
        """Load recordings for the current month."""
        if not self._api_client:
            logger.warning("API client not available")
            return

        try:
            first_of_month = date(self._current_year, self._current_month, 1)
            if self._current_month == 12:
                last_of_month = date(self._current_year + 1, 1, 1) - timedelta(days=1)
            else:
                last_of_month = date(
                    self._current_year, self._current_month + 1, 1
                ) - timedelta(days=1)

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

            GLib.idle_add(self._update_calendar_highlights)

            logger.debug(
                f"Loaded {len(recordings_data)} recordings for {start_date} to {end_date}"
            )

        except Exception as e:
            logger.error(f"Failed to load recordings: {e}")

    def _update_calendar_highlights(self) -> bool:
        """Update day cells with recording counts and refresh day view if active."""
        for cell in self._day_cells:
            if hasattr(cell, "day_date") and hasattr(cell, "indicator"):
                date_str = cell.day_date.isoformat()
                recordings = self._recordings_cache.get(date_str, [])
                count = len(recordings)

                if count > 0:
                    cell.indicator.set_label(f"● {count}" if count > 1 else "●")
                    cell.indicator.set_visible(True)
                    if not cell.has_css_class("selected") and not cell.has_css_class(
                        "today"
                    ):
                        cell.add_css_class("has-recordings")
                else:
                    cell.indicator.set_visible(False)
                    cell.remove_css_class("has-recordings")

        if self._view_mode == "day" and self._selected_date:
            self._update_day_view()

        return False

    def set_recording_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for recording requests."""
        self._recording_callback = callback

    def set_delete_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for delete requests."""
        self._delete_callback = callback

    def set_change_date_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for change date requests."""
        self._change_date_callback = callback

    def set_export_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for export requests."""
        self._export_callback = callback

    def refresh(self) -> None:
        """Refresh the calendar data."""
        self._rebuild_calendar_grid()
        self._schedule_refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._schedule_refresh()
