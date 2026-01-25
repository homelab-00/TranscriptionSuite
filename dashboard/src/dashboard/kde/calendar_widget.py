"""
Calendar widget for Audio Notebook.

Displays a monthly calendar grid view with recording indicators,
and a day view with hourly time slots matching the web UI design.
"""

import asyncio
import calendar
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDate, QLocale, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.models import Recording

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class DayCell(QFrame):
    """A single day cell in the calendar grid."""

    clicked = pyqtSignal(date)

    def __init__(
        self, day_date: date | None, is_current_month: bool = True, parent=None
    ):
        super().__init__(parent)
        self._date = day_date
        self._is_current_month = is_current_month
        self._is_selected = False
        self._is_today = day_date == date.today() if day_date else False
        self._recording_count = 0

        self.setObjectName("dayCell")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Day number label
        self._day_label = QLabel(str(day_date.day) if day_date else "")
        self._day_label.setObjectName("dayNumber")
        layout.addWidget(self._day_label)

        # Recording indicator
        self._indicator = QLabel()
        self._indicator.setObjectName("recordingIndicator")
        self._indicator.hide()
        layout.addWidget(self._indicator)

        layout.addStretch()
        self._update_style()

    def set_recording_count(self, count: int) -> None:
        """Set the number of recordings for this day."""
        self._recording_count = count
        if count > 0:
            self._indicator.setText(f"● {count}" if count > 1 else "●")
            self._indicator.show()
        else:
            self._indicator.hide()
        self._update_style()

    def set_selected(self, selected: bool) -> None:
        """Set the selected state."""
        self._is_selected = selected
        self._update_style()

    def _update_style(self) -> None:
        """Update the cell styling based on state."""
        if self._is_selected:
            self.setProperty("state", "selected")
        elif self._is_today:
            self.setProperty("state", "today")
        elif not self._is_current_month:
            self.setProperty("state", "other-month")
        elif self._recording_count > 0:
            self.setProperty("state", "has-recordings")
        else:
            self.setProperty("state", "normal")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        """Handle mouse click."""
        if self._date:
            self.clicked.emit(self._date)
        super().mousePressEvent(event)


