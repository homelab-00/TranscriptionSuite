"""
Audio player widget for Audio Notebook.

Provides audio playback controls with seek functionality
using Qt's multimedia framework.
"""

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AudioPlayer(QWidget):
    """
    Audio playback widget with transport controls.

    Provides play/pause, seek, skip forward/back, and volume controls.
    Emits position updates for transcript synchronization.
    """

    # Signal emitted on position change (in milliseconds)
    position_changed = pyqtSignal(int)

    # Signal emitted when playback starts/stops
    playing_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)

        # Default volume
        self._audio_output.setVolume(0.8)

        self._duration_ms = 0
        self._is_seeking = False

        self._setup_ui()
        self._apply_styles()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Set up the audio player UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Seek slider
        slider_container = QWidget()
        slider_layout = QHBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(8)

        self._current_time_label = QLabel("0:00")
        self._current_time_label.setObjectName("timeLabel")
        self._current_time_label.setFixedWidth(50)
        slider_layout.addWidget(self._current_time_label)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setObjectName("seekSlider")
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        slider_layout.addWidget(self._seek_slider, 1)

        self._duration_label = QLabel("0:00")
        self._duration_label.setObjectName("timeLabel")
        self._duration_label.setFixedWidth(50)
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        slider_layout.addWidget(self._duration_label)

        layout.addWidget(slider_container)

        # Transport controls
        controls_container = QWidget()
        controls_layout = QHBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        controls_layout.addStretch()

        # Skip backward button
        self._skip_back_btn = QPushButton("↺")
        self._skip_back_btn.setObjectName("skipButton")
        self._skip_back_btn.setFixedSize(36, 36)
        self._skip_back_btn.setToolTip("-10s")
        self._skip_back_btn.clicked.connect(self._skip_backward)
        controls_layout.addWidget(self._skip_back_btn)

        # Play/Pause button
        self._play_pause_btn = QPushButton("▶")
        self._play_pause_btn.setObjectName("playButton")
        self._play_pause_btn.setFixedSize(48, 48)
        self._play_pause_btn.clicked.connect(self._toggle_play_pause)
        controls_layout.addWidget(self._play_pause_btn)

        # Skip forward button
        self._skip_forward_btn = QPushButton("↻")
        self._skip_forward_btn.setObjectName("skipButton")
        self._skip_forward_btn.setFixedSize(36, 36)
        self._skip_forward_btn.setToolTip("+10s")
        self._skip_forward_btn.clicked.connect(self._skip_forward)
        controls_layout.addWidget(self._skip_forward_btn)

        controls_layout.addStretch()

        # Volume control
        volume_label = QLabel("◉")
        volume_label.setObjectName("volumeIcon")
        controls_layout.addWidget(volume_label)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setObjectName("volumeSlider")
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(80)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self._volume_slider)

        layout.addWidget(controls_container)

    def _apply_styles(self) -> None:
        """Apply styling to audio player components."""
        self.setStyleSheet("""
            #timeLabel {
                color: #a0a0a0;
                font-size: 12px;
                font-family: monospace;
            }

            #seekSlider {
                height: 20px;
            }

            #seekSlider::groove:horizontal {
                background-color: #2d2d2d;
                height: 6px;
                border-radius: 3px;
            }

            #seekSlider::handle:horizontal {
                background-color: #0AFCCF;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }

            #seekSlider::handle:horizontal:hover {
                background-color: #08d9b3;
            }

            #seekSlider::sub-page:horizontal {
                background-color: #0AFCCF;
                border-radius: 3px;
            }

            #skipButton {
                background-color: transparent;
                border: none;
                border-radius: 18px;
                color: #a0a0a0;
                font-size: 20px;
            }

            #skipButton:hover {
                color: #0AFCCF;
            }

            #playButton {
                background-color: #0AFCCF;
                border: none;
                border-radius: 24px;
                color: #121212;
                font-size: 18px;
                font-weight: bold;
            }

            #playButton:hover {
                background-color: #08d9b3;
            }

            #volumeIcon {
                color: #a0a0a0;
                font-size: 14px;
            }

            #volumeSlider {
                height: 20px;
            }

            #volumeSlider::groove:horizontal {
                background-color: #2d2d2d;
                height: 4px;
                border-radius: 2px;
            }

            #volumeSlider::handle:horizontal {
                background-color: #0AFCCF;
                width: 10px;
                height: 10px;
                margin: -3px 0;
                border-radius: 5px;
            }

            #volumeSlider::sub-page:horizontal {
                background-color: #606060;
                border-radius: 2px;
            }
        """)

    def _connect_signals(self) -> None:
        """Connect media player signals."""
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.errorOccurred.connect(self._on_error)

        # Seek slider signals
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)

    def load(self, url: str) -> None:
        """
        Load audio from URL.

        Args:
            url: Audio file URL (can be local file or HTTP URL)
        """
        logger.debug(f"Loading audio: {url}")
        self._player.setSource(QUrl(url))
        self._play_pause_btn.setText("▶")

    def play(self) -> None:
        """Start playback."""
        self._player.play()

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()

    def stop(self) -> None:
        """Stop playback."""
        self._player.stop()

    def seek(self, position_ms: int) -> None:
        """
        Seek to position.

        Args:
            position_ms: Position in milliseconds
        """
        self._player.setPosition(position_ms)

    def seek_seconds(self, seconds: float) -> None:
        """
        Seek to position in seconds.

        Args:
            seconds: Position in seconds
        """
        self.seek(int(seconds * 1000))

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def get_position_ms(self) -> int:
        """Get current position in milliseconds."""
        return self._player.position()

    def get_duration_ms(self) -> int:
        """Get total duration in milliseconds."""
        return self._duration_ms

    def _toggle_play_pause(self) -> None:
        """Toggle between play and pause."""
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def _skip_backward(self) -> None:
        """Skip backward 10 seconds."""
        new_pos = max(0, self._player.position() - 10000)
        self._player.setPosition(new_pos)

    def _skip_forward(self) -> None:
        """Skip forward 10 seconds."""
        new_pos = min(self._duration_ms, self._player.position() + 10000)
        self._player.setPosition(new_pos)

    def _on_volume_changed(self, value: int) -> None:
        """Handle volume slider change."""
        self._audio_output.setVolume(value / 100.0)

    def _on_position_changed(self, position: int) -> None:
        """Handle playback position change."""
        # Update time label
        self._current_time_label.setText(self._format_time(position))

        # Update slider (unless user is dragging)
        if not self._is_seeking and self._duration_ms > 0:
            slider_pos = int((position / self._duration_ms) * 1000)
            self._seek_slider.setValue(slider_pos)

        # Emit signal for transcript sync
        self.position_changed.emit(position)

    def _on_duration_changed(self, duration: int) -> None:
        """Handle duration change when media loads."""
        self._duration_ms = duration
        self._duration_label.setText(self._format_time(duration))
        logger.debug(f"Audio duration: {duration}ms")

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        """Handle playback state changes."""
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_pause_btn.setText("⏸" if is_playing else "▶")
        self.playing_changed.emit(is_playing)

    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        """Handle media player errors."""
        logger.error(f"Media player error: {error} - {message}")

    def _on_slider_pressed(self) -> None:
        """Handle slider press (start seeking)."""
        self._is_seeking = True

    def _on_slider_released(self) -> None:
        """Handle slider release (finish seeking)."""
        self._is_seeking = False
        if self._duration_ms > 0:
            position = int((self._seek_slider.value() / 1000.0) * self._duration_ms)
            self._player.setPosition(position)

    def _on_slider_moved(self, value: int) -> None:
        """Handle slider movement during seek."""
        if self._duration_ms > 0:
            position = int((value / 1000.0) * self._duration_ms)
            self._current_time_label.setText(self._format_time(position))

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
        self._player.stop()
        self._player.setSource(QUrl())
