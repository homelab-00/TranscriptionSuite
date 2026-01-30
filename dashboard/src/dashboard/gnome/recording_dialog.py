"""
Recording dialog for Audio Notebook (GNOME/GTK4 version).

Displays a recording with transcript, audio playback, and AI features.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango

from dashboard.common.models import Recording, Transcription
from dashboard.gnome.audio_player import AudioPlayer

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class RecordingDialog(Adw.Window):
    """
    Dialog for viewing and playing a recording.

    Features:
    - Audio playback with seek
    - Transcript display with speaker labels
    - Word-level click-to-seek
    - Title editing
    - AI summary generation (future)
    """

    def __init__(
        self,
        api_client: "APIClient",
        recording_id: int,
        parent: Gtk.Window | None = None,
    ):
        super().__init__()
        self._api_client = api_client
        self._recording_id = recording_id
        self._parent = parent

        self._recording: Recording | None = None
        self._transcription: Transcription | None = None

        # Word positions for click-to-seek: list of (start_offset, end_offset, start_time, end_time)
        self._word_positions: list[tuple[int, int, float, float]] = []

        # Callback for recording deletion
        self._deletion_callback: Callable[[int], None] | None = None
        # Callback for recording updates (recording_id, title)
        self._update_callback: Callable[[int, str], None] | None = None

        self._setup_ui()
        self._apply_styles()

        # Load data
        self._load_recording()

    def connect_recording_deleted(self, callback: Callable[[int], None]) -> None:
        """Connect callback for recording deletion."""
        self._deletion_callback = callback

    def connect_recording_updated(self, callback: Callable[[int, str], None]) -> None:
        """Connect callback for recording updates (receives recording_id and new title)."""
        self._update_callback = callback

    # Alias for compatibility
    @property
    def recording_deleted(self):
        """Compatibility property for signal-like access."""

        class SignalProxy:
            def __init__(self, dialog):
                self._dialog = dialog

            def connect(self, callback):
                self._dialog._deletion_callback = callback

        return SignalProxy(self)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.set_title("Recording")
        self.set_default_size(1000, 700)
        if self._parent:
            self.set_transient_for(self._parent)
            self.set_modal(True)

        # Main content box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        # Delete button in header
        self._delete_btn = Gtk.Button(label="Delete")
        self._delete_btn.add_css_class("destructive-action")
        self._delete_btn.connect("clicked", lambda _: self._confirm_delete())
        header.pack_start(self._delete_btn)

        main_box.append(header)

        # Content area
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(24)
        content.set_margin_end(24)

        # Title row
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self._title_entry = Gtk.Entry()
        self._title_entry.set_placeholder_text("Recording title...")
        self._title_entry.set_hexpand(True)
        self._title_entry.add_css_class("title-entry")
        self._title_entry.connect("activate", lambda _: self._on_title_changed())
        title_box.append(self._title_entry)

        content.append(title_box)

        # Metadata row
        self._metadata_label = Gtk.Label()
        self._metadata_label.add_css_class("dim-label")
        self._metadata_label.set_xalign(0)
        content.append(self._metadata_label)

        # Audio player
        self._audio_player = AudioPlayer()
        self._audio_player.connect_position_changed(self._on_playback_position_changed)
        content.append(self._audio_player)

        # Transcript section
        transcript_header = Gtk.Label(label="Transcript")
        transcript_header.add_css_class("heading")
        transcript_header.set_xalign(0)
        content.append(transcript_header)

        # Transcript text view in scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._transcript_view = Gtk.TextView()
        self._transcript_view.set_editable(False)
        self._transcript_view.set_cursor_visible(False)
        self._transcript_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._transcript_view.add_css_class("transcript-view")
        self._transcript_buffer = self._transcript_view.get_buffer()

        # Create text tags for formatting
        self._speaker_tag = self._transcript_buffer.create_tag(
            "speaker",
            weight=Pango.Weight.BOLD,
            foreground="#0AFCCF",
        )
        self._timestamp_tag = self._transcript_buffer.create_tag(
            "timestamp",
            foreground="#606060",
            scale=0.9,
        )
        self._text_tag = self._transcript_buffer.create_tag(
            "text",
            foreground="#e0e0e0",
        )
        self._highlight_tag = self._transcript_buffer.create_tag(
            "highlight",
            background="#2d4a6d",
            foreground="#ffffff",
        )

        # Connect click handler
        gesture = Gtk.GestureClick.new()
        gesture.connect("pressed", self._on_transcript_click)
        self._transcript_view.add_controller(gesture)

        scrolled.set_child(self._transcript_view)
        content.append(scrolled)

        main_box.append(content)

        self.set_content(main_box)

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css = b"""
        .title-entry {
            font-size: 20px;
            font-weight: bold;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 6px 8px;
        }

        .title-entry:hover {
            background: #2d2d2d;
        }

        .title-entry:focus {
            background: #1e1e1e;
            border-color: #0AFCCF;
        }

        .transcript-view {
            background-color: #1e1e1e;
            border-radius: 8px;
            padding: 16px;
            font-size: 14px;
        }

        .transcript-view text {
            background-color: #1e1e1e;
        }
        """

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _load_recording(self) -> None:
        """Load recording data from server."""
        # Schedule async loading
        GLib.idle_add(self._start_async_load)

    def _start_async_load(self) -> bool:
        """Start async data loading."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._fetch_recording())
            else:
                loop.run_until_complete(self._fetch_recording())
        except RuntimeError:
            asyncio.run(self._fetch_recording())
        return False

    async def _fetch_recording(self) -> None:
        """Fetch recording and transcription data."""
        try:
            # Fetch recording metadata
            recording_data = await self._api_client.get_recording(self._recording_id)
            self._recording = Recording.from_dict(recording_data)

            # Update UI with recording info
            GLib.idle_add(self._update_ui_with_recording)

            # Load audio
            audio_url = self._api_client.get_audio_url(self._recording_id)
            GLib.idle_add(self._audio_player.load, audio_url)

            # Fetch transcription
            transcription_data = await self._api_client.get_transcription(
                self._recording_id
            )
            self._transcription = Transcription.from_dict(transcription_data)

            # Display transcript
            GLib.idle_add(self._display_transcript)

        except Exception as e:
            logger.error(f"Failed to load recording: {e}")
            GLib.idle_add(self._show_error, str(e))

    def _update_ui_with_recording(self) -> bool:
        """Update UI with recording data (called on main thread)."""
        if not self._recording:
            return False

        self._title_entry.set_text(self._recording.title or self._recording.filename)
        self._update_metadata()
        return False

    def _show_error(self, error: str) -> bool:
        """Show error message in transcript area."""
        self._transcript_buffer.set_text(f"Error loading recording: {error}")
        return False

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

        self._metadata_label.set_text("  \u2022  ".join(metadata_parts))

    def _display_transcript(self) -> bool:
        """Display the transcript with formatting."""
        if not self._transcription:
            self._transcript_buffer.set_text("No transcript available")
            return False

        self._word_positions.clear()
        self._transcript_buffer.set_text("")

        iter_pos = self._transcript_buffer.get_start_iter()
        current_speaker = None

        for segment in self._transcription.segments:
            # Add speaker label if changed
            if segment.speaker and segment.speaker != current_speaker:
                current_speaker = segment.speaker
                if self._transcript_buffer.get_char_count() > 0:
                    self._transcript_buffer.insert(iter_pos, "\n\n")

                self._transcript_buffer.insert_with_tags(
                    iter_pos, segment.speaker, self._speaker_tag
                )

                # Add timestamp
                timestamp = self._format_timestamp(segment.start)
                self._transcript_buffer.insert_with_tags(
                    iter_pos, f"  [{timestamp}]", self._timestamp_tag
                )
                self._transcript_buffer.insert(iter_pos, "\n")

            # Add segment text with word tracking
            if segment.words:
                for i, word in enumerate(segment.words):
                    start_offset = iter_pos.get_offset()

                    # Add space before word (except first)
                    if i > 0:
                        self._transcript_buffer.insert_with_tags(
                            iter_pos, " ", self._text_tag
                        )
                        start_offset = iter_pos.get_offset()

                    self._transcript_buffer.insert_with_tags(
                        iter_pos, word.word.lstrip(), self._text_tag
                    )
                    end_offset = iter_pos.get_offset()

                    # Store word position for click-to-seek
                    self._word_positions.append(
                        (start_offset, end_offset, word.start, word.end)
                    )
            else:
                # No word-level data, just insert segment text
                if segment.text:
                    self._transcript_buffer.insert_with_tags(
                        iter_pos, segment.text, self._text_tag
                    )

            # Add line break after segment
            self._transcript_buffer.insert(iter_pos, "\n")

        return False

    def _on_transcript_click(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        """Handle click on transcript to seek to word."""
        # Get buffer coordinates
        buffer_x, buffer_y = self._transcript_view.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT, int(x), int(y)
        )

        # Get iter at click position
        result = self._transcript_view.get_iter_at_location(buffer_x, buffer_y)
        if result[0]:  # result is (success, iter)
            click_offset = result[1].get_offset()

            # Find word at position
            for start_offset, end_offset, start_time, end_time in self._word_positions:
                if start_offset <= click_offset <= end_offset:
                    # Seek to word start time
                    self._audio_player.seek_seconds(start_time)
                    if not self._audio_player.is_playing():
                        self._audio_player.play()
                    break

    def _on_playback_position_changed(self, position_ms: int) -> None:
        """Handle playback position change for word highlighting."""
        position_sec = position_ms / 1000.0

        # Remove previous highlight
        start_iter = self._transcript_buffer.get_start_iter()
        end_iter = self._transcript_buffer.get_end_iter()
        self._transcript_buffer.remove_tag(self._highlight_tag, start_iter, end_iter)

        # Find and highlight current word
        for start_offset, end_offset, start_time, end_time in self._word_positions:
            if start_time <= position_sec <= end_time:
                # Highlight this word
                word_start = self._transcript_buffer.get_iter_at_offset(start_offset)
                word_end = self._transcript_buffer.get_iter_at_offset(end_offset)
                self._transcript_buffer.apply_tag(
                    self._highlight_tag, word_start, word_end
                )

                # Scroll to show highlighted word
                self._transcript_view.scroll_to_iter(word_start, 0.1, False, 0, 0.5)
                break

    def _on_title_changed(self) -> None:
        """Handle title edit completion."""
        new_title = self._title_entry.get_text().strip()
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
            # Notify about update with new title
            if self._update_callback:
                GLib.idle_add(self._update_callback, self._recording_id, title)
        except Exception as e:
            logger.error(f"Failed to save title: {e}")

    def _confirm_delete(self) -> None:
        """Show delete confirmation dialog."""
        dialog = Adw.MessageDialog.new(
            self,
            "Delete Recording?",
            "Are you sure you want to delete this recording?\n\n"
            "This action cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_delete_response)
        dialog.present()

    def _on_delete_response(self, dialog: Adw.MessageDialog, response: str) -> None:
        """Handle delete confirmation response."""
        if response == "delete":
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

            # Emit deletion callback
            if self._deletion_callback:
                GLib.idle_add(self._deletion_callback, self._recording_id)

            # Close dialog
            GLib.idle_add(self.close)

        except Exception as e:
            logger.error(f"Failed to delete recording: {e}")
            GLib.idle_add(self._show_delete_error, str(e))

    def _show_delete_error(self, error: str) -> bool:
        """Show delete error dialog."""
        dialog = Adw.MessageDialog.new(
            self,
            "Delete Failed",
            f"Failed to delete recording:\n{error}",
        )
        dialog.add_response("ok", "OK")
        dialog.present()
        return False

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

    def do_close_request(self) -> bool:
        """Handle window close."""
        self._audio_player.cleanup()
        return False  # Allow close