class CalendarWidget(QWidget):
    """
    Calendar-based recording browser with month and day views.

    Shows a monthly calendar grid with visual indicators for days that have recordings,
    and a day view with hourly time slots when a date is selected.
    """

    recording_requested = pyqtSignal(int)

    def __init__(
        self,
        api_client: "APIClient",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client

        # State
        self._recordings_cache: dict[str, list[Recording]] = {}
        self._current_year = date.today().year
        self._current_month = date.today().month
        self._selected_date: date | None = date.today()
        self._day_cells: list[DayCell] = []
        self._view_mode = "month"  # "month" or "day"

        self._setup_ui()
        self._apply_styles()
        self._schedule_refresh()

    def _setup_ui(self) -> None:
        """Set up the calendar widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header with navigation
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)

        # Back to month button (only visible in day view)
        self._back_btn = QPushButton("← Month")
        self._back_btn.setObjectName("secondaryButton")
        self._back_btn.clicked.connect(self._show_month_view)
        self._back_btn.hide()
        header_layout.addWidget(self._back_btn)

        # Month/Day title
        self._title_label = QLabel()
        self._title_label.setObjectName("calendarTitle")
        header_layout.addWidget(self._title_label, 1)

        # Navigation buttons
        self._prev_btn = QPushButton("←")
        self._prev_btn.setObjectName("navButton")
        self._prev_btn.setFixedSize(36, 36)
        self._prev_btn.clicked.connect(self._go_prev)
        header_layout.addWidget(self._prev_btn)

        self._next_btn = QPushButton("→")
        self._next_btn.setObjectName("navButton")
        self._next_btn.setFixedSize(36, 36)
        self._next_btn.clicked.connect(self._go_next)
        header_layout.addWidget(self._next_btn)

        layout.addWidget(header)

        # Stacked widget for month/day views
        self._stack = QStackedWidget()

        # Month view
        self._month_view = self._create_month_view()
        self._stack.addWidget(self._month_view)

        # Day view
        self._day_view = self._create_day_view()
        self._stack.addWidget(self._day_view)

        layout.addWidget(self._stack, 1)
        self._update_title()

    def _create_month_view(self) -> QWidget:
        """Create the month grid view."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Day of week headers
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 8)
        header_layout.setSpacing(2)

        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for day in days:
            lbl = QLabel(day)
            lbl.setObjectName("dayHeader")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(lbl)

        layout.addWidget(header)

        # Calendar grid
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(2)

        layout.addWidget(self._grid_widget, 1)
        self._rebuild_calendar_grid()

        return container

    def _create_day_view(self) -> QWidget:
        """Create the day view with hourly time slots."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        # Morning section (12 AM - 11 AM)
        morning = self._create_time_section("Morning", range(0, 12))
        layout.addWidget(morning, 1)

        # Afternoon & Evening section (12 PM - 11 PM)
        afternoon = self._create_time_section("Afternoon & Evening", range(12, 24))
        layout.addWidget(afternoon, 1)

        return container

    def _create_time_section(self, title: str, hours: range) -> QWidget:
        """Create a time section (morning or afternoon)."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Section title
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        if "Morning" in title:
            title_label.setStyleSheet(
                "color: #90caf9; font-size: 16px; font-weight: bold;"
            )
        else:
            title_label.setStyleSheet(
                "color: #f48fb1; font-size: 16px; font-weight: bold;"
            )
        layout.addWidget(title_label)

        # Scrollable time slots
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("timeScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        slots_widget = QWidget()
        slots_widget.setObjectName(f"timeSlots_{title.replace(' ', '_')}")
        slots_layout = QVBoxLayout(slots_widget)
        slots_layout.setContentsMargins(0, 0, 0, 0)
        slots_layout.setSpacing(0)

        for hour in hours:
            slot = self._create_time_slot(hour)
            slots_layout.addWidget(slot)

        slots_layout.addStretch()
        scroll.setWidget(slots_widget)
        layout.addWidget(scroll, 1)

        # Store reference for updating
        if "Morning" in title:
            self._morning_slots = slots_widget
        else:
            self._afternoon_slots = slots_widget

        return container

    def _create_time_slot(self, hour: int) -> QWidget:
        """Create a single time slot row."""
        slot = QFrame()
        slot.setObjectName("timeSlot")
        slot.setMinimumHeight(50)
        slot.setProperty("hour", hour)

        layout = QHBoxLayout(slot)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Time label
        if hour == 0:
            time_str = "12 AM"
        elif hour < 12:
            time_str = f"{hour} AM"
        elif hour == 12:
            time_str = "12 PM"
        else:
            time_str = f"{hour - 12} PM"

        time_label = QLabel(time_str)
        time_label.setObjectName("timeLabel")
        time_label.setFixedWidth(50)
        layout.addWidget(time_label)

        # Indicator dot
        dot = QLabel("●")
        dot.setObjectName("timeDot")
        dot.setFixedWidth(16)
        layout.addWidget(dot)

        # Recordings container (for this hour)
        recordings_container = QWidget()
        recordings_container.setObjectName(f"recordings_{hour}")
        recordings_layout = QHBoxLayout(recordings_container)
        recordings_layout.setContentsMargins(0, 0, 0, 0)
        recordings_layout.setSpacing(8)

        # Add button placeholder
        add_btn = QPushButton("+")
        add_btn.setObjectName("addButton")
        add_btn.setFixedSize(24, 24)
        add_btn.setToolTip("Import recording for this time")
        recordings_layout.addWidget(add_btn)

        recordings_layout.addStretch()
        layout.addWidget(recordings_container, 1)

        return slot

    def _apply_styles(self) -> None:
        """Apply styling to calendar components."""
        self.setStyleSheet("""
            /* Title */
            #calendarTitle {
                color: #ffffff;
                font-size: 24px;
                font-weight: bold;
            }

            /* Navigation buttons */
            #navButton, #secondaryButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: #ffffff;
                font-size: 14px;
            }

            #navButton:hover, #secondaryButton:hover {
                background-color: #3d3d3d;
            }

            /* Day headers */
            #dayHeader {
                color: #808080;
                font-size: 12px;
                font-weight: 500;
                padding: 8px;
            }

            /* Day cells */
            #dayCell {
                background-color: #1a1a2e;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
            }

            #dayCell:hover {
                background-color: #252540;
                border-color: #3d3d3d;
            }

            #dayCell[state="selected"] {
                background-color: #2d4a6d;
                border: 2px solid #90caf9;
            }

            #dayCell[state="today"] {
                background-color: #1e3a5f;
                border: 2px solid #90caf9;
            }

            #dayCell[state="other-month"] {
                background-color: #0d0d1a;
            }

            #dayCell[state="other-month"] #dayNumber {
                color: #404040;
            }

            #dayCell[state="has-recordings"] {
                background-color: #1e2a3a;
            }

            #dayNumber {
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
            }

            #recordingIndicator {
                color: #90caf9;
                font-size: 10px;
            }

            /* Time slots in day view */
            #timeSlot {
                background-color: transparent;
                border-bottom: 1px solid #2d2d2d;
            }

            #timeSlot:hover {
                background-color: #1e1e2e;
            }

            #timeLabel {
                color: #808080;
                font-size: 12px;
            }

            #timeDot {
                color: #90caf9;
                font-size: 8px;
            }

            #addButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #606060;
                font-size: 14px;
            }

            #addButton:hover {
                background-color: #3d3d3d;
                color: #90caf9;
            }

            /* Scroll area */
            #timeScroll {
                background-color: transparent;
                border: none;
            }

            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 8px;
                border-radius: 4px;
            }

            QScrollBar::handle:vertical {
                background-color: #3d3d3d;
                border-radius: 4px;
                min-height: 20px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #505050;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

    def _rebuild_calendar_grid(self) -> None:
        """Rebuild the calendar grid for the current month."""
        # Clear existing cells
        for cell in self._day_cells:
            cell.setParent(None)
            cell.deleteLater()
        self._day_cells.clear()

        # Get calendar data for the month
        cal = calendar.Calendar(firstweekday=6)  # Sunday first
        month_days = cal.monthdatescalendar(self._current_year, self._current_month)

        # Build grid
        for row, week in enumerate(month_days):
            for col, day_date in enumerate(week):
                is_current_month = day_date.month == self._current_month
                cell = DayCell(day_date, is_current_month)
                cell.clicked.connect(self._on_day_clicked)

                # Set recording count if available
                date_str = day_date.isoformat()
                recordings = self._recordings_cache.get(date_str, [])
                cell.set_recording_count(len(recordings))

                # Mark selected
                if self._selected_date and day_date == self._selected_date:
                    cell.set_selected(True)

                self._grid_layout.addWidget(cell, row, col)
                self._day_cells.append(cell)

        # Make rows stretch equally
        for row in range(len(month_days)):
            self._grid_layout.setRowStretch(row, 1)
        for col in range(7):
            self._grid_layout.setColumnStretch(col, 1)

    def _update_title(self) -> None:
        """Update the title based on current view mode."""
        if self._view_mode == "month":
            month_name = calendar.month_name[self._current_month]
            self._title_label.setText(f"{month_name} {self._current_year}")
        else:
            if self._selected_date:
                self._title_label.setText(self._selected_date.strftime("%A, %b %d"))

    def _on_day_clicked(self, clicked_date: date) -> None:
        """Handle day cell click."""
        # Update selection
        for cell in self._day_cells:
            cell.set_selected(cell._date == clicked_date)

        self._selected_date = clicked_date

        # Switch to day view
        self._show_day_view()

    def _show_month_view(self) -> None:
        """Switch to month view."""
        self._view_mode = "month"
        self._stack.setCurrentIndex(0)
        self._back_btn.hide()
        self._update_title()

    def _show_day_view(self) -> None:
        """Switch to day view for selected date."""
        self._view_mode = "day"
        self._stack.setCurrentIndex(1)
        self._back_btn.show()
        self._update_title()
        self._update_day_view()

    def _update_day_view(self) -> None:
        """Update day view with recordings for the selected date."""
        if not self._selected_date:
            return

        date_str = self._selected_date.isoformat()
        recordings = self._recordings_cache.get(date_str, [])

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

        # TODO: Update time slot widgets with recording cards

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
            # Don't go past current month
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
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._load_month_recordings())
            else:
                loop.run_until_complete(self._load_month_recordings())
        except RuntimeError:
            asyncio.run(self._load_month_recordings())

    async def _load_month_recordings(self) -> None:
        """Load recordings for the current month."""
        if self._api_client is None:
            logger.warning("API client not available")
            return

        try:
            # Calculate date range
            first_of_month = date(self._current_year, self._current_month, 1)
            if self._current_month == 12:
                last_of_month = date(self._current_year + 1, 1, 1) - timedelta(days=1)
            else:
                last_of_month = date(
                    self._current_year, self._current_month + 1, 1
                ) - timedelta(days=1)

            # Extend range to cover the full calendar view
            start_date = first_of_month - timedelta(days=7)
            end_date = last_of_month + timedelta(days=7)

            # Fetch recordings
            recordings_data = await self._api_client.get_recordings(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

            # Parse and cache recordings by date
            self._recordings_cache.clear()
            for rec_data in recordings_data:
                recording = Recording.from_dict(rec_data)
                rec_date = recording.recorded_at[:10]  # YYYY-MM-DD
                if rec_date not in self._recordings_cache:
                    self._recordings_cache[rec_date] = []
                self._recordings_cache[rec_date].append(recording)

            # Update calendar display
            self._update_calendar_highlights()

            logger.debug(
                f"Loaded {len(recordings_data)} recordings for {start_date} to {end_date}"
            )

        except Exception as e:
            logger.error(f"Failed to load recordings: {e}")

    def _update_calendar_highlights(self) -> None:
        """Update day cells with recording counts."""
        for cell in self._day_cells:
            if cell._date:
                date_str = cell._date.isoformat()
                recordings = self._recordings_cache.get(date_str, [])
                cell.set_recording_count(len(recordings))

    def refresh(self) -> None:
        """Refresh the calendar data."""
        self._rebuild_calendar_grid()
        self._schedule_refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._schedule_refresh()
