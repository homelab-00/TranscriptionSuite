"""
Import widget for Audio Notebook.

Provides file upload and import functionality for audio files
with transcription options.
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


# Supported audio formats
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


class ImportJob:
    """Represents an import job in the queue."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.filename = file_path.name
        self.status = "pending"  # pending, transcribing, completed, failed
        self.progress: float | None = None
        self.message: str | None = None
        self.recording_id: int | None = None


class DropZone(QFrame):
    """
    Drag-and-drop zone for file imports.
    """

    files_dropped = pyqtSignal(list)  # List of file paths

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel("📁")
        icon_label.setObjectName("dropIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text_label = QLabel("Drag audio files here\nor click to browse")
        text_label.setObjectName("dropText")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label)

        formats_label = QLabel("Supported: MP3, WAV, M4A, FLAC, OGG, and more")
        formats_label.setObjectName("dropFormats")
        formats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(formats_label)

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

        files = []
        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                files.append(file_path)

        if files:
            self.files_dropped.emit(files)

    def mousePressEvent(self, event) -> None:
        """Handle click to open file browser."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_file_browser()

    def _open_file_browser(self) -> None:
        """Open file browser dialog."""
        extensions = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio Files",
            "",
            f"Audio Files ({extensions});;All Files (*)",
        )

        if files:
            self.files_dropped.emit([Path(f) for f in files])


class ImportWidget(QWidget):
    """
    Import interface for Audio Notebook.

    Provides drag-and-drop file upload with transcription options
    and job queue management.
    """

    # Signal emitted when a recording is created
    recording_created = pyqtSignal(int)  # recording_id

    def __init__(
        self,
        api_client: "APIClient",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._api_client = api_client

        # Import job queue
        self._jobs: list[ImportJob] = []
        self._current_job: ImportJob | None = None
        self._is_processing = False

        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self) -> None:
        """Set up the import widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Drop zone
        self._drop_zone = DropZone()
        self._drop_zone.setMinimumHeight(180)
        self._drop_zone.files_dropped.connect(self._add_files)
        layout.addWidget(self._drop_zone)

        # Options section
        options_container = QFrame()
        options_container.setObjectName("optionsCard")
        options_layout = QHBoxLayout(options_container)
        options_layout.setContentsMargins(16, 12, 16, 12)
        options_layout.setSpacing(24)

        options_label = QLabel("Options:")
        options_label.setObjectName("optionsLabel")
        options_layout.addWidget(options_label)

        self._diarization_checkbox = QCheckBox("Speaker diarization")
        self._diarization_checkbox.setObjectName("optionCheckbox")
        self._diarization_checkbox.setChecked(True)
        self._diarization_checkbox.setToolTip(
            "Identify and label different speakers in the audio"
        )
        options_layout.addWidget(self._diarization_checkbox)

        self._word_timestamps_checkbox = QCheckBox("Word-level timestamps")
        self._word_timestamps_checkbox.setObjectName("optionCheckbox")
        self._word_timestamps_checkbox.setChecked(True)
        self._word_timestamps_checkbox.setToolTip(
            "Include precise timestamps for each word"
        )
        options_layout.addWidget(self._word_timestamps_checkbox)

        options_layout.addStretch()

        layout.addWidget(options_container)

        # Queue section
        queue_header = QWidget()
        queue_header_layout = QHBoxLayout(queue_header)
        queue_header_layout.setContentsMargins(0, 0, 0, 0)

        self._queue_label = QLabel("Import Queue")
        self._queue_label.setObjectName("queueLabel")
        queue_header_layout.addWidget(self._queue_label)

        queue_header_layout.addStretch()

        self._clear_completed_btn = QPushButton("Clear Completed")
        self._clear_completed_btn.setObjectName("secondaryButton")
        self._clear_completed_btn.clicked.connect(self._clear_completed_jobs)
        self._clear_completed_btn.setEnabled(False)
        queue_header_layout.addWidget(self._clear_completed_btn)

        layout.addWidget(queue_header)

        # Queue list
        self._queue_list = QListWidget()
        self._queue_list.setObjectName("queueList")
        layout.addWidget(self._queue_list, 1)

        # Status section
        status_container = QWidget()
        status_layout = QVBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)

        self._status_label = QLabel("Ready to import")
        self._status_label.setObjectName("statusLabel")
        status_layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("importProgress")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        status_layout.addWidget(self._progress_bar)

        layout.addWidget(status_container)

    def _apply_styles(self) -> None:
        """Apply styling to import components."""
        self.setStyleSheet("""
            #dropZone {
                background-color: #1e1e1e;
                border: 2px dashed #3d3d3d;
                border-radius: 12px;
                padding: 30px;
            }

            #dropZone[dragOver="true"] {
                border-color: #90caf9;
                background-color: #1e2a3a;
            }

            #dropZone:hover {
                border-color: #606060;
                cursor: pointer;
            }

            #dropIcon {
                font-size: 48px;
                color: #606060;
            }

            #dropText {
                color: #a0a0a0;
                font-size: 14px;
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

            #queueLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }

            #queueList {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                padding: 4px;
            }

            #queueList::item {
                padding: 10px;
                border-bottom: 1px solid #2d2d2d;
                border-radius: 4px;
                margin: 2px;
            }

            #queueList::item:selected {
                background-color: #2d4a6d;
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
        """)

    def _add_files(self, file_paths: list[Path]) -> None:
        """Add files to the import queue."""
        added_count = 0
        for file_path in file_paths:
            # Check if already in queue
            if any(job.file_path == file_path for job in self._jobs):
                logger.debug(f"File already in queue: {file_path}")
                continue

            job = ImportJob(file_path)
            self._jobs.append(job)
            self._add_job_to_list(job)
            added_count += 1

        if added_count > 0:
            self._status_label.setText(f"Added {added_count} file(s) to queue")
            self._process_queue()

    def _add_job_to_list(self, job: ImportJob) -> None:
        """Add a job item to the queue list."""
        item = QListWidgetItem()
        self._update_job_item(item, job)
        item.setData(Qt.ItemDataRole.UserRole, job)
        self._queue_list.addItem(item)

    def _update_job_item(self, item: QListWidgetItem, job: ImportJob) -> None:
        """Update the display text for a job item."""
        status_icons = {
            "pending": "⏳",
            "transcribing": "🔄",
            "completed": "✅",
            "failed": "❌",
        }
        icon = status_icons.get(job.status, "❓")

        text = f"{icon}  {job.filename}"

        if job.status == "transcribing" and job.progress is not None:
            text += f"  ({int(job.progress * 100)}%)"
        elif job.status == "failed" and job.message:
            text += f"\n    Error: {job.message}"
        elif job.status == "completed":
            text += "  - Transcription complete"

        item.setText(text)

    def _process_queue(self) -> None:
        """Process the next job in the queue."""
        if self._is_processing:
            return

        # Find next pending job
        pending_jobs = [j for j in self._jobs if j.status == "pending"]
        if not pending_jobs:
            self._is_processing = False
            self._progress_bar.setVisible(False)

            # Update clear button state
            completed_jobs = [
                j for j in self._jobs if j.status in ("completed", "failed")
            ]
            self._clear_completed_btn.setEnabled(len(completed_jobs) > 0)
            return

        self._is_processing = True
        self._current_job = pending_jobs[0]

        # Start transcription
        self._status_label.setText(f"Transcribing: {self._current_job.filename}")
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)

        # Schedule async upload
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._upload_file(self._current_job))
            else:
                loop.run_until_complete(self._upload_file(self._current_job))
        except RuntimeError:
            asyncio.run(self._upload_file(self._current_job))

    async def _upload_file(self, job: ImportJob) -> None:
        """Upload and transcribe a file."""
        try:
            job.status = "transcribing"
            self._update_queue_display()

            def on_progress(message: str) -> None:
                """Handle progress updates."""
                job.message = message
                # Simple progress estimation
                if "uploading" in message.lower():
                    job.progress = 0.2
                elif "transcribing" in message.lower():
                    job.progress = 0.5
                elif "complete" in message.lower():
                    job.progress = 1.0
                self._update_queue_display()

            result = await self._api_client.upload_file_to_notebook(
                file_path=job.file_path,
                diarization=self._diarization_checkbox.isChecked(),
                word_timestamps=self._word_timestamps_checkbox.isChecked(),
                on_progress=on_progress,
            )

            job.status = "completed"
            job.recording_id = result.get("id") or result.get("recording_id")
            job.message = None
            job.progress = 1.0

            logger.info(f"Import complete: {job.filename} -> ID {job.recording_id}")

            # Emit signal for the new recording
            if job.recording_id:
                self.recording_created.emit(job.recording_id)

        except Exception as e:
            logger.error(f"Import failed for {job.filename}: {e}")
            job.status = "failed"
            job.message = str(e)

        finally:
            self._update_queue_display()
            self._is_processing = False
            self._current_job = None

            # Process next job
            QTimer.singleShot(100, self._process_queue)

    def _update_queue_display(self) -> None:
        """Update all queue items display."""
        for i in range(self._queue_list.count()):
            item = self._queue_list.item(i)
            if item:
                job = item.data(Qt.ItemDataRole.UserRole)
                if job:
                    self._update_job_item(item, job)

        # Update progress bar
        if self._current_job and self._current_job.progress is not None:
            self._progress_bar.setValue(int(self._current_job.progress * 100))

        # Update status
        pending = sum(1 for j in self._jobs if j.status == "pending")
        transcribing = sum(1 for j in self._jobs if j.status == "transcribing")

        if transcribing > 0:
            self._status_label.setText(f"Transcribing... ({pending} pending)")
        elif pending > 0:
            self._status_label.setText(f"{pending} file(s) in queue")
        else:
            completed = sum(1 for j in self._jobs if j.status == "completed")
            failed = sum(1 for j in self._jobs if j.status == "failed")
            self._status_label.setText(f"Done: {completed} completed, {failed} failed")

    def _clear_completed_jobs(self) -> None:
        """Clear completed and failed jobs from the queue."""
        # Remove from jobs list
        self._jobs = [j for j in self._jobs if j.status not in ("completed", "failed")]

        # Rebuild queue list
        self._queue_list.clear()
        for job in self._jobs:
            self._add_job_to_list(job)

        self._clear_completed_btn.setEnabled(False)

        if not self._jobs:
            self._status_label.setText("Ready to import")

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
