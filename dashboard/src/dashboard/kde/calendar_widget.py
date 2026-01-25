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

from pathlib import Path

from PyQt6.QtCore import QDate, QLocale, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
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
        self._is_future = day_date > date.today() if day_date else False
        self._recording_count = 0

        self.setObjectName("dayCell")
        if not self._is_future:
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
        if self._is_future:
            self.setProperty("state", "future")
        elif self._is_selected:
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
        if self._date and not self._is_future:
            self.clicked.emit(self._date)
        super().mousePressEvent(event)


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


class DayViewDropZone(QFrame):
    """Drag-and-drop zone for day view import dialog."""

    files_dropped = pyqtSignal(list)  # List of file paths

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dayViewDropZone")
        self._file_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        # Upload icon
        self._icon_label = QLabel("⬆")
        self._icon_label.setObjectName("dropIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._text_label = QLabel("Drag audio file here")
        self._text_label.setObjectName("dropText")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._text_label)

        self._formats_label = QLabel("Supported: MP3, WAV, M4A, FLAC, OGG, and more")
        self._formats_label.setObjectName("dropFormats")
        self._formats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._formats_label)

        # Enable click cursor
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        """Handle click to open file browser."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_file_browser()
        super().mousePressEvent(event)

    def _open_file_browser(self) -> None:
        """Open file browser dialog."""
        extensions = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            "",
            f"Audio Files ({extensions});;All Files (*)",
        )

        if file_path:
            path_obj = Path(file_path)
            self._file_path = path_obj
            self._update_display()
            self.files_dropped.emit([path_obj])

    def dragEnterEvent(self, event) -> None:
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragOver", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:
        """Handle drag leave event."""
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event) -> None:
        """Handle drop event."""
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                self._file_path = file_path
                self._update_display()
                self.files_dropped.emit([file_path])
                break  # Only accept one file

    def _update_display(self) -> None:
        """Update display to show selected file."""
        if self._file_path:
            self._icon_label.setText("🎵")
            self._text_label.setText(self._file_path.name)
            self._formats_label.setText("Drop another file to replace")

    def get_file_path(self) -> Path | None:
        """Get the currently selected file path."""
        return self._file_path

    def clear(self) -> None:
        """Clear the selected file."""
        self._file_path = None
        self._icon_label.setText("⬆")
        self._text_label.setText("Drag audio file here")
        self._formats_label.setText("Supported: MP3, WAV, M4A, FLAC, OGG, and more")


class DayViewImportDialog(QDialog):
    """
    Import dialog for adding audio entries from the day view.

    This dialog provides a simplified import experience without the queue UI,
    allowing users to drag-and-drop a single file and set transcription options.
    """

    transcription_complete = pyqtSignal(int)  # recording_id

    def __init__(
        self,
        api_client: "APIClient",
        target_date: date,
        hour: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client
        self._target_date = target_date
        self._hour = hour
        self._is_transcribing = False

        self.setWindowTitle("Add Audio Entry")
        self.setMinimumWidth(450)
        self.setMinimumHeight(380)

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header with date/time info
        time_str = self._format_time(self._hour)
        date_str = self._target_date.strftime("%B %d, %Y")
        header_label = QLabel(f"Adding entry for {date_str} at {time_str}")
        header_label.setObjectName("dialogHeader")
        layout.addWidget(header_label)

        # Drop zone
        self._drop_zone = DayViewDropZone()
        self._drop_zone.setMinimumHeight(140)
        self._drop_zone.files_dropped.connect(self._on_file_dropped)
        layout.addWidget(self._drop_zone)

        # Options section
        options_container = QFrame()
        options_container.setObjectName("optionsCard")
        options_layout = QVBoxLayout(options_container)
        options_layout.setContentsMargins(16, 12, 16, 12)
        options_layout.setSpacing(12)

        options_label = QLabel("Transcription Options:")
        options_label.setObjectName("optionsLabel")
        options_layout.addWidget(options_label)

        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setSpacing(24)

        self._diarization_checkbox = QCheckBox("Speaker diarization")
        self._diarization_checkbox.setObjectName("optionCheckbox")
        self._diarization_checkbox.setChecked(True)
        self._diarization_checkbox.setToolTip(
            "Identify and label different speakers in the audio"
        )
        checkboxes_layout.addWidget(self._diarization_checkbox)

        self._word_timestamps_checkbox = QCheckBox("Word-level timestamps")
        self._word_timestamps_checkbox.setObjectName("optionCheckbox")
        self._word_timestamps_checkbox.setChecked(True)
        self._word_timestamps_checkbox.setToolTip(
            "Include precise timestamps for each word"
        )
        checkboxes_layout.addWidget(self._word_timestamps_checkbox)

        checkboxes_layout.addStretch()
        options_layout.addLayout(checkboxes_layout)

        layout.addWidget(options_container)

        # Progress section (hidden by default)
        self._progress_container = QWidget()
        progress_layout = QVBoxLayout(self._progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)

        self._status_label = QLabel("")
        self._status_label.setObjectName("statusLabel")
        progress_layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("importProgress")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        progress_layout.addWidget(self._progress_bar)

        self._progress_container.hide()
        layout.addWidget(self._progress_container)

        layout.addStretch()

        # Button row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("secondaryButton")
        self._cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self._cancel_btn)

        button_layout.addStretch()

        self._transcribe_btn = QPushButton("Transcribe")
        self._transcribe_btn.setObjectName("primaryButton")
        self._transcribe_btn.setEnabled(False)
        self._transcribe_btn.clicked.connect(self._start_transcription)
        button_layout.addWidget(self._transcribe_btn)

        layout.addLayout(button_layout)

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

    def _apply_styles(self) -> None:
        """Apply styling to dialog components."""
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
            }

            #dialogHeader {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }

            #dayViewDropZone {
                background-color: #1e1e1e;
                border: 2px dashed #3d3d3d;
                border-radius: 12px;
                padding: 20px;
            }

            #dayViewDropZone[dragOver="true"] {
                border-color: #90caf9;
                background-color: #1e2a3a;
            }

            #dropIcon {
                font-size: 36px;
                color: #ffffff;
            }

            #dropText {
                color: #a0a0a0;
                font-size: 13px;
                margin-top: 8px;
            }

            #dropFormats {
                color: #606060;
                font-size: 11px;
                margin-top: 4px;
            }

            #optionsCard {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }

            #optionsLabel {
                color: #a0a0a0;
                font-size: 13px;
                font-weight: bold;
            }

            #optionCheckbox {
                color: #e0e0e0;
                font-size: 13px;
            }

            #optionCheckbox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #3d3d3d;
                border-radius: 3px;
                background-color: #1e1e1e;
            }

            #optionCheckbox::indicator:checked {
                background-color: #90caf9;
                border-color: #90caf9;
            }

            #statusLabel {
                color: #a0a0a0;
                font-size: 13px;
            }

            #importProgress {
                background-color: #2d2d2d;
                border: none;
                border-radius: 4px;
                height: 8px;
            }

            #importProgress::chunk {
                background-color: #90caf9;
                border-radius: 4px;
            }

            #primaryButton {
                background-color: #1e88e5;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 13px;
            }

            #primaryButton:hover {
                background-color: #2196f3;
            }

            #primaryButton:disabled {
                background-color: #2d2d2d;
                color: #606060;
            }

            #secondaryButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: #ffffff;
                padding: 10px 24px;
                font-size: 13px;
            }

            #secondaryButton:hover {
                background-color: #3d3d3d;
            }
        """)

    def _on_file_dropped(self, files: list[Path]) -> None:
        """Handle file being dropped."""
        if files:
            self._transcribe_btn.setEnabled(True)

    def _start_transcription(self) -> None:
        """Start the transcription process."""
        file_path = self._drop_zone.get_file_path()
        if not file_path:
            return

        self._is_transcribing = True
        self._transcribe_btn.setEnabled(False)
        self._cancel_btn.setText("Close")
        self._progress_container.show()
        self._status_label.setText("Starting transcription...")
        self._progress_bar.setValue(0)

        # Build target datetime
        target_datetime = datetime(
            self._target_date.year,
            self._target_date.month,
            self._target_date.day,
            self._hour,
            0,
            0,
        ).isoformat()

        # Start async upload
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._upload_file(file_path, target_datetime))
            else:
                loop.run_until_complete(self._upload_file(file_path, target_datetime))
        except RuntimeError:
            asyncio.run(self._upload_file(file_path, target_datetime))

    async def _upload_file(self, file_path: Path, recorded_at: str) -> None:
        """Upload and transcribe the file."""
        if self._api_client is None:
            self._status_label.setText("Error: Not connected to server")
            self._is_transcribing = False
            return

        try:
            def on_progress(message: str) -> None:
                """Handle progress updates."""
                self._status_label.setText(message)
                if "uploading" in message.lower():
                    self._progress_bar.setValue(20)
                elif "transcribing" in message.lower():
                    self._progress_bar.setValue(50)
                elif "complete" in message.lower():
                    self._progress_bar.setValue(100)

            result = await self._api_client.upload_file_to_notebook(
                file_path=file_path,
                diarization=self._diarization_checkbox.isChecked(),
                word_timestamps=self._word_timestamps_checkbox.isChecked(),
                recorded_at=recorded_at,
                on_progress=on_progress,
            )

            recording_id = result.get("id") or result.get("recording_id")
            self._progress_bar.setValue(100)
            self._status_label.setText("Transcription complete!")

            logger.info(f"Day view import complete: {file_path.name} -> ID {recording_id}")

            if recording_id:
                self.transcription_complete.emit(recording_id)

            # Auto-close after brief delay
            QTimer.singleShot(1000, self.accept)

        except Exception as e:
            logger.error(f"Day view import failed for {file_path.name}: {e}")
            self._status_label.setText(f"Error: {e}")
            self._is_transcribing = False


