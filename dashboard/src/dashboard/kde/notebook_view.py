"""
Audio Notebook view for KDE Dashboard.

Provides a tabbed interface with Calendar, Search, and Import sub-tabs
for managing audio recordings and transcriptions.
"""

import logging
from typing import TYPE_CHECKING

import asyncio

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
        self._calendar_widget.delete_requested.connect(self._on_delete_requested)
        self._calendar_widget.change_date_requested.connect(
            self._on_change_date_requested
        )
        self._calendar_widget.export_requested.connect(self._on_export_requested)
        self._search_widget.recording_requested.connect(self._on_recording_requested)
        self._import_widget.recording_created.connect(self._on_import_complete)

        layout.addWidget(self._tabs, 1)

        # Apply tab styling
        self._apply_tab_styles()

    def _apply_tab_styles(self) -> None:
        """Apply consistent styling to the tab widget."""
        self.setStyleSheet("""
            #notebookHeader {
                background-color: #141414;
                border-bottom: 1px solid #2d2d2d;
            }

            #viewTitle {
                color: #ffffff;
                font-size: 18px;
                font-weight: bold;
            }
        """)

        # Hide the tab bar - tabs are now accessed via sidebar submenu
        self._tabs.tabBar().setVisible(False)
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #141414;
            }
        """)

    def _on_recording_requested(self, recording_id: int) -> None:
        """Handle request to open a recording."""
        logger.debug(f"Recording requested: {recording_id}")
        self.recording_requested.emit(recording_id)

    def _on_import_complete(self, recording_id: int) -> None:
        """Handle import completion - refresh calendar (don't auto-open)."""
        logger.info(f"Import complete, recording ID: {recording_id}")
        # Refresh calendar to show new recording
        self._calendar_widget.refresh()
        # Don't auto-open the recording - let user review queue first

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

    def remove_recording_from_cache(self, recording_id: int) -> None:
        """Remove a recording from the calendar cache and update UI immediately."""
        self._calendar_widget.remove_recording_from_cache(recording_id)

    def update_recording_in_cache(self, recording_id: int, title: str) -> None:
        """Update a recording's title in the calendar cache and update UI immediately."""
        self._calendar_widget.update_recording_in_cache(recording_id, title)

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._calendar_widget.set_api_client(api_client)
        self._search_widget.set_api_client(api_client)
        self._import_widget.set_api_client(api_client)

    def set_tab(self, index: int) -> None:
        """Set the active tab by index."""
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    def _on_delete_requested(self, recording_id: int) -> None:
        """Handle delete request from calendar."""
        reply = QMessageBox.question(
            self,
            "Delete Recording",
            "Are you sure you want to delete this recording?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._delete_recording(recording_id))
                else:
                    loop.run_until_complete(self._delete_recording(recording_id))
            except RuntimeError:
                asyncio.run(self._delete_recording(recording_id))

    async def _delete_recording(self, recording_id: int) -> None:
        """Delete a recording and refresh the view."""
        try:
            await self._api_client.delete_recording(recording_id)
            logger.info(f"Deleted recording {recording_id}")
            # Remove from cache immediately and update UI
            self._calendar_widget.remove_recording_from_cache(recording_id)
            self._calendar_widget.refresh()
        except Exception as e:
            logger.error(f"Failed to delete recording: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to delete recording: {e}",
            )

    def _on_change_date_requested(self, recording_id: int) -> None:
        """Handle change date request from calendar."""
        from PyQt6.QtCore import QDateTime

        dialog = QDialog(self)
        dialog.setWindowTitle("Change Date & Time")
        dialog.setMinimumWidth(300)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
            }
            QLabel {
                color: #e0e0e0;
                font-size: 13px;
            }
            QDateTimeEdit {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #e0e0e0;
                padding: 8px;
                font-size: 13px;
            }
            QDateTimeEdit::drop-down {
                border: none;
                width: 20px;
            }
            QPushButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #e0e0e0;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QPushButton:default {
                background-color: #1e3a5f;
                border-color: #2d4a6d;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        label = QLabel("Select new date and time:")
        layout.addWidget(label)

        datetime_edit = QDateTimeEdit()
        datetime_edit.setDateTime(QDateTime.currentDateTime())
        datetime_edit.setCalendarPopup(True)
        datetime_edit.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        layout.addWidget(datetime_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_datetime = datetime_edit.dateTime().toPyDateTime()
            new_datetime_iso = new_datetime.isoformat()
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        self._update_recording_date(recording_id, new_datetime_iso)
                    )
                else:
                    loop.run_until_complete(
                        self._update_recording_date(recording_id, new_datetime_iso)
                    )
            except RuntimeError:
                asyncio.run(self._update_recording_date(recording_id, new_datetime_iso))

    async def _update_recording_date(self, recording_id: int, new_date: str) -> None:
        """Update a recording's date and refresh the view."""
        try:
            await self._api_client.update_recording_date(recording_id, new_date)
            logger.info(f"Updated recording {recording_id} date to {new_date}")
            self._calendar_widget.refresh()
        except Exception as e:
            logger.error(f"Failed to update recording date: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to update recording date: {e}",
            )

    def _on_export_requested(self, recording_id: int) -> None:
        """Handle export request from calendar."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._prompt_and_export_recording(recording_id))
            else:
                loop.run_until_complete(self._prompt_and_export_recording(recording_id))
        except RuntimeError:
            asyncio.run(self._prompt_and_export_recording(recording_id))

    async def _prompt_and_export_recording(self, recording_id: int) -> None:
        """Resolve export capabilities, prompt for format, then export."""
        from PyQt6.QtWidgets import QFileDialog

        try:
            recording = await self._api_client.get_recording(recording_id)
        except Exception as e:
            logger.error(f"Failed to fetch recording details for export: {e}")
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to prepare export: {e}",
            )
            return

        has_diarization = bool(recording.get("has_diarization"))
        has_words = bool(recording.get("words"))
        is_pure_note = (not has_diarization) and (not has_words)

        format_dialog = QMessageBox(self)
        format_dialog.setWindowTitle("Export Format")
        format_dialog.setText("Choose export format:")
        format_dialog.setStyleSheet("""
            QMessageBox {
                background-color: #1e1e1e;
            }
            QLabel {
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #e0e0e0;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
        """)

        format_buttons = {}
        if is_pure_note:
            txt_btn = format_dialog.addButton(
                "Text (.txt)", QMessageBox.ButtonRole.AcceptRole
            )
            format_buttons[txt_btn] = ("txt", "Text Files (*.txt)", ".txt")
        else:
            srt_btn = format_dialog.addButton(
                "SubRip (.srt)", QMessageBox.ButtonRole.AcceptRole
            )
            ass_btn = format_dialog.addButton(
                "Advanced SubStation Alpha (.ass)",
                QMessageBox.ButtonRole.AcceptRole,
            )
            format_buttons[srt_btn] = ("srt", "SubRip Files (*.srt)", ".srt")
            format_buttons[ass_btn] = (
                "ass",
                "ASS Subtitle Files (*.ass)",
                ".ass",
            )

        format_dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        format_dialog.exec()

        clicked = format_dialog.clickedButton()
        if clicked not in format_buttons:
            return

        export_format, file_filter, default_ext = format_buttons[clicked]
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Transcription",
            f"transcription_export{default_ext}",
            file_filter,
        )
        if not file_path:
            return

        await self._export_recording(recording_id, export_format, file_path)

    async def _export_recording(
        self, recording_id: int, format: str, file_path: str
    ) -> None:
        """Export a recording to a file."""
        try:
            content, _ = await self._api_client.export_recording(recording_id, format)

            # Write to file
            from pathlib import Path

            Path(file_path).write_bytes(content)

            logger.info(f"Exported recording {recording_id} to {file_path}")
            QMessageBox.information(
                self,
                "Export Complete",
                f"Transcription exported successfully to:\n{file_path}",
            )
        except Exception as e:
            logger.error(f"Failed to export recording: {e}")
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export recording: {e}",
            )
