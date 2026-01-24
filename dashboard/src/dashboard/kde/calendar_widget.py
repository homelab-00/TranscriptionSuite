"""
Calendar widget for Audio Notebook.

Displays a monthly calendar view with recording counts per day,
allowing users to browse and select recordings by date.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.models import Recording

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class CalendarWidget(QWidget):
    """
    Calendar-based recording browser.

    Shows a monthly calendar with visual indicators for days that have recordings,
    and a list of recordings for the selected day.
    """

    # Signal emitted when a recording is selected
    recording_requested = pyqtSignal(int)  # recording_id

    def __init__(
        self,
        api_client: "APIClient",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client

        # Cache for recordings by date
        self._recordings_cache: dict[str, list[Recording]] = {}
        self._current_month_start: date | None = None

        self._setup_ui()
        self._apply_styles()

        # Load initial data
        self._schedule_refresh()

    def _setup_ui(self) -> None:
        """Set up the calendar widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Create splitter for calendar and recordings list
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Left side: Calendar
        calendar_container = QWidget()
        calendar_layout = QVBoxLayout(calendar_container)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        calendar_layout.setSpacing(12)

        # Calendar navigation
        nav_container = QWidget()
        nav_layout = QHBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)

        self._prev_month_btn = QPushButton("<")
        self._prev_month_btn.setObjectName("secondaryButton")
        self._prev_month_btn.setFixedWidth(40)
        self._prev_month_btn.clicked.connect(self._go_prev_month)
        nav_layout.addWidget(self._prev_month_btn)

        self._month_label = QLabel()
        self._month_label.setObjectName("monthLabel")
        self._month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self._month_label, 1)

        self._next_month_btn = QPushButton(">")
        self._next_month_btn.setObjectName("secondaryButton")
        self._next_month_btn.setFixedWidth(40)
        self._next_month_btn.clicked.connect(self._go_next_month)
        nav_layout.addWidget(self._next_month_btn)

        self._today_btn = QPushButton("Today")
        self._today_btn.setObjectName("secondaryButton")
        self._today_btn.clicked.connect(self._go_today)
        nav_layout.addWidget(self._today_btn)

        calendar_layout.addWidget(nav_container)

        # Calendar widget
        self._calendar = QCalendarWidget()
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self._calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self._calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self._calendar.selectionChanged.connect(self._on_date_selected)
        self._calendar.currentPageChanged.connect(self._on_month_changed)

        calendar_layout.addWidget(self._calendar)
        calendar_layout.addStretch()

        splitter.addWidget(calendar_container)

        # Right side: Recordings list for selected day
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        self._selected_date_label = QLabel("Select a date")
        self._selected_date_label.setObjectName("selectedDateLabel")
        list_layout.addWidget(self._selected_date_label)

        # Recordings list
        self._recordings_list = QListWidget()
        self._recordings_list.setObjectName("recordingsList")
        self._recordings_list.itemDoubleClicked.connect(
            self._on_recording_double_clicked
        )
        list_layout.addWidget(self._recordings_list, 1)

        # Recording count label
        self._count_label = QLabel()
        self._count_label.setObjectName("countLabel")
        list_layout.addWidget(self._count_label)

        splitter.addWidget(list_container)

        # Set initial splitter sizes (60% calendar, 40% list)
        splitter.setSizes([600, 400])

        layout.addWidget(splitter, 1)

        # Update month label
        self._update_month_label()

    def _apply_styles(self) -> None:
        """Apply styling to calendar components."""
        self.setStyleSheet("""
            #monthLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }

            #selectedDateLabel {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }

            #countLabel {
                color: #a0a0a0;
                font-size: 12px;
            }

            #recordingsList {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                padding: 4px;
            }

            #recordingsList::item {
                padding: 10px;
                border-bottom: 1px solid #2d2d2d;
                border-radius: 4px;
                margin: 2px;
            }

            #recordingsList::item:selected {
                background-color: #2d4a6d;
                border: 1px solid #90caf9;
            }

            #recordingsList::item:hover:!selected {
                background-color: #2d2d2d;
            }

            QCalendarWidget {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }

            QCalendarWidget QToolButton {
                color: #ffffff;
                background-color: transparent;
                border: none;
                padding: 4px;
            }

            QCalendarWidget QToolButton:hover {
                background-color: #2d2d2d;
                border-radius: 4px;
            }

            QCalendarWidget QMenu {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #2d2d2d;
            }

            QCalendarWidget QSpinBox {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #2d2d2d;
            }

            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #1e1e1e;
                border-bottom: 1px solid #2d2d2d;
            }

            QCalendarWidget QAbstractItemView:enabled {
                background-color: #1e1e1e;
                color: #ffffff;
                selection-background-color: #2d4a6d;
                selection-color: #ffffff;
            }

            QCalendarWidget QAbstractItemView:disabled {
                color: #606060;
            }

            QSplitter::handle {
                background-color: #2d2d2d;
                border-radius: 2px;
            }

            QSplitter::handle:hover {
                background-color: #3d3d3d;
            }
        """)

    def _schedule_refresh(self) -> None:
        """Schedule an async refresh."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._load_month_recordings())
            else:
                loop.run_until_complete(self._load_month_recordings())
        except RuntimeError:
            # No event loop, try to create one
            asyncio.run(self._load_month_recordings())

    async def _load_month_recordings(self) -> None:
        """Load recordings for the current month."""
        try:
            # Get the first and last day of the current calendar page
            current_date = self._calendar.selectedDate()
            year = current_date.year()
            month = current_date.month()

            # Calculate date range (include some days from adjacent months for display)
            first_of_month = date(year, month, 1)
            if month == 12:
                last_of_month = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_of_month = date(year, month + 1, 1) - timedelta(days=1)

            # Extend range to cover the full calendar view
            start_date = first_of_month - timedelta(days=7)
            end_date = last_of_month + timedelta(days=7)

            self._current_month_start = first_of_month

            # Fetch recordings
            recordings_data = await self._api_client.get_recordings(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

            # Parse and cache recordings by date
            self._recordings_cache.clear()
            for rec_data in recordings_data:
                recording = Recording.from_dict(rec_data)
                # Extract date from recorded_at (ISO format)
                rec_date = recording.recorded_at[:10]  # YYYY-MM-DD
                if rec_date not in self._recordings_cache:
                    self._recordings_cache[rec_date] = []
                self._recordings_cache[rec_date].append(recording)

            # Update calendar display
            self._update_calendar_highlights()
            # Update the recordings list for selected date
            self._update_recordings_list()

            logger.debug(
                f"Loaded {len(recordings_data)} recordings for "
                f"{start_date} to {end_date}"
            )

        except Exception as e:
            logger.error(f"Failed to load recordings: {e}")

    def _update_calendar_highlights(self) -> None:
        """Update calendar to highlight days with recordings."""
        # Reset all date formats
        default_format = QTextCharFormat()

        # Format for days with recordings
        has_recordings_format = QTextCharFormat()
        has_recordings_format.setBackground(QColor("#2d4a6d"))
        has_recordings_format.setForeground(QColor("#90caf9"))

        # Apply formats
        for date_str, recordings in self._recordings_cache.items():
            if recordings:
                try:
                    year, month, day = map(int, date_str.split("-"))
                    qdate = QDate(year, month, day)
                    self._calendar.setDateTextFormat(qdate, has_recordings_format)
                except ValueError:
                    continue

    def _update_recordings_list(self) -> None:
        """Update the recordings list for the selected date."""
        self._recordings_list.clear()

        selected_qdate = self._calendar.selectedDate()
        selected_date = date(
            selected_qdate.year(),
            selected_qdate.month(),
            selected_qdate.day(),
        )
        date_str = selected_date.isoformat()

        # Update date label
        self._selected_date_label.setText(selected_date.strftime("%A, %B %d, %Y"))

        recordings = self._recordings_cache.get(date_str, [])

        # Sort by time (recorded_at)
        recordings.sort(key=lambda r: r.recorded_at)

        for recording in recordings:
            item = QListWidgetItem()

            # Extract time from recorded_at
            try:
                rec_datetime = datetime.fromisoformat(
                    recording.recorded_at.replace("Z", "+00:00")
                )
                time_str = rec_datetime.strftime("%H:%M")
            except (ValueError, AttributeError):
                time_str = "??:??"

            # Format duration
            duration_mins = int(recording.duration_seconds // 60)
            duration_secs = int(recording.duration_seconds % 60)
            duration_str = f"{duration_mins}:{duration_secs:02d}"

            # Display title or filename
            title = recording.title or recording.filename

            # Truncate long titles
            if len(title) > 50:
                title = title[:47] + "..."

            # Create display text
            display_text = f"{time_str}  |  {title}\n"
            display_text += (
                f"Duration: {duration_str}  •  Words: {recording.word_count}"
            )
            if recording.has_diarization:
                display_text += "  •  Diarized"

            item.setText(display_text)
            item.setData(Qt.ItemDataRole.UserRole, recording.id)

            self._recordings_list.addItem(item)

        # Update count label
        count = len(recordings)
        if count == 0:
            self._count_label.setText("No recordings on this date")
        elif count == 1:
            self._count_label.setText("1 recording")
        else:
            self._count_label.setText(f"{count} recordings")

    def _update_month_label(self) -> None:
        """Update the month navigation label."""
        current_date = self._calendar.selectedDate()
        month_name = QDate.longMonthName(current_date.month())
        self._month_label.setText(f"{month_name} {current_date.year()}")

        # Disable next month button if it would go into the future
        today = date.today()
        current_month_date = date(current_date.year(), current_date.month(), 1)
        today_month = date(today.year, today.month, 1)
        self._next_month_btn.setEnabled(current_month_date < today_month)

    def _on_date_selected(self) -> None:
        """Handle date selection in calendar."""
        self._update_recordings_list()

    def _on_month_changed(self, year: int, month: int) -> None:
        """Handle month navigation."""
        self._update_month_label()
        self._schedule_refresh()

    def _go_prev_month(self) -> None:
        """Navigate to previous month."""
        current = self._calendar.selectedDate()
        new_date = current.addMonths(-1)
        self._calendar.setSelectedDate(new_date)

    def _go_next_month(self) -> None:
        """Navigate to next month."""
        current = self._calendar.selectedDate()
        new_date = current.addMonths(1)

        # Don't go past current month
        today = QDate.currentDate()
        if new_date.year() > today.year() or (
            new_date.year() == today.year() and new_date.month() > today.month()
        ):
            return

        self._calendar.setSelectedDate(new_date)

    def _go_today(self) -> None:
        """Navigate to today's date."""
        self._calendar.setSelectedDate(QDate.currentDate())

    def _on_recording_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle double-click on a recording."""
        recording_id = item.data(Qt.ItemDataRole.UserRole)
        if recording_id:
            self.recording_requested.emit(recording_id)

    def refresh(self) -> None:
        """Refresh the calendar data."""
        self._schedule_refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._schedule_refresh()
