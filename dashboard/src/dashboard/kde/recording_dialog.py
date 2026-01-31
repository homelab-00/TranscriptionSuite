"""
Recording dialog for Audio Notebook.

Displays a recording with transcript, audio playback, and AI features.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import (
    QEvent,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dashboard.common.models import Recording, Segment, Transcription, Word
from dashboard.kde.audio_player import AudioPlayer

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class ChatBubble(QWidget):
    """Chat bubble with hover copy button."""

    def __init__(self, role: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._role = role
        self._text = text
        self.setMouseTracking(True)
        # Let the bubble size to its contents while still allowing word-wrap.
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._bubble_frame = QFrame()
        # Ensure stylesheet background/border-radius are painted for this frame.
        self._bubble_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._bubble_frame.setFrameShape(QFrame.Shape.NoFrame)
        self._bubble_frame.setObjectName(
            "chatBubbleUser" if role == "user" else "chatBubbleAssistant"
        )
        self._bubble_frame.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self._bubble_frame.setMaximumWidth(260)
        self.setMaximumWidth(self._bubble_frame.maximumWidth())

        bubble_layout = QVBoxLayout(self._bubble_frame)
        bubble_layout.setContentsMargins(10, 8, 10, 8)
        bubble_layout.setSpacing(4)

        self._copy_btn = QPushButton("Copy", self._bubble_frame)
        self._copy_btn.setObjectName("chatCopyButton")
        self._copy_btn.clicked.connect(self._copy_text)
        self._copy_btn.hide()

        self._label = QLabel()
        self._label.setObjectName(
            "chatBubbleTextUser" if role == "user" else "chatBubbleTextAssistant"
        )
        self._label.setWordWrap(True)
        self._label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self._label.setMaximumWidth(240)
        bubble_layout.addWidget(self._label)

        outer.addWidget(self._bubble_frame)
        self._render_text(text)
        self._position_copy_button()

    def update_text(self, text: str) -> None:
        self._text = text
        self._render_text(text)

    def get_text(self) -> str:
        return self._text

    def enterEvent(self, event) -> None:
        self._position_copy_button()
        self._copy_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._copy_btn.hide()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_copy_button()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position_copy_button()

    def _position_copy_button(self) -> None:
        if not self._copy_btn or not self._bubble_frame:
            return
        padding = 6
        size = self._copy_btn.sizeHint()
        x = max(self._bubble_frame.width() - size.width() - padding, padding)
        y = padding
        self._copy_btn.setGeometry(x, y, size.width(), size.height())
        self._copy_btn.raise_()

    def _render_text(self, text: str) -> None:
        if not text:
            self._label.setText("")
            self._label.setTextFormat(Qt.TextFormat.PlainText)
            return
        try:
            import markdown

            html = markdown.markdown(
                text,
                extensions=["fenced_code", "sane_lists", "nl2br", "tables"],
            )
            self._label.setTextFormat(Qt.TextFormat.RichText)
            self._label.setText(html)
        except Exception:
            self._label.setTextFormat(Qt.TextFormat.PlainText)
            self._label.setText(text)

    def _copy_text(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._text)


class RecordingDialog(QWidget):
    """
    Dialog for viewing and playing a recording.

    Features:
    - Audio playback with seek
    - Transcript display with speaker labels
    - Word-level click-to-seek
    - Title editing
    - AI summary generation (inline)
    """

    # Signal emitted when recording is deleted
    recording_deleted = pyqtSignal(int)  # recording_id
    # Signal emitted when recording is updated (recording_id, title)
    recording_updated = pyqtSignal(int, str)  # recording_id, title
    # Signal emitted when the view should close
    close_requested = pyqtSignal()

    _THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

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

        # Summary state
        self._summary_raw = ""
        self._summary_text = ""
        self._summary_streaming = False
        self._summary_task: asyncio.Task | None = None
        self._summary_dirty = False
        self._summary_save_timer = QTimer(self)
        self._summary_save_timer.setSingleShot(True)
        self._summary_save_timer.timeout.connect(self._save_summary_if_dirty)

        # LLM status
        self._lm_available = False
        self._lm_model_name: str | None = None

        # Chat state
        self._chat_conversations: list[dict] = []
        self._active_conversation_id: int | None = None
        self._chat_streaming = False
        self._chat_streaming_label: ChatBubble | None = None
        self._chat_opacity_effect: QGraphicsOpacityEffect | None = None
        self._chat_fade_anim: QPropertyAnimation | None = None

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
        self.setObjectName("recordingView")
        self.setMinimumSize(600, 500)
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
        content_widget.setObjectName("recordingContent")
        self._content_widget = content_widget
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 16, 24, 24)
        content_layout.setSpacing(16)
        self._content_layout = content_layout

        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        # Audio player
        self._audio_player = AudioPlayer()
        self._audio_player.position_changed.connect(self._on_playback_position_changed)
        main_layout.addWidget(self._audio_player)

        # AI Summary panel
        self._summary_panel = QFrame()
        self._summary_panel.setObjectName("summaryPanel")
        summary_layout = QVBoxLayout(self._summary_panel)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(8)

        summary_header = QWidget()
        summary_header.setObjectName("summaryHeader")
        summary_header_layout = QHBoxLayout(summary_header)
        summary_header_layout.setContentsMargins(0, 0, 0, 0)
        summary_header_layout.setSpacing(8)

        self._summary_title_label = QLabel("AI Summary")
        self._summary_title_label.setObjectName("summaryTitle")
        summary_header_layout.addWidget(self._summary_title_label)

        self._summary_model_label = QLabel("")
        self._summary_model_label.setObjectName("summaryModel")
        summary_header_layout.addWidget(self._summary_model_label)
        summary_header_layout.addStretch()

        self._summary_stop_btn = QPushButton("Stop")
        self._summary_stop_btn.setObjectName("summaryActionButton")
        self._summary_stop_btn.clicked.connect(self._on_summary_stop_clicked)
        self._summary_stop_btn.hide()
        summary_header_layout.addWidget(self._summary_stop_btn)

        self._summary_regen_btn = QPushButton("Regenerate")
        self._summary_regen_btn.setObjectName("summaryActionButton")
        self._summary_regen_btn.clicked.connect(self._on_summarize_clicked)
        summary_header_layout.addWidget(self._summary_regen_btn)

        self._summary_clear_btn = QPushButton("Clear")
        self._summary_clear_btn.setObjectName("summaryActionButton")
        self._summary_clear_btn.clicked.connect(self._on_clear_summary_clicked)
        summary_header_layout.addWidget(self._summary_clear_btn)

        summary_layout.addWidget(summary_header)

        self._summary_stack = QStackedWidget()
        self._summary_display = QTextEdit()
        self._summary_display.setObjectName("summaryDisplay")
        self._summary_display.setReadOnly(True)
        self._summary_display.setAcceptRichText(True)
        self._summary_display.mousePressEvent = self._on_summary_display_clicked
        self._summary_stack.addWidget(self._summary_display)

        self._summary_edit = QTextEdit()
        self._summary_edit.setObjectName("summaryEdit")
        self._summary_edit.setAcceptRichText(False)
        self._summary_edit.textChanged.connect(self._on_summary_text_changed)
        self._summary_edit.installEventFilter(self)
        self._summary_stack.addWidget(self._summary_edit)

        summary_layout.addWidget(self._summary_stack)

        self._summary_status_label = QLabel("")
        self._summary_status_label.setObjectName("summaryStatus")
        self._summary_status_label.hide()
        summary_layout.addWidget(self._summary_status_label)

        self._summary_hint_label = QLabel("Click to edit")
        self._summary_hint_label.setObjectName("summaryHint")
        summary_layout.addWidget(self._summary_hint_label)

        self._summary_panel.hide()
        main_layout.addWidget(self._summary_panel)

        # Transcript section
        transcript_header = QWidget()
        transcript_header_layout = QHBoxLayout(transcript_header)
        transcript_header_layout.setContentsMargins(0, 0, 0, 0)
        transcript_header_layout.setSpacing(12)

        transcript_title = QLabel("Transcript")
        transcript_title.setObjectName("sectionTitle")
        transcript_header_layout.addWidget(transcript_title)

        transcript_header_layout.addStretch()

        # LM Studio status indicator
        self._lm_status_dot = QLabel("●")
        self._lm_status_dot.setObjectName("lmStatusDot")
        self._lm_status_dot.setFixedWidth(12)
        transcript_header_layout.addWidget(self._lm_status_dot)

        self._lm_status_label = QLabel("LM Studio")
        self._lm_status_label.setObjectName("lmStatusLabel")
        transcript_header_layout.addWidget(self._lm_status_label)

        # Chat button
        self._chat_btn = QPushButton("💬 Chat")
        self._chat_btn.setObjectName("lmButton")
        self._chat_btn.setToolTip("Chat with AI about this transcript")
        self._chat_btn.clicked.connect(self._on_chat_clicked)
        transcript_header_layout.addWidget(self._chat_btn)

        # Summarize button
        self._summarize_btn = QPushButton("✨ Summarize")
        self._summarize_btn.setObjectName("lmButton")
        self._summarize_btn.setToolTip("Generate AI summary")
        self._summarize_btn.clicked.connect(self._on_summarize_clicked)
        transcript_header_layout.addWidget(self._summarize_btn)

        main_layout.addWidget(transcript_header)

        # Transcript text area
        self._transcript_edit = QTextEdit()
        self._transcript_edit.setObjectName("transcriptEdit")
        self._transcript_edit.setReadOnly(True)
        self._transcript_edit.setAcceptRichText(True)
        self._transcript_edit.mousePressEvent = self._on_transcript_click
        main_layout.addWidget(self._transcript_edit, 1)

        content_layout.addWidget(main_panel, 1)

        # Chat sidebar (hidden by default)
        self._chat_panel = QFrame()
        self._chat_panel.setObjectName("chatPanel")
        self._chat_panel.setFixedWidth(360)
        self._chat_panel.hide()
        chat_layout = QVBoxLayout(self._chat_panel)
        chat_layout.setContentsMargins(12, 12, 12, 12)
        chat_layout.setSpacing(8)

        chat_header = QWidget()
        chat_header.setObjectName("chatHeader")
        chat_header_layout = QHBoxLayout(chat_header)
        chat_header_layout.setContentsMargins(0, 0, 0, 0)
        chat_header_layout.setSpacing(8)

        chat_title = QLabel("AI Chat")
        chat_title.setObjectName("chatTitle")
        chat_header_layout.addWidget(chat_title)
        chat_header_layout.addStretch()

        self._chat_import_btn = QPushButton("Import")
        self._chat_import_btn.setObjectName("chatActionButton")
        self._chat_import_btn.clicked.connect(self._on_import_chat_clicked)
        chat_header_layout.addWidget(self._chat_import_btn)

        self._chat_export_btn = QPushButton("Export")
        self._chat_export_btn.setObjectName("chatActionButton")
        self._chat_export_btn.clicked.connect(self._on_export_chat_clicked)
        chat_header_layout.addWidget(self._chat_export_btn)

        self._chat_close_btn = QPushButton("Close")
        self._chat_close_btn.setObjectName("chatCloseButton")
        self._chat_close_btn.clicked.connect(self._toggle_chat_panel)
        chat_header_layout.addWidget(self._chat_close_btn)

        chat_layout.addWidget(chat_header)

        chat_status_row = QWidget()
        chat_status_row.setObjectName("chatStatusRow")
        chat_status_layout = QHBoxLayout(chat_status_row)
        chat_status_layout.setContentsMargins(0, 0, 0, 0)
        chat_status_layout.setSpacing(6)

        self._chat_status_dot = QLabel("●")
        self._chat_status_dot.setObjectName("chatStatusDot")
        self._chat_status_dot.setFixedWidth(10)
        chat_status_layout.addWidget(self._chat_status_dot)

        self._chat_status_label = QLabel("LM Studio")
        self._chat_status_label.setObjectName("chatStatusLabel")
        chat_status_layout.addWidget(self._chat_status_label)
        chat_status_layout.addStretch()

        self._chat_refresh_btn = QPushButton("Refresh")
        self._chat_refresh_btn.setObjectName("chatActionButton")
        self._chat_refresh_btn.clicked.connect(self._check_lm_status)
        chat_status_layout.addWidget(self._chat_refresh_btn)

        chat_layout.addWidget(chat_status_row)

        # Conversations list
        convo_header = QWidget()
        convo_header.setObjectName("chatConvoHeader")
        convo_header_layout = QHBoxLayout(convo_header)
        convo_header_layout.setContentsMargins(0, 0, 0, 0)
        convo_header_layout.setSpacing(6)

        convo_label = QLabel("Conversations")
        convo_label.setObjectName("chatSectionLabel")
        convo_header_layout.addWidget(convo_label)
        convo_header_layout.addStretch()

        self._chat_delete_btn = QPushButton("Delete")
        self._chat_delete_btn.setObjectName("chatActionButton")
        self._chat_delete_btn.clicked.connect(self._on_delete_chat_clicked)
        convo_header_layout.addWidget(self._chat_delete_btn)

        self._chat_rename_btn = QPushButton("Rename")
        self._chat_rename_btn.setObjectName("chatActionButton")
        self._chat_rename_btn.clicked.connect(self._on_rename_chat_clicked)
        convo_header_layout.addWidget(self._chat_rename_btn)

        self._chat_new_btn = QPushButton("New Chat")
        self._chat_new_btn.setObjectName("chatActionButton")
        self._chat_new_btn.clicked.connect(self._on_new_chat_clicked)
        convo_header_layout.addWidget(self._chat_new_btn)

        chat_layout.addWidget(convo_header)

        self._chat_convo_list = QListWidget()
        self._chat_convo_list.setObjectName("chatConvoList")
        self._chat_convo_list.itemClicked.connect(self._on_conversation_selected)
        self._chat_convo_list.setFixedHeight(120)
        chat_layout.addWidget(self._chat_convo_list)

        # Messages area
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setObjectName("chatScroll")
        chat_layout.addWidget(self._chat_scroll, 1)

        self._chat_messages_container = QWidget()
        self._chat_messages_layout = QVBoxLayout(self._chat_messages_container)
        self._chat_messages_layout.setContentsMargins(0, 0, 0, 0)
        self._chat_messages_layout.setSpacing(6)
        self._chat_scroll.setWidget(self._chat_messages_container)

        self._chat_error_label = QLabel("")
        self._chat_error_label.setObjectName("chatErrorLabel")
        self._chat_error_label.hide()
        chat_layout.addWidget(self._chat_error_label)

        # Input area
        chat_input_row = QWidget()
        chat_input_row.setObjectName("chatInputRow")
        chat_input_layout = QHBoxLayout(chat_input_row)
        chat_input_layout.setContentsMargins(0, 0, 0, 0)
        chat_input_layout.setSpacing(6)

        self._chat_input = QTextEdit()
        self._chat_input.setObjectName("chatInput")
        self._chat_input.setFixedHeight(70)
        self._chat_input.installEventFilter(self)
        chat_input_layout.addWidget(self._chat_input, 1)

        self._chat_send_btn = QPushButton("Send")
        self._chat_send_btn.setObjectName("chatSendButton")
        self._chat_send_btn.clicked.connect(self._on_send_chat_clicked)
        chat_input_layout.addWidget(self._chat_send_btn)

        chat_layout.addWidget(chat_input_row)

        self._chat_panel.setParent(content_widget)
        self._chat_opacity_effect = QGraphicsOpacityEffect(self._chat_panel)
        self._chat_opacity_effect.setOpacity(0.0)
        self._chat_panel.setGraphicsEffect(self._chat_opacity_effect)
        # Check LM Studio status (after chat widgets exist)
        self._check_lm_status()

        layout.addWidget(content_widget, 1)

        # Footer with close button
        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 12)

        footer_layout.addStretch()

        close_btn = QPushButton("Back")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self.close_requested.emit)
        footer_layout.addWidget(close_btn)

        layout.addWidget(footer)

    def _apply_styles(self) -> None:
        """Apply styling to dialog components."""
        self.setStyleSheet("""
            #recordingView {
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
                border-color: #0AFCCF;
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
                background-color: #0AFCCF;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 500;
            }

            #primaryButton:hover {
                background-color: #08d9b3;
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

            #lmStatusDot {
                color: #606060;
                font-size: 10px;
            }

            #lmStatusLabel {
                color: #a0a0a0;
                font-size: 12px;
            }

            #lmButton {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #a0a0a0;
                padding: 4px 10px;
                font-size: 12px;
            }

            #lmButton:hover {
                background-color: #2d2d2d;
                border-color: #0AFCCF;
                color: #0AFCCF;
            }

            #lmButton:disabled {
                color: #404040;
                border-color: #2d2d2d;
            }

            #summaryPanel {
                background-color: #141414;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }

            #summaryTitle {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }

            #summaryModel {
                color: #8a8a8a;
                font-size: 11px;
            }

            #summaryDisplay, #summaryEdit {
                background-color: #0f0f0f;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #e0e0e0;
                font-size: 13px;
                padding: 8px;
            }

            #summaryActionButton {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #a0a0a0;
                padding: 4px 8px;
                font-size: 11px;
            }

            #summaryActionButton:hover {
                background-color: #2d2d2d;
                border-color: #0AFCCF;
                color: #0AFCCF;
            }

            #summaryStatus {
                color: #f0a020;
                font-size: 11px;
            }

            #summaryHint {
                color: #6a6a6a;
                font-size: 11px;
            }

            #chatPanel {
                background-color: #121212;
                border-left: 1px solid #2d2d2d;
            }

            #chatHeader, #chatStatusRow, #chatConvoHeader, #chatInputRow {
                background-color: transparent;
            }

            #chatTitle {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }

            #chatCloseButton, #chatActionButton {
                background-color: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #a0a0a0;
                padding: 4px 8px;
                font-size: 11px;
            }

            #chatCloseButton:hover, #chatActionButton:hover {
                background-color: #2d2d2d;
                border-color: #0AFCCF;
                color: #0AFCCF;
            }

            #chatStatusDot {
                color: #606060;
                font-size: 10px;
            }

            #chatStatusLabel {
                color: #a0a0a0;
                font-size: 11px;
            }

            #chatSectionLabel {
                color: #a0a0a0;
                font-size: 11px;
            }

            #chatConvoList {
                background-color: #121212;
                border: 1px solid #2d2d2d;
                color: #d0d0d0;
            }

            #chatConvoList::item {
                background-color: transparent;
            }

            #chatConvoList::item:selected {
                background-color: #1e3a5f;
                color: #ffffff;
            }

            #chatScroll {
                border: none;
                background-color: #121212;
            }

            #chatScroll QWidget#qt_scrollarea_viewport {
                background-color: #121212;
            }

            #chatInput {
                background-color: #121212;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #e0e0e0;
                font-size: 12px;
                padding: 6px;
            }

            #chatSendButton {
                background-color: #0AFCCF;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 500;
            }

            #chatSendButton:disabled {
                background-color: #2d2d2d;
                color: #5a5a5a;
            }

            #chatErrorLabel {
                color: #f44336;
                font-size: 11px;
            }

            #chatBubbleUser {
                background-color: #2b2b2b;
                border: none;
                border-radius: 6px;
            }

            #chatBubbleAssistant {
                background-color: #ff007a;
                border: none;
                border-radius: 6px;
            }

            #chatBubbleTextUser {
                background-color: transparent;
                color: #ffffff;
                font-weight: 500;
            }

            #chatBubbleTextAssistant {
                background-color: transparent;
                color: #ffffff;
            }

            /* Prevent nested widgets (labels/buttons) from painting a different background inside bubbles. */
            #chatBubbleUser *, #chatBubbleAssistant * {
                background-color: transparent;
            }

            #chatCopyButton {
                background-color: #3a3a3a;
                border: none;
                border-radius: 4px;
                color: #d6d6d6;
                padding: 2px 6px;
                font-size: 10px;
            }

            #chatCopyButton:hover {
                background-color: #4a4a4a;
                color: #0AFCCF;
            }
        """)

    def eventFilter(self, obj, event) -> bool:
        """Handle key and focus events for chat input and summary editor."""
        if (
            obj == getattr(self, "_chat_input", None)
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._on_send_chat_clicked()
                    return True

        if (
            obj == getattr(self, "_summary_edit", None)
            and event.type() == QEvent.Type.FocusOut
        ):
            self._exit_summary_edit(save=True)

        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        """Keep the chat panel overlaid on resize."""
        super().resizeEvent(event)
        self._position_chat_panel()

    def _position_chat_panel(self) -> None:
        """Position chat sidebar overlay."""
        if not hasattr(self, "_chat_panel") or self._chat_panel is None:
            return
        if not hasattr(self, "_content_widget") or self._content_widget is None:
            return
        if not self._chat_panel.isVisible():
            return
        margins = self._content_layout.contentsMargins()
        width = self._chat_panel.width()
        height = self._content_widget.height() - margins.top() - margins.bottom()
        x = self._content_widget.width() - margins.right() - width
        y = margins.top()
        self._chat_panel.setGeometry(x, y, width, max(height, 0))
        self._chat_panel.raise_()

    def _strip_think_blocks(self, text: str) -> str:
        """Remove <think> blocks from LLM output."""
        if not text:
            return ""
        lower = text.lower()
        open_idx = lower.find("<think>")
        if open_idx != -1 and lower.find("</think>", open_idx) == -1:
            text = text[:open_idx]
        cleaned = self._THINK_BLOCK_RE.sub("", text)
        cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _update_summary_display(self, text: str) -> None:
        """Render summary markdown into the display widget."""
        if not text.strip():
            self._summary_display.setPlainText("")
            return
        try:
            self._summary_display.setMarkdown(text)
        except Exception:
            self._summary_display.setPlainText(text)

    def _refresh_summary_ui(self) -> None:
        """Update summary panel visibility and controls."""
        has_summary = bool(self._summary_text.strip())
        should_show = (
            has_summary
            or self._summary_streaming
            or self._summary_status_label.isVisible()
        )
        self._summary_panel.setVisible(should_show)

        self._summary_stop_btn.setVisible(self._summary_streaming)
        self._summary_regen_btn.setEnabled(
            self._lm_available and not self._summary_streaming
        )
        self._summary_clear_btn.setEnabled(has_summary and not self._summary_streaming)
        self._summary_hint_label.setVisible(
            not self._summary_streaming
            and self._summary_stack.currentIndex() == 0
            and has_summary
        )

    def _on_summary_display_clicked(self, event) -> None:
        """Switch to edit mode when summary display is clicked."""
        if self._summary_streaming:
            return
        if not self._summary_text.strip():
            return
        self._enter_summary_edit()
        QTextEdit.mousePressEvent(self._summary_display, event)

    def _enter_summary_edit(self) -> None:
        """Show editable summary text."""
        if self._summary_streaming:
            return
        self._summary_edit.blockSignals(True)
        self._summary_edit.setPlainText(self._summary_text)
        self._summary_edit.blockSignals(False)
        self._summary_stack.setCurrentWidget(self._summary_edit)
        self._summary_hint_label.setVisible(False)
        self._summary_edit.setFocus()

    def _exit_summary_edit(self, save: bool = True) -> None:
        """Exit summary edit mode and optionally save."""
        if self._summary_stack.currentWidget() != self._summary_edit:
            return
        if save:
            self._summary_text = self._summary_edit.toPlainText().strip()
            self._update_summary_display(self._summary_text)
            self._queue_summary_save(self._summary_text)
        self._summary_stack.setCurrentWidget(self._summary_display)
        self._refresh_summary_ui()

    def _on_summary_text_changed(self) -> None:
        """Debounce summary saves while editing."""
        if self._summary_streaming:
            return
        self._summary_dirty = True
        self._summary_save_timer.start(1200)

    def _save_summary_if_dirty(self) -> None:
        """Persist summary after debounce."""
        if not self._summary_dirty or self._summary_streaming:
            return
        self._summary_dirty = False
        self._summary_text = self._summary_edit.toPlainText().strip()
        self._queue_summary_save(self._summary_text)

    def _queue_summary_save(self, text: str | None) -> None:
        """Queue summary save to the server."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._do_save_summary(text))
            else:
                loop.run_until_complete(self._do_save_summary(text))
        except RuntimeError:
            asyncio.run(self._do_save_summary(text))

    async def _do_save_summary(self, text: str | None) -> None:
        """Persist summary to the backend."""
        if not self._recording:
            return
        summary_value = text if text and text.strip() else None
        try:
            await self._api_client.update_summary(self._recording_id, summary_value)
            self._recording.summary = summary_value
            self._summary_text = summary_value or ""
            self._update_summary_display(self._summary_text)
            self._summary_status_label.hide()
            self._refresh_summary_ui()
        except Exception as e:
            logger.error(f"Failed to save summary: {e}")
            self._summary_status_label.setText("Failed to save summary.")
            self._summary_status_label.show()
            self._refresh_summary_ui()

    def _on_clear_summary_clicked(self) -> None:
        """Clear summary content."""
        if self._summary_streaming:
            return
        self._summary_text = ""
        self._summary_raw = ""
        self._summary_status_label.hide()
        self._update_summary_display("")
        self._summary_stack.setCurrentWidget(self._summary_display)
        self._queue_summary_save(None)
        self._refresh_summary_ui()

    def _on_summary_stop_clicked(self) -> None:
        """Stop summary generation."""
        if self._summary_task and not self._summary_task.done():
            self._summary_task.cancel()
        self._handle_summary_cancelled()

    def _finish_summary_stream(self, cleaned: str) -> None:
        """Finalize summary after successful streaming."""
        self._summary_streaming = False
        self._summary_text = cleaned.strip()
        self._summary_status_label.hide()
        self._summary_stack.setCurrentWidget(self._summary_display)
        self._update_summary_display(self._summary_text)
        self._refresh_summary_ui()
        self._queue_summary_save(self._summary_text if self._summary_text else None)

    def _handle_summary_error(self, error_msg: str) -> None:
        """Handle summary generation errors."""
        self._summary_streaming = False
        self._summary_status_label.setText(error_msg or "Summary generation failed.")
        self._summary_status_label.show()
        self._refresh_summary_ui()

    def _handle_summary_cancelled(self) -> None:
        """Handle summary generation cancellation."""
        self._summary_streaming = False
        self._summary_status_label.setText("Summary generation stopped.")
        self._summary_status_label.show()
        self._refresh_summary_ui()

    def _toggle_chat_panel(self) -> None:
        """Show or hide the chat sidebar."""
        if self._chat_panel.isVisible():
            self._hide_chat_panel()
        else:
            self._show_chat_panel()

    def _show_chat_panel(self) -> None:
        """Fade in the chat sidebar."""
        self._chat_panel.show()
        self._position_chat_panel()
        self._chat_panel.raise_()
        self._start_chat_fade(0.0, 1.0)
        self._load_chat_panel()

    def _hide_chat_panel(self) -> None:
        """Fade out the chat sidebar."""
        self._start_chat_fade(
            self._chat_opacity_effect.opacity() if self._chat_opacity_effect else 1.0,
            0.0,
            on_finished=self._chat_panel.hide,
        )

    def _start_chat_fade(
        self, start: float, end: float, on_finished: Callable[[], None] | None = None
    ) -> None:
        if not self._chat_opacity_effect:
            return
        if self._chat_fade_anim:
            self._chat_fade_anim.stop()
        anim = QPropertyAnimation(self._chat_opacity_effect, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        if on_finished:
            anim.finished.connect(on_finished)
        self._chat_fade_anim = anim
        anim.start()

    def _load_chat_panel(self) -> None:
        """Load chat conversations and status."""
        self._chat_error_label.hide()
        self._check_lm_status()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_load_conversations())
            else:
                loop.run_until_complete(self._async_load_conversations())
        except RuntimeError:
            asyncio.run(self._async_load_conversations())

    async def _async_load_conversations(self) -> None:
        """Fetch conversations for this recording and select the latest."""
        try:
            data = await self._api_client.get_conversations(self._recording_id)
            conversations = (
                data.get("conversations") if isinstance(data, dict) else data
            )
            self._chat_conversations = conversations or []

            self._chat_convo_list.clear()
            for convo in self._chat_conversations:
                item = QListWidgetItem(convo.get("title", "New Chat"))
                item.setData(Qt.ItemDataRole.UserRole, convo.get("id"))
                self._chat_convo_list.addItem(item)

            if self._chat_conversations:
                latest_id = self._chat_conversations[0].get("id")
                if latest_id is not None:
                    self._select_conversation_item(latest_id)
                    await self._async_load_conversation(latest_id)
            else:
                result = await self._api_client.create_conversation(
                    self._recording_id, "New Chat"
                )
                new_id = result.get("conversation_id")
                if new_id:
                    await self._async_load_conversations()
        except Exception as e:
            logger.error(f"Failed to load conversations: {e}")
            self._chat_error_label.setText("Failed to load conversations.")
            self._chat_error_label.show()

    def _select_conversation_item(self, conversation_id: int) -> None:
        """Select a conversation in the list."""
        for idx in range(self._chat_convo_list.count()):
            item = self._chat_convo_list.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == conversation_id:
                self._chat_convo_list.setCurrentItem(item)
                break

    def _on_new_chat_clicked(self) -> None:
        """Create a new chat conversation."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_create_new_chat())
            else:
                loop.run_until_complete(self._async_create_new_chat())
        except RuntimeError:
            asyncio.run(self._async_create_new_chat())

    def _on_delete_chat_clicked(self) -> None:
        """Delete the currently selected conversation."""
        if not self._active_conversation_id:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Conversation",
            "Delete this conversation and all its messages?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._async_delete_chat(self._active_conversation_id)
                )
            else:
                loop.run_until_complete(
                    self._async_delete_chat(self._active_conversation_id)
                )
        except RuntimeError:
            asyncio.run(self._async_delete_chat(self._active_conversation_id))

    def _on_rename_chat_clicked(self) -> None:
        """Rename the currently selected conversation."""
        if not self._active_conversation_id:
            return

        current_title = None
        for convo in self._chat_conversations:
            if convo.get("id") == self._active_conversation_id:
                current_title = convo.get("title", "")
                break

        new_title, ok = QInputDialog.getText(
            self,
            "Rename Conversation",
            "New title:",
            text=current_title or "",
        )
        if not ok:
            return
        new_title = new_title.strip()
        if not new_title:
            return

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._async_rename_chat(self._active_conversation_id, new_title)
                )
            else:
                loop.run_until_complete(
                    self._async_rename_chat(self._active_conversation_id, new_title)
                )
        except RuntimeError:
            asyncio.run(
                self._async_rename_chat(self._active_conversation_id, new_title)
            )

    async def _async_delete_chat(self, conversation_id: int) -> None:
        try:
            await self._api_client.delete_conversation(conversation_id)
            self._active_conversation_id = None
            await self._async_load_conversations()
        except Exception as e:
            logger.error(f"Failed to delete conversation: {e}")
            self._chat_error_label.setText("Failed to delete conversation.")
            self._chat_error_label.show()

    async def _async_rename_chat(self, conversation_id: int, title: str) -> None:
        try:
            await self._api_client.update_conversation_title(conversation_id, title)
            await self._async_load_conversations()
        except Exception as e:
            logger.error(f"Failed to rename conversation: {e}")
            self._chat_error_label.setText("Failed to rename conversation.")
            self._chat_error_label.show()

    def _on_export_chat_clicked(self) -> None:
        """Export the active conversation to JSON."""
        if not self._active_conversation_id:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Conversation",
            f"conversation_{self._active_conversation_id}.json",
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_export_chat(file_path))
            else:
                loop.run_until_complete(self._async_export_chat(file_path))
        except RuntimeError:
            asyncio.run(self._async_export_chat(file_path))

    async def _async_export_chat(self, file_path: str) -> None:
        try:
            convo = await self._api_client.get_conversation(
                self._active_conversation_id
            )
            export_data = {
                "format_version": 1,
                "recording_id": self._recording_id,
                "title": convo.get("title", "Conversation"),
                "messages": [
                    {
                        "role": msg.get("role"),
                        "content": msg.get("content"),
                        "created_at": msg.get("created_at"),
                    }
                    for msg in convo.get("messages", [])
                ],
            }
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(export_data, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to export conversation: {e}")
            self._chat_error_label.setText("Failed to export conversation.")
            self._chat_error_label.show()

    def _on_import_chat_clicked(self) -> None:
        """Import a conversation from JSON."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Conversation",
            "",
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_import_chat(file_path))
            else:
                loop.run_until_complete(self._async_import_chat(file_path))
        except RuntimeError:
            asyncio.run(self._async_import_chat(file_path))

    async def _async_import_chat(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            title = payload.get("title") or "Imported Chat"
            messages = payload.get("messages", [])
            if not isinstance(messages, list):
                raise ValueError("Invalid conversation format")

            result = await self._api_client.create_conversation(
                self._recording_id, title
            )
            conversation_id = result.get("conversation_id")
            if not conversation_id:
                raise ValueError("Failed to create conversation")

            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                if role not in ("user", "assistant", "system"):
                    continue
                await self._api_client.add_conversation_message(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                )

            await self._async_load_conversations()
            self._select_conversation_item(conversation_id)
            await self._async_load_conversation(conversation_id)
        except Exception as e:
            logger.error(f"Failed to import conversation: {e}")
            self._chat_error_label.setText("Failed to import conversation.")
            self._chat_error_label.show()

    async def _async_create_new_chat(self) -> None:
        try:
            result = await self._api_client.create_conversation(
                self._recording_id, "New Chat"
            )
            new_id = result.get("conversation_id")
            await self._async_load_conversations()
            if new_id:
                self._select_conversation_item(new_id)
                await self._async_load_conversation(new_id)
        except Exception as e:
            logger.error(f"Failed to create conversation: {e}")
            self._chat_error_label.setText("Failed to create conversation.")
            self._chat_error_label.show()

    def _on_conversation_selected(self, item: QListWidgetItem) -> None:
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if not conversation_id:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_load_conversation(conversation_id))
            else:
                loop.run_until_complete(self._async_load_conversation(conversation_id))
        except RuntimeError:
            asyncio.run(self._async_load_conversation(conversation_id))

    async def _async_load_conversation(self, conversation_id: int) -> None:
        """Load messages for the selected conversation."""
        try:
            convo = await self._api_client.get_conversation(conversation_id)
            self._active_conversation_id = conversation_id
            self._render_chat_messages(convo.get("messages", []))
            self._update_chat_controls()
        except Exception as e:
            logger.error(f"Failed to load conversation: {e}")
            self._chat_error_label.setText("Failed to load conversation.")
            self._chat_error_label.show()

    def _render_chat_messages(self, messages: list[dict]) -> None:
        """Render chat messages into the scroll area."""
        while self._chat_messages_layout.count():
            item = self._chat_messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for msg in messages:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            self._add_chat_bubble(role, content)

        self._chat_messages_layout.addStretch(1)
        self._scroll_chat_to_bottom()

    def _add_chat_bubble(self, role: str, content: str) -> ChatBubble:
        """Add a chat bubble and return its widget."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        bubble = ChatBubble(role, content)

        if role == "user":
            row_layout.addStretch()
            row_layout.addWidget(bubble)
            row_layout.setAlignment(
                bubble,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            )
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch()
            row_layout.setAlignment(
                bubble,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )

        # Keep the bottom spacer (stretch) at the end so new messages don't end up after it.
        insert_at = self._chat_messages_layout.count()
        if insert_at and self._chat_messages_layout.itemAt(insert_at - 1).spacerItem():
            self._chat_messages_layout.insertWidget(insert_at - 1, row)
        else:
            self._chat_messages_layout.addWidget(row)
        return bubble

    def _scroll_chat_to_bottom(self) -> None:
        """Scroll the chat view to the latest message."""
        QTimer.singleShot(
            0,
            lambda: self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum()
            ),
        )

    def _update_chat_controls(self) -> None:
        """Enable/disable chat controls based on status."""
        can_send = (
            self._lm_available
            and self._active_conversation_id is not None
            and not self._chat_streaming
        )
        self._chat_send_btn.setEnabled(can_send)
        self._chat_input.setEnabled(self._lm_available and not self._chat_streaming)
        self._chat_delete_btn.setEnabled(
            self._active_conversation_id is not None and not self._chat_streaming
        )
        self._chat_rename_btn.setEnabled(
            self._active_conversation_id is not None and not self._chat_streaming
        )
        self._chat_export_btn.setEnabled(
            self._active_conversation_id is not None and not self._chat_streaming
        )

    def _on_send_chat_clicked(self) -> None:
        """Send a chat message."""
        if self._chat_streaming:
            return
        if not self._active_conversation_id:
            return
        if not self._lm_available:
            self._chat_error_label.setText("LM Studio is offline.")
            self._chat_error_label.show()
            return

        message = self._chat_input.toPlainText().strip()
        if not message:
            return

        self._chat_error_label.hide()
        self._chat_input.clear()
        self._chat_streaming = True
        self._update_chat_controls()

        self._add_chat_bubble("user", message)
        self._chat_streaming_label = self._add_chat_bubble("assistant", "")
        self._scroll_chat_to_bottom()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._async_send_chat(self._active_conversation_id, message)
                )
            else:
                loop.run_until_complete(
                    self._async_send_chat(self._active_conversation_id, message)
                )
        except RuntimeError:
            asyncio.run(self._async_send_chat(self._active_conversation_id, message))

    async def _async_send_chat(self, conversation_id: int, message: str) -> None:
        """Stream a chat response."""

        def on_chunk(content: str) -> None:
            if not self._chat_streaming_label:
                return
            QTimer.singleShot(
                0,
                lambda: self._chat_streaming_label.update_text(
                    self._chat_streaming_label.get_text() + content
                ),
            )

        def on_done(_full: str) -> None:
            QTimer.singleShot(0, lambda: self._finish_chat_stream(conversation_id))

        def on_error(error_msg: str) -> None:
            QTimer.singleShot(0, lambda: self._handle_chat_error(error_msg))

        await self._api_client.chat_stream(
            conversation_id=conversation_id,
            user_message=message,
            include_transcription=True,
            on_chunk=on_chunk,
            on_done=on_done,
            on_error=on_error,
        )

    def _finish_chat_stream(self, conversation_id: int) -> None:
        """Finish streaming and refresh conversation view."""
        self._chat_streaming = False
        self._chat_streaming_label = None
        self._update_chat_controls()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_load_conversations())
            else:
                loop.run_until_complete(self._async_load_conversations())
        except RuntimeError:
            asyncio.run(self._async_load_conversations())

    def _handle_chat_error(self, error_msg: str) -> None:
        """Handle chat streaming errors."""
        self._chat_streaming = False
        self._chat_streaming_label = None
        self._chat_error_label.setText(error_msg)
        self._chat_error_label.show()
        self._update_chat_controls()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_load_conversations())
            else:
                loop.run_until_complete(self._async_load_conversations())
        except RuntimeError:
            asyncio.run(self._async_load_conversations())

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

            # Load existing summary (if any)
            self._summary_raw = self._recording.summary or ""
            self._summary_text = self._strip_think_blocks(self._summary_raw)
            self._summary_status_label.hide()
            self._summary_stack.setCurrentWidget(self._summary_display)
            self._update_summary_display(self._summary_text)
            self._refresh_summary_ui()

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
        speaker_format.setForeground(QColor("#0AFCCF"))

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

                    cursor.insertText(word.word.lstrip(), text_format)
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
            self.close_requested.emit()
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

    def _check_lm_status(self) -> None:
        """Check LM Studio connection status and update UI."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._do_check_lm_status())
            else:
                loop.run_until_complete(self._do_check_lm_status())
        except RuntimeError:
            asyncio.run(self._do_check_lm_status())

    async def _do_check_lm_status(self) -> None:
        """Perform LM Studio status check."""
        try:
            status = await self._api_client.get_llm_status()
            if status.get("available"):
                model = status.get("model", "unknown")
                self._lm_available = True
                self._lm_model_name = model
                self._lm_status_dot.setStyleSheet("color: #0AFCCF;")
                self._lm_status_label.setText(f"LM Studio: {model}")
                self._chat_btn.setEnabled(True)
                self._summarize_btn.setEnabled(True)
                self._summary_model_label.setText(model)
                self._chat_status_dot.setStyleSheet("color: #0AFCCF;")
                self._chat_status_label.setText(f"LM Studio: {model}")
            else:
                self._lm_available = False
                self._lm_model_name = None
                self._lm_status_dot.setStyleSheet("color: #606060;")
                self._lm_status_label.setText("LM Studio: Offline")
                self._chat_btn.setEnabled(False)
                self._summarize_btn.setEnabled(False)
                self._summary_model_label.setText("")
                self._chat_status_dot.setStyleSheet("color: #606060;")
                self._chat_status_label.setText("LM Studio: Offline")
        except Exception as e:
            logger.debug(f"LM Studio status check failed: {e}")
            self._lm_available = False
            self._lm_model_name = None
            self._lm_status_dot.setStyleSheet("color: #606060;")
            self._lm_status_label.setText("LM Studio: Offline")
            self._chat_btn.setEnabled(False)
            self._summarize_btn.setEnabled(False)
            self._summary_model_label.setText("")
            self._chat_status_dot.setStyleSheet("color: #606060;")
            self._chat_status_label.setText("LM Studio: Offline")
        finally:
            self._refresh_summary_ui()
            self._update_chat_controls()

    def _on_chat_clicked(self) -> None:
        """Handle chat button click."""
        self._toggle_chat_panel()

    def _on_summarize_clicked(self) -> None:
        """Handle summarize button click."""
        if not self._transcription:
            QMessageBox.warning(
                self, "No Transcript", "No transcript available to summarize."
            )
            return
        if self._summary_streaming:
            return

        self._summary_streaming = True
        self._summary_status_label.setText("Generating summary...")
        self._summary_status_label.show()
        self._summary_raw = ""
        self._summary_text = ""
        self._summary_stack.setCurrentWidget(self._summary_display)
        self._update_summary_display("")
        self._summary_panel.show()
        self._refresh_summary_ui()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._summary_task = asyncio.create_task(self._do_summarize())
            else:
                loop.run_until_complete(self._do_summarize())
        except RuntimeError:
            asyncio.run(self._do_summarize())

    async def _do_summarize(self) -> None:
        """Perform summarization via LLM (streaming)."""
        self._summary_streaming = True
        self._summarize_btn.setEnabled(False)
        self._summarize_btn.setText("⏳ Summarizing...")
        self._summary_stop_btn.show()
        self._refresh_summary_ui()

        def on_chunk(content: str) -> None:
            self._summary_raw += content
            cleaned = self._strip_think_blocks(self._summary_raw)
            self._summary_text = cleaned
            QTimer.singleShot(0, lambda: self._update_summary_display(cleaned))

        def on_done(_full: str) -> None:
            cleaned = self._strip_think_blocks(self._summary_raw)
            QTimer.singleShot(0, lambda: self._finish_summary_stream(cleaned))

        def on_error(error_msg: str) -> None:
            QTimer.singleShot(0, lambda: self._handle_summary_error(error_msg))

        try:
            await self._api_client.summarize_recording(
                self._recording_id,
                on_chunk=on_chunk,
                on_done=on_done,
                on_error=on_error,
            )
        except asyncio.CancelledError:
            QTimer.singleShot(0, self._handle_summary_cancelled)
        except Exception as e:
            QTimer.singleShot(0, lambda: self._handle_summary_error(str(e)))
        finally:
            self._summarize_btn.setEnabled(True)
            self._summarize_btn.setText("✨ Summarize")

    def closeEvent(self, event) -> None:
        """Clean up on dialog close."""
        if self._summary_task and not self._summary_task.done():
            self._summary_task.cancel()
        self._audio_player.cleanup()
        super().closeEvent(event)
