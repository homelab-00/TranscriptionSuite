"""
Import widget for Audio Notebook (GNOME/GTK4).

Provides file upload and import functionality for audio files.
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

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

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)

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
        self.status = "pending"
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


class ImportWidget:
    """
    Import interface for Audio Notebook (GNOME).

    Provides drag-and-drop file upload with transcription options.
    """

    def __init__(self, api_client: "APIClient | None"):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for ImportWidget")

        self._api_client = api_client
        self._jobs: list[ImportJob] = []
        self._current_job: ImportJob | None = None
        self._is_processing = False
        self._recording_created_callback: Callable[[int], None] | None = None

        # Target date/time for imports from Day View (overrides file date)
        self._target_recorded_at: str | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the import widget UI."""
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.widget.set_margin_start(20)
        self.widget.set_margin_end(20)
        self.widget.set_margin_top(20)
        self.widget.set_margin_bottom(20)

        # Drop zone
        self._drop_zone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._drop_zone.add_css_class("drop-zone")
        self._drop_zone.set_valign(Gtk.Align.CENTER)
        self._drop_zone.set_halign(Gtk.Align.CENTER)
        self._drop_zone.set_size_request(-1, 180)
        self._drop_zone.set_hexpand(True)

        # Use themed folder icon instead of emoji
        icon_image = Gtk.Image.new_from_icon_name("folder-symbolic")
        icon_image.set_pixel_size(48)
        icon_image.add_css_class("drop-icon")
        self._drop_zone.append(icon_image)

        text_label = Gtk.Label(label="Drag audio files here\nor click to browse")
        text_label.add_css_class("drop-text")
        self._drop_zone.append(text_label)

        formats_label = Gtk.Label(label="Supported: MP3, WAV, M4A, FLAC, OGG, and more")
        formats_label.add_css_class("drop-formats")
        self._drop_zone.append(formats_label)

        # Set up drag-and-drop
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        drop_target.connect("enter", self._on_drag_enter)
        drop_target.connect("leave", self._on_drag_leave)
        self._drop_zone.add_controller(drop_target)

        # Click to browse
        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", lambda *_: self._open_file_chooser())
        self._drop_zone.add_controller(click_controller)

        self.widget.append(self._drop_zone)

        # Options section
        options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        options_box.add_css_class("options-box")
        options_box.set_margin_start(16)
        options_box.set_margin_end(16)
        options_box.set_margin_top(12)
        options_box.set_margin_bottom(12)

        options_label = Gtk.Label(label="Options:")
        options_label.add_css_class("options-label")
        options_box.append(options_label)

        self._diarization_check = Gtk.CheckButton(label="Speaker diarization")
        self._diarization_check.set_active(False)
        options_box.append(self._diarization_check)

        self._word_timestamps_check = Gtk.CheckButton(label="Word-level timestamps")
        self._word_timestamps_check.set_active(True)
        options_box.append(self._word_timestamps_check)

        self.widget.append(options_box)

        # Queue header
        queue_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        queue_label = Gtk.Label(label="Import Queue")
        queue_label.add_css_class("queue-label")
        queue_header.append(queue_label)

        queue_header.append(Gtk.Box(hexpand=True))

        self._start_btn = Gtk.Button(label="Start Transcribing")
        self._start_btn.add_css_class("primary-button")
        self._start_btn.set_sensitive(False)
        self._start_btn.connect("clicked", lambda _: self._start_transcribing())
        queue_header.append(self._start_btn)

        self._clear_btn = Gtk.Button(label="Clear Completed")
        self._clear_btn.add_css_class("secondary-button")
        self._clear_btn.set_sensitive(False)
        self._clear_btn.connect("clicked", lambda _: self._clear_completed_jobs())
        queue_header.append(self._clear_btn)

        self.widget.append(queue_header)

        # Queue list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._queue_list = Gtk.ListBox()
        self._queue_list.add_css_class("queue-list")
        scrolled.set_child(self._queue_list)

        self.widget.append(scrolled)

        # Status section
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self._status_label = Gtk.Label(label="Ready to import")
        self._status_label.add_css_class("status-label")
        self._status_label.set_xalign(0)
        status_box.append(self._status_label)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.add_css_class("import-progress")
        self._progress_bar.set_visible(False)
        status_box.append(self._progress_bar)

        self.widget.append(status_box)
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .primary-button {
                background-color: #1e88e5;
                border: none;
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
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
                padding: 8px 16px;
            }

            .secondary-button:hover {
                background-color: #3d3d3d;
            }

            .drop-zone {
                background-color: #1e1e1e;
                border: 2px dashed #3d3d3d;
                border-radius: 12px;
                padding: 30px;
            }

            .drop-zone.drag-over {
                border-color: #90caf9;
                background-color: #1e2a3a;
            }

            .drop-icon {
                font-size: 48px;
                color: #606060;
            }

            .drop-text {
                color: #a0a0a0;
                font-size: 14px;
            }

            .drop-formats {
                color: #606060;
                font-size: 11px;
            }

            .options-box {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }

            .options-label {
                color: #a0a0a0;
                font-weight: bold;
            }

            .queue-label {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }

            .queue-list {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }

            .queue-list row {
                padding: 10px;
                border-bottom: 1px solid #2d2d2d;
            }

            .status-label {
                color: #a0a0a0;
            }

            .import-progress {
                background-color: #2d2d2d;
                border-radius: 4px;
            }

            .import-progress progress {
                background-color: #90caf9;
                border-radius: 4px;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.widget.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

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
                self._add_files([file_path])
                return True
        return False

    def _open_file_chooser(self) -> None:
        """Open file chooser dialog."""
        dialog = Gtk.FileChooserDialog(
            title="Select Audio Files",
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Open", Gtk.ResponseType.ACCEPT)
        dialog.set_select_multiple(True)

        # Add filter for audio files
        filter_audio = Gtk.FileFilter()
        filter_audio.set_name("Audio files")
        for ext in AUDIO_EXTENSIONS:
            filter_audio.add_pattern(f"*{ext}")
        dialog.add_filter(filter_audio)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All files")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)

        dialog.connect("response", self._on_file_chooser_response)
        dialog.present()

    def _on_file_chooser_response(self, dialog, response) -> None:
        """Handle file chooser response."""
        if response == Gtk.ResponseType.ACCEPT:
            files = []
            file_list = dialog.get_files()
            for i in range(file_list.get_n_items()):
                gfile = file_list.get_item(i)
                file_path = Path(gfile.get_path())
                if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                    files.append(file_path)

            if files:
                self._add_files(files)

        dialog.destroy()

    def _add_files(self, file_paths: list[Path]) -> None:
        """Add files to the import queue."""
        added_count = 0
        for file_path in file_paths:
            if any(job.file_path == file_path for job in self._jobs):
                continue

            # Use target date/time if set (from Day View), otherwise use file date
            job = ImportJob(file_path, recorded_at=self._target_recorded_at)
            self._jobs.append(job)
            self._add_job_to_list(job)
            added_count += 1

        # Clear target date after adding files
        self._target_recorded_at = None

        if added_count > 0:
            self._status_label.set_label(f"Added {added_count} file(s) to queue")
            self._update_start_button()

    def _add_job_to_list(self, job: ImportJob) -> None:
        """Add a job item to the queue list."""
        row = Gtk.ListBoxRow()
        row.job = job

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        self._update_job_row(box, job)
        row.set_child(box)
        row.box_widget = box

        self._queue_list.append(row)

    def _update_job_row(self, box: Gtk.Box, job: ImportJob) -> None:
        """Update the display of a job row."""
        # Clear existing children
        while True:
            child = box.get_first_child()
            if child is None:
                break
            box.remove(child)

        status_icons = {
            "pending": "⏳",
            "transcribing": "🔄",
            "completed": "✅",
            "failed": "❌",
        }
        icon = status_icons.get(job.status, "❓")

        icon_label = Gtk.Label(label=icon)
        box.append(icon_label)

        text = job.filename
        if job.status == "transcribing" and job.progress is not None:
            text += f"  ({int(job.progress * 100)}%)"
        elif job.status == "failed" and job.message:
            text += f" - Error: {job.message[:50]}"
        elif job.status == "completed":
            text += " - Complete"

        name_label = Gtk.Label(label=text)
        name_label.set_xalign(0)
        name_label.set_hexpand(True)
        box.append(name_label)

    def _update_start_button(self) -> None:
        """Update the state of the Start Transcribing button."""
        pending_jobs = [j for j in self._jobs if j.status == "pending"]
        self._start_btn.set_sensitive(len(pending_jobs) > 0 and not self._is_processing)

    def _start_transcribing(self) -> None:
        """Start processing the queue when user clicks the button."""
        if not self._is_processing:
            self._process_queue()

    def _process_queue(self) -> None:
        """Process the next job in the queue."""
        if self._is_processing:
            return

        pending_jobs = [j for j in self._jobs if j.status == "pending"]
        if not pending_jobs:
            self._is_processing = False
            self._progress_bar.set_visible(False)

            completed = [j for j in self._jobs if j.status in ("completed", "failed")]
            self._clear_btn.set_sensitive(len(completed) > 0)
            self._start_btn.set_sensitive(False)
            return

        # Disable start button while processing
        self._start_btn.set_sensitive(False)

        self._is_processing = True
        self._current_job = pending_jobs[0]

        self._status_label.set_label(f"Transcribing: {self._current_job.filename}")
        self._progress_bar.set_visible(True)
        self._progress_bar.set_fraction(0)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._upload_file(self._current_job))
            else:
                asyncio.run(self._upload_file(self._current_job))
        except RuntimeError:
            pass

    async def _upload_file(self, job: ImportJob) -> None:
        """Upload and transcribe a file."""
        if not self._api_client:
            job.status = "failed"
            job.message = "No API client"
            GLib.idle_add(self._update_queue_display)
            return

        try:
            job.status = "transcribing"
            GLib.idle_add(self._update_queue_display)

            def on_progress(message: str) -> None:
                job.message = message
                if "uploading" in message.lower():
                    job.progress = 0.2
                elif "transcribing" in message.lower():
                    job.progress = 0.5
                elif "complete" in message.lower():
                    job.progress = 1.0
                GLib.idle_add(self._update_queue_display)

            result = await self._api_client.upload_file_to_notebook(
                file_path=job.file_path,
                diarization=self._diarization_check.get_active(),
                word_timestamps=self._word_timestamps_check.get_active(),
                recorded_at=job.recorded_at,
                on_progress=on_progress,
            )

            job.status = "completed"
            job.recording_id = result.get("id") or result.get("recording_id")
            job.message = None
            job.progress = 1.0

            if job.recording_id and self._recording_created_callback:
                GLib.idle_add(
                    lambda: self._recording_created_callback(job.recording_id)
                )

        except Exception as e:
            logger.error(f"Import failed for {job.filename}: {e}")
            job.status = "failed"
            job.message = str(e)

        finally:
            GLib.idle_add(self._update_queue_display)
            self._is_processing = False
            self._current_job = None
            GLib.timeout_add(100, lambda: self._process_queue() or False)

    def _update_queue_display(self) -> bool:
        """Update all queue items display."""
        row = self._queue_list.get_first_child()
        while row:
            if hasattr(row, "job") and hasattr(row, "box_widget"):
                self._update_job_row(row.box_widget, row.job)
            row = row.get_next_sibling()

        if self._current_job and self._current_job.progress is not None:
            self._progress_bar.set_fraction(self._current_job.progress)

        pending = sum(1 for j in self._jobs if j.status == "pending")
        transcribing = sum(1 for j in self._jobs if j.status == "transcribing")

        if transcribing > 0:
            self._status_label.set_label(f"Transcribing... ({pending} pending)")
        elif pending > 0:
            self._status_label.set_label(f"{pending} file(s) in queue")
        else:
            completed = sum(1 for j in self._jobs if j.status == "completed")
            failed = sum(1 for j in self._jobs if j.status == "failed")
            self._status_label.set_label(
                f"Done: {completed} completed, {failed} failed"
            )

        return False

    def _clear_completed_jobs(self) -> None:
        """Clear completed and failed jobs."""
        self._jobs = [j for j in self._jobs if j.status not in ("completed", "failed")]

        while True:
            row = self._queue_list.get_first_child()
            if row is None:
                break
            self._queue_list.remove(row)

        for job in self._jobs:
            self._add_job_to_list(job)

        self._clear_btn.set_sensitive(False)

        if not self._jobs:
            self._status_label.set_label("Ready to import")

    def set_recording_created_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for when a recording is created."""
        self._recording_created_callback = callback

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client

    def import_for_datetime(self, target_date, hour: int) -> None:
        """Open file browser with a preset target date/time for the import."""
        # Set the target datetime (will be used instead of file creation date)
        self._target_recorded_at = datetime(
            target_date.year, target_date.month, target_date.day, hour, 0, 0
        ).isoformat()
        # Open file browser
        self._open_file_chooser()
