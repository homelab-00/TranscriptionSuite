"""
Audio Notebook view for KDE Dashboard.

Provides a tabbed interface with Calendar, Search, and Import sub-tabs
for managing audio recordings and transcriptions.
"""

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dashboard.kde.calendar_widget import CalendarWidget
from dashboard.kde.import_widget import ImportWidget
from dashboard.kde.search_widget import SearchWidget

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class NotebookView(QWidget):
    """
    Main Audio Notebook view with tabbed interface.

    Contains three sub-tabs:
    - Calendar: Browse recordings by date
    - Search: Full-text search across transcriptions
    - Import: Upload and transcribe audio files
    """

    # Signal emitted when a recording should be opened
    recording_requested = pyqtSignal(int)  # recording_id

    def __init__(
        self,
        api_client: "APIClient",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the notebook view UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header section
        header = QWidget()
        header.setObjectName("notebookHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)

        title = QLabel("Audio Notebook")
        title.setObjectName("viewTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addWidget(header)

        # Tab widget for sub-tabs
        self._tabs = QTabWidget()
        self._tabs.setObjectName("notebookTabs")
        self._tabs.setDocumentMode(True)

        # Create sub-tab widgets
        self._calendar_widget = CalendarWidget(self._api_client)
        self._search_widget = SearchWidget(self._api_client)
        self._import_widget = ImportWidget(self._api_client)

        # Add tabs
        self._tabs.addTab(self._calendar_widget, "Calendar")
        self._tabs.addTab(self._search_widget, "Search")
        self._tabs.addTab(self._import_widget, "Import")

        # Connect signals
        self._calendar_widget.recording_requested.connect(self._on_recording_requested)
        self._search_widget.recording_requested.connect(self._on_recording_requested)
        self._import_widget.recording_created.connect(self._on_import_complete)

        layout.addWidget(self._tabs, 1)

        # Apply tab styling
        self._apply_tab_styles()

    def _apply_tab_styles(self) -> None:
        """Apply consistent styling to the tab widget."""
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #0a0a0a;
            }

            QTabBar::tab {
                background-color: #1e1e1e;
                color: #a0a0a0;
                padding: 10px 20px;
                border: none;
                border-bottom: 2px solid transparent;
                font-size: 13px;
                min-width: 80px;
            }

            QTabBar::tab:selected {
                color: #90caf9;
                border-bottom: 2px solid #90caf9;
                background-color: #1e1e1e;
            }

            QTabBar::tab:hover:!selected {
                color: #ffffff;
                background-color: #2d2d2d;
            }
        """)

    def _on_recording_requested(self, recording_id: int) -> None:
        """Handle request to open a recording."""
        logger.debug(f"Recording requested: {recording_id}")
        self.recording_requested.emit(recording_id)

    def _on_import_complete(self, recording_id: int) -> None:
        """Handle import completion - refresh calendar and open recording."""
        logger.info(f"Import complete, recording ID: {recording_id}")
        # Refresh calendar to show new recording
        self._calendar_widget.refresh()
        # Emit signal to open the recording
        self.recording_requested.emit(recording_id)

    def refresh(self) -> None:
        """Refresh all notebook data."""
        current_index = self._tabs.currentIndex()
        if current_index == 0:
            self._calendar_widget.refresh()
        elif current_index == 1:
            # Search doesn't need refresh, user triggers it
            pass
        elif current_index == 2:
            # Import doesn't need refresh
            pass

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._calendar_widget.set_api_client(api_client)
        self._search_widget.set_api_client(api_client)
        self._import_widget.set_api_client(api_client)
