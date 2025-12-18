"""
GNOME system tray implementation using GTK + AppIndicator.

Provides system tray integration for GNOME desktop.
Requires the AppIndicator GNOME extension to be installed.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client.common.config import ClientConfig

logger = logging.getLogger(__name__)


def run_tray(config: "ClientConfig") -> int:
    """
    Run the GNOME tray application.

    Args:
        config: Client configuration

    Returns:
        Exit code
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3, Gtk
    except (ImportError, ValueError) as e:
        logger.error(f"GTK/AppIndicator not available: {e}")
        print("Error: GTK3 and AppIndicator are required for GNOME tray.")
        print("Install with: sudo pacman -S gtk3 libappindicator-gtk3")
        print("Also ensure the AppIndicator GNOME extension is installed.")
        return 1

    # Create indicator
    indicator = AppIndicator3.Indicator.new(
        "transcription-suite",
        "audio-input-microphone",  # Use system icon
        AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
    indicator.set_title("TranscriptionSuite")

    # Create menu
    menu = Gtk.Menu()

    # Start Recording
    start_item = Gtk.MenuItem(label="Start Recording")
    start_item.connect("activate", lambda w: logger.info("Start recording clicked"))
    menu.append(start_item)

    # Stop Recording
    stop_item = Gtk.MenuItem(label="Stop Recording")
    stop_item.connect("activate", lambda w: logger.info("Stop recording clicked"))
    menu.append(stop_item)

    menu.append(Gtk.SeparatorMenuItem())

    # Transcribe File
    transcribe_item = Gtk.MenuItem(label="Transcribe File...")
    transcribe_item.connect("activate", lambda w: logger.info("Transcribe file clicked"))
    menu.append(transcribe_item)

    menu.append(Gtk.SeparatorMenuItem())

    # Open Audio Notebook
    notebook_item = Gtk.MenuItem(label="Open Audio Notebook")
    notebook_item.connect("activate", lambda w: _open_url(config, "/"))
    menu.append(notebook_item)

    menu.append(Gtk.SeparatorMenuItem())

    # Quit
    quit_item = Gtk.MenuItem(label="Quit")
    quit_item.connect("activate", lambda w: Gtk.main_quit())
    menu.append(quit_item)

    menu.show_all()
    indicator.set_menu(menu)

    logger.info("GNOME tray started")
    print("Tray icon is now running. Click for menu.")

    Gtk.main()
    return 0


def _open_url(config: "ClientConfig", path: str) -> None:
    """Open a URL in the default browser."""
    import webbrowser

    scheme = "https" if config.use_https else "http"
    url = f"{scheme}://{config.server_host}:{config.server_port}{path}"
    webbrowser.open(url)
