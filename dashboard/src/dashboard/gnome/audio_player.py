"""
Audio player widget for Audio Notebook (GNOME/GTK4 version).

Provides audio playback controls with seek functionality
using GStreamer.
"""

import logging
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst, Gtk

logger = logging.getLogger(__name__)

# Initialize GStreamer
Gst.init(None)


class AudioPlayer(Gtk.Box):
    """
    Audio playback widget with transport controls.

    Provides play/pause, seek, skip forward/back, and volume controls.
    Emits position updates for transcript synchronization.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self._player = Gst.ElementFactory.make("playbin", "player")
        if not self._player:
            logger.error("Failed to create GStreamer playbin")
            return

        self._duration_ns = 0
        self._is_seeking = False
        self._position_callback: Callable[[int], None] | None = None
        self._playing_callback: Callable[[bool], None] | None = None

        # Set up GStreamer bus for messages
        bus = self._player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        self._setup_ui()
        self._apply_styles()

        # Start position update timer
        GLib.timeout_add(100, self._update_position)

    def _setup_ui(self) -> None:
        """Set up the audio player UI."""
        # Seek slider row
        slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._current_time_label = Gtk.Label(label="0:00")
        self._current_time_label.add_css_class("time-label")
        self._current_time_label.set_width_chars(6)
        slider_box.append(self._current_time_label)

        self._seek_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 1000, 1
        )
        self._seek_scale.set_draw_value(False)
        self._seek_scale.set_hexpand(True)
        self._seek_scale.add_css_class("seek-scale")
        self._seek_scale.connect("value-changed", self._on_seek_changed)
        self._seek_scale.connect("button-press-event", self._on_seek_press)
        self._seek_scale.connect("button-release-event", self._on_seek_release)
        slider_box.append(self._seek_scale)

        self._duration_label = Gtk.Label(label="0:00")
        self._duration_label.add_css_class("time-label")
        self._duration_label.set_width_chars(6)
        self._duration_label.set_xalign(1.0)
        slider_box.append(self._duration_label)

        self.append(slider_box)

        # Transport controls
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls_box.set_halign(Gtk.Align.CENTER)

        # Skip backward button
        self._skip_back_btn = Gtk.Button(label="-10s")
        self._skip_back_btn.add_css_class("transport-button")
        self._skip_back_btn.connect("clicked", lambda _: self._skip_backward())
        controls_box.append(self._skip_back_btn)

        # Play/Pause button
        self._play_pause_btn = Gtk.Button()
        self._play_pause_btn.set_icon_name("media-playback-start-symbolic")
        self._play_pause_btn.add_css_class("play-button")
        self._play_pause_btn.connect("clicked", lambda _: self._toggle_play_pause())
        controls_box.append(self._play_pause_btn)

        # Skip forward button
        self._skip_forward_btn = Gtk.Button(label="+10s")
        self._skip_forward_btn.add_css_class("transport-button")
        self._skip_forward_btn.connect("clicked", lambda _: self._skip_forward())
        controls_box.append(self._skip_forward_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls_box.append(spacer)

        # Volume control
        volume_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        volume_icon.add_css_class("volume-icon")
        controls_box.append(volume_icon)

        self._volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self._volume_scale.set_value(80)
        self._volume_scale.set_draw_value(False)
        self._volume_scale.set_size_request(80, -1)
        self._volume_scale.add_css_class("volume-scale")
        self._volume_scale.connect("value-changed", self._on_volume_changed)
        controls_box.append(self._volume_scale)

        self.append(controls_box)

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css = b"""
        .time-label {
            color: #a0a0a0;
            font-size: 12px;
            font-family: monospace;
        }

        .seek-scale {
            margin: 4px 0;
        }

        .seek-scale trough {
            background-color: #2d2d2d;
            min-height: 6px;
            border-radius: 3px;
        }

        .seek-scale highlight {
            background-color: #90caf9;
            border-radius: 3px;
        }

        .seek-scale slider {
            background-color: #90caf9;
            min-width: 14px;
            min-height: 14px;
            border-radius: 7px;
        }

        .seek-scale slider:hover {
            background-color: #42a5f5;
        }

        .transport-button {
            background: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            color: #ffffff;
            padding: 8px 16px;
            font-size: 12px;
        }

        .transport-button:hover {
            background: #3d3d3d;
            border-color: #4d4d4d;
        }

        .play-button {
            background: #90caf9;
            border: none;
            border-radius: 24px;
            color: #121212;
            min-width: 48px;
            min-height: 48px;
        }

        .play-button:hover {
            background: #42a5f5;
        }

        .volume-icon {
            color: #a0a0a0;
        }

        .volume-scale {
            margin: 0 4px;
        }

        .volume-scale trough {
            background-color: #2d2d2d;
            min-height: 4px;
            border-radius: 2px;
        }

        .volume-scale highlight {
            background-color: #606060;
            border-radius: 2px;
        }

        .volume-scale slider {
            background-color: #90caf9;
            min-width: 10px;
            min-height: 10px;
            border-radius: 5px;
        }
        """

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def connect_position_changed(self, callback: Callable[[int], None]) -> None:
        """Connect callback for position changes (in milliseconds)."""
        self._position_callback = callback

    def connect_playing_changed(self, callback: Callable[[bool], None]) -> None:
        """Connect callback for play state changes."""
        self._playing_callback = callback

    def load(self, url: str) -> None:
        """
        Load audio from URL.

        Args:
            url: Audio file URL (can be local file or HTTP URL)
        """
        logger.debug(f"Loading audio: {url}")
        self._player.set_state(Gst.State.NULL)
        self._player.set_property("uri", url)
        self._play_pause_btn.set_icon_name("media-playback-start-symbolic")

    def play(self) -> None:
        """Start playback."""
        self._player.set_state(Gst.State.PLAYING)
        self._play_pause_btn.set_icon_name("media-playback-pause-symbolic")
        if self._playing_callback:
            self._playing_callback(True)

    def pause(self) -> None:
        """Pause playback."""
        self._player.set_state(Gst.State.PAUSED)
        self._play_pause_btn.set_icon_name("media-playback-start-symbolic")
        if self._playing_callback:
            self._playing_callback(False)

    def stop(self) -> None:
        """Stop playback."""
        self._player.set_state(Gst.State.NULL)
        self._play_pause_btn.set_icon_name("media-playback-start-symbolic")
        if self._playing_callback:
            self._playing_callback(False)

    def seek(self, position_ms: int) -> None:
        """
        Seek to position.

        Args:
            position_ms: Position in milliseconds
        """
        position_ns = position_ms * Gst.MSECOND
        self._player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            position_ns,
        )

    def seek_seconds(self, seconds: float) -> None:
        """
        Seek to position in seconds.

        Args:
            seconds: Position in seconds
        """
        self.seek(int(seconds * 1000))

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        _, state, _ = self._player.get_state(Gst.CLOCK_TIME_NONE)
        return state == Gst.State.PLAYING

    def get_position_ms(self) -> int:
        """Get current position in milliseconds."""
        success, position = self._player.query_position(Gst.Format.TIME)
        if success:
            return position // Gst.MSECOND
        return 0

    def get_duration_ms(self) -> int:
        """Get total duration in milliseconds."""
        return self._duration_ns // Gst.MSECOND if self._duration_ns > 0 else 0

    def _toggle_play_pause(self) -> None:
        """Toggle between play and pause."""
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def _skip_backward(self) -> None:
        """Skip backward 10 seconds."""
        new_pos = max(0, self.get_position_ms() - 10000)
        self.seek(new_pos)

    def _skip_forward(self) -> None:
        """Skip forward 10 seconds."""
        duration = self.get_duration_ms()
        if duration > 0:
            new_pos = min(duration, self.get_position_ms() + 10000)
            self.seek(new_pos)

    def _on_volume_changed(self, scale: Gtk.Scale) -> None:
        """Handle volume slider change."""
        volume = scale.get_value() / 100.0
        self._player.set_property("volume", volume)

    def _on_seek_press(self, scale, event) -> None:
        """Handle seek slider press."""
        self._is_seeking = True

    def _on_seek_release(self, scale, event) -> None:
        """Handle seek slider release."""
        self._is_seeking = False

    def _on_seek_changed(self, scale: Gtk.Scale) -> None:
        """Handle seek slider value change."""
        if self._is_seeking and self._duration_ns > 0:
            value = scale.get_value()
            position_ns = int((value / 1000.0) * self._duration_ns)
            self._player.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                position_ns,
            )

    def _update_position(self) -> bool:
        """Update position display (called periodically)."""
        if not self._player:
            return False

        # Get current position
        success, position = self._player.query_position(Gst.Format.TIME)
        if success and not self._is_seeking:
            position_ms = position // Gst.MSECOND
            self._current_time_label.set_text(self._format_time(position_ms))

            # Update slider
            if self._duration_ns > 0:
                slider_value = (position / self._duration_ns) * 1000
                self._seek_scale.set_value(slider_value)

            # Emit position callback
            if self._position_callback:
                self._position_callback(position_ms)

        return True  # Continue timer

    def _on_bus_message(self, bus, message) -> None:
        """Handle GStreamer bus messages."""
        if message.type == Gst.MessageType.DURATION_CHANGED:
            # Query new duration
            success, duration = self._player.query_duration(Gst.Format.TIME)
            if success:
                self._duration_ns = duration
                duration_ms = duration // Gst.MSECOND
                self._duration_label.set_text(self._format_time(duration_ms))
                logger.debug(f"Audio duration: {duration_ms}ms")

        elif message.type == Gst.MessageType.EOS:
            # End of stream
            self._player.set_state(Gst.State.PAUSED)
            self.seek(0)
            self._play_pause_btn.set_icon_name("media-playback-start-symbolic")
            if self._playing_callback:
                self._playing_callback(False)

        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"GStreamer error: {err.message} ({debug})")

        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._player:
                old_state, new_state, pending = message.parse_state_changed()
                if new_state == Gst.State.PLAYING:
                    # Query duration when playback starts
                    success, duration = self._player.query_duration(Gst.Format.TIME)
                    if success and duration > 0:
                        self._duration_ns = duration
                        duration_ms = duration // Gst.MSECOND
                        self._duration_label.set_text(self._format_time(duration_ms))

    @staticmethod
    def _format_time(ms: int) -> str:
        """Format milliseconds as M:SS or H:MM:SS."""
        total_seconds = ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._player:
            self._player.set_state(Gst.State.NULL)
