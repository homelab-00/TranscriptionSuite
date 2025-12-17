"""
GTK4/libappindicator tray for GNOME Wayland.

GNOME doesn't natively support system trays, so we use AppIndicator3.
Requires the AppIndicator GNOME Shell extension to be installed and enabled.
"""

import subprocess
from typing import Optional

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3, GLib, Gtk

    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

from .base import AbstractTray, TrayAction, TrayState


class Gtk4Tray(AbstractTray):
    """GTK + AppIndicator3 tray for GNOME."""

    # Icon names for different states (using system theme icons)
    ICON_NAMES: dict[TrayState, str] = {
        TrayState.DISCONNECTED: "network-offline-symbolic",
        TrayState.CONNECTING: "network-transmit-symbolic",
        TrayState.STANDBY: "audio-input-microphone-symbolic",
        TrayState.RECORDING: "media-record-symbolic",
        TrayState.UPLOADING: "network-transmit-symbolic",
        TrayState.TRANSCRIBING: "preferences-system-time-symbolic",
        TrayState.ERROR: "dialog-error-symbolic",
    }

    def __init__(self, app_name: str = "TranscriptionSuite"):
        if not HAS_GTK:
            raise ImportError(
                "GTK3 and AppIndicator3 are required. "
                "Install with: sudo dnf install gtk3 libappindicator-gtk3"
            )

        super().__init__(app_name)

        # Create AppIndicator
        self.indicator = AppIndicator3.Indicator.new(
            "transcription-suite",
            self.ICON_NAMES[TrayState.DISCONNECTED],
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title(app_name)

        # Menu items (stored for state updates)
        self.start_item: Optional[Gtk.MenuItem] = None
        self.stop_item: Optional[Gtk.MenuItem] = None

        # Create menu
        self._setup_menu()

        self.state = TrayState.DISCONNECTED

    def _setup_menu(self) -> None:
        """Create the indicator menu."""
        menu = Gtk.Menu()

        # Recording actions
        self.start_item = Gtk.MenuItem(label="Start Recording")
        self.start_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.START_RECORDING)
        )
        menu.append(self.start_item)

        self.stop_item = Gtk.MenuItem(label="Stop Recording")
        self.stop_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.STOP_RECORDING)
        )
        self.stop_item.set_sensitive(False)
        menu.append(self.stop_item)

        menu.append(Gtk.SeparatorMenuItem())

        # File transcription
        transcribe_item = Gtk.MenuItem(label="Transcribe File...")
        transcribe_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.TRANSCRIBE_FILE)
        )
        menu.append(transcribe_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Web interfaces
        notebook_item = Gtk.MenuItem(label="Open Audio Notebook")
        notebook_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.OPEN_AUDIO_NOTEBOOK)
        )
        menu.append(notebook_item)

        remote_item = Gtk.MenuItem(label="Open Remote Server")
        remote_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.OPEN_REMOTE_SERVER)
        )
        menu.append(remote_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Settings
        settings_item = Gtk.MenuItem(label="Settings...")
        settings_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.SETTINGS)
        )
        menu.append(settings_item)

        # Quit
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: self.quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def set_state(self, state: TrayState) -> None:
        """Update indicator icon based on state."""
        self.state = state
        icon_name = self.ICON_NAMES.get(state, "dialog-question-symbolic")
        self.indicator.set_icon(icon_name)

        # Update menu sensitivity
        if self.start_item and self.stop_item:
            if state == TrayState.RECORDING:
                self.start_item.set_sensitive(False)
                self.stop_item.set_sensitive(True)
            else:
                self.start_item.set_sensitive(state == TrayState.STANDBY)
                self.stop_item.set_sensitive(False)

    def show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification via notify-send."""
        try:
            subprocess.run(
                ["notify-send", "-a", self.app_name, title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass  # notify-send not available

    def run(self) -> None:
        """Start the GTK main loop."""
        Gtk.main()

    def quit(self) -> None:
        """Exit the application."""
        self._trigger_callback(TrayAction.QUIT)
        Gtk.main_quit()

    def open_file_dialog(
        self, title: str, filetypes: list[tuple[str, str]]
    ) -> Optional[str]:
        """Open a file chooser dialog."""
        dialog = Gtk.FileChooserDialog(
            title=title,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Open", Gtk.ResponseType.ACCEPT)

        for name, pattern in filetypes:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(name)
            # Handle multiple patterns like "*.wav *.mp3"
            for p in pattern.split():
                file_filter.add_pattern(p)
            dialog.add_filter(file_filter)

        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        return path
