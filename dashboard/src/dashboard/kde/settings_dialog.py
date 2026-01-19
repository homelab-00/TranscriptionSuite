"""
Settings dialog for TranscriptionSuite.

Provides a unified tabbed dialog for configuring all settings.
Styled to match the Dashboard UI design language.

Tabs:
- App: Clipboard, notifications, stop server on quit behavior
- Client: Audio input device + connection settings
- Server: Open config.yaml button + path display
"""

import logging

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
    QVBoxLayout,
    QWidget,
)

from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.config import ClientConfig, get_config_dir
from dashboard.common.docker_manager import DockerManager

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Unified settings dialog with tabbed interface matching Dashboard design."""

    def __init__(self, config: ClientConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self._docker_manager = DockerManager()

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

        # Create tabs in order: App, Client, Server
        self._create_app_tab()
        self._create_client_tab()
        self._create_server_tab()

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
                color: #90caf9;
                border-bottom: 2px solid #90caf9;
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
                color: #90caf9;
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
                border-color: #90caf9;
            }

            QLineEdit:disabled {
                background-color: #1a1a1a;
                color: #606060;
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
                border-color: #90caf9;
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
                border-color: #90caf9;
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
                selection-color: #90caf9;
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
                background-color: #90caf9;
                border-color: #90caf9;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMxMjEyMTIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cG9seWxpbmUgcG9pbnRzPSIyMCA2IDkgMTcgNCAxMiI+PC9wb2x5bGluZT48L3N2Zz4=);
            }

            QCheckBox::indicator:unchecked:hover {
                border-color: #707070;
                background-color: #252525;
            }

            QCheckBox::indicator:checked:hover {
                background-color: #42a5f5;
                border-color: #42a5f5;
            }

            #primaryButton {
                background-color: #90caf9;
                border: none;
                border-radius: 6px;
                color: #121212;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 500;
                min-width: 80px;
            }

            #primaryButton:hover {
                background-color: #42a5f5;
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
                color: #90caf9;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 4px;
                background-color: #1e1e1e;
                color: #90caf9;
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
            "• Remote: my-machine.tail1234.ts.net or 100.101.102.103"
        )
        host_help.setObjectName("helpText")
        host_help.setWordWrap(True)
        connection_layout.addWidget(host_help)

        # Use remote checkbox
        self.use_remote_check = QCheckBox("Use remote server instead of local")
        connection_layout.addWidget(self.use_remote_check)

        # Help text for remote
        remote_help = QLabel(
            "Don't forget to enable HTTPS and switch port to 8443 if using remote server"
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

        # === Advanced TLS Options Sub-section ===
        tls_group = QGroupBox("Advanced TLS Options")
        tls_layout = QVBoxLayout(tls_group)

        # TLS Verify checkbox
        self.tls_verify_check = QCheckBox("Verify TLS certificates")
        self.tls_verify_check.setChecked(True)
        self.tls_verify_check.setToolTip(
            "Disable for self-signed certificates.\nConnection is still encrypted."
        )
        tls_layout.addWidget(self.tls_verify_check)

        # Allow HTTP to remote hosts
        self.allow_insecure_http_check = QCheckBox(
            "Allow HTTP to remote hosts (WireGuard encrypts traffic)"
        )
        self.allow_insecure_http_check.setToolTip(
            "Enable for Tailscale without MagicDNS.\n"
            "Use Tailscale IP (e.g., 100.x.y.z) with port 8000."
        )
        tls_layout.addWidget(self.allow_insecure_http_check)

        connection_layout.addWidget(tls_group)

        layout.addWidget(connection_group)

        layout.addStretch()

        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "Client")

    def _create_server_tab(self) -> None:
        """Create the Server settings tab (open config.yaml + path info)."""
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

        # === Server Configuration Section ===
        config_group = QGroupBox("Server Configuration")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(12)

        # Description
        desc_label = QLabel(
            "Server settings are stored in config.yaml. Click below to open "
            "it in your default text editor."
        )
        desc_label.setWordWrap(True)
        config_layout.addWidget(desc_label)

        # Open config button
        open_config_btn = QPushButton("Open config.yaml in Text Editor")
        open_config_btn.setObjectName("primaryButton")
        open_config_btn.clicked.connect(self._on_open_config_file)
        config_layout.addWidget(open_config_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Separator
        separator = QFrame()
        separator.setObjectName("sectionSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        config_layout.addWidget(separator)

        # Path info
        config_dir = get_config_dir()
        config_path = config_dir / "config.yaml"

        path_info_label = QLabel("You can also edit the config file directly at:")
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

    def _toggle_token_visibility(self, checked: bool) -> None:
        """Toggle token visibility."""
        if checked:
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_token_btn.setText("Hide")
        else:
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_token_btn.setText("Show")

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
                    f"     transcription-suite-setup\n\n"
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

        # Advanced TLS options
        self.tls_verify_check.setChecked(
            self.config.get("server", "tls_verify", default=True)
        )
        self.allow_insecure_http_check.setChecked(
            self.config.get("server", "allow_insecure_http", default=False)
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

        # Advanced TLS options
        self.config.set("server", "tls_verify", value=self.tls_verify_check.isChecked())
        self.config.set(
            "server",
            "allow_insecure_http",
            value=self.allow_insecure_http_check.isChecked(),
        )

        # Save to file
        if self.config.save():
            logger.info("Settings saved successfully")
        else:
            logger.error("Failed to save settings")

        self.accept()
