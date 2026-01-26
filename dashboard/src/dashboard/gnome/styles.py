"""
Stylesheet definitions for GNOME Dashboard.

This module contains CSS stylesheets used by the GNOME Dashboard
for consistent theming across GTK4/Adwaita widgets.
"""

import logging

logger = logging.getLogger(__name__)

# Import GTK4 for type hints
try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    HAS_GTK4 = True
except (ImportError, ValueError):
    HAS_GTK4 = False
    Gdk = None  # type: ignore
    Gtk = None  # type: ignore


def get_dashboard_css() -> bytes:
    """Get the main dashboard CSS stylesheet.

    Color palette:
    - Background: #131313, #060606
    - Accents from logo: #9C1971 (magenta), #B9295E (pink), #DD4243/#E24343 (red), #0AFCCF (cyan)
    - Status: success=#4caf50, warning=#ff9800, error=#f44336
    """
    return b"""
    /* Sidebar styling */
    .sidebar {
        background-color: #131313;
        border-right: 1px solid #2d2d2d;
    }

    .sidebar-title {
        color: #0AFCCF;
        font-size: 20px;
        font-weight: bold;
    }

    .sidebar-subtitle {
        color: #9C1971;
        font-size: 16px;
    }

    .sidebar-button {
        border-radius: 8px;
        padding: 10px 12px;
        margin: 2px 4px;
        background: transparent;
        transition: background-color 200ms;
    }

    .sidebar-button:hover {
        background-color: #1e1e1e;
    }

    .sidebar-button:checked {
        background-color: #1e1e1e;
        color: #0AFCCF;
    }

    /* Status lights */
    .status-light-green { color: #4caf50; font-size: 8px; }
    .status-light-red { color: #f44336; font-size: 8px; }
    .status-light-blue { color: #2196f3; font-size: 8px; }
    .status-light-orange { color: #ff9800; font-size: 8px; }
    .status-light-gray { color: #6c757d; font-size: 8px; }

    /* Status card styling */
    .status-card {
        background-color: #131313;
        border-radius: 12px;
        padding: 16px;
        border: 1px solid #2d2d2d;
    }

    /* Welcome view */
    .welcome-title {
        font-size: 28px;
        font-weight: bold;
    }

    .welcome-subtitle {
        font-size: 14px;
        color: #808080;
    }

    /* Button styles */
    .primary-button {
        background-color: #0AFCCF;
        color: #060606;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: bold;
    }

    .primary-button:hover {
        background-color: #08d9b3;
    }

    .stop-button {
        background-color: #DD4243;
        color: white;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: bold;
    }

    .stop-button:hover {
        background-color: #E24343;
    }

    .danger-button {
        background-color: #3d3d3d;
        color: #DD4243;
        border-radius: 8px;
        padding: 10px 16px;
    }

    .danger-button:hover {
        background-color: #4d4d4d;
    }

    .secondary-button {
        background-color: #1e1e1e;
        border: 1px solid #3d3d3d;
        border-radius: 8px;
        padding: 10px 20px;
    }

    .secondary-button:hover {
        background-color: #2d2d2d;
    }

    /* Status indicators */
    .status-running {
        color: #4caf50;
    }

    .status-stopped {
        color: #ff9800;
    }

    .status-error {
        color: #DD4243;
    }

    .status-unknown {
        color: #6c757d;
    }

    /* Management group styling */
    .management-group {
        background-color: #131313;
        border: 1px solid #2d2d2d;
        border-radius: 8px;
        padding: 12px;
    }

    /* Column headers */
    .column-header {
        font-size: 12px;
        font-weight: bold;
        color: #0AFCCF;
        margin-bottom: 8px;
    }

    /* Toggle button styles */
    .toggle-enabled {
        background-color: rgba(10, 252, 207, 0.15);
        color: #0AFCCF;
        border: 1px solid rgba(10, 252, 207, 0.3);
        border-radius: 6px;
    }

    .toggle-disabled {
        background-color: rgba(108, 117, 125, 0.2);
        color: #6c757d;
        border: 1px solid rgba(108, 117, 125, 0.3);
        border-radius: 6px;
    }

    /* Live preview section */
    .preview-card {
        background-color: #131313;
        border: 1px solid #2d2d2d;
        border-radius: 8px;
        padding: 12px;
    }

    .live-transcription-view {
        background-color: #1e1e1e;
        border-radius: 4px;
        padding: 8px;
        font-family: 'Inter', sans-serif;
        font-size: 13px;
    }

    /* Volumes status card */
    .volumes-card {
        background-color: #131313;
        border: 1px solid #2d2d2d;
        border-radius: 10px;
        padding: 16px;
    }
    """


def get_readme_css() -> bytes:
    """Get the CSS for README viewer."""
    return b"""
    .readme-view {
        background-color: #1e1e1e;
        color: #d4d4d4;
        font-family: "CaskaydiaCove Nerd Font", monospace;
        font-size: 10pt;
    }
    .readme-view text {
        background-color: #1e1e1e;
        color: #d4d4d4;
    }
    """


def get_about_dialog_css() -> bytes:
    """Get the CSS for About dialog."""
    return b"""
    .about-title {
        font-size: 24px;
        font-weight: bold;
    }
    .about-version {
        color: #808080;
        font-size: 14px;
    }
    .about-description {
        color: #a0a0a0;
    }
    """


def apply_css_to_display(css: bytes) -> None:
    """Apply CSS to the default display."""
    if not HAS_GTK4:
        logger.warning("GTK4 not available, cannot apply CSS")
        return

    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
