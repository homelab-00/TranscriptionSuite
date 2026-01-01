"""
Settings dialog for TranscriptionSuite client.

Provides a tabbed dialog for configuring client settings.
Styled to match the Mothership UI design language.
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from client.common.audio_recorder import AudioRecorder
from client.common.config import ClientConfig

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Settings dialog with tabbed interface matching Mothership design language."""

    def __init__(self, config: ClientConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config

        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)

        # Set window icon from system theme
        icon = QIcon.fromTheme("preferences-system")
        if icon.isNull():
            icon = QIcon.fromTheme("audio-input-microphone")
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self._create_connection_tab()
        self._create_audio_tab()
        self._create_behavior_tab()

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
        """Apply dark theme styling matching Mothership UI."""
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
            
            QLabel#helpText {
                color: #6c757d;
                font-size: 11px;
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
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #3d3d3d;
                background-color: #1e1e1e;
            }
            
            QCheckBox::indicator:checked {
                background-color: #90caf9;
                border-color: #90caf9;
            }
            
            QCheckBox::indicator:hover {
                border-color: #90caf9;
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
            
            QFrame#settingsCard {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }
        """)

    def _create_connection_tab(self) -> None:
        """Create the Connection settings tab."""
        tab = QWidget()
        tab.setObjectName("tabContent")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Local host row
        local_row = QHBoxLayout()
        local_label = QLabel("Local Host:")
        local_label.setObjectName("fieldLabel")
        local_row.addWidget(local_label)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        local_row.addWidget(self.host_edit, 1)
        layout.addLayout(local_row)

        # Remote host row
        remote_row = QHBoxLayout()
        remote_label = QLabel("Remote Host:")
        remote_label.setObjectName("fieldLabel")
        remote_row.addWidget(remote_label)
        self.remote_host_edit = QLineEdit()
        self.remote_host_edit.setPlaceholderText("e.g., my-desktop.tail1234.ts.net")
        remote_row.addWidget(self.remote_host_edit, 1)
        layout.addLayout(remote_row)

        # Use remote checkbox
        self.use_remote_check = QCheckBox("Use remote server instead of local")
        layout.addWidget(self.use_remote_check)

        # Help text for remote
        remote_help = QLabel(
            "Don't forget to enable HTTPS and switch port to 8443 if using remote server"
        )
        remote_help.setObjectName("helpText")
        remote_help.setWordWrap(True)
        layout.addWidget(remote_help)

        layout.addSpacing(8)

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

        layout.addLayout(token_row)

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
        layout.addLayout(port_row)

        # HTTPS checkbox
        self.https_check = QCheckBox("Use HTTPS")
        layout.addWidget(self.https_check)

        layout.addSpacing(8)

        # Help text for host settings
        host_help = QLabel(
            "Enter ONLY the hostname (no http://, no port). Examples:\n"
            "• Local: localhost or 127.0.0.1\n"
            "• Remote: my-machine.tail1234.ts.net or 100.101.102.103"
        )
        host_help.setObjectName("helpText")
        host_help.setWordWrap(True)
        layout.addWidget(host_help)

        layout.addStretch()

        self.tabs.addTab(tab, "Connection")

    def _create_audio_tab(self) -> None:
        """Create the Audio settings tab."""
        tab = QWidget()
        tab.setObjectName("tabContent")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

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

        layout.addLayout(device_row)

        # Sample rate info
        sample_rate_label = QLabel("Sample Rate: 16000 Hz (fixed for Whisper)")
        sample_rate_label.setObjectName("helpText")
        layout.addWidget(sample_rate_label)

        # Populate devices
        self._refresh_devices()

        layout.addStretch()

        self.tabs.addTab(tab, "Audio")

    def _create_behavior_tab(self) -> None:
        """Create the Behavior settings tab."""
        tab = QWidget()
        tab.setObjectName("tabContent")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Hotkeys checkbox
        self.hotkeys_enabled_check = QCheckBox("Enable global hotkeys")
        layout.addWidget(self.hotkeys_enabled_check)

        # Auto-copy checkbox
        self.auto_copy_check = QCheckBox(
            "Automatically copy transcription to clipboard"
        )
        layout.addWidget(self.auto_copy_check)

        # Notifications checkbox
        self.notifications_check = QCheckBox("Show desktop notifications")
        layout.addWidget(self.notifications_check)

        layout.addStretch()

        self.tabs.addTab(tab, "Behavior")

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

    def _load_values(self) -> None:
        """Load current configuration values into the dialog."""
        # Connection tab
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

        # Audio tab - select current device
        current_device = self.config.get("recording", "device_index")
        if current_device is None:
            self.device_combo.setCurrentIndex(0)  # Default
        else:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == current_device:
                    self.device_combo.setCurrentIndex(i)
                    break

        # Behavior tab
        self.hotkeys_enabled_check.setChecked(
            self.config.get("hotkeys", "enabled", default=True)
        )
        self.auto_copy_check.setChecked(
            self.config.get("clipboard", "auto_copy", default=True)
        )
        self.notifications_check.setChecked(
            self.config.get("ui", "notifications", default=True)
        )

    def _save_and_close(self) -> None:
        """Save settings and close the dialog."""
        # Connection tab
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

        # Audio tab
        device_index = self.device_combo.currentData()
        self.config.set("recording", "device_index", value=device_index)

        # Behavior tab
        self.config.set(
            "hotkeys", "enabled", value=self.hotkeys_enabled_check.isChecked()
        )
        self.config.set(
            "clipboard", "auto_copy", value=self.auto_copy_check.isChecked()
        )
        self.config.set(
            "ui", "notifications", value=self.notifications_check.isChecked()
        )

        # Save to file
        if self.config.save():
            logger.info("Settings saved successfully")
        else:
            logger.error("Failed to save settings")

        self.accept()
