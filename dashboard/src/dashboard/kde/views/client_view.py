"""
Client view creation for the Dashboard.

This module contains the client management view UI creation,
extracted to keep the main dashboard.py file smaller.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def create_client_view(dashboard) -> QWidget:
    """Create the client management view.

    Args:
        dashboard: The DashboardWindow instance

    Returns:
        The client view widget
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    view = QWidget()
    view.setMinimumWidth(450)
    layout = QVBoxLayout(view)
    layout.setContentsMargins(40, 30, 40, 30)

    # Title
    title = QLabel("Client")
    title.setObjectName("viewTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    layout.addSpacing(20)

    # Status card
    status_frame = QFrame()
    status_frame.setObjectName("statusCard")
    status_layout = QVBoxLayout(status_frame)
    status_layout.setSpacing(12)

    # Client status
    client_row = QHBoxLayout()
    status_label = QLabel("Status:")
    status_label.setObjectName("statusLabel")
    client_row.addWidget(status_label)
    dashboard._client_status_label = QLabel("Stopped")
    dashboard._client_status_label.setObjectName("statusValue")
    client_row.addWidget(dashboard._client_status_label)
    client_row.addStretch()
    status_layout.addLayout(client_row)

    # Connection info
    conn_row = QHBoxLayout()
    conn_label = QLabel("Connection:")
    conn_label.setObjectName("statusLabel")
    conn_row.addWidget(conn_label)
    dashboard._connection_info_label = QLabel("Not connected")
    dashboard._connection_info_label.setObjectName("statusValue")
    conn_row.addWidget(dashboard._connection_info_label)
    conn_row.addStretch()
    status_layout.addLayout(conn_row)

    layout.addWidget(status_frame)

    layout.addSpacing(25)

    # Control buttons
    btn_container = QWidget()
    btn_layout = QHBoxLayout(btn_container)
    btn_layout.setSpacing(12)

    dashboard._start_client_local_btn = QPushButton("Start Local")
    dashboard._start_client_local_btn.setObjectName("primaryButton")
    dashboard._start_client_local_btn.clicked.connect(dashboard._on_start_client_local)
    dashboard._start_client_local_btn.setFixedWidth(120)
    btn_layout.addWidget(dashboard._start_client_local_btn)

    dashboard._start_client_remote_btn = QPushButton("Start Remote")
    dashboard._start_client_remote_btn.setObjectName("primaryButton")
    dashboard._start_client_remote_btn.clicked.connect(
        dashboard._on_start_client_remote
    )
    dashboard._start_client_remote_btn.setFixedWidth(120)
    btn_layout.addWidget(dashboard._start_client_remote_btn)

    dashboard._stop_client_btn = QPushButton("Stop")
    dashboard._stop_client_btn.setObjectName("stopButton")
    dashboard._stop_client_btn.clicked.connect(dashboard._on_stop_client)
    dashboard._stop_client_btn.setEnabled(False)
    dashboard._stop_client_btn.setFixedWidth(120)
    btn_layout.addWidget(dashboard._stop_client_btn)

    layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(15)

    # Model management button
    dashboard._unload_models_btn = QPushButton("Unload All Models")
    dashboard._unload_models_btn.setObjectName("primaryButton")
    dashboard._unload_models_btn.setToolTip(
        "Unload transcription models to free GPU memory"
    )
    dashboard._unload_models_btn.setEnabled(False)
    dashboard._unload_models_btn.setFixedWidth(150)
    dashboard._unload_models_btn.clicked.connect(dashboard._on_toggle_models)
    layout.addWidget(
        dashboard._unload_models_btn, alignment=Qt.AlignmentFlag.AlignCenter
    )

    layout.addSpacing(20)

    # Options row
    options_frame = QFrame()
    options_frame.setObjectName("optionsRow")
    options_frame.setStyleSheet(
        "QFrame#optionsRow { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
        "border-radius: 8px; padding: 8px; }"
    )
    options_layout = QHBoxLayout(options_frame)
    options_layout.setContentsMargins(12, 10, 12, 10)
    options_layout.setSpacing(16)

    # Live Transcriber toggle
    preview_label = QLabel("Live Transcriber:")
    preview_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    options_layout.addWidget(preview_label)

    dashboard._preview_toggle_btn = QPushButton("Disabled")
    dashboard._preview_toggle_btn.setCheckable(True)
    dashboard._preview_toggle_btn.setFixedWidth(80)
    live_transcriber_enabled = dashboard.config.get_server_config(
        "transcription_options", "enable_live_transcriber", default=False
    )
    dashboard._preview_toggle_btn.setChecked(live_transcriber_enabled)
    dashboard._preview_toggle_btn.setText(
        "Enabled" if live_transcriber_enabled else "Disabled"
    )
    dashboard._preview_toggle_btn.setToolTip(
        "Enable live transcriber during recording.\n"
        "Uses a faster model for real-time feedback.\n"
        "Only editable when server is stopped."
    )
    dashboard._preview_toggle_btn.clicked.connect(dashboard._on_live_transcriber_toggle)
    dashboard._update_live_transcriber_toggle_style()
    options_layout.addWidget(dashboard._preview_toggle_btn)

    options_layout.addSpacing(8)

    # Live Mode Language selector
    language_label = QLabel("Language:")
    language_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    options_layout.addWidget(language_label)

    dashboard._live_language_combo = QComboBox()
    dashboard._live_language_combo.setMinimumWidth(120)
    dashboard._live_language_combo.setStyleSheet(
        "QComboBox { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "border-radius: 6px; padding: 6px 10px; color: #e0e0e0; font-size: 12px; }"
        "QComboBox:hover { border-color: #505050; }"
        "QComboBox::drop-down { border: none; width: 20px; }"
        "QComboBox::down-arrow { image: none; border-left: 4px solid transparent; "
        "border-right: 4px solid transparent; border-top: 5px solid #808080; margin-right: 6px; }"
        "QComboBox QAbstractItemView { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "color: #e0e0e0; selection-background-color: #404040; padding: 4px; }"
    )

    # Full Whisper language list (99 languages)
    languages = [
        ("Auto-detect", ""),
        ("Afrikaans", "af"),
        ("Amharic", "am"),
        ("Arabic", "ar"),
        ("Assamese", "as"),
        ("Azerbaijani", "az"),
        ("Bashkir", "ba"),
        ("Belarusian", "be"),
        ("Bulgarian", "bg"),
        ("Bengali", "bn"),
        ("Tibetan", "bo"),
        ("Breton", "br"),
        ("Bosnian", "bs"),
        ("Catalan", "ca"),
        ("Czech", "cs"),
        ("Welsh", "cy"),
        ("Danish", "da"),
        ("German", "de"),
        ("Greek", "el"),
        ("English", "en"),
        ("Spanish", "es"),
        ("Estonian", "et"),
        ("Basque", "eu"),
        ("Persian", "fa"),
        ("Finnish", "fi"),
        ("Faroese", "fo"),
        ("French", "fr"),
        ("Galician", "gl"),
        ("Gujarati", "gu"),
        ("Hausa", "ha"),
        ("Hawaiian", "haw"),
        ("Hebrew", "he"),
        ("Hindi", "hi"),
        ("Croatian", "hr"),
        ("Haitian Creole", "ht"),
        ("Hungarian", "hu"),
        ("Armenian", "hy"),
        ("Indonesian", "id"),
        ("Icelandic", "is"),
        ("Italian", "it"),
        ("Japanese", "ja"),
        ("Javanese", "jw"),
        ("Georgian", "ka"),
        ("Kazakh", "kk"),
        ("Khmer", "km"),
        ("Kannada", "kn"),
        ("Korean", "ko"),
        ("Latin", "la"),
        ("Luxembourgish", "lb"),
        ("Lingala", "ln"),
        ("Lao", "lo"),
        ("Lithuanian", "lt"),
        ("Latvian", "lv"),
        ("Malagasy", "mg"),
        ("Maori", "mi"),
        ("Macedonian", "mk"),
        ("Malayalam", "ml"),
        ("Mongolian", "mn"),
        ("Marathi", "mr"),
        ("Malay", "ms"),
        ("Maltese", "mt"),
        ("Burmese", "my"),
        ("Nepali", "ne"),
        ("Dutch", "nl"),
        ("Norwegian Nynorsk", "nn"),
        ("Norwegian", "no"),
        ("Occitan", "oc"),
        ("Punjabi", "pa"),
        ("Polish", "pl"),
        ("Pashto", "ps"),
        ("Portuguese", "pt"),
        ("Romanian", "ro"),
        ("Russian", "ru"),
        ("Sanskrit", "sa"),
        ("Sindhi", "sd"),
        ("Sinhala", "si"),
        ("Slovak", "sk"),
        ("Slovenian", "sl"),
        ("Shona", "sn"),
        ("Somali", "so"),
        ("Albanian", "sq"),
        ("Serbian", "sr"),
        ("Sundanese", "su"),
        ("Swedish", "sv"),
        ("Swahili", "sw"),
        ("Tamil", "ta"),
        ("Telugu", "te"),
        ("Tajik", "tg"),
        ("Thai", "th"),
        ("Turkmen", "tk"),
        ("Tagalog", "tl"),
        ("Turkish", "tr"),
        ("Tatar", "tt"),
        ("Ukrainian", "uk"),
        ("Urdu", "ur"),
        ("Uzbek", "uz"),
        ("Vietnamese", "vi"),
        ("Yiddish", "yi"),
        ("Yoruba", "yo"),
        ("Chinese", "zh"),
        ("Cantonese", "yue"),
    ]
    for name, code in languages:
        dashboard._live_language_combo.addItem(name, code)

    saved_language = dashboard.config.get_server_config(
        "live_transcriber", "live_language", default="en"
    )
    for i in range(dashboard._live_language_combo.count()):
        if dashboard._live_language_combo.itemData(i) == saved_language:
            dashboard._live_language_combo.setCurrentIndex(i)
            break

    dashboard._live_language_combo.setToolTip(
        "Force a specific language for Live Mode.\n"
        "Recommended: Select your language for better accuracy.\n"
        "Auto-detect works poorly with short utterances.\n"
        "Only editable when server is stopped."
    )
    dashboard._live_language_combo.currentIndexChanged.connect(
        dashboard._on_live_language_changed
    )
    options_layout.addWidget(dashboard._live_language_combo)

    options_layout.addStretch()

    layout.addWidget(options_frame)

    layout.addSpacing(10)

    # Collapsible preview display section
    preview_display_frame = QFrame()
    preview_display_frame.setObjectName("previewCard")
    preview_display_frame.setStyleSheet(
        "QFrame#previewCard { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
        "border-radius: 8px; padding: 8px; }"
    )
    preview_display_layout = QVBoxLayout(preview_display_frame)
    preview_display_layout.setContentsMargins(12, 8, 12, 8)
    preview_display_layout.setSpacing(8)

    # Header with collapse toggle
    preview_header = QHBoxLayout()
    dashboard._preview_collapse_btn = QPushButton("\u25bc")
    dashboard._preview_collapse_btn.setFixedSize(24, 24)
    dashboard._preview_collapse_btn.setStyleSheet(
        "QPushButton { background-color: transparent; border: none; "
        "color: #808080; font-size: 12px; }"
        "QPushButton:hover { color: #e0e0e0; }"
    )
    dashboard._preview_collapse_btn.clicked.connect(
        dashboard._toggle_live_preview_collapse
    )
    preview_header.addWidget(dashboard._preview_collapse_btn)

    preview_title = QLabel("Live Preview")
    preview_title.setStyleSheet("color: #a0a0a0; font-size: 13px;")
    preview_header.addWidget(preview_title)
    preview_header.addStretch()

    dashboard._copy_clear_btn = QPushButton("Copy and Clear")
    dashboard._copy_clear_btn.setMaximumWidth(120)
    dashboard._copy_clear_btn.setFixedHeight(24)
    dashboard._copy_clear_btn.setStyleSheet(
        "QPushButton { background-color: #2d2d2d; border: 1px solid #404040; "
        "border-radius: 4px; color: #e0e0e0; font-size: 11px; padding: 0 8px; }"
        "QPushButton:hover { background-color: #3d3d3d; border-color: #505050; }"
        "QPushButton:pressed { background-color: #1e1e1e; }"
    )
    dashboard._copy_clear_btn.clicked.connect(dashboard._copy_and_clear_live_preview)
    preview_header.addWidget(dashboard._copy_clear_btn)

    preview_display_layout.addLayout(preview_header)

    # Collapsible content
    dashboard._preview_content = QWidget()
    preview_content_layout = QVBoxLayout(dashboard._preview_content)
    preview_content_layout.setContentsMargins(0, 4, 0, 0)
    preview_content_layout.setSpacing(8)

    dashboard._live_transcription_text_edit = QPlainTextEdit()
    dashboard._live_transcription_text_edit.setReadOnly(True)
    dashboard._live_transcription_text_edit.setPlaceholderText(
        "Start Live Mode to see transcription..."
    )
    dashboard._live_transcription_text_edit.setMinimumHeight(180)
    dashboard._live_transcription_text_edit.setMaximumHeight(250)
    dashboard._live_transcription_text_edit.setStyleSheet(
        "QPlainTextEdit { background-color: #252526; border-radius: 4px; "
        "padding: 8px; color: #e0e0e0; font-family: 'Inter', sans-serif; "
        "font-size: 13px; border: none; }"
        "QPlainTextEdit::placeholder { color: #808080; }"
    )
    dashboard._live_transcription_history = []
    preview_content_layout.addWidget(dashboard._live_transcription_text_edit)

    preview_display_layout.addWidget(dashboard._preview_content)

    layout.addWidget(preview_display_frame)

    layout.addSpacing(15)

    # Show logs button
    dashboard._show_client_logs_btn = QPushButton("Show Logs")
    dashboard._show_client_logs_btn.setObjectName("secondaryButton")
    logs_icon = dashboard._icon_loader.get_icon("logs")
    if not logs_icon.isNull():
        dashboard._show_client_logs_btn.setIcon(logs_icon)
    dashboard._show_client_logs_btn.clicked.connect(dashboard._toggle_client_logs)
    layout.addWidget(
        dashboard._show_client_logs_btn, alignment=Qt.AlignmentFlag.AlignCenter
    )

    layout.addStretch()

    scroll.setWidget(view)
    return scroll
