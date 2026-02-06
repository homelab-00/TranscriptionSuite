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

from dashboard.kde.apple_switch import AppleSwitch
from dashboard.kde.language_options import populate_language_combo, set_combo_language


def _apply_combo_style(combo: QComboBox, *, min_width: int = 140) -> None:
    combo.setMinimumWidth(min_width)
    combo.setStyleSheet(
        "QComboBox { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "border-radius: 6px; padding: 6px 10px; color: #e0e0e0; font-size: 12px; }"
        "QComboBox:hover { border-color: #505050; }"
        "QComboBox::drop-down { border: none; width: 20px; }"
        "QComboBox::down-arrow { image: none; border-left: 4px solid transparent; "
        "border-right: 4px solid transparent; border-top: 5px solid #808080; margin-right: 6px; }"
        "QComboBox QAbstractItemView { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "color: #e0e0e0; selection-background-color: #404040; padding: 4px; }"
    )


def _create_client_card(title: str, width: int) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("clientCard")
    frame.setFixedWidth(width)
    frame.setStyleSheet(
        "QFrame#clientCard { background-color: #1e1e1e; border: 1px solid #2d2d2d; "
        "border-radius: 8px; padding: 8px; }"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)

    title_label = QLabel(title)
    title_label.setStyleSheet("color: #a0a0a0; font-size: 14px; font-weight: 600;")
    layout.addWidget(title_label)

    return frame, layout


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

    card_width = 550

    # Status card
    status_frame = QFrame()
    status_frame.setObjectName("statusCard")
    status_frame.setFixedWidth(card_width)
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

    layout.addWidget(status_frame, alignment=Qt.AlignmentFlag.AlignCenter)

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

    layout.addSpacing(18)

    # Main transcription card
    main_card, main_layout = _create_client_card("Main Transcription", card_width)
    main_row = QHBoxLayout()
    main_label = QLabel("Language:")
    main_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    main_row.addWidget(main_label)

    dashboard._main_language_combo = QComboBox()
    _apply_combo_style(dashboard._main_language_combo, min_width=200)
    populate_language_combo(dashboard._main_language_combo, include_auto_detect=True)
    set_combo_language(
        dashboard._main_language_combo,
        dashboard.config.get_server_config(
            "longform_recording",
            "language",
            default=None,
        ),
    )
    dashboard._main_language_combo.setToolTip(
        "Language for main (longform/static/notebook) transcription.\n"
        "Auto-detect is recommended unless you always speak one language."
    )
    dashboard._main_language_combo.currentIndexChanged.connect(
        dashboard._on_main_language_changed
    )
    main_row.addWidget(dashboard._main_language_combo)
    main_row.addStretch()
    main_layout.addLayout(main_row)

    layout.addWidget(main_card, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(12)

    # Source card
    source_card, source_layout = _create_client_card("Source", card_width)

    source_toggle_row = QHBoxLayout()
    source_label = QLabel("Input Source:")
    source_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    source_toggle_row.addWidget(source_label)

    dashboard._source_mic_label = QLabel("Microphone")
    dashboard._source_mic_label.setStyleSheet(
        "color: #d0d0d0; font-size: 12px; font-weight: 600;"
    )
    source_toggle_row.addWidget(dashboard._source_mic_label)

    dashboard._source_switch = AppleSwitch()
    source_type = dashboard.config.get("recording", "source_type", default="microphone")
    is_system_audio = source_type == "system_audio"
    dashboard._source_switch.setChecked(is_system_audio)
    dashboard._source_switch.setToolTip(
        "Toggle between microphone and system audio loopback capture."
    )
    source_toggle_row.addWidget(dashboard._source_switch)

    dashboard._source_system_label = QLabel("System Audio")
    dashboard._source_system_label.setStyleSheet(
        "color: #7f7f7f; font-size: 12px; font-weight: 500;"
    )
    source_toggle_row.addWidget(dashboard._source_system_label)
    source_toggle_row.addStretch()

    source_layout.addLayout(source_toggle_row)

    mic_row = QHBoxLayout()
    mic_label = QLabel("Microphone:")
    mic_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    mic_row.addWidget(mic_label)

    dashboard._microphone_combo = QComboBox()
    _apply_combo_style(dashboard._microphone_combo, min_width=260)
    mic_row.addWidget(dashboard._microphone_combo, 1)
    source_layout.addLayout(mic_row)

    sys_row = QHBoxLayout()
    sys_label = QLabel("System Audio:")
    sys_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    sys_row.addWidget(sys_label)

    dashboard._system_audio_combo = QComboBox()
    _apply_combo_style(dashboard._system_audio_combo, min_width=260)
    sys_row.addWidget(dashboard._system_audio_combo, 1)

    dashboard._refresh_sources_btn = QPushButton("Refresh")
    dashboard._refresh_sources_btn.setObjectName("secondaryButton")
    dashboard._refresh_sources_btn.setFixedWidth(84)
    sys_row.addWidget(dashboard._refresh_sources_btn)
    source_layout.addLayout(sys_row)

    source_help = QLabel(
        "Default devices are used unless you explicitly choose a specific one."
    )
    source_help.setStyleSheet("color: #808080; font-size: 11px;")
    source_help.setWordWrap(True)
    source_layout.addWidget(source_help)

    dashboard._source_switch.toggled.connect(dashboard._on_audio_source_toggled)
    dashboard._microphone_combo.currentIndexChanged.connect(
        dashboard._on_microphone_device_changed
    )
    dashboard._system_audio_combo.currentIndexChanged.connect(
        dashboard._on_system_audio_device_changed
    )
    dashboard._refresh_sources_btn.clicked.connect(dashboard._refresh_source_devices)

    dashboard._refresh_source_devices()
    dashboard._sync_audio_source_ui()

    layout.addWidget(source_card, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(12)

    # Live Mode card
    live_card, live_layout = _create_client_card("Live Mode", card_width)

    controls_row = QHBoxLayout()
    controls_row.setSpacing(12)

    live_status_label = QLabel("Status:")
    live_status_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    controls_row.addWidget(live_status_label)

    dashboard._preview_toggle_btn = QPushButton("Disabled")
    dashboard._preview_toggle_btn.setCheckable(True)
    dashboard._preview_toggle_btn.setFixedWidth(78)
    live_mode_enabled = dashboard.config.get_server_config(
        "live_transcriber", "enabled", default=False
    )
    dashboard._preview_toggle_btn.setChecked(live_mode_enabled)
    dashboard._preview_toggle_btn.setText(
        "Enabled" if live_mode_enabled else "Disabled"
    )
    dashboard._preview_toggle_btn.setToolTip(
        "Start or stop Live Mode.\nRequires the client to be running."
    )
    dashboard._preview_toggle_btn.clicked.connect(dashboard._on_live_transcriber_toggle)
    dashboard._update_live_transcriber_toggle_style()
    controls_row.addWidget(dashboard._preview_toggle_btn)

    dashboard._live_mode_mute_btn = QPushButton("Mute")
    dashboard._live_mode_mute_btn.setFixedWidth(70)
    dashboard._live_mode_mute_btn.setEnabled(False)
    dashboard._live_mode_mute_btn.setStyleSheet(
        "QPushButton { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "border-radius: 6px; padding: 6px 10px; color: #e0e0e0; font-size: 12px; }"
        "QPushButton:hover { border-color: #505050; }"
        "QPushButton:disabled { color: #606060; border-color: #2d2d2d; }"
    )
    dashboard._live_mode_mute_btn.clicked.connect(dashboard._on_live_mode_mute_click)
    controls_row.addWidget(dashboard._live_mode_mute_btn)

    live_language_label = QLabel("Language:")
    live_language_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
    controls_row.addWidget(live_language_label)

    dashboard._live_language_combo = QComboBox()
    _apply_combo_style(dashboard._live_language_combo, min_width=150)
    populate_language_combo(dashboard._live_language_combo, include_auto_detect=True)
    set_combo_language(
        dashboard._live_language_combo,
        dashboard.config.get_server_config(
            "live_transcriber", "live_language", default="en"
        ),
    )
    dashboard._live_language_combo.setToolTip(
        "Force a specific language for Live Mode.\n"
        "Recommended: Select your language for better accuracy.\n"
        "Auto-detect works poorly with short utterances.\n"
        "Live Mode will restart to apply changes."
    )
    dashboard._live_language_combo.currentIndexChanged.connect(
        dashboard._on_live_language_changed
    )
    controls_row.addWidget(dashboard._live_language_combo)
    controls_row.addStretch()

    live_layout.addLayout(controls_row)

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

    live_layout.addLayout(preview_header)

    dashboard._preview_content = QWidget()
    preview_content_layout = QVBoxLayout(dashboard._preview_content)
    preview_content_layout.setContentsMargins(0, 2, 0, 0)
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
        "padding: 8px; color: #e0e0e0; font-size: 13px; border: none; }"
        "QPlainTextEdit::placeholder { color: #808080; }"
    )
    dashboard._live_transcription_history = []
    preview_content_layout.addWidget(dashboard._live_transcription_text_edit)
    live_layout.addWidget(dashboard._preview_content)

    layout.addWidget(live_card, alignment=Qt.AlignmentFlag.AlignCenter)

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
