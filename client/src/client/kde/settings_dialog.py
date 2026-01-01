"""
Settings dialog for TranscriptionSuite client.

Provides a tabbed dialog for configuring client settings.
"""

import logging

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
    """Settings dialog with tabbed interface."""

    def __init__(self, config: ClientConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config

        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)
        self.setMinimumHeight(350)
        
        # Set window icon from system theme
        icon = QIcon.fromTheme("audio-input-microphone")
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Main layout
        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self._create_connection_tab()
        self._create_audio_tab()
        self._create_behavior_tab()

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save_and_close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Load current values
        self._load_values()

    def _create_connection_tab(self) -> None:
        """Create the Connection settings tab."""
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Local host
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        form.addRow("Local Host:", self.host_edit)

        # Remote host (Tailscale)
        self.remote_host_edit = QLineEdit()
        self.remote_host_edit.setPlaceholderText("e.g., my-desktop.tail1234.ts.net")
        form.addRow("Remote Host:", self.remote_host_edit)

        # Use remote toggle
        self.use_remote_check = QCheckBox("Use remote server instead of local")
        form.addRow("", self.use_remote_check)

        # Help text for remote usage
        remote_help_label = QLabel(
            "Don't forget to enable HTTPS and switch port to 8443 if using remote server"
        )
        remote_help_label.setWordWrap(True)
        remote_help_label.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", remote_help_label)

        # Token
        token_layout = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Authentication token")
        token_layout.addWidget(self.token_edit)

        self.show_token_btn = QPushButton("Show")
        self.show_token_btn.setCheckable(True)
        self.show_token_btn.setFixedWidth(60)
        self.show_token_btn.toggled.connect(self._toggle_token_visibility)
        token_layout.addWidget(self.show_token_btn)

        form.addRow("Auth Token:", token_layout)

        # Port
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8000)
        form.addRow("Port:", self.port_spin)

        # HTTPS
        self.https_check = QCheckBox("Use HTTPS")
        form.addRow("", self.https_check)

        # Help text for host settings
        host_help_label = QLabel(
            "Enter ONLY the hostname (no http://, no port). Examples:\n"
            "• Local: localhost or 127.0.0.1\n"
            "• Remote: my-machine.tail1234.ts.net or 100.101.102.103"
        )
        host_help_label.setWordWrap(True)
        host_help_label.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", host_help_label)

        self.tabs.addTab(tab, "Connection")

    def _create_audio_tab(self) -> None:
        """Create the Audio settings tab."""
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Device selector
        device_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(250)
        device_layout.addWidget(self.device_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(70)
        refresh_btn.clicked.connect(self._refresh_devices)
        device_layout.addWidget(refresh_btn)

        form.addRow("Input Device:", device_layout)

        # Sample rate info
        self.sample_rate_label = QLabel("Sample Rate: 16000 Hz (fixed for Whisper)")
        self.sample_rate_label.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", self.sample_rate_label)

        # Populate devices
        self._refresh_devices()

        self.tabs.addTab(tab, "Audio")

    def _create_behavior_tab(self) -> None:
        """Create the Behavior settings tab."""
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.hotkeys_enabled_check = QCheckBox("Enable global hotkeys")
        form.addRow("", self.hotkeys_enabled_check)

        # Auto-copy to clipboard
        self.auto_copy_check = QCheckBox("Automatically copy transcription to clipboard")
        form.addRow("", self.auto_copy_check)

        # Notifications
        self.notifications_check = QCheckBox("Show desktop notifications")
        form.addRow("", self.notifications_check)

        # TODO: Implement configurable click actions
        # Left-click action
        # self.left_click_combo = QComboBox()
        # self.left_click_combo.addItem("Start Recording", "start_recording")
        # self.left_click_combo.addItem("Show Menu", "show_menu")
        # form.addRow("Left-click action:", self.left_click_combo)

        # Middle-click action
        # self.middle_click_combo = QComboBox()
        # self.middle_click_combo.addItem("Stop & Transcribe", "stop_transcribe")
        # self.middle_click_combo.addItem("Cancel Recording", "cancel_recording")
        # self.middle_click_combo.addItem("None", "none")
        # form.addRow("Middle-click action:", self.middle_click_combo)

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
        self.https_check.setChecked(self.config.get("server", "use_https", default=False))
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

        # TODO: Implement configurable click actions
        # Left-click action
        # left_click = self.config.get("ui", "left_click", default="start_recording")
        # index = self.left_click_combo.findData(left_click)
        # if index >= 0:
        #     self.left_click_combo.setCurrentIndex(index)

        # Middle-click action
        # middle_click = self.config.get("ui", "middle_click", default="stop_transcribe")
        # index = self.middle_click_combo.findData(middle_click)
        # if index >= 0:
        #     self.middle_click_combo.setCurrentIndex(index)

    def _save_and_close(self) -> None:
        """Save settings and close the dialog."""
        # Connection tab
        self.config.set("server", "host", value=self.host_edit.text().strip() or "localhost")
        self.config.set("server", "port", value=self.port_spin.value())
        self.config.set("server", "use_https", value=self.https_check.isChecked())
        self.config.set("server", "token", value=self.token_edit.text().strip())
        self.config.set("server", "use_remote", value=self.use_remote_check.isChecked())
        self.config.set("server", "remote_host", value=self.remote_host_edit.text().strip())

        # Audio tab
        device_index = self.device_combo.currentData()
        self.config.set("recording", "device_index", value=device_index)

        # Behavior tab
        self.config.set(
            "hotkeys", "enabled", value=self.hotkeys_enabled_check.isChecked()
        )
        self.config.set("clipboard", "auto_copy", value=self.auto_copy_check.isChecked())
        self.config.set("ui", "notifications", value=self.notifications_check.isChecked())
        # TODO: Implement configurable click actions
        # self.config.set("ui", "left_click", value=self.left_click_combo.currentData())
        # self.config.set("ui", "middle_click", value=self.middle_click_combo.currentData())

        # Save to file
        if self.config.save():
            logger.info("Settings saved successfully")
        else:
            logger.error("Failed to save settings")

        self.accept()
