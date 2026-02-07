"""
Import widget for Audio Notebook.

Provides file upload and import functionality for audio files
with transcription options.
"""

import asyncio
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
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

from dashboard.kde.apple_switch import AppleSwitch

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)

WORD_TIMESTAMPS_TOOLTIP = "Include precise timestamps for each word"
WORD_TIMESTAMPS_REQUIRED_TOOLTIP = (
    "Word-level timestamps are required when speaker diarization is enabled"
)
DIARIZATION_REASON_MESSAGES = {
    "token_missing": "HuggingFace token is not configured.",
    "token_invalid": "Configured HuggingFace token is invalid.",
    "terms_not_accepted": "PyAnnote model terms have not been accepted on HuggingFace.",
    "unavailable": "Diarization service is currently unavailable.",
}


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

    def __init__(self, file_path: Path, recorded_at: str | None = None):
        self.file_path = file_path
        self.filename = file_path.name
        self.status = "pending"  # pending, transcribing, completed, failed
        self.progress: float | None = None
        self.message: str | None = None
        self.recording_id: int | None = None
        # Extract file modification time if not provided
        if recorded_at:
            self.recorded_at = recorded_at
        else:
            try:
                mtime = os.path.getmtime(file_path)
                self.recorded_at = datetime.fromtimestamp(mtime).isoformat()
            except (OSError, ValueError):
                self.recorded_at = None


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
        layout.setSpacing(8)

        # Simple upload icon (white, centered)
        self._icon_label = QLabel("⬆")
        self._icon_label.setObjectName("dropIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setMargin(6)
        layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignCenter)

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
    diarization_status_loaded = pyqtSignal(bool, object)

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

        # Target date/time for imports from Day View (overrides file date)
        self._target_recorded_at: str | None = None
        self._diarization_available = True

        self._setup_ui()
        self._apply_styles()
        self.diarization_status_loaded.connect(self._on_diarization_status_loaded)
        self._refresh_diarization_availability()

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

        self._diarization_checkbox = AppleSwitch("Speaker diarization")
        self._diarization_checkbox.setObjectName("optionCheckbox")
        self._diarization_checkbox.setChecked(False)
        self._diarization_checkbox.setToolTip(
            "Identify and label different speakers in the audio"
        )
        options_layout.addWidget(self._diarization_checkbox)

        self._word_timestamps_checkbox = AppleSwitch("Word-level timestamps")
        self._word_timestamps_checkbox.setObjectName("optionCheckbox")
        self._word_timestamps_checkbox.setChecked(True)
        self._word_timestamps_checkbox.setToolTip(WORD_TIMESTAMPS_TOOLTIP)
        options_layout.addWidget(self._word_timestamps_checkbox)
        self._diarization_checkbox.toggled.connect(self._on_diarization_toggled)
        self._on_diarization_toggled(self._diarization_checkbox.isChecked())

        options_layout.addStretch()

        layout.addWidget(options_container)

        self._diarization_notice = QLabel("")
        self._diarization_notice.setObjectName("statusLabel")
        self._diarization_notice.setVisible(False)
        layout.addWidget(self._diarization_notice)

        # Queue section
        queue_header = QWidget()
        queue_header_layout = QHBoxLayout(queue_header)
        queue_header_layout.setContentsMargins(0, 0, 0, 0)

        self._queue_label = QLabel("Import Queue")
        self._queue_label.setObjectName("queueLabel")
        queue_header_layout.addWidget(self._queue_label)

        queue_header_layout.addStretch()

        self._start_btn = QPushButton("Start Transcribing")
        self._start_btn.setObjectName("primaryButton")
        self._start_btn.clicked.connect(self._start_transcribing)
        self._start_btn.setEnabled(False)
        queue_header_layout.addWidget(self._start_btn)

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

    def _on_diarization_toggled(self, enabled: bool) -> None:
        """Enforce diarization dependency on word-level timestamps."""
        if not self._diarization_available:
            self._word_timestamps_checkbox.setEnabled(True)
            self._word_timestamps_checkbox.setToolTip(WORD_TIMESTAMPS_TOOLTIP)
            return

        if enabled:
            self._word_timestamps_checkbox.setChecked(True)
            self._word_timestamps_checkbox.setEnabled(False)
            self._word_timestamps_checkbox.setToolTip(WORD_TIMESTAMPS_REQUIRED_TOOLTIP)
            return

        self._word_timestamps_checkbox.setEnabled(True)
        self._word_timestamps_checkbox.setToolTip(WORD_TIMESTAMPS_TOOLTIP)

    def _reason_to_text(self, reason: str | None) -> str:
        if reason is None:
            return DIARIZATION_REASON_MESSAGES["unavailable"]
        return DIARIZATION_REASON_MESSAGES.get(
            reason, DIARIZATION_REASON_MESSAGES["unavailable"]
        )

    def _on_diarization_status_loaded(self, available: bool, reason: object) -> None:
        reason_text = reason if isinstance(reason, str) else None
        self._apply_diarization_availability(available, reason_text)

    def _apply_diarization_availability(
        self, available: bool, reason: str | None
    ) -> None:
        self._diarization_available = available
        if available:
            self._diarization_checkbox.setEnabled(True)
            self._diarization_checkbox.setToolTip(
                "Identify and label different speakers in the audio"
            )
            self._diarization_notice.setVisible(False)
            self._on_diarization_toggled(self._diarization_checkbox.isChecked())
            return

        self._diarization_checkbox.setChecked(False)
        self._diarization_checkbox.setEnabled(False)
        reason_text = self._reason_to_text(reason)
        self._diarization_checkbox.setToolTip(f"Diarization unavailable: {reason_text}")
        self._diarization_notice.setText(f"Diarization unavailable: {reason_text}")
        self._diarization_notice.setVisible(True)
        self._on_diarization_toggled(False)

    def _refresh_diarization_availability(self) -> None:
        if self._api_client is None:
            self._apply_diarization_availability(False, "unavailable")
            return

        def worker() -> None:
            available = True
            reason: str | None = None
            try:
                status = asyncio.run(self._api_client.get_status())
                available, reason = self._api_client.get_diarization_feature(status)
            except Exception as e:
                logger.debug(f"Could not load diarization feature status: {e}")
                available = False
                reason = "unavailable"

            self.diarization_status_loaded.emit(available, reason)

        threading.Thread(
            target=worker,
            name="DiarizationFeatureCheck",
            daemon=True,
        ).start()

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
                border-color: #0AFCCF;
                background-color: #1e2a3a;
            }

            #dropZone:hover {
                border-color: #606060;
            }

            #dropIcon {
                font-size: 42px;
                color: #ffffff;
                padding: 6px 0;
                line-height: 1.2em;
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

            #primaryButton {
                background-color: #0AFCCF;
                border: none;
                border-radius: 6px;
                color: #141414;
                padding: 8px 16px;
                font-weight: bold;
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

            #importProgress {
                background-color: #2d2d2d;
                border: none;
                border-radius: 4px;
                height: 8px;
            }

            #importProgress::chunk {
                background-color: #0AFCCF;
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

            # Use target date/time if set (from Day View), otherwise use file date
            job = ImportJob(file_path, recorded_at=self._target_recorded_at)
            self._jobs.append(job)
            self._add_job_to_list(job)
            added_count += 1

        # Clear target date after adding files
        self._target_recorded_at = None

        if added_count > 0:
            self._status_label.setText(f"Added {added_count} file(s) to queue")
            self._update_start_button()

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
            completion_text = job.message or "Transcription complete"
            text += f"  - {completion_text}"

        item.setText(text)

    def _update_start_button(self) -> None:
        """Update the state of the Start Transcribing button."""
        pending_jobs = [j for j in self._jobs if j.status == "pending"]
        self._start_btn.setEnabled(len(pending_jobs) > 0 and not self._is_processing)

    def _start_transcribing(self) -> None:
        """Start processing the queue when user clicks the button."""
        if not self._is_processing:
            self._process_queue()

    def _process_queue(self) -> None:
        """Process the next job in the queue."""
        if self._is_processing:
            return

        # Find next pending job
        pending_jobs = [j for j in self._jobs if j.status == "pending"]
        if not pending_jobs:
            self._is_processing = False
            self._progress_bar.setVisible(False)

            # Update button states
            completed_jobs = [
                j for j in self._jobs if j.status in ("completed", "failed")
            ]
            self._clear_completed_btn.setEnabled(len(completed_jobs) > 0)
            self._start_btn.setEnabled(False)
            return

        # Disable start button while processing
        self._start_btn.setEnabled(False)

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
        if self._api_client is None:
            job.status = "failed"
            job.message = "Not connected to server"
            self._update_queue_display()
            self._is_processing = False
            self._current_job = None
            QTimer.singleShot(100, self._process_queue)
            return

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
                recorded_at=job.recorded_at,
                on_progress=on_progress,
            )

            job.status = "completed"
            job.recording_id = result.get("id") or result.get("recording_id")
            diarization = result.get("diarization", {})
            if diarization.get("requested") and not diarization.get("performed"):
                reason_text = self._reason_to_text(diarization.get("reason"))
                job.message = (
                    f"Transcription complete (without diarization: {reason_text})"
                )
            else:
                job.message = "Transcription complete"
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
        self._refresh_diarization_availability()

    def import_for_datetime(self, target_date, hour: int) -> None:
        """Open file browser with a preset target date/time for the import."""
        # Set the target datetime (will be used instead of file creation date)
        self._target_recorded_at = datetime(
            target_date.year, target_date.month, target_date.day, hour, 0, 0
        ).isoformat()
        # Open file browser
        self._drop_zone._open_file_browser()