class CalendarWidget(QWidget):
    """
    Calendar-based recording browser with month and day views.

    Shows a monthly calendar grid with visual indicators for days that have recordings,
    and a day view with hourly time slots when a date is selected.
    """

    recording_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)  # recording_id
    change_date_requested = pyqtSignal(int)  # recording_id

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
        self._time_slots: dict[int, dict] = {}  # hour -> {slot, dot, add_btn}
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

        # Afternoon section (12 PM - 11 PM)
        afternoon = self._create_time_section("Afternoon", range(12, 24))
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

    def _create_time_slot(self, hour: int) -> QFrame:
        """Create a single time slot row."""
        slot = QFrame()
        slot.setObjectName("timeSlot")
        slot.setMinimumHeight(72)
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

        # Scrollable recordings container (for this hour)
        recordings_scroll = QScrollArea()
        recordings_scroll.setObjectName(f"recordings_scroll_{hour}")
        recordings_scroll.setWidgetResizable(True)
        recordings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        recordings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        recordings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        recordings_container = QWidget()
        recordings_container.setObjectName(f"recordings_{hour}")
        recordings_layout = QHBoxLayout(recordings_container)
        recordings_layout.setContentsMargins(0, 0, 0, 0)
        recordings_layout.setSpacing(8)

        recordings_layout.addStretch()

        # Add button at the END - hidden by default, shown on hover
        add_btn = QPushButton("+")
        add_btn.setObjectName("addButton")
        add_btn.setFixedSize(28, 28)
        add_btn.setToolTip("Import recording for this time")
        add_btn.clicked.connect(lambda checked, h=hour: self._on_add_clicked(h))
        add_btn.hide()  # Hidden by default, shown on hover
        recordings_layout.addWidget(add_btn)
        
        recordings_scroll.setWidget(recordings_container)
        layout.addWidget(recordings_scroll, 1)

        # Install event filter on slot for hover detection
        slot.enterEvent = lambda e, h=hour: self._on_slot_enter(h)
        slot.leaveEvent = lambda e, h=hour: self._on_slot_leave(h)

        # Store references for later updates
        self._time_slots[hour] = {
            "slot": slot,
            "add_btn": add_btn,
            "recordings_layout": recordings_layout,
            "recording_widgets": [],  # Track recording widgets for cleanup
        }

        return slot

    def _on_slot_enter(self, hour: int) -> None:
        """Show add button when mouse enters time slot."""
        slot_info = self._time_slots.get(hour)
        if slot_info and slot_info["add_btn"].isEnabled():
            slot_info["add_btn"].show()

    def _on_slot_leave(self, hour: int) -> None:
        """Hide add button when mouse leaves time slot."""
        slot_info = self._time_slots.get(hour)
        if slot_info:
            slot_info["add_btn"].hide()

    def _on_add_clicked(self, hour: int) -> None:
        """Handle add button click for a time slot - show import dialog."""
        if self._selected_date:
            dialog = DayViewImportDialog(
                api_client=self._api_client,
                target_date=self._selected_date,
                hour=hour,
                parent=self,
            )
            dialog.transcription_complete.connect(self._on_day_view_import_complete)
            dialog.exec()

    def _on_day_view_import_complete(self, recording_id: int) -> None:
        """Handle completion of a day view import - refresh calendar."""
        logger.info(f"Day view import complete, recording ID: {recording_id}")
        self.refresh()

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

            #dayCell[state="future"] {
                background-color: #0d0d1a;
                cursor: default;
            }

            #dayCell[state="future"] #dayNumber {
                color: #404040;
            }

            #dayCell[state="future"]:hover {
                background-color: #0d0d1a;
                border-color: #2d2d2d;
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

            #addButton {
                background-color: transparent;
                border: 1px dashed #3d3d3d;
                border-radius: 4px;
                color: #606060;
                font-size: 16px;
            }

            #addButton:hover {
                background-color: #2d2d2d;
                border-color: #90caf9;
                color: #90caf9;
            }

            #addButton:disabled {
                color: #404040;
                border-color: #2d2d2d;
            }

            /* Recording card in day view */
            #recordingCard {
                background-color: #1e2a3a;
                border: 1px solid #2d4a6d;
                border-radius: 8px;
                min-width: 180px;
            }

            #recordingCard:hover {
                background-color: #263a4f;
                border-color: #90caf9;
            }

            #cardTitle {
                color: #ffffff;
                font-size: 13px;
                font-weight: 500;
            }

            #cardInfo {
                color: #808080;
                font-size: 11px;
            }

            #cardDuration {
                color: #a0a0a0;
                font-size: 11px;
            }

            #diarizationBadge {
                background-color: #1e3a5f;
                border: 1px solid #4a90d9;
                border-radius: 4px;
                color: #90caf9;
                font-size: 10px;
                padding: 2px 6px;
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

            /* Horizontal scrollbar for recording cards */
            QScrollArea[objectName^="recordings_scroll_"] {
                background-color: transparent;
                border: none;
            }

            QScrollBar:horizontal {
                background-color: transparent;
                height: 6px;
                margin: 0;
            }

            QScrollBar::handle:horizontal {
                background-color: rgba(61, 61, 61, 0.6);
                border-radius: 3px;
                min-width: 20px;
            }

            QScrollBar::handle:horizontal:hover {
                background-color: rgba(80, 80, 80, 0.8);
            }

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }

            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
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
            recordings_layout = slot_info["recordings_layout"]

            # Clear existing recording widgets
            for widget in slot_info["recording_widgets"]:
                recordings_layout.removeWidget(widget)
                widget.deleteLater()
            slot_info["recording_widgets"] = []

            # Add recording cards for this hour
            hour_recordings = recordings_by_hour.get(hour, [])
            for rec in hour_recordings:
                card = self._create_recording_card(rec)
                # Insert at position 0 (before stretch and add button)
                recordings_layout.insertWidget(0, card)
                slot_info["recording_widgets"].append(card)

            # Disable add button for future time slots
            is_future = self._selected_date > today or (
                self._selected_date == today and hour > now.hour
            )
            add_btn.setEnabled(not is_future)
            if is_future:
                add_btn.setToolTip("Cannot import to future time slots")
            else:
                add_btn.setToolTip("Import recording for this time")

    def _create_recording_card(self, rec: Recording) -> QFrame:
        """Create a card widget for a recording entry."""
        card = QFrame()
        card.setObjectName("recordingCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Top row: title + diarization badge
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        title = rec.title or rec.filename or "Recording"
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        top_layout.addWidget(title_label)
        top_layout.addStretch()

        # Diarization badge top-right
        if rec.has_diarization:
            diar_badge = QLabel("Diarization")
            diar_badge.setObjectName("diarizationBadge")
            top_layout.addWidget(diar_badge)

        layout.addLayout(top_layout)

        # Bottom row: time (left) and duration (right)
        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(12)

        # Time (e.g., "12:01 AM")
        try:
            rec_dt = datetime.fromisoformat(rec.recorded_at.replace("Z", "+00:00"))
            time_str = rec_dt.strftime("%I:%M %p").lstrip("0")
        except (ValueError, AttributeError):
            time_str = ""
        time_label = QLabel(f"● {time_str}")
        time_label.setObjectName("cardInfo")
        info_layout.addWidget(time_label)

        info_layout.addStretch()

        # Duration right-aligned
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
        duration_label = QLabel(duration_str)
        duration_label.setObjectName("cardDuration")
        info_layout.addWidget(duration_label)

        layout.addLayout(info_layout)

        # Left-click opens recording, right-click shows context menu
        def on_mouse_press(event, rid=rec.id):
            if event.button() == Qt.MouseButton.LeftButton:
                self.recording_requested.emit(rid)

        card.mousePressEvent = on_mouse_press

        # Context menu for right-click
        def show_context_menu(pos, rid=rec.id):
            menu = QMenu(card)
            menu.setStyleSheet("""
                QMenu {
                    background-color: #2d2d2d;
                    border: 1px solid #3d3d3d;
                    border-radius: 4px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 8px 24px;
                    color: #e0e0e0;
                }
                QMenu::item:selected {
                    background-color: #3d3d3d;
                }
            """)

            change_date_action = QAction("Change date && time", menu)
            change_date_action.triggered.connect(
                lambda: self.change_date_requested.emit(rid)
            )
            menu.addAction(change_date_action)

            delete_action = QAction("Delete note", menu)
            delete_action.triggered.connect(lambda: self.delete_requested.emit(rid))
            menu.addAction(delete_action)

            menu.exec(card.mapToGlobal(pos))

        card.customContextMenuRequested.connect(show_context_menu)

        return card

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
        """Update day cells with recording counts and refresh day view if active."""
        for cell in self._day_cells:
            if cell._date:
                date_str = cell._date.isoformat()
                recordings = self._recordings_cache.get(date_str, [])
                cell.set_recording_count(len(recordings))

        # Also refresh day view if currently visible
        if self._view_mode == "day" and self._selected_date:
            self._update_day_view()

    def refresh(self) -> None:
        """Refresh the calendar data."""
        self._rebuild_calendar_grid()
        self._schedule_refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._schedule_refresh()
