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
    """Get the main dashboard CSS stylesheet."""
    return b"""
    /* Sidebar styling */
    .sidebar {
        background-color: #1a1a1a;
        border-right: 1px solid #2d2d2d;
    }

    .sidebar-button {
        border-radius: 8px;
        padding: 10px 12px;
        margin: 2px 4px;
        background: transparent;
        transition: background-color 200ms;
    }

    .sidebar-button:hover {
        background-color: rgba(255, 255, 255, 0.08);
    }

    .sidebar-button:checked {
        background-color: rgba(255, 255, 255, 0.12);
    }

    /* Status card styling */
    .status-card {
        background-color: #252526;
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
        background-color: #0078d4;
        color: white;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: bold;
    }

    .primary-button:hover {
        background-color: #1084d8;
    }

    .stop-button {
        background-color: #dc3545;
        color: white;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: bold;
    }

    .stop-button:hover {
        background-color: #e04555;
    }

    .danger-button {
        background-color: #3d3d3d;
        color: #f44336;
        border-radius: 8px;
        padding: 10px 16px;
    }

    .danger-button:hover {
        background-color: #4d4d4d;
    }

    .secondary-button {
        background-color: #2d2d2d;
        border: 1px solid #3d3d3d;
        border-radius: 8px;
        padding: 10px 20px;
    }

    .secondary-button:hover {
        background-color: #3d3d3d;
    }

    /* Status indicators */
    .status-running {
        color: #4caf50;
    }

    .status-stopped {
        color: #ff9800;
    }

    .status-error {
        color: #f44336;
    }

    .status-unknown {
        color: #6c757d;
    }

    /* Management group styling */
    .management-group {
        background-color: #1e1e1e;
        border: 1px solid #2d2d2d;
        border-radius: 8px;
        padding: 12px;
    }

    /* Column headers */
    .column-header {
        font-size: 12px;
        font-weight: bold;
        color: #808080;
        margin-bottom: 8px;
    }

    /* Toggle button styles */
    .toggle-enabled {
        background-color: rgba(76, 175, 80, 0.2);
        color: #4caf50;
        border: 1px solid rgba(76, 175, 80, 0.3);
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
        background-color: #1e1e1e;
        border: 1px solid #2d2d2d;
        border-radius: 8px;
        padding: 12px;
    }

    .live-transcription-view {
        background-color: #252526;
        border-radius: 4px;
        padding: 8px;
        font-family: 'Inter', sans-serif;
        font-size: 13px;
    }

    /* Volumes status card */
    .volumes-card {
        background-color: #1a1a1a;
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
