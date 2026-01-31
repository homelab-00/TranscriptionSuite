"""
Settings dialog for TranscriptionSuite.

Provides a unified tabbed dialog for configuring all settings.
Styled to match the Dashboard UI design language.

Tabs:
- App: Clipboard, notifications, stop server on quit behavior
- Client: Audio input device + connection settings
- Server: Nested config editor + config.yaml file access
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import yaml

from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.config import ClientConfig, get_config_dir
from dashboard.common.docker_manager import DockerManager

logger = logging.getLogger(__name__)


@dataclass
class ConfigNode:
    key: str
    path: tuple[str, ...]
    value: Any | None
    comment: str
    commented: bool
    children: list["ConfigNode"]

    @property
    def is_leaf(self) -> bool:
        return not self.children


class CollapsibleSection(QWidget):
    """Collapsible container for nested settings sections."""

    def __init__(
        self,
        title: str,
        description: str | None = None,
        level: int = 0,
        expanded: bool = False,
    ):
        super().__init__()
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("sectionToggle")
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_button.clicked.connect(self._on_toggled)
        layout.addWidget(self.toggle_button)

        self.content = QWidget()
        self.content.setObjectName("sectionContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12 + (level * 8), 4, 0, 0)
        self.content_layout.setSpacing(10)

        if description:
            desc_label = QLabel(description)
            desc_label.setObjectName("helpText")
            desc_label.setWordWrap(True)
            self.content_layout.addWidget(desc_label)

        layout.addWidget(self.content)
        self.content.setVisible(expanded)

    def _on_toggled(self, checked: bool) -> None:
        self._expanded = checked
        self.content.setVisible(checked)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self.toggle_button.setChecked(expanded)
        self._on_toggled(expanded)


class SettingsDialog(QDialog):
    """Unified settings dialog with tabbed interface matching Dashboard design."""

    def __init__(self, config: ClientConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self._docker_manager = DockerManager()
        self._server_section_tree: list[dict[str, Any]] = []
        self._server_field_inputs: dict[tuple[str, ...], QWidget] = {}
        self._server_field_types: dict[tuple[str, ...], type] = {}
        self._server_field_original: dict[tuple[str, ...], Any] = {}
        self._server_field_commented: dict[tuple[str, ...], bool] = {}
        self._server_field_enablers: dict[tuple[str, ...], QCheckBox] = {}
        self._server_row_search: dict[QWidget, str] = {}
        self._server_hidden_paths: set[tuple[str, ...]] = {
            ("live_transcriber", "enabled"),
            ("live_transcriber", "live_language"),
            ("live_transcriber", "model"),
            ("longform_recording", "auto_add_to_audio_notebook"),
            ("main_transcriber", "model"),
        }
        self._server_config_exists = False

        self.setWindowTitle("Settings")
        self.setMinimumWidth(540)
        self.setMinimumHeight(520)

        # Set window icon from system theme
        icon = QIcon.fromTheme("preferences-system")
        if icon.isNull():
            icon = QIcon.fromTheme("configure")
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs in order: App, Client, Server, Notebook
        self._create_app_tab()
        self._create_client_tab()
        self._create_server_tab()
        self._create_notebook_tab()

        # Button container
        btn_container = QWidget()
        btn_container.setObjectName("buttonContainer")
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(16, 12, 16, 16)
        btn_layout.setSpacing(12)

        btn_layout.addStretch()

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        # Save button
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(save_btn)

        layout.addWidget(btn_container)

        # Apply styling
        self._apply_styles()

        # Load current values
        self._load_values()

    def _apply_styles(self) -> None:
        """Apply dark theme styling matching Dashboard UI."""
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }

            QTabWidget::pane {
                background-color: #121212;
                border: none;
                border-top: 1px solid #2d2d2d;
            }

            QTabBar::tab {
                background-color: #1e1e1e;
                color: #a0a0a0;
                padding: 10px 20px;
                border: none;
                border-bottom: 2px solid transparent;
                font-size: 13px;
            }

            QTabBar::tab:selected {
                color: #0AFCCF;
                border-bottom: 2px solid #0AFCCF;
            }

            QTabBar::tab:hover:!selected {
                color: #ffffff;
                background-color: #2d2d2d;
            }

            QWidget#tabContent {
                background-color: #121212;
            }

            QLabel {
                color: #a0a0a0;
                font-size: 13px;
            }

            QLabel#fieldLabel {
                color: #a0a0a0;
                font-size: 13px;
                min-width: 100px;
            }

            QLabel#sectionHeader {
                color: #0AFCCF;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 4px;
            }

            QLabel#helpText {
                color: #6c757d;
                font-size: 11px;
            }

            QLabel#pathLabel {
                color: #6c757d;
                font-size: 12px;
                font-family: monospace;
            }

            QLineEdit {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                padding: 8px 12px;
                font-size: 13px;
            }

            QLineEdit:focus {
                border-color: #0AFCCF;
            }

            QLineEdit:disabled {
                background-color: #141414;
                color: #606060;
            }

            QLineEdit#searchField {
                background-color: #1a1a1a;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                padding: 8px 12px;
                color: #ffffff;
            }

            QToolButton#sectionToggle {
                background: transparent;
                border: none;
                color: #0AFCCF;
                font-size: 13px;
                font-weight: 600;
                padding: 4px 0;
            }

            QToolButton#sectionToggle:hover {
                color: #ffffff;
            }

            QWidget#configRow {
                background-color: #171717;
                border: 1px solid #2a2a2a;
                border-radius: 8px;
                padding: 8px;
            }

            QSpinBox {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                padding: 8px 12px;
                font-size: 13px;
            }

            QSpinBox:focus {
                border-color: #0AFCCF;
            }

            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #2d2d2d;
                border: none;
                width: 20px;
            }

            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #3d3d3d;
            }

            QComboBox {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                padding: 8px 12px;
                font-size: 13px;
                min-width: 200px;
            }

            QComboBox:focus {
                border-color: #0AFCCF;
            }

            QComboBox::drop-down {
                border: none;
                width: 24px;
            }

            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #a0a0a0;
                margin-right: 8px;
            }

            QComboBox QAbstractItemView {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #ffffff;
                selection-background-color: #2d2d2d;
                selection-color: #0AFCCF;
            }

            QCheckBox {
                color: #ffffff;
                font-size: 13px;
                spacing: 8px;
            }

            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 2px solid #505050;
                background-color: #1e1e1e;
            }

            QCheckBox::indicator:checked {
                background-color: #0AFCCF;
                border-color: #0AFCCF;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMxMjEyMTIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cG9seWxpbmUgcG9pbnRzPSIyMCA2IDkgMTcgNCAxMiI+PC9wb2x5bGluZT48L3N2Zz4=);
            }

            QCheckBox::indicator:unchecked:hover {
                border-color: #707070;
                background-color: #252525;
            }

            QCheckBox::indicator:checked:hover {
                background-color: #08d9b3;
                border-color: #08d9b3;
            }

            #primaryButton {
                background-color: #0AFCCF;
                border: none;
                border-radius: 6px;
                color: #141414;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 500;
                min-width: 80px;
            }

            #primaryButton:hover {
                background-color: #08d9b3;
            }

            #secondaryButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                color: #ffffff;
                padding: 10px 24px;
                font-size: 13px;
                min-width: 80px;
            }

            #secondaryButton:hover {
                background-color: #3d3d3d;
                border-color: #4d4d4d;
            }

            #smallButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px 12px;
                font-size: 12px;
            }

            #smallButton:hover {
                background-color: #3d3d3d;
            }

            #buttonContainer {
                background-color: #1e1e1e;
                border-top: 1px solid #2d2d2d;
            }

            QGroupBox {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                margin-top: 10px;
                padding: 12px;
                padding-top: 20px;
                font-size: 13px;
                font-weight: bold;
                color: #0AFCCF;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 4px;
                background-color: #1e1e1e;
                color: #0AFCCF;
            }

            QFrame#settingsCard {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }

            QFrame#sectionSeparator {
                background-color: #2d2d2d;
                max-height: 1px;
                margin: 8px 0;
            }

            QScrollArea {
                background-color: #121212;
                border: none;
            }

            QScrollBar:vertical {
                background-color: #1e1e1e;
                width: 10px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background-color: #3d3d3d;
                min-height: 30px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #4d4d4d;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }

            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

    def _create_app_tab(self) -> None:
        """Create the App settings tab (clipboard, notifications, docker behavior)."""
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Create content widget
        tab = QWidget()
        tab.setObjectName("tabContent")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # === Clipboard Section ===
        clipboard_group = QGroupBox("Clipboard")
        clipboard_layout = QVBoxLayout(clipboard_group)

        self.auto_copy_check = QCheckBox(
            "Automatically copy transcription to clipboard"
        )
        clipboard_layout.addWidget(self.auto_copy_check)

        layout.addWidget(clipboard_group)

        # === Notifications Section ===
        notifications_group = QGroupBox("Notifications")
        notifications_layout = QVBoxLayout(notifications_group)

        self.notifications_check = QCheckBox("Show desktop notifications")
        notifications_layout.addWidget(self.notifications_check)

        layout.addWidget(notifications_group)

        # === Docker Server Section ===
        docker_group = QGroupBox("Docker Server")
        docker_layout = QVBoxLayout(docker_group)

        self.stop_server_check = QCheckBox("Stop server when quitting dashboard")
        docker_layout.addWidget(self.stop_server_check)

        layout.addWidget(docker_group)

        layout.addStretch()

        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "App")

    def _create_client_tab(self) -> None:
        """Create the Client settings tab (audio + connection in one tab)."""
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Create content widget
        tab = QWidget()
        tab.setObjectName("tabContent")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # === Audio Section ===
        audio_group = QGroupBox("Audio")
        audio_layout = QVBoxLayout(audio_group)

        # Device selector row
        device_row = QHBoxLayout()
        device_label = QLabel("Input Device:")
        device_label.setObjectName("fieldLabel")
        device_row.addWidget(device_label)

        self.device_combo = QComboBox()
        device_row.addWidget(self.device_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("smallButton")
        refresh_btn.clicked.connect(self._refresh_devices)
        device_row.addWidget(refresh_btn)

        audio_layout.addLayout(device_row)

        # Sample rate info
        sample_rate_label = QLabel("Sample Rate: 16000 Hz (fixed for Whisper)")
        sample_rate_label.setObjectName("helpText")
        audio_layout.addWidget(sample_rate_label)

        # Live Mode grace period
        grace_row = QHBoxLayout()
        grace_label = QLabel("Live Mode Grace Period:")
        grace_label.setObjectName("fieldLabel")
        grace_label.setToolTip(
            "How long to keep recording after detecting silence.\n"
            "Allows natural pauses while speaking."
        )
        grace_row.addWidget(grace_label)

        self.grace_period_spin = QDoubleSpinBox()
        self.grace_period_spin.setRange(0.1, 10.0)
        self.grace_period_spin.setSingleStep(0.1)
        self.grace_period_spin.setValue(1.0)
        self.grace_period_spin.setDecimals(1)
        self.grace_period_spin.setSuffix(" seconds")
        self.grace_period_spin.setFixedWidth(130)
        self.grace_period_spin.setToolTip(
            "Recommended: 2-4 seconds. Higher values allow longer pauses\n"
            "but may make responses feel slower."
        )
        grace_row.addWidget(self.grace_period_spin)
        grace_row.addStretch()
        audio_layout.addLayout(grace_row)

        # Help text for grace period
        grace_help = QLabel(
            "Tip: Increase if your transcriptions cut off mid-sentence, decrease for faster responses."
        )
        grace_help.setObjectName("helpText")
        grace_help.setWordWrap(True)
        audio_layout.addWidget(grace_help)

        layout.addWidget(audio_group)

        # Populate devices
        self._refresh_devices()

        # === Diarization Section ===
        diarization_group = QGroupBox("Diarization")
        diarization_layout = QVBoxLayout(diarization_group)

        # Constrain speakers checkbox
        self.constrain_speakers_check = QCheckBox(
            "Constrain to expected number of speakers"
        )
        self.constrain_speakers_check.setToolTip(
            "When enabled, forces diarization to identify exactly the specified number of speakers.\n"
            "Useful for podcasts with known hosts where occasional clips should be attributed to the main speakers."
        )
        self.constrain_speakers_check.toggled.connect(
            self._on_constrain_speakers_toggled
        )
        diarization_layout.addWidget(self.constrain_speakers_check)

        # Number of speakers row
        speakers_row = QHBoxLayout()
        speakers_label = QLabel("Number of speakers:")
        speakers_label.setObjectName("fieldLabel")
        speakers_row.addWidget(speakers_label)

        self.expected_speakers_spin = QSpinBox()
        self.expected_speakers_spin.setRange(2, 10)
        self.expected_speakers_spin.setValue(2)
        self.expected_speakers_spin.setFixedWidth(100)
        self.expected_speakers_spin.setToolTip(
            "Specify the exact number of speakers (2-10).\n"
            "Example: Set to 2 for a podcast with 2 hosts."
        )
        speakers_row.addWidget(self.expected_speakers_spin)
        speakers_row.addStretch()
        diarization_layout.addLayout(speakers_row)

        # Help text
        diarization_help = QLabel(
            "Useful for podcasts with known hosts. Forces all speech to be attributed to "
            "exactly this many speakers, ignoring occasional clips."
        )
        diarization_help.setObjectName("helpText")
        diarization_help.setWordWrap(True)
        diarization_layout.addWidget(diarization_help)

        layout.addWidget(diarization_group)

        # === Audio Notebook Section ===
        notebook_group = QGroupBox("Audio Notebook")
        notebook_layout = QVBoxLayout(notebook_group)

        self.auto_add_notebook_check = QCheckBox(
            "Auto-add recordings to Audio Notebook"
        )
        self.auto_add_notebook_check.setToolTip(
            "When enabled, recordings are saved to Audio Notebook with diarization\n"
            "instead of copying transcription to clipboard.\n"
            "Requires server restart to take effect."
        )
        notebook_layout.addWidget(self.auto_add_notebook_check)

        notebook_help = QLabel(
            "When enabled, completed recordings are automatically saved to "
            "the Audio Notebook with speaker diarization."
        )
        notebook_help.setObjectName("helpText")
        notebook_help.setWordWrap(True)
        notebook_layout.addWidget(notebook_help)

        layout.addWidget(notebook_group)

        # === Connection Section ===
        connection_group = QGroupBox("Connection")
        connection_layout = QVBoxLayout(connection_group)
        connection_layout.setSpacing(10)

        # Local host row
        local_row = QHBoxLayout()
        local_label = QLabel("Local Host:")
        local_label.setObjectName("fieldLabel")
        local_row.addWidget(local_label)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        local_row.addWidget(self.host_edit, 1)
        connection_layout.addLayout(local_row)

        # Remote host row
        remote_row = QHBoxLayout()
        remote_label = QLabel("Remote Host:")
        remote_label.setObjectName("fieldLabel")
        remote_row.addWidget(remote_label)
        self.remote_host_edit = QLineEdit()
        self.remote_host_edit.setPlaceholderText("e.g., my-desktop.tail1234.ts.net")
        remote_row.addWidget(self.remote_host_edit, 1)
        connection_layout.addLayout(remote_row)

        # Help text for host settings
        host_help = QLabel(
            "Enter ONLY the hostname (no http://, no port). Examples:\n"
            "• Local: localhost or 127.0.0.1\n"
            "• Remote: my-machine.tail1234.ts.net"
        )
        host_help.setObjectName("helpText")
        host_help.setWordWrap(True)
        connection_layout.addWidget(host_help)

        # Use remote checkbox
        self.use_remote_check = QCheckBox("Use remote server instead of local")
        connection_layout.addWidget(self.use_remote_check)

        # Help text for remote
        remote_help = QLabel(
            "Remote access requires Tailscale HTTPS and port 8443."
        )
        remote_help.setObjectName("helpText")
        remote_help.setWordWrap(True)
        connection_layout.addWidget(remote_help)

        # Separator
        separator = QFrame()
        separator.setObjectName("sectionSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        connection_layout.addWidget(separator)

        # Token row
        token_row = QHBoxLayout()
        token_label = QLabel("Auth Token:")
        token_label.setObjectName("fieldLabel")
        token_row.addWidget(token_label)

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Authentication token")
        token_row.addWidget(self.token_edit, 1)

        self.show_token_btn = QPushButton("Show")
        self.show_token_btn.setObjectName("smallButton")
        self.show_token_btn.setCheckable(True)
        self.show_token_btn.setFixedWidth(60)
        self.show_token_btn.toggled.connect(self._toggle_token_visibility)
        token_row.addWidget(self.show_token_btn)

        connection_layout.addLayout(token_row)

        # Port row
        port_row = QHBoxLayout()
        port_label = QLabel("Port:")
        port_label.setObjectName("fieldLabel")
        port_row.addWidget(port_label)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8000)
        self.port_spin.setFixedWidth(100)
        port_row.addWidget(self.port_spin)
        port_row.addStretch()
        connection_layout.addLayout(port_row)

        # HTTPS checkbox
        self.https_check = QCheckBox("Use HTTPS")
        connection_layout.addWidget(self.https_check)

        layout.addWidget(connection_group)

        layout.addStretch()

        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "Client")

    def _create_server_tab(self) -> None:
        """Create the Server settings tab (nested config editor + file access)."""
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Create content widget
        tab = QWidget()
        tab.setObjectName("tabContent")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Header + search
        header_label = QLabel(
            "Server settings are stored in config.yaml. Changes apply after a server restart."
        )
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        self._server_search = QLineEdit()
        self._server_search.setObjectName("searchField")
        self._server_search.setPlaceholderText("Search server settings...")
        self._server_search.textChanged.connect(self._filter_server_settings)
        layout.addWidget(self._server_search)

        separator = QFrame()
        separator.setObjectName("sectionSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        # Settings editor
        config_dir = get_config_dir()
        config_path = config_dir / "config.yaml"
        self._server_config_exists = config_path.exists()

        if self._server_config_exists:
            root = self._parse_server_config(config_path)
            sections_container = QWidget()
            sections_layout = QVBoxLayout(sections_container)
            sections_layout.setContentsMargins(0, 0, 0, 0)
            sections_layout.setSpacing(12)

            for section_node in root.children:
                section_info = self._build_server_section(section_node, sections_layout)
                if section_info:
                    self._server_section_tree.append(section_info)

            sections_layout.addStretch()
            layout.addWidget(sections_container)
        else:
            missing_label = QLabel(
                "config.yaml not found. Run the setup wizard or open the file manually."
            )
            missing_label.setWordWrap(True)
            layout.addWidget(missing_label)
            self._server_search.setEnabled(False)

        # Config file access
        config_group = QGroupBox("Config File")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(12)

        open_config_btn = QPushButton("Open config.yaml in Text Editor")
        open_config_btn.setObjectName("primaryButton")
        open_config_btn.clicked.connect(self._on_open_config_file)
        config_layout.addWidget(open_config_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        path_info_label = QLabel("Location:")
        path_info_label.setObjectName("helpText")
        config_layout.addWidget(path_info_label)

        path_label = QLabel(str(config_path))
        path_label.setObjectName("pathLabel")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        config_layout.addWidget(path_label)

        layout.addWidget(config_group)
        layout.addStretch()

        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "Server")

    def _clean_comment_block(self, lines: list[str]) -> str:
        cleaned: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if all(ch in "-=" for ch in stripped):
                continue
            cleaned.append(stripped)
        return "\n".join(cleaned).strip()

    def _parse_server_config(self, config_path) -> ConfigNode:
        text = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        root = ConfigNode(
            key="root",
            path=(),
            value=None,
            comment="",
            commented=False,
            children=[],
        )

        pending_comments: list[str] = []
        stack: list[tuple[int, ConfigNode]] = [(-1, root)]

        def get_value(path: tuple[str, ...]) -> Any:
            value: Any = data
            for key in path:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return None
            return value

        for line in text.splitlines():
            if not line.strip():
                pending_comments = []
                continue

            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if stripped.startswith("#"):
                comment_body = stripped[1:].lstrip()
                key_match = re.match(r"([a-z0-9_]+)\s*:(.*)$", comment_body)
                if key_match:
                    key = key_match.group(1)
                    value_part = key_match.group(2).strip()
                    inline_comment = ""
                    if "#" in value_part:
                        value_part, inline_comment = value_part.split("#", 1)
                        value_part = value_part.strip()
                        inline_comment = inline_comment.strip()

                    while stack and indent <= stack[-1][0]:
                        stack.pop()
                    parent = stack[-1][1]

                    comment_text = self._clean_comment_block(pending_comments)
                    pending_comments = []
                    if inline_comment:
                        comment_text = (
                            f"{comment_text}\n{inline_comment}"
                            if comment_text
                            else inline_comment
                        )

                    try:
                        value = yaml.safe_load(value_part) if value_part else None
                    except Exception:
                        value = value_part if value_part else None

                    node = ConfigNode(
                        key=key,
                        path=parent.path + (key,),
                        value=value,
                        comment=comment_text,
                        commented=True,
                        children=[],
                    )
                    parent.children.append(node)
                else:
                    if comment_body:
                        pending_comments.append(comment_body)
                continue

            match = re.match(r"(\s*)([A-Za-z0-9_]+)\s*:(.*)$", line)
            if not match:
                continue

            key = match.group(2)
            value_part = match.group(3)
            inline_comment = ""
            if "#" in value_part:
                value_part, inline_comment = value_part.split("#", 1)
                inline_comment = inline_comment.strip()
            value_part = value_part.strip()

            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]

            comment_text = self._clean_comment_block(pending_comments)
            pending_comments = []
            if inline_comment:
                comment_text = (
                    f"{comment_text}\n{inline_comment}"
                    if comment_text
                    else inline_comment
                )

            if value_part == "":
                node = ConfigNode(
                    key=key,
                    path=parent.path + (key,),
                    value=None,
                    comment=comment_text,
                    commented=False,
                    children=[],
                )
                parent.children.append(node)
                stack.append((indent, node))
            else:
                value = get_value(parent.path + (key,))
                node = ConfigNode(
                    key=key,
                    path=parent.path + (key,),
                    value=value,
                    comment=comment_text,
                    commented=False,
                    children=[],
                )
                parent.children.append(node)

        return root

    def _titleize(self, key: str) -> str:
        return key.replace("_", " ").strip().title()

    def _section_title_and_description(self, node: ConfigNode) -> tuple[str, str]:
        if node.comment:
            lines = [line.strip() for line in node.comment.splitlines() if line.strip()]
            if lines:
                first = lines[0]
                if len(first) <= 60 and not first.endswith("."):
                    description = "\n".join(lines[1:]).strip()
                    return first, description
        return self._titleize(node.key), node.comment

    def _infer_expected_type(self, node: ConfigNode) -> type:
        type_hints: dict[tuple[str, ...], type] = {
            ("longform_recording", "language"): str,
            ("transcription_options", "language"): str,
            ("main_transcriber", "initial_prompt"): str,
            ("diarization", "hf_token"): str,
            ("diarization", "min_speakers"): int,
            ("diarization", "max_speakers"): int,
            ("audio", "input_device_index"): int,
        }
        if node.value is not None:
            return type(node.value)
        if node.commented and node.value is not None:
            return type(node.value)
        return type_hints.get(node.path, str)

    def _format_config_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return yaml.safe_dump(
                value, default_flow_style=True, sort_keys=False
            ).strip()
        return str(value)

    def _create_config_row(self, node: ConfigNode) -> QWidget:
        row = QWidget()
        row.setObjectName("configRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(6)

        top_row = QHBoxLayout()
        label = QLabel(self._titleize(node.key))
        label.setObjectName("fieldLabel")
        top_row.addWidget(label)
        top_row.addStretch()

        expected_type = self._infer_expected_type(node)
        self._server_field_types[node.path] = expected_type
        self._server_field_original[node.path] = node.value
        self._server_field_commented[node.path] = node.commented

        if expected_type is bool:
            input_widget = QCheckBox()
            input_widget.setChecked(bool(node.value))
        else:
            input_widget = QLineEdit()
            input_widget.setText(self._format_config_value(node.value))
            input_widget.setPlaceholderText("null")

        if node.commented:
            enable_check = QCheckBox("Enable")
            enable_check.setChecked(False)
            enable_check.toggled.connect(input_widget.setEnabled)
            input_widget.setEnabled(False)
            self._server_field_enablers[node.path] = enable_check
            top_row.addWidget(enable_check)

        top_row.addWidget(input_widget)
        row_layout.addLayout(top_row)

        if node.comment:
            help_label = QLabel(node.comment)
            help_label.setObjectName("helpText")
            help_label.setWordWrap(True)
            row_layout.addWidget(help_label)

        self._server_field_inputs[node.path] = input_widget

        search_text = " ".join(
            [node.key, " ".join(node.path), node.comment or ""]
        ).lower()
        self._server_row_search[row] = search_text

        return row

    def _build_server_section(
        self, node: ConfigNode, parent_layout: QVBoxLayout, level: int = 0
    ) -> dict[str, Any] | None:
        if node.is_leaf:
            return None

        title, description = self._section_title_and_description(node)
        section_widget = CollapsibleSection(title, description, level=level)
        parent_layout.addWidget(section_widget)

        rows: list[QWidget] = []
        children: list[dict[str, Any]] = []

        for child in node.children:
            if child.is_leaf:
                if child.path in self._server_hidden_paths:
                    continue
                row = self._create_config_row(child)
                section_widget.content_layout.addWidget(row)
                rows.append(row)
            else:
                child_section = self._build_server_section(
                    child, section_widget.content_layout, level=level + 1
                )
                if child_section:
                    children.append(child_section)

        if not rows and not children:
            section_widget.setVisible(False)
            return None

        return {"section": section_widget, "rows": rows, "children": children}

    def _filter_server_settings(self, text: str) -> None:
        query = text.strip().lower()

        def filter_section(section_info: dict[str, Any]) -> bool:
            any_visible = False
            for row in section_info["rows"]:
                match = not query or query in self._server_row_search.get(row, "")
                row.setVisible(match)
                any_visible = any_visible or match

            for child in section_info["children"]:
                child_visible = filter_section(child)
                child["section"].setVisible(child_visible)
                any_visible = any_visible or child_visible

            if query:
                section_info["section"].set_expanded(any_visible)
            return any_visible

        for section in self._server_section_tree:
            visible = filter_section(section)
            section["section"].setVisible(visible or not query)

    def _parse_list_value(self, text: str) -> list[Any]:
        try:
            parsed = yaml.safe_load(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        if "," in text:
            parts = [p.strip() for p in text.split(",") if p.strip()]
            return [yaml.safe_load(part) for part in parts]
        raise ValueError("Invalid list format")

    def _collect_server_config_updates(
        self,
    ) -> tuple[dict[tuple[str, ...], Any], list[str]]:
        updates: dict[tuple[str, ...], Any] = {}
        errors: list[str] = []

        for path, widget in self._server_field_inputs.items():
            expected = self._server_field_types.get(path, str)
            original = self._server_field_original.get(path)
            is_commented = self._server_field_commented.get(path, False)
            enable_check = self._server_field_enablers.get(path)

            if is_commented and enable_check and not enable_check.isChecked():
                continue

            try:
                if expected is bool:
                    value = widget.isChecked()  # type: ignore[union-attr]
                else:
                    text = widget.text().strip()  # type: ignore[union-attr]
                    if text == "":
                        value = None
                    elif expected is str:
                        value = text
                    elif expected is int:
                        value = int(text)
                    elif expected is float:
                        value = float(text)
                    elif expected is list:
                        value = self._parse_list_value(text)
                    else:
                        value = yaml.safe_load(text)
            except Exception:
                errors.append(".".join(path))
                continue

            if is_commented:
                updates[path] = value
            else:
                if value != original:
                    updates[path] = value

        return updates, errors

    def _toggle_token_visibility(self, checked: bool) -> None:
        """Toggle token visibility."""
        if checked:
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_token_btn.setText("Hide")
        else:
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_token_btn.setText("Show")

    def _on_constrain_speakers_toggled(self, checked: bool) -> None:
        """Enable/disable the expected speakers spinbox based on checkbox state."""
        self.expected_speakers_spin.setEnabled(checked)

    def _refresh_devices(self) -> None:
        """Refresh the audio device list."""
        self.device_combo.clear()

        # Add default option
        self.device_combo.addItem("Default Device", None)

        # List available devices
        try:
            devices = AudioRecorder.list_devices()
            for device in devices:
                name = device.get("name", f"Device {device['index']}")
                self.device_combo.addItem(name, device["index"])
        except Exception as e:
            logger.warning(f"Failed to list audio devices: {e}")

    def _on_open_config_file(self) -> None:
        """Open the server config.yaml file in default text editor."""
        from PyQt6.QtWidgets import QMessageBox

        config_file = self._docker_manager._find_config_file()
        success = self._docker_manager.open_config_file()

        if not success:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Cannot Open Settings")

            if not config_file:
                msg_box.setText("Configuration file not found")
                msg_box.setInformativeText(
                    "The config.yaml file doesn't exist yet.\n\n"
                    "To create it:\n"
                    f"  1. Run first-time setup from terminal:\n"
                    f"     transcriptionsuite-setup\n\n"
                    f"  2. Or create it manually at:\n"
                    f"     {self._docker_manager.config_dir}/config.yaml"
                )
            else:
                msg_box.setText("Failed to open config.yaml")
                msg_box.setInformativeText(
                    f"The file exists but no editor was found.\n\n"
                    f"Location: {config_file}\n\n"
                    f"To edit manually, try:\n"
                    f"  • kate {config_file}\n"
                    f"  • gedit {config_file}\n"
                    f"  • nano {config_file}"
                )

            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()

    def _create_notebook_tab(self) -> None:
        """Create the Notebook tab for backup/restore functionality."""
        import asyncio
        from PyQt6.QtWidgets import QMessageBox, QListWidget, QListWidgetItem

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Backup section
        backup_group = QGroupBox("Database Backup")
        backup_group.setObjectName("settingsGroup")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setSpacing(12)

        backup_desc = QLabel(
            "Create a backup of your Audio Notebook database. "
            "Backups include all recordings metadata and transcriptions."
        )
        backup_desc.setWordWrap(True)
        backup_desc.setObjectName("descriptionLabel")
        backup_layout.addWidget(backup_desc)

        # Backup list
        self._backup_list = QListWidget()
        self._backup_list.setObjectName("backupList")
        self._backup_list.setMaximumHeight(120)
        self._backup_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
                color: #e0e0e0;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 6px 8px;
            }
            QListWidget::item:selected {
                background-color: #2d4a6d;
            }
        """)
        backup_layout.addWidget(self._backup_list)

        # Backup buttons
        backup_btn_layout = QHBoxLayout()
        backup_btn_layout.setSpacing(12)

        self._create_backup_btn = QPushButton("Create Backup")
        self._create_backup_btn.setObjectName("primaryButton")
        self._create_backup_btn.clicked.connect(self._on_create_backup)
        backup_btn_layout.addWidget(self._create_backup_btn)

        self._refresh_backups_btn = QPushButton("Refresh")
        self._refresh_backups_btn.setObjectName("secondaryButton")
        self._refresh_backups_btn.clicked.connect(self._refresh_backup_list)
        backup_btn_layout.addWidget(self._refresh_backups_btn)

        backup_btn_layout.addStretch()
        backup_layout.addLayout(backup_btn_layout)

        layout.addWidget(backup_group)

        # Restore section
        restore_group = QGroupBox("Database Restore")
        restore_group.setObjectName("settingsGroup")
        restore_layout = QVBoxLayout(restore_group)
        restore_layout.setSpacing(12)

        restore_desc = QLabel(
            "Restore your database from a backup. "
            "Warning: This will replace all current data with the backup data. "
            "A safety backup will be created automatically before restoring."
        )
        restore_desc.setWordWrap(True)
        restore_desc.setObjectName("descriptionLabel")
        restore_desc.setStyleSheet("color: #ff9800;")  # Warning color
        restore_layout.addWidget(restore_desc)

        restore_btn_layout = QHBoxLayout()

        self._restore_backup_btn = QPushButton("Restore Selected Backup")
        self._restore_backup_btn.setObjectName("dangerButton")
        self._restore_backup_btn.clicked.connect(self._on_restore_backup)
        restore_btn_layout.addWidget(self._restore_backup_btn)

        restore_btn_layout.addStretch()
        restore_layout.addLayout(restore_btn_layout)

        layout.addWidget(restore_group)

        layout.addStretch()

        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "Notebook")

        # Load backup list on tab creation
        self._refresh_backup_list()

    def _get_api_client(self):
        """Get API client for backup operations."""
        from dashboard.common.api_client import APIClient
        from dashboard.common.docker_manager import ServerStatus

        server_status = self._docker_manager.get_server_status()
        if server_status != ServerStatus.RUNNING:
            return None

        use_remote = self.config.get("server", "use_remote", default=False)
        use_https = self.config.get("server", "use_https", default=False)

        if use_remote:
            host = self.config.get("server", "remote_host", default="")
            port = self.config.get("server", "port", default=8443)
        else:
            host = "localhost"
            port = self.config.get("server", "port", default=8000)

        token = self.config.get("server", "token", default="")

        if not host:
            return None

        return APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token if token else None,
        )

    def _refresh_backup_list(self) -> None:
        """Refresh the list of available backups."""
        import asyncio
        from PyQt6.QtWidgets import QListWidgetItem

        self._backup_list.clear()

        api_client = self._get_api_client()
        if not api_client:
            item = QListWidgetItem("Server not running - cannot list backups")
            item.setForeground(Qt.GlobalColor.gray)
            self._backup_list.addItem(item)
            return

        async def fetch_backups():
            try:
                backups = await api_client.list_backups()
                return backups
            except Exception as e:
                logger.error(f"Failed to list backups: {e}")
                return None
            finally:
                await api_client.close()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule task and return immediately
                asyncio.create_task(self._async_refresh_backup_list(api_client))
            else:
                backups = loop.run_until_complete(fetch_backups())
                self._populate_backup_list(backups)
        except RuntimeError:
            backups = asyncio.run(fetch_backups())
            self._populate_backup_list(backups)

    async def _async_refresh_backup_list(self, api_client) -> None:
        """Async version of backup list refresh."""
        try:
            backups = await api_client.list_backups()
            self._populate_backup_list(backups)
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            self._populate_backup_list(None)
        finally:
            await api_client.close()

    def _populate_backup_list(self, backups) -> None:
        """Populate the backup list widget."""
        from PyQt6.QtWidgets import QListWidgetItem

        self._backup_list.clear()

        if backups is None:
            item = QListWidgetItem("Failed to load backups")
            item.setForeground(Qt.GlobalColor.red)
            self._backup_list.addItem(item)
            return

        if not backups:
            item = QListWidgetItem("No backups available")
            item.setForeground(Qt.GlobalColor.gray)
            self._backup_list.addItem(item)
            return

        for backup in backups:
            filename = backup.get("filename", "Unknown")
            created = backup.get("created_at", "")
            size_bytes = backup.get("size_bytes", 0)

            # Format size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

            # Format date
            if created:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(created)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = created[:16] if len(created) > 16 else created
            else:
                date_str = "Unknown date"

            item = QListWidgetItem(f"{filename}  |  {date_str}  |  {size_str}")
            item.setData(Qt.ItemDataRole.UserRole, filename)
            self._backup_list.addItem(item)

    def _on_create_backup(self) -> None:
        """Handle create backup button click."""
        import asyncio
        from PyQt6.QtWidgets import QMessageBox

        api_client = self._get_api_client()
        if not api_client:
            QMessageBox.warning(
                self,
                "Server Not Running",
                "The server must be running to create backups.",
            )
            return

        async def create_backup():
            try:
                result = await api_client.create_backup()
                return result
            except Exception as e:
                logger.error(f"Failed to create backup: {e}")
                return {"success": False, "message": str(e)}
            finally:
                await api_client.close()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_create_backup(api_client))
            else:
                result = loop.run_until_complete(create_backup())
                self._handle_backup_result(result)
        except RuntimeError:
            result = asyncio.run(create_backup())
            self._handle_backup_result(result)

    async def _async_create_backup(self, api_client) -> None:
        """Async version of backup creation."""
        from PyQt6.QtWidgets import QMessageBox

        try:
            result = await api_client.create_backup()
            self._handle_backup_result(result)
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            QMessageBox.critical(self, "Backup Failed", f"Failed to create backup: {e}")
        finally:
            await api_client.close()

    def _handle_backup_result(self, result) -> None:
        """Handle backup creation result."""
        from PyQt6.QtWidgets import QMessageBox

        if result.get("success"):
            QMessageBox.information(
                self,
                "Backup Created",
                f"Backup created successfully.\n\n{result.get('backup', {}).get('filename', '')}",
            )
            self._refresh_backup_list()
        else:
            QMessageBox.critical(
                self,
                "Backup Failed",
                f"Failed to create backup: {result.get('message', 'Unknown error')}",
            )

    def _on_restore_backup(self) -> None:
        """Handle restore backup button click."""
        import asyncio
        from PyQt6.QtWidgets import QMessageBox

        selected_items = self._backup_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(
                self,
                "No Backup Selected",
                "Please select a backup from the list to restore.",
            )
            return

        filename = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if not filename:
            QMessageBox.warning(
                self, "Invalid Selection", "Please select a valid backup."
            )
            return

        # Confirm restore
        reply = QMessageBox.warning(
            self,
            "Confirm Restore",
            f"Are you sure you want to restore from:\n\n{filename}\n\n"
            "This will replace ALL current data with the backup data.\n"
            "A safety backup will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        api_client = self._get_api_client()
        if not api_client:
            QMessageBox.warning(
                self,
                "Server Not Running",
                "The server must be running to restore backups.",
            )
            return

        async def restore_backup():
            try:
                result = await api_client.restore_backup(filename)
                return result
            except Exception as e:
                logger.error(f"Failed to restore backup: {e}")
                return {"success": False, "message": str(e)}
            finally:
                await api_client.close()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_restore_backup(api_client, filename))
            else:
                result = loop.run_until_complete(restore_backup())
                self._handle_restore_result(result)
        except RuntimeError:
            result = asyncio.run(restore_backup())
            self._handle_restore_result(result)

    async def _async_restore_backup(self, api_client, filename: str) -> None:
        """Async version of backup restore."""
        from PyQt6.QtWidgets import QMessageBox

        try:
            result = await api_client.restore_backup(filename)
            self._handle_restore_result(result)
        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            QMessageBox.critical(
                self, "Restore Failed", f"Failed to restore backup: {e}"
            )
        finally:
            await api_client.close()

    def _handle_restore_result(self, result) -> None:
        """Handle backup restore result."""
        from PyQt6.QtWidgets import QMessageBox

        if result.get("success"):
            QMessageBox.information(
                self,
                "Restore Complete",
                f"Database restored successfully from:\n{result.get('restored_from', 'backup')}\n\n"
                "You may need to refresh the Notebook view to see the restored data.",
            )
            self._refresh_backup_list()
        else:
            QMessageBox.critical(
                self,
                "Restore Failed",
                f"Failed to restore backup: {result.get('message', 'Unknown error')}",
            )

    def _load_values(self) -> None:
        """Load current configuration values into the dialog."""
        # App tab
        self.auto_copy_check.setChecked(
            self.config.get("clipboard", "auto_copy", default=True)
        )
        self.notifications_check.setChecked(
            self.config.get("ui", "notifications", default=True)
        )
        self.stop_server_check.setChecked(
            self.config.get("dashboard", "stop_server_on_quit", default=True)
        )

        # Client tab - Audio
        current_device = self.config.get("recording", "device_index")
        if current_device is None:
            self.device_combo.setCurrentIndex(0)  # Default
        else:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == current_device:
                    self.device_combo.setCurrentIndex(i)
                    break

        # Live Mode grace period
        grace_period = self.config.get("live_mode", "grace_period", default=1.0)
        self.grace_period_spin.setValue(grace_period)

        # Client tab - Diarization
        expected_speakers = self.config.get(
            "diarization", "expected_speakers", default=None
        )
        if expected_speakers is not None:
            self.constrain_speakers_check.setChecked(True)
            self.expected_speakers_spin.setValue(expected_speakers)
            self.expected_speakers_spin.setEnabled(True)
        else:
            self.constrain_speakers_check.setChecked(False)
            self.expected_speakers_spin.setValue(2)
            self.expected_speakers_spin.setEnabled(False)

        # Client tab - Audio Notebook
        auto_add_notebook = self.config.get_server_config(
            "longform_recording", "auto_add_to_audio_notebook", default=False
        )
        self.auto_add_notebook_check.setChecked(auto_add_notebook)

        # Client tab - Connection
        self.host_edit.setText(self.config.get("server", "host", default="localhost"))
        self.port_spin.setValue(self.config.get("server", "port", default=8000))
        self.https_check.setChecked(
            self.config.get("server", "use_https", default=False)
        )
        token = self.config.get("server", "token", default="")
        self.token_edit.setText(token.strip() if token else "")
        self.use_remote_check.setChecked(
            self.config.get("server", "use_remote", default=False)
        )
        self.remote_host_edit.setText(
            self.config.get("server", "remote_host", default="")
        )

    def _save_and_close(self) -> None:
        """Save settings and close the dialog."""
        # App tab
        self.config.set(
            "clipboard", "auto_copy", value=self.auto_copy_check.isChecked()
        )
        self.config.set(
            "ui", "notifications", value=self.notifications_check.isChecked()
        )
        self.config.set(
            "dashboard", "stop_server_on_quit", value=self.stop_server_check.isChecked()
        )

        # Client tab - Audio
        device_index = self.device_combo.currentData()
        self.config.set("recording", "device_index", value=device_index)

        # Live Mode grace period
        self.config.set(
            "live_mode", "grace_period", value=self.grace_period_spin.value()
        )

        # Client tab - Diarization
        if self.constrain_speakers_check.isChecked():
            self.config.set(
                "diarization",
                "expected_speakers",
                value=self.expected_speakers_spin.value(),
            )
        else:
            self.config.set("diarization", "expected_speakers", value=None)

        # Client tab - Audio Notebook
        auto_add_value = self.auto_add_notebook_check.isChecked()

        # Client tab - Connection
        self.config.set(
            "server", "host", value=self.host_edit.text().strip() or "localhost"
        )
        self.config.set("server", "port", value=self.port_spin.value())
        self.config.set("server", "use_https", value=self.https_check.isChecked())
        self.config.set("server", "token", value=self.token_edit.text().strip())
        self.config.set("server", "use_remote", value=self.use_remote_check.isChecked())
        self.config.set(
            "server", "remote_host", value=self.remote_host_edit.text().strip()
        )

        # Save to file
        if not self.config.save():
            logger.error("Failed to save settings")
            return

        # Save server config edits (if present)
        updates, errors = self._collect_server_config_updates()
        updates[("longform_recording", "auto_add_to_audio_notebook")] = auto_add_value
        if errors:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Invalid Server Settings",
                "Some values could not be parsed:\n\n" + "\n".join(errors),
            )
            return

        if self._server_config_exists:
            if not self.config.set_server_config_values(updates):
                from PyQt6.QtWidgets import QMessageBox

                QMessageBox.critical(
                    self,
                    "Server Settings Not Saved",
                    "Failed to update config.yaml. Check file permissions.",
                )
                return

        logger.info("Settings saved successfully")

        self.accept()
