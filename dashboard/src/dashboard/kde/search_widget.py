"""
Search widget for Audio Notebook.

Provides full-text search across transcriptions with filtering options.
"""

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.models import SearchResult

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class SearchWidget(QWidget):
    """
    Search interface for Audio Notebook.

    Provides full-text search with options for fuzzy matching
    and date range filtering.
    """

    # Signal emitted when a recording is selected (with optional timestamp)
    recording_requested = pyqtSignal(int)  # recording_id

    def __init__(
        self,
        api_client: "APIClient",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client

        # Debounce timer for search
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)  # 300ms debounce
        self._search_timer.timeout.connect(self._perform_search)

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self) -> None:
        """Set up the search widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Search input section
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(12)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("searchInput")
        self._search_input.setPlaceholderText("Search transcriptions...")
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(self._perform_search)
        search_layout.addWidget(self._search_input, 1)

        self._search_btn = QPushButton("Search")
        self._search_btn.setObjectName("primaryButton")
        self._search_btn.clicked.connect(self._perform_search)
        search_layout.addWidget(self._search_btn)

        layout.addWidget(search_container)

        # Filters section
        filters_container = QFrame()
        filters_container.setObjectName("filtersCard")
        filters_layout = QHBoxLayout(filters_container)
        filters_layout.setContentsMargins(16, 12, 16, 12)
        filters_layout.setSpacing(20)

        # Fuzzy search toggle
        self._fuzzy_checkbox = QCheckBox("Fuzzy matching")
        self._fuzzy_checkbox.setObjectName("filterCheckbox")
        self._fuzzy_checkbox.setToolTip("Enable fuzzy matching to find similar words")
        filters_layout.addWidget(self._fuzzy_checkbox)

        filters_layout.addWidget(self._create_separator())

        # Date range filters
        date_label = QLabel("Date range:")
        date_label.setObjectName("filterLabel")
        filters_layout.addWidget(date_label)

        self._from_date = QDateEdit()
        self._from_date.setObjectName("dateInput")
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("yyyy-MM-dd")
        self._from_date.setDate(date.today().replace(month=1, day=1))  # Start of year
        self._from_date.setSpecialValueText("Any")
        filters_layout.addWidget(self._from_date)

        to_label = QLabel("to")
        to_label.setObjectName("filterLabel")
        filters_layout.addWidget(to_label)

        self._to_date = QDateEdit()
        self._to_date.setObjectName("dateInput")
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("yyyy-MM-dd")
        self._to_date.setDate(date.today())
        self._to_date.setSpecialValueText("Any")
        filters_layout.addWidget(self._to_date)

        self._clear_dates_btn = QPushButton("Clear dates")
        self._clear_dates_btn.setObjectName("secondaryButton")
        self._clear_dates_btn.clicked.connect(self._clear_date_filters)
        filters_layout.addWidget(self._clear_dates_btn)

        filters_layout.addStretch()

        layout.addWidget(filters_container)

        # Results section
        results_header = QWidget()
        results_header_layout = QHBoxLayout(results_header)
        results_header_layout.setContentsMargins(0, 0, 0, 0)

        self._results_label = QLabel("Enter a search term to begin")
        self._results_label.setObjectName("resultsLabel")
        results_header_layout.addWidget(self._results_label)
        results_header_layout.addStretch()

        layout.addWidget(results_header)

        # Results list
        self._results_list = QListWidget()
        self._results_list.setObjectName("resultsList")
        self._results_list.itemDoubleClicked.connect(self._on_result_double_clicked)
        layout.addWidget(self._results_list, 1)

    def _create_separator(self) -> QFrame:
        """Create a vertical separator line."""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background-color: #3d3d3d;")
        return separator

    def _apply_styles(self) -> None:
        """Apply styling to search components."""
        self.setStyleSheet("""
            #searchInput {
                background-color: #1e1e1e;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: #ffffff;
                padding: 10px 14px;
                font-size: 14px;
            }

            #searchInput:focus {
                border-color: #0AFCCF;
            }

            #searchInput::placeholder {
                color: #6c757d;
            }

            #filtersCard {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }

            #filterLabel {
                color: #a0a0a0;
                font-size: 13px;
            }

            #filterCheckbox {
                color: #e0e0e0;
                font-size: 13px;
            }

            #filterCheckbox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #3d3d3d;
                border-radius: 3px;
                background-color: #1e1e1e;
            }

            #filterCheckbox::indicator:checked {
                background-color: #0AFCCF;
                border-color: #0AFCCF;
            }

            #dateInput {
                background-color: #1e1e1e;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px 10px;
                font-size: 12px;
            }

            #dateInput:focus {
                border-color: #0AFCCF;
            }

            #resultsLabel {
                color: #a0a0a0;
                font-size: 13px;
            }

            #resultsList {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                padding: 4px;
            }

            #resultsList::item {
                padding: 12px;
                border-bottom: 1px solid #2d2d2d;
                border-radius: 4px;
                margin: 2px;
            }

            #resultsList::item:selected {
                background-color: #1e2a3a;
                border: 1px solid #0AFCCF;
            }

            #resultsList::item:hover:!selected {
                background-color: #2d2d2d;
            }

            #primaryButton {
                background-color: #0AFCCF;
                border: none;
                border-radius: 6px;
                color: #141414;
                padding: 10px 20px;
                font-weight: 500;
            }

            #primaryButton:hover {
                background-color: #08d9b3;
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
                padding: 8px 16px;
            }

            #secondaryButton:hover {
                background-color: #3d3d3d;
            }
        """)

    def _on_search_text_changed(self, text: str) -> None:
        """Handle search text changes with debouncing."""
        if len(text) >= 2:
            self._search_timer.start()
        elif len(text) == 0:
            self._results_list.clear()
            self._results_label.setText("Enter a search term to begin")

    def _perform_search(self) -> None:
        """Execute the search."""
        query = self._search_input.text().strip()
        if len(query) < 2:
            return

        # Schedule async search
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._do_search(query))
            else:
                loop.run_until_complete(self._do_search(query))
        except RuntimeError:
            asyncio.run(self._do_search(query))

    async def _do_search(self, query: str) -> None:
        """Perform the actual search request."""
        if self._api_client is None:
            self._results_label.setText("Not connected to server")
            return

        try:
            self._results_label.setText("Searching...")
            self._results_list.clear()

            # Get filter values
            fuzzy = self._fuzzy_checkbox.isChecked()

            # Get date range if set
            from_date = self._from_date.date()
            to_date = self._to_date.date()

            start_date = (
                date(from_date.year(), from_date.month(), from_date.day()).isoformat()
                if from_date.isValid()
                else None
            )
            end_date = (
                date(to_date.year(), to_date.month(), to_date.day()).isoformat()
                if to_date.isValid()
                else None
            )

            # Perform search
            results_data = await self._api_client.search(
                query=query,
                fuzzy=fuzzy,
                start_date=start_date,
                end_date=end_date,
                limit=100,
            )

            # Parse results
            results = results_data.get("results", [])

            if not results:
                self._results_label.setText(f"No results found for '{query}'")
                return

            # Display results
            self._results_label.setText(f"Found {len(results)} result(s)")

            for result_data in results:
                result = SearchResult.from_dict(result_data)
                self._add_result_item(result)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            self._results_label.setText(f"Search failed: {str(e)}")

    def _add_result_item(self, result: SearchResult) -> None:
        """Add a search result to the list."""
        item = QListWidgetItem()

        # Get recording info
        recording = result.recording
        if recording:
            title = recording.title or recording.filename
            # Format date
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

        # Format timestamp
        minutes = int(result.start_time // 60)
        seconds = int(result.start_time % 60)
        timestamp = f"{minutes}:{seconds:02d}"

        # Match type badge
        match_type_display = {
            "word": "[Word]",
            "filename": "[Filename]",
            "summary": "[Summary]",
        }.get(result.match_type, "[Match]")

        # Create display text
        display_text = f"{match_type_display}  {title}\n"
        display_text += f"{date_str}  •  at {timestamp}\n"
        if result.context:
            # Truncate context if too long
            context = result.context
            if len(context) > 100:
                context = context[:97] + "..."
            display_text += f'"{context}"'

        item.setText(display_text)
        item.setData(Qt.ItemDataRole.UserRole, result.recording_id)
        item.setData(Qt.ItemDataRole.UserRole + 1, result.start_time)

        self._results_list.addItem(item)

    def _clear_date_filters(self) -> None:
        """Clear the date filter inputs."""
        self._from_date.setDate(date.today().replace(month=1, day=1))
        self._to_date.setDate(date.today())

    def _on_result_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle double-click on a search result."""
        recording_id = item.data(Qt.ItemDataRole.UserRole)
        if recording_id:
            # TODO: Pass timestamp to recording dialog
            self.recording_requested.emit(recording_id)

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
