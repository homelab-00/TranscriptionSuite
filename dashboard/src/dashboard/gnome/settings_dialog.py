"""
Settings dialog for TranscriptionSuite GNOME client.

Provides a GTK3 tabbed dialog for configuring client settings.
"""

import logging
from typing import Any

from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.config import ClientConfig

logger = logging.getLogger(__name__)

# Import GTK
try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    Gtk = None  # type: ignore


class SettingsDialog:
    """GTK3 Settings dialog with tabbed interface."""

    def __init__(self, config: ClientConfig, parent: Any = None):
        if Gtk is None:
            raise ImportError("GTK3 is required for the settings dialog")

        self.config = config
        self.dialog: Gtk.Dialog | None = None

        # Widgets that need to be accessed later
        self.port_spin: Gtk.SpinButton | None = None
        self.https_check: Gtk.CheckButton | None = None
        self.token_entry: Gtk.Entry | None = None
        self.use_remote_check: Gtk.CheckButton | None = None
        self.host_entry: Gtk.Entry | None = None
        self.remote_host_entry: Gtk.Entry | None = None
        self.device_combo: Gtk.ComboBoxText | None = None
        self.auto_copy_check: Gtk.CheckButton | None = None
        self.notifications_check: Gtk.CheckButton | None = None

    def show(self) -> None:
        """Create and show the settings dialog."""
        self.dialog = Gtk.Dialog(
            title="Settings",
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self.dialog.set_default_size(450, 400)

        # Set window icon from system theme
        self.dialog.set_icon_name("audio-input-microphone-symbolic")

        # Add buttons
        self.dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.dialog.add_button("Save", Gtk.ResponseType.OK)

        # Create notebook (tab container)
        notebook = Gtk.Notebook()
        content_area = self.dialog.get_content_area()
        content_area.set_spacing(8)
        content_area.set_margin_start(8)
        content_area.set_margin_end(8)
        content_area.set_margin_top(8)
        content_area.set_margin_bottom(8)
        content_area.pack_start(notebook, True, True, 0)

        # Create tabs
        notebook.append_page(
            self._create_connection_tab(), Gtk.Label(label="Connection")
        )
        notebook.append_page(self._create_audio_tab(), Gtk.Label(label="Audio"))
        notebook.append_page(self._create_behavior_tab(), Gtk.Label(label="Behavior"))

        # Load current values
        self._load_values()

        # Show all widgets
        self.dialog.show_all()

        # Run dialog
        response = self.dialog.run()
        if response == Gtk.ResponseType.OK:
            self._save_values()

        self.dialog.destroy()

    def _create_connection_tab(self) -> Gtk.Box:
        """Create the Connection settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Local host
        host_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        host_label = Gtk.Label(label="Local Host:")
        host_label.set_xalign(0)
        host_label.set_size_request(100, -1)
        host_box.pack_start(host_label, False, False, 0)

        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text("localhost")
        host_box.pack_start(self.host_entry, True, True, 0)
        box.pack_start(host_box, False, False, 0)

        # Remote host
        remote_host_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        remote_host_label = Gtk.Label(label="Remote Host:")
        remote_host_label.set_xalign(0)
        remote_host_label.set_size_request(100, -1)
        remote_host_box.pack_start(remote_host_label, False, False, 0)

        self.remote_host_entry = Gtk.Entry()
        self.remote_host_entry.set_placeholder_text("e.g., my-desktop.tail1234.ts.net")
        remote_host_box.pack_start(self.remote_host_entry, True, True, 0)
        box.pack_start(remote_host_box, False, False, 0)

        # Use remote toggle
        self.use_remote_check = Gtk.CheckButton(
            label="Use remote server instead of local"
        )
        box.pack_start(self.use_remote_check, False, False, 0)

        # Help text for remote usage
        remote_help_label = Gtk.Label()
        remote_help_label.set_markup(
            '<span size="small" foreground="gray">'
            "Don't forget to enable HTTPS and switch port to 8443 if using remote server"
            "</span>"
        )
        remote_help_label.set_line_wrap(True)
        remote_help_label.set_xalign(0)
        box.pack_start(remote_help_label, False, False, 0)

        # Token
        token_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        token_label = Gtk.Label(label="Auth Token:")
        token_label.set_xalign(0)
        token_label.set_size_request(100, -1)
        token_box.pack_start(token_label, False, False, 0)

        self.token_entry = Gtk.Entry()
        self.token_entry.set_visibility(False)
        self.token_entry.set_placeholder_text("Authentication token")
        token_box.pack_start(self.token_entry, True, True, 0)

        show_token_btn = Gtk.ToggleButton(label="Show")
        show_token_btn.connect("toggled", self._on_toggle_token_visibility)
        token_box.pack_start(show_token_btn, False, False, 0)
        box.pack_start(token_box, False, False, 0)

        # Port
        port_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        port_label = Gtk.Label(label="Port:")
        port_label.set_xalign(0)
        port_label.set_size_request(100, -1)
        port_box.pack_start(port_label, False, False, 0)

        adjustment = Gtk.Adjustment(value=8000, lower=1, upper=65535, step_increment=1)
        self.port_spin = Gtk.SpinButton()
        self.port_spin.set_adjustment(adjustment)
        self.port_spin.set_numeric(True)
        port_box.pack_start(self.port_spin, True, True, 0)
        box.pack_start(port_box, False, False, 0)

        # HTTPS checkbox
        self.https_check = Gtk.CheckButton(label="Use HTTPS")
        box.pack_start(self.https_check, False, False, 0)

        # Help text
        host_help_label = Gtk.Label()
        host_help_label.set_markup(
            '<span size="small" foreground="gray">'
            "Enter ONLY the hostname (no http://, no port). Examples:\n"
            "  - Local: localhost or 127.0.0.1\n"
            "  - Remote: my-machine.tail1234.ts.net or 100.101.102.103"
            "</span>"
        )
        host_help_label.set_line_wrap(True)
        host_help_label.set_xalign(0)
        box.pack_start(host_help_label, False, False, 0)

        return box

    def _create_audio_tab(self) -> Gtk.Box:
        """Create the Audio settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Device selector
        device_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        device_label = Gtk.Label(label="Input Device:")
        device_label.set_xalign(0)
        device_label.set_size_request(100, -1)
        device_box.pack_start(device_label, False, False, 0)

        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.set_hexpand(True)
        device_box.pack_start(self.device_combo, True, True, 0)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", self._on_refresh_devices)
        device_box.pack_start(refresh_btn, False, False, 0)
        box.pack_start(device_box, False, False, 0)

        # Populate devices
        self._refresh_devices()

        # Sample rate info
        sample_rate_label = Gtk.Label()
        sample_rate_label.set_markup(
            '<span size="small" foreground="gray">'
            "Sample Rate: 16000 Hz (fixed for Whisper)"
            "</span>"
        )
        sample_rate_label.set_xalign(0)
        box.pack_start(sample_rate_label, False, False, 0)

        return box

    def _create_behavior_tab(self) -> Gtk.Box:
        """Create the Behavior settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # === Clipboard Section ===
        clipboard_frame = Gtk.Frame(label="Clipboard")
        clipboard_frame.set_margin_bottom(8)
        clipboard_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        clipboard_box.set_margin_start(8)
        clipboard_box.set_margin_end(8)
        clipboard_box.set_margin_top(8)
        clipboard_box.set_margin_bottom(8)

        # Auto-copy to clipboard
        self.auto_copy_check = Gtk.CheckButton(
            label="Automatically copy transcription to clipboard"
        )
        clipboard_box.pack_start(self.auto_copy_check, False, False, 0)

        clipboard_frame.add(clipboard_box)
        box.pack_start(clipboard_frame, False, False, 0)

        # === Notifications Section ===
        notifications_frame = Gtk.Frame(label="Notifications")
        notifications_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        notifications_box.set_margin_start(8)
        notifications_box.set_margin_end(8)
        notifications_box.set_margin_top(8)
        notifications_box.set_margin_bottom(8)

        # Notifications
        self.notifications_check = Gtk.CheckButton(label="Show desktop notifications")
        notifications_box.pack_start(self.notifications_check, False, False, 0)

        notifications_frame.add(notifications_box)
        box.pack_start(notifications_frame, False, False, 0)

        return box

    def _on_toggle_token_visibility(self, button: Gtk.ToggleButton) -> None:
        """Toggle token visibility."""
        if self.token_entry:
            self.token_entry.set_visibility(button.get_active())
            button.set_label("Hide" if button.get_active() else "Show")

    def _on_refresh_devices(self, button: Gtk.Button | None = None) -> None:
        """Refresh the audio device list."""
        self._refresh_devices()

    def _refresh_devices(self) -> None:
        """Populate the device combo box."""
        if not self.device_combo:
            return

        self.device_combo.remove_all()
        self.device_combo.append("default", "Default Device")

        try:
            devices = AudioRecorder.list_devices()
            for device in devices:
                name = device.get("name", f"Device {device['index']}")
                self.device_combo.append(str(device["index"]), name)
        except Exception as e:
            logger.warning(f"Failed to list audio devices: {e}")

    def _load_values(self) -> None:
        """Load current configuration values into the dialog."""
        # Connection tab
        if self.host_entry:
            self.host_entry.set_text(
                self.config.get("server", "host", default="localhost")
            )
        if self.port_spin:
            self.port_spin.set_value(self.config.get("server", "port", default=8000))
        if self.https_check:
            self.https_check.set_active(
                self.config.get("server", "use_https", default=False)
            )
        if self.token_entry:
            token = self.config.get("server", "token", default="")
            self.token_entry.set_text(token.strip() if token else "")
        if self.use_remote_check:
            self.use_remote_check.set_active(
                self.config.get("server", "use_remote", default=False)
            )
        if self.remote_host_entry:
            self.remote_host_entry.set_text(
                self.config.get("server", "remote_host", default="")
            )

        # Audio tab - select current device
        if self.device_combo:
            current_device = self.config.get("recording", "device_index")
            if current_device is None:
                self.device_combo.set_active_id("default")
            else:
                self.device_combo.set_active_id(str(current_device))

        # Behavior tab
        if self.auto_copy_check:
            self.auto_copy_check.set_active(
                self.config.get("clipboard", "auto_copy", default=True)
            )
        if self.notifications_check:
            self.notifications_check.set_active(
                self.config.get("ui", "notifications", default=True)
            )

    def _save_values(self) -> None:
        """Save settings from the dialog."""
        # Connection tab
        if self.host_entry:
            self.config.set(
                "server",
                "host",
                value=self.host_entry.get_text().strip() or "localhost",
            )
        if self.port_spin:
            self.config.set("server", "port", value=int(self.port_spin.get_value()))
        if self.https_check:
            self.config.set("server", "use_https", value=self.https_check.get_active())
        if self.token_entry:
            self.config.set(
                "server", "token", value=self.token_entry.get_text().strip()
            )
        if self.use_remote_check:
            self.config.set(
                "server", "use_remote", value=self.use_remote_check.get_active()
            )
        if self.remote_host_entry:
            self.config.set(
                "server", "remote_host", value=self.remote_host_entry.get_text().strip()
            )

        # Audio tab
        if self.device_combo:
            device_id = self.device_combo.get_active_id()
            if device_id == "default":
                self.config.set("recording", "device_index", value=None)
            else:
                try:
                    self.config.set("recording", "device_index", value=int(device_id))
                except (ValueError, TypeError):
                    self.config.set("recording", "device_index", value=None)

        # Behavior tab
        if self.auto_copy_check:
            self.config.set(
                "clipboard", "auto_copy", value=self.auto_copy_check.get_active()
            )
        if self.notifications_check:
            self.config.set(
                "ui", "notifications", value=self.notifications_check.get_active()
            )

        # Save to file
        if self.config.save():
            logger.info("Settings saved successfully")
        else:
            logger.error("Failed to save settings")
