"""
Recording dialog for Audio Notebook.

Displays a recording with transcript, audio playback, and AI features.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.models import Recording, Segment, Transcription, Word
from dashboard.kde.audio_player import AudioPlayer

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class RecordingDialog(QDialog):
    """
    Dialog for viewing and playing a recording.

    Features:
    - Audio playback with seek
    - Transcript display with speaker labels
    - Word-level click-to-seek
    - Title editing
    - AI summary generation (future)
    """

    # Signal emitted when recording is deleted
    recording_deleted = pyqtSignal(int)  # recording_id
    # Signal emitted when recording is updated (recording_id, title)
    recording_updated = pyqtSignal(int, str)  # recording_id, title

    def __init__(
        self,
        api_client: "APIClient",
        recording_id: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client
        self._recording_id = recording_id

        self._recording: Recording | None = None
        self._transcription: Transcription | None = None

        # Word positions for click-to-seek
        self._word_positions: list[
            tuple[int, int, float, float]
        ] = []  # (start_char, end_char, start_time, end_time)

        # Current highlight
        self._current_highlight_cursor: QTextCursor | None = None

        self._setup_ui()
        self._apply_styles()

        # Load data
        self._load_recording()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle("Recording")
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header section
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 16)
        header_layout.setSpacing(8)

        # Title row with edit
        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("titleEdit")
        self._title_edit.setPlaceholderText("Recording title...")
        self._title_edit.editingFinished.connect(self._on_title_changed)
        title_row.addWidget(self._title_edit, 1)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("dangerButton")
        self._delete_btn.clicked.connect(self._confirm_delete)
        title_row.addWidget(self._delete_btn)

        header_layout.addLayout(title_row)

        # Metadata row
        self._metadata_label = QLabel()
        self._metadata_label.setObjectName("metadataLabel")
        header_layout.addWidget(self._metadata_label)

        layout.addWidget(header)

        # Main content area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 16, 24, 24)
        content_layout.setSpacing(16)

        # Audio player
        self._audio_player = AudioPlayer()
        self._audio_player.position_changed.connect(self._on_playback_position_changed)
        content_layout.addWidget(self._audio_player)

        # Transcript section
        transcript_header = QWidget()
        transcript_header_layout = QHBoxLayout(transcript_header)
        transcript_header_layout.setContentsMargins(0, 0, 0, 0)

        transcript_title = QLabel("Transcript")
        transcript_title.setObjectName("sectionTitle")
        transcript_header_layout.addWidget(transcript_title)

        transcript_header_layout.addStretch()

        content_layout.addWidget(transcript_header)

        # Transcript text area
        self._transcript_edit = QTextEdit()
        self._transcript_edit.setObjectName("transcriptEdit")
        self._transcript_edit.setReadOnly(True)
        self._transcript_edit.setAcceptRichText(True)
        self._transcript_edit.mousePressEvent = self._on_transcript_click
        content_layout.addWidget(self._transcript_edit, 1)

        layout.addWidget(content_widget, 1)

        # Footer with close button
        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 12)

        footer_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)

        layout.addWidget(footer)

    def _apply_styles(self) -> None:
        """Apply styling to dialog components."""
        self.setStyleSheet("""
            QDialog {
                background-color: #0a0a0a;
            }

            #dialogHeader {
                background-color: #1e1e1e;
                border-bottom: 1px solid #2d2d2d;
            }

            #titleEdit {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                color: #ffffff;
                font-size: 20px;
                font-weight: bold;
                padding: 6px 8px;
            }

            #titleEdit:hover {
                background-color: #2d2d2d;
            }

            #titleEdit:focus {
                background-color: #1e1e1e;
                border-color: #90caf9;
            }

            #metadataLabel {
                color: #a0a0a0;
                font-size: 13px;
            }

            #sectionTitle {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }

            #transcriptEdit {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                color: #e0e0e0;
                font-size: 14px;
                line-height: 1.6;
                padding: 16px;
            }

            #dialogFooter {
                background-color: #1e1e1e;
                border-top: 1px solid #2d2d2d;
            }

            #primaryButton {
                background-color: #90caf9;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 500;
            }

            #primaryButton:hover {
                background-color: #42a5f5;
            }

            #dangerButton {
                background-color: transparent;
                border: 1px solid #f44336;
                border-radius: 6px;
                color: #f44336;
                padding: 8px 16px;
                font-size: 12px;
            }

            #dangerButton:hover {
                background-color: #f44336;
                color: #ffffff;
            }
        """)

    def _load_recording(self) -> None:
        """Load recording data from server."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._fetch_recording())
            else:
                loop.run_until_complete(self._fetch_recording())
        except RuntimeError:
            asyncio.run(self._fetch_recording())

    async def _fetch_recording(self) -> None:
        """Fetch recording and transcription data."""
        try:
            # Fetch recording metadata
            recording_data = await self._api_client.get_recording(self._recording_id)
            self._recording = Recording.from_dict(recording_data)

            # Update UI with recording info
            self._title_edit.setText(self._recording.title or self._recording.filename)
            self._update_metadata()

            # Load audio
            audio_url = self._api_client.get_audio_url(self._recording_id)
            self._audio_player.load(audio_url)

            # Fetch transcription
            transcription_data = await self._api_client.get_transcription(
                self._recording_id
            )
            self._transcription = Transcription.from_dict(transcription_data)

            # Display transcript
            self._display_transcript()

        except Exception as e:
            logger.error(f"Failed to load recording: {e}")
            self._transcript_edit.setText(f"Error loading recording: {e}")

    def _update_metadata(self) -> None:
        """Update metadata display."""
        if not self._recording:
            return

        try:
            rec_datetime = datetime.fromisoformat(
                self._recording.recorded_at.replace("Z", "+00:00")
            )
            date_str = rec_datetime.strftime("%B %d, %Y at %H:%M")
        except (ValueError, AttributeError):
            date_str = "Unknown date"

        # Format duration
        duration_mins = int(self._recording.duration_seconds // 60)
        duration_secs = int(self._recording.duration_seconds % 60)
        duration_str = f"{duration_mins}:{duration_secs:02d}"

        metadata_parts = [
            date_str,
            f"Duration: {duration_str}",
            f"Words: {self._recording.word_count}",
        ]

        if self._recording.has_diarization:
            metadata_parts.append("Speaker diarization")

        self._metadata_label.setText("  •  ".join(metadata_parts))

    def _display_transcript(self) -> None:
        """Display the transcript with formatting."""
        if not self._transcription:
            self._transcript_edit.setText("No transcript available")
            return

        self._word_positions.clear()
        self._transcript_edit.clear()

        cursor = self._transcript_edit.textCursor()

        # Text formats
        speaker_format = QTextCharFormat()
        speaker_format.setFontWeight(QFont.Weight.Bold)
        speaker_format.setForeground(QColor("#90caf9"))

        text_format = QTextCharFormat()
        text_format.setForeground(QColor("#e0e0e0"))

        timestamp_format = QTextCharFormat()
        timestamp_format.setForeground(QColor("#606060"))
        timestamp_format.setFontPointSize(11)

        current_speaker = None

        for segment in self._transcription.segments:
            # Add speaker label if changed
            if segment.speaker and segment.speaker != current_speaker:
                current_speaker = segment.speaker
                if cursor.position() > 0:
                    cursor.insertText("\n\n")

                cursor.insertText(f"{segment.speaker}", speaker_format)

                # Add timestamp
                timestamp = self._format_timestamp(segment.start)
                cursor.insertText(f"  [{timestamp}]", timestamp_format)
                cursor.insertText("\n", text_format)

            # Add segment text with word tracking
            if segment.words:
                for i, word in enumerate(segment.words):
                    start_pos = cursor.position()

                    # Add space before word (except first)
                    if i > 0:
                        cursor.insertText(" ", text_format)
                        start_pos = cursor.position()

                    cursor.insertText(word.word, text_format)
                    end_pos = cursor.position()

                    # Store word position for click-to-seek
                    self._word_positions.append(
                        (start_pos, end_pos, word.start, word.end)
                    )
            else:
                # No word-level data, just insert segment text
                if segment.text:
                    cursor.insertText(segment.text, text_format)

            # Add line break after segment
            cursor.insertText("\n", text_format)

        self._transcript_edit.setTextCursor(cursor)

    def _on_transcript_click(self, event) -> None:
        """Handle click on transcript to seek to word."""
        # Get cursor position at click
        cursor = self._transcript_edit.cursorForPosition(event.pos())
        click_pos = cursor.position()

        # Find word at position
        for start_char, end_char, start_time, end_time in self._word_positions:
            if start_char <= click_pos <= end_char:
                # Seek to word start time
                self._audio_player.seek_seconds(start_time)
                if not self._audio_player.is_playing():
                    self._audio_player.play()
                break

        # Call original event handler
        QTextEdit.mousePressEvent(self._transcript_edit, event)

    def _on_playback_position_changed(self, position_ms: int) -> None:
        """Handle playback position change for word highlighting."""
        position_sec = position_ms / 1000.0

        # Clear previous highlight
        if self._current_highlight_cursor:
            self._clear_highlight()

        # Find current word
        for start_char, end_char, start_time, end_time in self._word_positions:
            if start_time <= position_sec <= end_time:
                # Highlight this word
                self._highlight_word(start_char, end_char)
                break

    def _highlight_word(self, start: int, end: int) -> None:
        """Highlight a word in the transcript."""
        cursor = self._transcript_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)

        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor("#2d4a6d"))
        highlight_format.setForeground(QColor("#ffffff"))

        cursor.mergeCharFormat(highlight_format)
        self._current_highlight_cursor = cursor

        # Scroll to show highlighted word
        self._transcript_edit.setTextCursor(cursor)
        self._transcript_edit.ensureCursorVisible()

    def _clear_highlight(self) -> None:
        """Clear the current word highlight."""
        if self._current_highlight_cursor:
            # Reset format to default
            default_format = QTextCharFormat()
            default_format.setBackground(QColor("transparent"))
            default_format.setForeground(QColor("#e0e0e0"))
            self._current_highlight_cursor.mergeCharFormat(default_format)
            self._current_highlight_cursor = None

    def _on_title_changed(self) -> None:
        """Handle title edit completion."""
        new_title = self._title_edit.text().strip()
        if not new_title or not self._recording:
            return

        if new_title != self._recording.title:
            self._save_title(new_title)

    def _save_title(self, title: str) -> None:
        """Save updated title to server."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._do_save_title(title))
            else:
                loop.run_until_complete(self._do_save_title(title))
        except RuntimeError:
            asyncio.run(self._do_save_title(title))

    async def _do_save_title(self, title: str) -> None:
        """Perform title save."""
        try:
            await self._api_client.update_recording_title(self._recording_id, title)
            if self._recording:
                self._recording.title = title
            logger.info(f"Title updated: {title}")
            self.recording_updated.emit(self._recording_id, title)
        except Exception as e:
            logger.error(f"Failed to save title: {e}")

    def _confirm_delete(self) -> None:
        """Show delete confirmation dialog."""
        result = QMessageBox.question(
            self,
            "Delete Recording",
            "Are you sure you want to delete this recording?\n\n"
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if result == QMessageBox.StandardButton.Yes:
            self._delete_recording()

    def _delete_recording(self) -> None:
        """Delete the recording."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._do_delete())
            else:
                loop.run_until_complete(self._do_delete())
        except RuntimeError:
            asyncio.run(self._do_delete())

    async def _do_delete(self) -> None:
        """Perform recording deletion."""
        try:
            await self._api_client.delete_recording(self._recording_id)
            logger.info(f"Recording deleted: {self._recording_id}")
            self.recording_deleted.emit(self._recording_id)
            self.accept()
        except Exception as e:
            logger.error(f"Failed to delete recording: {e}")
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Failed to delete recording:\n{e}",
            )

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as M:SS or H:MM:SS."""
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"

    def closeEvent(self, event) -> None:
        """Clean up on dialog close."""
        self._audio_player.cleanup()
        super().closeEvent(event)
