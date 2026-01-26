"""
Settings dialog for TranscriptionSuite GNOME Dashboard.

Provides a unified tabbed dialog for configuring all settings.
Supports both GTK4/Adwaita (for Dashboard) and GTK3 (for tray fallback).
Styled to match the Dashboard UI design language.

Tabs:
- App: Clipboard, notifications, stop server on quit behavior
- Client: Audio input device + connection settings
- Server: Open config.yaml button + path display
"""

import logging
from typing import Any

from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.config import ClientConfig, get_config_dir
from dashboard.common.docker_manager import DockerManager

logger = logging.getLogger(__name__)

# Try to import GTK4 first (preferred), fall back to GTK3
HAS_GTK4 = False
HAS_GTK3 = False
Adw = None
Gdk = None
Gtk = None

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    HAS_GTK4 = True
    logger.debug("Using GTK4/Adwaita for settings dialog")
except (ImportError, ValueError):
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk

        HAS_GTK3 = True
        logger.debug("Using GTK3 for settings dialog")
    except (ImportError, ValueError) as e:
        logger.warning(f"Neither GTK4 nor GTK3 available: {e}")


class SettingsDialog:
    """Settings dialog with tabbed interface matching KDE design.

    Supports GTK4/Adwaita (for Dashboard) and GTK3 (for tray fallback).
    """

    def __init__(self, config: ClientConfig, parent: Any = None):
        if not HAS_GTK4 and not HAS_GTK3:
            raise ImportError("Neither GTK4 nor GTK3 is available")

        self.config = config
        self.parent = parent
        self._docker_manager = DockerManager()
        self.dialog: Any = None

        # Widgets that need to be accessed later
        # App tab
        self.auto_copy_check: Any = None
        self.notifications_check: Any = None
        self.stop_server_check: Any = None

        # Client tab - Audio
        self.device_combo: Any = None

        # Client tab - Diarization
        self.constrain_speakers_check: Any = None
        self.expected_speakers_spin: Any = None

        # Client tab - Connection
        self.host_entry: Any = None
        self.remote_host_entry: Any = None
        self.use_remote_check: Any = None
        self.token_entry: Any = None
        self.show_token_btn: Any = None
        self.port_spin: Any = None
        self.https_check: Any = None
        self.tls_verify_check: Any = None
        self.allow_insecure_http_check: Any = None

    def show(self) -> None:
        """Create and show the settings dialog."""
        if HAS_GTK4:
            self._show_gtk4()
        elif HAS_GTK3:
            self._show_gtk3()
        else:
            logger.error("No GTK available for settings dialog")

    def _show_gtk4(self) -> None:
        """Show GTK4/Adwaita settings dialog."""
        self.dialog = Adw.Window()
        self.dialog.set_title("Settings")
        self.dialog.set_default_size(540, 580)
        if self.parent:
            self.dialog.set_transient_for(self.parent)
        self.dialog.set_modal(True)

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        main_box.append(header)

        # Tab view using Adw.ViewStack with Adw.ViewSwitcher
        self._stack = Adw.ViewStack()

        # Create tabs
        self._create_app_tab()
        self._create_client_tab()
        self._create_server_tab()
        self._create_notebook_tab()

        # View switcher in header
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        main_box.append(self._stack)

        # Bottom button bar
        button_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_bar.set_halign(Gtk.Align.END)
        button_bar.set_margin_top(12)
        button_bar.set_margin_bottom(12)
        button_bar.set_margin_start(16)
        button_bar.set_margin_end(16)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.dialog.close())
        button_bar.append(cancel_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda _: self._save_and_close())
        button_bar.append(save_btn)

        main_box.append(button_bar)

        self.dialog.set_content(main_box)

        # Apply styling
        self._apply_styles()

        # Load current values
        self._load_values()

        # Show dialog
        self.dialog.present()

    def _apply_styles(self) -> None:
        """Apply dark theme styling matching Dashboard UI."""
        css = b"""
        /* Settings dialog styling */
        .settings-section {
            background-color: #1e1e1e;
            border-radius: 8px;
            padding: 12px;
            margin: 4px 0;
        }

        .settings-section-title {
            color: #90caf9;
            font-weight: bold;
            font-size: 14px;
        }

        .settings-help-text {
            color: #6c757d;
            font-size: 11px;
        }

        .settings-path-label {
            color: #6c757d;
            font-size: 12px;
            font-family: monospace;
        }

        entry {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 6px;
            color: #ffffff;
            padding: 8px 12px;
        }

        entry:focus {
            border-color: #90caf9;
        }

        spinbutton {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 6px;
            color: #ffffff;
        }

        spinbutton:focus {
            border-color: #90caf9;
        }

        combobox button {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 6px;
            color: #ffffff;
            padding: 8px 12px;
        }

        combobox button:focus {
            border-color: #90caf9;
        }

        checkbutton {
            color: #ffffff;
        }

        checkbutton check {
            background-color: #1e1e1e;
            border: 2px solid #505050;
            border-radius: 3px;
        }

        checkbutton check:checked {
            background-color: #90caf9;
            border-color: #90caf9;
        }

        .small-button {
            padding: 6px 12px;
            font-size: 12px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _create_app_tab(self) -> None:
        """Create the App settings tab (clipboard, notifications, docker behavior)."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)

        # === Clipboard Section ===
        clipboard_frame = Gtk.Frame()
        clipboard_frame.add_css_class("settings-section")
        clipboard_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        clipboard_box.set_margin_start(12)
        clipboard_box.set_margin_end(12)
        clipboard_box.set_margin_top(8)
        clipboard_box.set_margin_bottom(8)

        clipboard_label = Gtk.Label(label="Clipboard")
        clipboard_label.add_css_class("settings-section-title")
        clipboard_label.set_halign(Gtk.Align.START)
        clipboard_box.append(clipboard_label)

        self.auto_copy_check = Gtk.CheckButton(
            label="Automatically copy transcription to clipboard"
        )
        clipboard_box.append(self.auto_copy_check)

        clipboard_frame.set_child(clipboard_box)
        content.append(clipboard_frame)

        # === Notifications Section ===
        notifications_frame = Gtk.Frame()
        notifications_frame.add_css_class("settings-section")
        notifications_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notifications_box.set_margin_start(12)
        notifications_box.set_margin_end(12)
        notifications_box.set_margin_top(8)
        notifications_box.set_margin_bottom(8)

        notifications_label = Gtk.Label(label="Notifications")
        notifications_label.add_css_class("settings-section-title")
        notifications_label.set_halign(Gtk.Align.START)
        notifications_box.append(notifications_label)

        self.notifications_check = Gtk.CheckButton(label="Show desktop notifications")
        notifications_box.append(self.notifications_check)

        notifications_frame.set_child(notifications_box)
        content.append(notifications_frame)

        # === Docker Server Section ===
        docker_frame = Gtk.Frame()
        docker_frame.add_css_class("settings-section")
        docker_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        docker_box.set_margin_start(12)
        docker_box.set_margin_end(12)
        docker_box.set_margin_top(8)
        docker_box.set_margin_bottom(8)

        docker_label = Gtk.Label(label="Docker Server")
        docker_label.add_css_class("settings-section-title")
        docker_label.set_halign(Gtk.Align.START)
        docker_box.append(docker_label)

        self.stop_server_check = Gtk.CheckButton(
            label="Stop server when quitting dashboard"
        )
        docker_box.append(self.stop_server_check)

        docker_frame.set_child(docker_box)
        content.append(docker_frame)

        scrolled.set_child(content)
        self._stack.add_titled_with_icon(
            scrolled, "app", "App", "preferences-system-symbolic"
        )

    def _create_client_tab(self) -> None:
        """Create the Client settings tab (audio + connection in one tab)."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)

        # === Audio Section ===
        audio_frame = Gtk.Frame()
        audio_frame.add_css_class("settings-section")
        audio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        audio_box.set_margin_start(12)
        audio_box.set_margin_end(12)
        audio_box.set_margin_top(8)
        audio_box.set_margin_bottom(8)

        audio_label = Gtk.Label(label="Audio")
        audio_label.add_css_class("settings-section-title")
        audio_label.set_halign(Gtk.Align.START)
        audio_box.append(audio_label)

        # Device selector row
        device_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        device_label = Gtk.Label(label="Input Device:")
        device_label.set_size_request(100, -1)
        device_label.set_halign(Gtk.Align.START)
        device_row.append(device_label)

        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.set_hexpand(True)
        device_row.append(self.device_combo)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.add_css_class("small-button")
        refresh_btn.connect("clicked", lambda _: self._refresh_devices())
        device_row.append(refresh_btn)

        audio_box.append(device_row)

        # Sample rate info
        sample_rate_label = Gtk.Label(label="Sample Rate: 16000 Hz (fixed for Whisper)")
        sample_rate_label.add_css_class("settings-help-text")
        sample_rate_label.set_halign(Gtk.Align.START)
        audio_box.append(sample_rate_label)

        # Live Mode grace period
        grace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        grace_label = Gtk.Label(label="Live Mode Grace Period:")
        grace_label.set_size_request(160, -1)
        grace_label.set_halign(Gtk.Align.START)
        grace_label.set_tooltip_text(
            "How long to keep recording after detecting silence.\n"
            "Allows natural pauses while speaking."
        )
        grace_row.append(grace_label)

        grace_adjustment = Gtk.Adjustment(
            value=1.0,
            lower=0.1,
            upper=10.0,
            step_increment=0.1,
            page_increment=0.5,
        )
        self.grace_period_spin = Gtk.SpinButton()
        self.grace_period_spin.set_adjustment(grace_adjustment)
        self.grace_period_spin.set_digits(1)
        self.grace_period_spin.set_value(1.0)
        self.grace_period_spin.set_tooltip_text(
            "Recommended: 0.5-3 seconds. Higher values allow longer pauses\n"
            "but may make responses feel slower."
        )
        grace_row.append(self.grace_period_spin)

        seconds_label = Gtk.Label(label="seconds")
        seconds_label.set_halign(Gtk.Align.START)
        grace_row.append(seconds_label)

        grace_row_spacer = Gtk.Box()
        grace_row_spacer.set_hexpand(True)
        grace_row.append(grace_row_spacer)

        audio_box.append(grace_row)

        # Help text for grace period
        grace_help = Gtk.Label(
            label="Tip: Increase if your transcriptions cut off mid-sentence, decrease for faster responses."
        )
        grace_help.add_css_class("settings-help-text")
        grace_help.set_halign(Gtk.Align.START)
        grace_help.set_wrap(True)
        audio_box.append(grace_help)

        audio_frame.set_child(audio_box)
        content.append(audio_frame)

        # Populate devices
        self._refresh_devices()

        # === Diarization Section ===
        diarization_frame = Gtk.Frame()
        diarization_frame.add_css_class("settings-section")
        diarization_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        diarization_box.set_margin_start(12)
        diarization_box.set_margin_end(12)
        diarization_box.set_margin_top(8)
        diarization_box.set_margin_bottom(8)

        diarization_label = Gtk.Label(label="Diarization")
        diarization_label.add_css_class("settings-section-title")
        diarization_label.set_halign(Gtk.Align.START)
        diarization_box.append(diarization_label)

        # Constrain speakers checkbox
        self.constrain_speakers_check = Gtk.CheckButton(
            label="Constrain to expected number of speakers"
        )
        self.constrain_speakers_check.set_tooltip_text(
            "When enabled, forces diarization to identify exactly the specified number of speakers.\n"
            "Useful for podcasts with known hosts where occasional clips should be attributed to the main speakers."
        )
        self.constrain_speakers_check.connect(
            "toggled", self._on_constrain_speakers_toggled
        )
        diarization_box.append(self.constrain_speakers_check)

        # Number of speakers row
        speakers_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        speakers_label = Gtk.Label(label="Number of speakers:")
        speakers_label.set_size_request(140, -1)
        speakers_label.set_halign(Gtk.Align.START)
        speakers_row.append(speakers_label)

        speakers_adjustment = Gtk.Adjustment(
            value=2.0,
            lower=2.0,
            upper=10.0,
            step_increment=1.0,
            page_increment=1.0,
        )
        self.expected_speakers_spin = Gtk.SpinButton()
        self.expected_speakers_spin.set_adjustment(speakers_adjustment)
        self.expected_speakers_spin.set_digits(0)
        self.expected_speakers_spin.set_value(2.0)
        self.expected_speakers_spin.set_tooltip_text(
            "Specify the exact number of speakers (2-10).\n"
            "Example: Set to 2 for a podcast with 2 hosts."
        )
        speakers_row.append(self.expected_speakers_spin)

        speakers_row_spacer = Gtk.Box()
        speakers_row_spacer.set_hexpand(True)
        speakers_row.append(speakers_row_spacer)

        diarization_box.append(speakers_row)

        # Help text
        diarization_help = Gtk.Label(
            label="Useful for podcasts with known hosts. Forces all speech to be attributed to "
            "exactly this many speakers, ignoring occasional clips."
        )
        diarization_help.add_css_class("settings-help-text")
        diarization_help.set_halign(Gtk.Align.START)
        diarization_help.set_wrap(True)
        diarization_box.append(diarization_help)

        diarization_frame.set_child(diarization_box)
        content.append(diarization_frame)

        # === Connection Section ===
        connection_frame = Gtk.Frame()
        connection_frame.add_css_class("settings-section")
        connection_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        connection_box.set_margin_start(12)
        connection_box.set_margin_end(12)
        connection_box.set_margin_top(8)
        connection_box.set_margin_bottom(8)

        connection_label = Gtk.Label(label="Connection")
        connection_label.add_css_class("settings-section-title")
        connection_label.set_halign(Gtk.Align.START)
        connection_box.append(connection_label)

        # Local host row
        local_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        local_label = Gtk.Label(label="Local Host:")
        local_label.set_size_request(100, -1)
        local_label.set_halign(Gtk.Align.START)
        local_row.append(local_label)

        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text("localhost")
        self.host_entry.set_hexpand(True)
        local_row.append(self.host_entry)
        connection_box.append(local_row)

        # Remote host row
        remote_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        remote_label = Gtk.Label(label="Remote Host:")
        remote_label.set_size_request(100, -1)
        remote_label.set_halign(Gtk.Align.START)
        remote_row.append(remote_label)

        self.remote_host_entry = Gtk.Entry()
        self.remote_host_entry.set_placeholder_text("e.g., my-desktop.tail1234.ts.net")
        self.remote_host_entry.set_hexpand(True)
        remote_row.append(self.remote_host_entry)
        connection_box.append(remote_row)

        # Help text for host settings
        host_help = Gtk.Label(
            label="Enter ONLY the hostname (no http://, no port). Examples:\n"
            "• Local: localhost or 127.0.0.1\n"
            "• Remote: my-machine.tail1234.ts.net or 100.101.102.103"
        )
        host_help.add_css_class("settings-help-text")
        host_help.set_halign(Gtk.Align.START)
        host_help.set_wrap(True)
        connection_box.append(host_help)

        # Use remote checkbox
        self.use_remote_check = Gtk.CheckButton(
            label="Use remote server instead of local"
        )
        connection_box.append(self.use_remote_check)

        # Help text for remote
        remote_help = Gtk.Label(
            label="Don't forget to enable HTTPS and switch port to 8443 if using remote server"
        )
        remote_help.add_css_class("settings-help-text")
        remote_help.set_halign(Gtk.Align.START)
        remote_help.set_wrap(True)
        connection_box.append(remote_help)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        connection_box.append(separator)

        # Token row
        token_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        token_label = Gtk.Label(label="Auth Token:")
        token_label.set_size_request(100, -1)
        token_label.set_halign(Gtk.Align.START)
        token_row.append(token_label)

        self.token_entry = Gtk.Entry()
        self.token_entry.set_visibility(False)
        self.token_entry.set_placeholder_text("Authentication token")
        self.token_entry.set_hexpand(True)
        token_row.append(self.token_entry)

        self.show_token_btn = Gtk.ToggleButton(label="Show")
        self.show_token_btn.add_css_class("small-button")
        self.show_token_btn.connect("toggled", self._on_toggle_token_visibility)
        token_row.append(self.show_token_btn)

        connection_box.append(token_row)

        # Port row
        port_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        port_label = Gtk.Label(label="Port:")
        port_label.set_size_request(100, -1)
        port_label.set_halign(Gtk.Align.START)
        port_row.append(port_label)

        adjustment = Gtk.Adjustment(
            value=8000, lower=1, upper=65535, step_increment=1, page_increment=10
        )
        self.port_spin = Gtk.SpinButton()
        self.port_spin.set_adjustment(adjustment)
        self.port_spin.set_numeric(True)
        self.port_spin.set_size_request(100, -1)
        port_row.append(self.port_spin)

        connection_box.append(port_row)

        # HTTPS checkbox
        self.https_check = Gtk.CheckButton(label="Use HTTPS")
        connection_box.append(self.https_check)

        # === Advanced TLS Options Sub-section ===
        tls_frame = Gtk.Frame()
        tls_frame.set_margin_top(8)
        tls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tls_box.set_margin_start(12)
        tls_box.set_margin_end(12)
        tls_box.set_margin_top(8)
        tls_box.set_margin_bottom(8)

        tls_label = Gtk.Label(label="Advanced TLS Options")
        tls_label.add_css_class("settings-section-title")
        tls_label.set_halign(Gtk.Align.START)
        tls_box.append(tls_label)

        # TLS Verify checkbox
        self.tls_verify_check = Gtk.CheckButton(label="Verify TLS certificates")
        self.tls_verify_check.set_tooltip_text(
            "Disable for self-signed certificates.\nConnection is still encrypted."
        )
        tls_box.append(self.tls_verify_check)

        # Allow HTTP to remote hosts
        self.allow_insecure_http_check = Gtk.CheckButton(
            label="Allow HTTP to remote hosts (WireGuard encrypts traffic)"
        )
        self.allow_insecure_http_check.set_tooltip_text(
            "Enable for Tailscale without MagicDNS.\n"
            "Use Tailscale IP (e.g., 100.x.y.z) with port 8000."
        )
        tls_box.append(self.allow_insecure_http_check)

        tls_frame.set_child(tls_box)
        connection_box.append(tls_frame)

        connection_frame.set_child(connection_box)
        content.append(connection_frame)

        scrolled.set_child(content)
        self._stack.add_titled_with_icon(
            scrolled, "client", "Client", "audio-input-microphone-symbolic"
        )

    def _create_server_tab(self) -> None:
        """Create the Server settings tab (open config.yaml + path info)."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)

        # === Server Configuration Section ===
        config_frame = Gtk.Frame()
        config_frame.add_css_class("settings-section")
        config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        config_box.set_margin_start(12)
        config_box.set_margin_end(12)
        config_box.set_margin_top(8)
        config_box.set_margin_bottom(8)

        config_label = Gtk.Label(label="Server Configuration")
        config_label.add_css_class("settings-section-title")
        config_label.set_halign(Gtk.Align.START)
        config_box.append(config_label)

        # Description
        desc_label = Gtk.Label(
            label="Server settings are stored in config.yaml. Click below to open "
            "it in your default text editor."
        )
        desc_label.set_wrap(True)
        desc_label.set_halign(Gtk.Align.START)
        config_box.append(desc_label)

        # Open config button
        open_config_btn = Gtk.Button(label="Open config.yaml in Text Editor")
        open_config_btn.add_css_class("suggested-action")
        open_config_btn.set_halign(Gtk.Align.START)
        open_config_btn.connect("clicked", lambda _: self._on_open_config_file())
        config_box.append(open_config_btn)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        config_box.append(separator)

        # Path info
        config_dir = get_config_dir()
        config_path = config_dir / "config.yaml"

        path_info_label = Gtk.Label(
            label="You can also edit the config file directly at:"
        )
        path_info_label.add_css_class("settings-help-text")
        path_info_label.set_halign(Gtk.Align.START)
        config_box.append(path_info_label)

        path_label = Gtk.Label(label=str(config_path))
        path_label.add_css_class("settings-path-label")
        path_label.set_selectable(True)
        path_label.set_wrap(True)
        path_label.set_halign(Gtk.Align.START)
        config_box.append(path_label)

        config_frame.set_child(config_box)
        content.append(config_frame)

        scrolled.set_child(content)
        self._stack.add_titled_with_icon(
            scrolled, "server", "Server", "network-server-symbolic"
        )

    def _create_notebook_tab(self) -> None:
        """Create the Notebook tab for backup/restore functionality."""
        import asyncio
        from dashboard.common.api_client import APIClient
        from dashboard.common.docker_manager import ServerStatus

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)

        # Backup section
        backup_frame = Gtk.Frame()
        backup_frame.set_label("Database Backup")
        backup_frame.add_css_class("settings-group")

        backup_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        backup_box.set_margin_start(12)
        backup_box.set_margin_end(12)
        backup_box.set_margin_top(12)
        backup_box.set_margin_bottom(12)

        backup_desc = Gtk.Label(
            label="Create a backup of your Audio Notebook database. "
            "Backups include all recordings metadata and transcriptions."
        )
        backup_desc.set_wrap(True)
        backup_desc.set_halign(Gtk.Align.START)
        backup_desc.add_css_class("dim-label")
        backup_box.append(backup_desc)

        # Backup list
        self._backup_listbox = Gtk.ListBox()
        self._backup_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._backup_listbox.add_css_class("boxed-list")
        self._backup_listbox.set_size_request(-1, 100)

        backup_scroll = Gtk.ScrolledWindow()
        backup_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        backup_scroll.set_child(self._backup_listbox)
        backup_scroll.set_min_content_height(100)
        backup_scroll.set_max_content_height(120)
        backup_box.append(backup_scroll)

        # Backup buttons
        backup_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        create_backup_btn = Gtk.Button(label="Create Backup")
        create_backup_btn.add_css_class("suggested-action")
        create_backup_btn.connect("clicked", lambda _: self._on_create_backup_gnome())
        backup_btn_box.append(create_backup_btn)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _: self._refresh_backup_list_gnome())
        backup_btn_box.append(refresh_btn)

        backup_box.append(backup_btn_box)
        backup_frame.set_child(backup_box)
        content.append(backup_frame)

        # Restore section
        restore_frame = Gtk.Frame()
        restore_frame.set_label("Database Restore")
        restore_frame.add_css_class("settings-group")

        restore_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        restore_box.set_margin_start(12)
        restore_box.set_margin_end(12)
        restore_box.set_margin_top(12)
        restore_box.set_margin_bottom(12)

        restore_desc = Gtk.Label(
            label="Restore your database from a backup. "
            "Warning: This will replace all current data. "
            "A safety backup will be created automatically."
        )
        restore_desc.set_wrap(True)
        restore_desc.set_halign(Gtk.Align.START)
        restore_desc.add_css_class("warning")

        restore_box.append(restore_desc)

        restore_btn = Gtk.Button(label="Restore Selected Backup")
        restore_btn.add_css_class("destructive-action")
        restore_btn.connect("clicked", lambda _: self._on_restore_backup_gnome())
        restore_btn.set_halign(Gtk.Align.START)
        restore_box.append(restore_btn)

        restore_frame.set_child(restore_box)
        content.append(restore_frame)

        scrolled.set_child(content)
        self._stack.add_titled_with_icon(
            scrolled, "notebook", "Notebook", "accessories-text-editor-symbolic"
        )

        # Load backup list
        self._refresh_backup_list_gnome()

    def _get_api_client_gnome(self):
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
        tls_verify = self.config.get("server", "tls_verify", default=True)

        if not host:
            return None

        return APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token if token else None,
            tls_verify=tls_verify,
        )

    def _refresh_backup_list_gnome(self) -> None:
        """Refresh the list of available backups."""
        import asyncio
        from gi.repository import GLib

        if not hasattr(self, "_backup_listbox"):
            return

        # Clear existing items
        while True:
            row = self._backup_listbox.get_row_at_index(0)
            if row is None:
                break
            self._backup_listbox.remove(row)

        api_client = self._get_api_client_gnome()
        if not api_client:
            label = Gtk.Label(label="Server not running - cannot list backups")
            label.add_css_class("dim-label")
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            self._backup_listbox.append(label)
            return

        async def fetch_and_populate():
            try:
                backups = await api_client.list_backups()
                GLib.idle_add(lambda: self._populate_backup_list_gnome(backups))
            except Exception as e:
                logger.error(f"Failed to list backups: {e}")
                GLib.idle_add(lambda: self._populate_backup_list_gnome(None))

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(fetch_and_populate())
            else:
                asyncio.run(fetch_and_populate())
        except RuntimeError:
            asyncio.run(fetch_and_populate())

    def _populate_backup_list_gnome(self, backups) -> None:
        """Populate the backup list widget."""
        if not hasattr(self, "_backup_listbox"):
            return

        # Clear existing
        while True:
            row = self._backup_listbox.get_row_at_index(0)
            if row is None:
                break
            self._backup_listbox.remove(row)

        if backups is None:
            label = Gtk.Label(label="Failed to load backups")
            label.add_css_class("error")
            self._backup_listbox.append(label)
            return

        if not backups:
            label = Gtk.Label(label="No backups available")
            label.add_css_class("dim-label")
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            self._backup_listbox.append(label)
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
                date_str = "Unknown"

            row = Adw.ActionRow()
            row.set_title(filename)
            row.set_subtitle(f"{date_str}  •  {size_str}")
            row.filename = filename  # Store for retrieval
            self._backup_listbox.append(row)

    def _on_create_backup_gnome(self) -> None:
        """Handle create backup button click."""
        import asyncio
        from gi.repository import GLib

        api_client = self._get_api_client_gnome()
        if not api_client:
            self._show_message_gnome("Server Not Running", "The server must be running to create backups.")
            return

        async def create_backup():
            try:
                result = await api_client.create_backup()
                GLib.idle_add(lambda: self._handle_backup_result_gnome(result))
            except Exception as e:
                logger.error(f"Failed to create backup: {e}")
                GLib.idle_add(lambda: self._show_message_gnome("Backup Failed", str(e)))

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(create_backup())
            else:
                asyncio.run(create_backup())
        except RuntimeError:
            asyncio.run(create_backup())

    def _handle_backup_result_gnome(self, result) -> None:
        """Handle backup creation result."""
        if result.get("success"):
            filename = result.get("backup", {}).get("filename", "")
            self._show_message_gnome("Backup Created", f"Backup created successfully.\n\n{filename}")
            self._refresh_backup_list_gnome()
        else:
            self._show_message_gnome("Backup Failed", result.get("message", "Unknown error"))

    def _on_restore_backup_gnome(self) -> None:
        """Handle restore backup button click."""
        import asyncio
        from gi.repository import GLib

        if not hasattr(self, "_backup_listbox"):
            return

        selected_row = self._backup_listbox.get_selected_row()
        if not selected_row or not hasattr(selected_row, "filename"):
            self._show_message_gnome("No Backup Selected", "Please select a backup from the list to restore.")
            return

        filename = selected_row.filename

        # Confirmation dialog
        dialog = Adw.MessageDialog.new(
            self.dialog,
            "Confirm Restore",
            f"Are you sure you want to restore from:\n\n{filename}\n\n"
            "This will replace ALL current data.\nA safety backup will be created first."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("restore", "Restore")
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dialog, response):
            dialog.destroy()
            if response == "restore":
                self._do_restore_gnome(filename)

        dialog.connect("response", on_response)
        dialog.present()

    def _do_restore_gnome(self, filename: str) -> None:
        """Perform the actual restore operation."""
        import asyncio
        from gi.repository import GLib

        api_client = self._get_api_client_gnome()
        if not api_client:
            self._show_message_gnome("Server Not Running", "The server must be running to restore backups.")
            return

        async def restore_backup():
            try:
                result = await api_client.restore_backup(filename)
                GLib.idle_add(lambda: self._handle_restore_result_gnome(result))
            except Exception as e:
                logger.error(f"Failed to restore backup: {e}")
                GLib.idle_add(lambda: self._show_message_gnome("Restore Failed", str(e)))

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(restore_backup())
            else:
                asyncio.run(restore_backup())
        except RuntimeError:
            asyncio.run(restore_backup())

    def _handle_restore_result_gnome(self, result) -> None:
        """Handle restore result."""
        if result.get("success"):
            restored_from = result.get("restored_from", "backup")
            self._show_message_gnome(
                "Restore Complete",
                f"Database restored successfully from:\n{restored_from}\n\n"
                "Refresh the Notebook view to see the restored data."
            )
            self._refresh_backup_list_gnome()
        else:
            self._show_message_gnome("Restore Failed", result.get("message", "Unknown error"))

    def _show_message_gnome(self, heading: str, body: str) -> None:
        """Show a message dialog."""
        if self.dialog:
            dialog = Adw.MessageDialog.new(self.dialog, heading, body)
            dialog.add_response("ok", "OK")
            dialog.present()

    def _on_toggle_token_visibility(self, button: Gtk.ToggleButton) -> None:
        """Toggle token visibility."""
        if self.token_entry:
            self.token_entry.set_visibility(button.get_active())
            button.set_label("Hide" if button.get_active() else "Show")

    def _on_constrain_speakers_toggled(self, button: Gtk.CheckButton) -> None:
        """Enable/disable the expected speakers spinbox based on checkbox state."""
        if self.expected_speakers_spin:
            self.expected_speakers_spin.set_sensitive(button.get_active())

    def _refresh_devices(self) -> None:
        """Refresh the audio device list."""
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

    def _on_open_config_file(self) -> None:
        """Open the server config.yaml file in default text editor."""
        config_file = self._docker_manager._find_config_file()
        success = self._docker_manager.open_config_file()

        if not success:
            # Show error dialog
            if self.dialog:
                error_dialog = Adw.MessageDialog.new(
                    self.dialog,
                    "Cannot Open Settings",
                    "",
                )

                if not config_file:
                    error_dialog.set_body(
                        "The config.yaml file doesn't exist yet.\n\n"
                        "To create it:\n"
                        "1. Run first-time setup from terminal:\n"
                        "   transcriptionsuite-setup\n\n"
                        f"2. Or create it manually at:\n"
                        f"   {self._docker_manager.config_dir}/config.yaml"
                    )
                else:
                    error_dialog.set_body(
                        f"The file exists but no editor was found.\n\n"
                        f"Location: {config_file}\n\n"
                        f"To edit manually, try:\n"
                        f"• kate {config_file}\n"
                        f"• gedit {config_file}\n"
                        f"• nano {config_file}"
                    )

                error_dialog.add_response("ok", "OK")
                error_dialog.present()

    def _load_values(self) -> None:
        """Load current configuration values into the dialog."""
        # Force reload from disk to get latest values
        # This prevents race conditions when tray and dashboard processes
        # both access the same config file
        self.config._load()

        # App tab
        if self.auto_copy_check:
            self.auto_copy_check.set_active(
                self.config.get("clipboard", "auto_copy", default=True)
            )
        if self.notifications_check:
            self.notifications_check.set_active(
                self.config.get("ui", "notifications", default=True)
            )
        if self.stop_server_check:
            self.stop_server_check.set_active(
                self.config.get("dashboard", "stop_server_on_quit", default=True)
            )

        # Client tab - Audio
        if self.device_combo:
            current_device = self.config.get("recording", "device_index")
            if current_device is None:
                self.device_combo.set_active_id("default")
            else:
                self.device_combo.set_active_id(str(current_device))

        # Live Mode grace period
        if self.grace_period_spin:
            grace_period = self.config.get("live_mode", "grace_period", default=1.0)
            self.grace_period_spin.set_value(grace_period)

        # Client tab - Diarization
        if self.constrain_speakers_check and self.expected_speakers_spin:
            expected_speakers = self.config.get(
                "diarization", "expected_speakers", default=None
            )
            if expected_speakers is not None:
                self.constrain_speakers_check.set_active(True)
                self.expected_speakers_spin.set_value(float(expected_speakers))
                self.expected_speakers_spin.set_sensitive(True)
            else:
                self.constrain_speakers_check.set_active(False)
                self.expected_speakers_spin.set_value(2.0)
                self.expected_speakers_spin.set_sensitive(False)

        # Client tab - Connection
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

        # Advanced TLS options
        if self.tls_verify_check:
            self.tls_verify_check.set_active(
                self.config.get("server", "tls_verify", default=True)
            )
        if self.allow_insecure_http_check:
            self.allow_insecure_http_check.set_active(
                self.config.get("server", "allow_insecure_http", default=False)
            )

    def _save_and_close(self) -> None:
        """Save settings and close the dialog."""
        # App tab
        if self.auto_copy_check:
            self.config.set(
                "clipboard", "auto_copy", value=self.auto_copy_check.get_active()
            )
        if self.notifications_check:
            self.config.set(
                "ui", "notifications", value=self.notifications_check.get_active()
            )
        if self.stop_server_check:
            self.config.set(
                "dashboard",
                "stop_server_on_quit",
                value=self.stop_server_check.get_active(),
            )

        # Client tab - Audio
        if self.device_combo:
            device_id = self.device_combo.get_active_id()
            if device_id == "default":
                self.config.set("recording", "device_index", value=None)
            else:
                try:
                    self.config.set("recording", "device_index", value=int(device_id))
                except (ValueError, TypeError):
                    self.config.set("recording", "device_index", value=None)

        # Live Mode grace period
        if self.grace_period_spin:
            self.config.set(
                "live_mode", "grace_period", value=self.grace_period_spin.get_value()
            )

        # Client tab - Diarization
        if self.constrain_speakers_check and self.expected_speakers_spin:
            if self.constrain_speakers_check.get_active():
                self.config.set(
                    "diarization",
                    "expected_speakers",
                    value=int(self.expected_speakers_spin.get_value()),
                )
            else:
                self.config.set("diarization", "expected_speakers", value=None)

        # Client tab - Connection
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
                "server",
                "remote_host",
                value=self.remote_host_entry.get_text().strip(),
            )

        # Advanced TLS options
        if self.tls_verify_check:
            self.config.set(
                "server", "tls_verify", value=self.tls_verify_check.get_active()
            )
        if self.allow_insecure_http_check:
            self.config.set(
                "server",
                "allow_insecure_http",
                value=self.allow_insecure_http_check.get_active(),
            )

        # Save to file
        if self.config.save():
            logger.info("Settings saved successfully")
        else:
            logger.error("Failed to save settings")

        # Close dialog
        if self.dialog:
            if HAS_GTK4:
                self.dialog.close()
            elif HAS_GTK3:
                self.dialog.destroy()

    # =========================================================================
    # GTK3 Fallback Implementation (for tray direct access)
    # =========================================================================

    def _show_gtk3(self) -> None:
        """Show GTK3 settings dialog (fallback for tray)."""
        self.dialog = Gtk.Dialog(
            title="Settings",
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        if self.parent:
            self.dialog.set_transient_for(self.parent)
        self.dialog.set_default_size(500, 550)

        # Set window icon from system theme
        self.dialog.set_icon_name("preferences-system")

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

        # Create tabs in order: App, Client, Server
        notebook.append_page(self._create_app_tab_gtk3(), Gtk.Label(label="App"))
        notebook.append_page(self._create_client_tab_gtk3(), Gtk.Label(label="Client"))
        notebook.append_page(self._create_server_tab_gtk3(), Gtk.Label(label="Server"))

        # Load current values
        self._load_values()

        # Show all widgets
        self.dialog.show_all()

        # Run dialog
        response = self.dialog.run()
        if response == Gtk.ResponseType.OK:
            self._save_and_close_gtk3()

        self.dialog.destroy()

    def _create_app_tab_gtk3(self) -> Gtk.ScrolledWindow:
        """Create the App settings tab for GTK3."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # === Clipboard Section ===
        clipboard_frame = Gtk.Frame(label="Clipboard")
        clipboard_frame.set_margin_bottom(8)
        clipboard_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        clipboard_box.set_margin_start(8)
        clipboard_box.set_margin_end(8)
        clipboard_box.set_margin_top(8)
        clipboard_box.set_margin_bottom(8)

        self.auto_copy_check = Gtk.CheckButton(
            label="Automatically copy transcription to clipboard"
        )
        clipboard_box.pack_start(self.auto_copy_check, False, False, 0)

        clipboard_frame.add(clipboard_box)
        box.pack_start(clipboard_frame, False, False, 0)

        # === Notifications Section ===
        notifications_frame = Gtk.Frame(label="Notifications")
        notifications_frame.set_margin_bottom(8)
        notifications_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        notifications_box.set_margin_start(8)
        notifications_box.set_margin_end(8)
        notifications_box.set_margin_top(8)
        notifications_box.set_margin_bottom(8)

        self.notifications_check = Gtk.CheckButton(label="Show desktop notifications")
        notifications_box.pack_start(self.notifications_check, False, False, 0)

        notifications_frame.add(notifications_box)
        box.pack_start(notifications_frame, False, False, 0)

        # === Docker Server Section ===
        docker_frame = Gtk.Frame(label="Docker Server")
        docker_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        docker_box.set_margin_start(8)
        docker_box.set_margin_end(8)
        docker_box.set_margin_top(8)
        docker_box.set_margin_bottom(8)

        self.stop_server_check = Gtk.CheckButton(
            label="Stop server when quitting dashboard"
        )
        docker_box.pack_start(self.stop_server_check, False, False, 0)

        docker_frame.add(docker_box)
        box.pack_start(docker_frame, False, False, 0)

        scrolled.add(box)
        return scrolled

    def _create_client_tab_gtk3(self) -> Gtk.ScrolledWindow:
        """Create the Client settings tab for GTK3."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # === Audio Section ===
        audio_frame = Gtk.Frame(label="Audio")
        audio_frame.set_margin_bottom(8)
        audio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        audio_box.set_margin_start(8)
        audio_box.set_margin_end(8)
        audio_box.set_margin_top(8)
        audio_box.set_margin_bottom(8)

        # Device selector row
        device_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        device_label = Gtk.Label(label="Input Device:")
        device_label.set_xalign(0)
        device_label.set_size_request(100, -1)
        device_row.pack_start(device_label, False, False, 0)

        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.set_hexpand(True)
        device_row.pack_start(self.device_combo, True, True, 0)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _: self._refresh_devices_gtk3())
        device_row.pack_start(refresh_btn, False, False, 0)

        audio_box.pack_start(device_row, False, False, 0)

        # Sample rate info
        sample_rate_label = Gtk.Label()
        sample_rate_label.set_markup(
            '<span size="small" foreground="gray">'
            "Sample Rate: 16000 Hz (fixed for Whisper)"
            "</span>"
        )
        sample_rate_label.set_xalign(0)
        audio_box.pack_start(sample_rate_label, False, False, 0)

        audio_frame.add(audio_box)
        box.pack_start(audio_frame, False, False, 0)

        # Populate devices
        self._refresh_devices_gtk3()

        # === Diarization Section ===
        diarization_frame = Gtk.Frame(label="Diarization")
        diarization_frame.set_margin_bottom(8)
        diarization_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        diarization_box.set_margin_start(8)
        diarization_box.set_margin_end(8)
        diarization_box.set_margin_top(8)
        diarization_box.set_margin_bottom(8)

        # Constrain speakers checkbox
        self.constrain_speakers_check = Gtk.CheckButton(
            label="Constrain to expected number of speakers"
        )
        self.constrain_speakers_check.set_tooltip_text(
            "When enabled, forces diarization to identify exactly the specified number of speakers.\n"
            "Useful for podcasts with known hosts where occasional clips should be attributed to the main speakers."
        )
        self.constrain_speakers_check.connect(
            "toggled", self._on_constrain_speakers_toggled_gtk3
        )
        diarization_box.pack_start(self.constrain_speakers_check, False, False, 0)

        # Number of speakers row
        speakers_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        speakers_label = Gtk.Label(label="Number of speakers:")
        speakers_label.set_xalign(0)
        speakers_label.set_size_request(140, -1)
        speakers_row.pack_start(speakers_label, False, False, 0)

        speakers_adjustment = Gtk.Adjustment(
            value=2.0,
            lower=2.0,
            upper=10.0,
            step_increment=1.0,
            page_increment=1.0,
        )
        self.expected_speakers_spin = Gtk.SpinButton()
        self.expected_speakers_spin.set_adjustment(speakers_adjustment)
        self.expected_speakers_spin.set_digits(0)
        self.expected_speakers_spin.set_value(2.0)
        self.expected_speakers_spin.set_tooltip_text(
            "Specify the exact number of speakers (2-10).\n"
            "Example: Set to 2 for a podcast with 2 hosts."
        )
        speakers_row.pack_start(self.expected_speakers_spin, False, False, 0)
        diarization_box.pack_start(speakers_row, False, False, 0)

        # Help text
        diarization_help = Gtk.Label()
        diarization_help.set_markup(
            '<span size="small" foreground="gray">'
            "Useful for podcasts with known hosts. Forces all speech to be attributed to "
            "exactly this many speakers, ignoring occasional clips."
            "</span>"
        )
        diarization_help.set_xalign(0)
        diarization_help.set_line_wrap(True)
        diarization_box.pack_start(diarization_help, False, False, 0)

        diarization_frame.add(diarization_box)
        box.pack_start(diarization_frame, False, False, 0)

        # === Connection Section ===
        connection_frame = Gtk.Frame(label="Connection")
        connection_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        connection_box.set_margin_start(8)
        connection_box.set_margin_end(8)
        connection_box.set_margin_top(8)
        connection_box.set_margin_bottom(8)

        # Local host
        host_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        host_label = Gtk.Label(label="Local Host:")
        host_label.set_xalign(0)
        host_label.set_size_request(100, -1)
        host_row.pack_start(host_label, False, False, 0)
        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text("localhost")
        host_row.pack_start(self.host_entry, True, True, 0)
        connection_box.pack_start(host_row, False, False, 0)

        # Remote host
        remote_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        remote_label = Gtk.Label(label="Remote Host:")
        remote_label.set_xalign(0)
        remote_label.set_size_request(100, -1)
        remote_row.pack_start(remote_label, False, False, 0)
        self.remote_host_entry = Gtk.Entry()
        self.remote_host_entry.set_placeholder_text("e.g., my-desktop.tail1234.ts.net")
        remote_row.pack_start(self.remote_host_entry, True, True, 0)
        connection_box.pack_start(remote_row, False, False, 0)

        # Use remote checkbox
        self.use_remote_check = Gtk.CheckButton(
            label="Use remote server instead of local"
        )
        connection_box.pack_start(self.use_remote_check, False, False, 0)

        # Token
        token_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        token_label = Gtk.Label(label="Auth Token:")
        token_label.set_xalign(0)
        token_label.set_size_request(100, -1)
        token_row.pack_start(token_label, False, False, 0)
        self.token_entry = Gtk.Entry()
        self.token_entry.set_visibility(False)
        self.token_entry.set_placeholder_text("Authentication token")
        token_row.pack_start(self.token_entry, True, True, 0)
        self.show_token_btn = Gtk.ToggleButton(label="Show")
        self.show_token_btn.connect("toggled", self._on_toggle_token_visibility_gtk3)
        token_row.pack_start(self.show_token_btn, False, False, 0)
        connection_box.pack_start(token_row, False, False, 0)

        # Port
        port_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        port_label = Gtk.Label(label="Port:")
        port_label.set_xalign(0)
        port_label.set_size_request(100, -1)
        port_row.pack_start(port_label, False, False, 0)
        adjustment = Gtk.Adjustment(value=8000, lower=1, upper=65535, step_increment=1)
        self.port_spin = Gtk.SpinButton()
        self.port_spin.set_adjustment(adjustment)
        self.port_spin.set_numeric(True)
        port_row.pack_start(self.port_spin, True, True, 0)
        connection_box.pack_start(port_row, False, False, 0)

        # HTTPS checkbox
        self.https_check = Gtk.CheckButton(label="Use HTTPS")
        connection_box.pack_start(self.https_check, False, False, 0)

        # TLS Options frame
        tls_frame = Gtk.Frame(label="Advanced TLS Options")
        tls_frame.set_margin_top(8)
        tls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tls_box.set_margin_start(8)
        tls_box.set_margin_end(8)
        tls_box.set_margin_top(8)
        tls_box.set_margin_bottom(8)

        self.tls_verify_check = Gtk.CheckButton(label="Verify TLS certificates")
        self.tls_verify_check.set_tooltip_text(
            "Disable for self-signed certificates.\nConnection is still encrypted."
        )
        tls_box.pack_start(self.tls_verify_check, False, False, 0)

        self.allow_insecure_http_check = Gtk.CheckButton(
            label="Allow HTTP to remote hosts (WireGuard encrypts traffic)"
        )
        self.allow_insecure_http_check.set_tooltip_text(
            "Enable for Tailscale without MagicDNS.\n"
            "Use Tailscale IP (e.g., 100.x.y.z) with port 8000."
        )
        tls_box.pack_start(self.allow_insecure_http_check, False, False, 0)

        tls_frame.add(tls_box)
        connection_box.pack_start(tls_frame, False, False, 0)

        connection_frame.add(connection_box)
        box.pack_start(connection_frame, False, False, 0)

        scrolled.add(box)
        return scrolled

    def _create_server_tab_gtk3(self) -> Gtk.ScrolledWindow:
        """Create the Server settings tab for GTK3."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # === Server Configuration Section ===
        config_frame = Gtk.Frame(label="Server Configuration")
        config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        config_box.set_margin_start(8)
        config_box.set_margin_end(8)
        config_box.set_margin_top(8)
        config_box.set_margin_bottom(8)

        # Description
        desc_label = Gtk.Label(
            label="Server settings are stored in config.yaml. Click below to open "
            "it in your default text editor."
        )
        desc_label.set_line_wrap(True)
        desc_label.set_xalign(0)
        config_box.pack_start(desc_label, False, False, 0)

        # Open config button
        open_config_btn = Gtk.Button(label="Open config.yaml in Text Editor")
        open_config_btn.connect("clicked", lambda _: self._on_open_config_file())
        config_box.pack_start(open_config_btn, False, False, 0)

        # Path info
        config_dir = get_config_dir()
        config_path = config_dir / "config.yaml"

        path_info_label = Gtk.Label()
        path_info_label.set_markup(
            f'<span size="small" foreground="gray">Config path: {config_path}</span>'
        )
        path_info_label.set_line_wrap(True)
        path_info_label.set_xalign(0)
        path_info_label.set_selectable(True)
        config_box.pack_start(path_info_label, False, False, 0)

        config_frame.add(config_box)
        box.pack_start(config_frame, False, False, 0)

        scrolled.add(box)
        return scrolled

    def _on_toggle_token_visibility_gtk3(self, button) -> None:
        """Toggle token visibility (GTK3)."""
        if self.token_entry:
            self.token_entry.set_visibility(button.get_active())
            button.set_label("Hide" if button.get_active() else "Show")

    def _on_constrain_speakers_toggled_gtk3(self, button) -> None:
        """Enable/disable the expected speakers spinbox based on checkbox state (GTK3)."""
        if self.expected_speakers_spin:
            self.expected_speakers_spin.set_sensitive(button.get_active())

    def _refresh_devices_gtk3(self) -> None:
        """Refresh the audio device list (GTK3)."""
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

    def _save_and_close_gtk3(self) -> None:
        """Save settings (GTK3 version - dialog destroyed by caller)."""
        # App tab
        if self.auto_copy_check:
            self.config.set(
                "clipboard", "auto_copy", value=self.auto_copy_check.get_active()
            )
        if self.notifications_check:
            self.config.set(
                "ui", "notifications", value=self.notifications_check.get_active()
            )
        if self.stop_server_check:
            self.config.set(
                "dashboard",
                "stop_server_on_quit",
                value=self.stop_server_check.get_active(),
            )

        # Client tab - Audio
        if self.device_combo:
            device_id = self.device_combo.get_active_id()
            if device_id == "default":
                self.config.set("recording", "device_index", value=None)
            else:
                try:
                    self.config.set("recording", "device_index", value=int(device_id))
                except (ValueError, TypeError):
                    self.config.set("recording", "device_index", value=None)

        # Client tab - Diarization
        if self.constrain_speakers_check and self.expected_speakers_spin:
            if self.constrain_speakers_check.get_active():
                self.config.set(
                    "diarization",
                    "expected_speakers",
                    value=int(self.expected_speakers_spin.get_value()),
                )
            else:
                self.config.set("diarization", "expected_speakers", value=None)

        # Client tab - Connection
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
                "server",
                "remote_host",
                value=self.remote_host_entry.get_text().strip(),
            )

        # Advanced TLS options
        if self.tls_verify_check:
            self.config.set(
                "server", "tls_verify", value=self.tls_verify_check.get_active()
            )
        if self.allow_insecure_http_check:
            self.config.set(
                "server",
                "allow_insecure_http",
                value=self.allow_insecure_http_check.get_active(),
            )

        # Save to file
        if self.config.save():
            logger.info("Settings saved successfully")
        else:
            logger.error("Failed to save settings")
