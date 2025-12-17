"""
Factory for creating platform-appropriate tray implementation.
"""

import os
import platform

from .base import AbstractTray


def detect_desktop_environment() -> str:
    """Detect the current desktop environment on Linux."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()

    if "kde" in desktop or "plasma" in desktop:
        return "kde"
    elif "gnome" in desktop:
        return "gnome"
    elif "xfce" in desktop:
        return "xfce"
    elif "cinnamon" in desktop:
        return "cinnamon"
    elif "mate" in desktop:
        return "mate"
    else:
        return desktop or "unknown"


def create_tray(app_name: str = "TranscriptionSuite") -> AbstractTray:
    """
    Create the appropriate tray implementation for the current platform.

    Args:
        app_name: Application name to display in the tray.

    Returns:
        AbstractTray implementation for the current platform.

    Raises:
        RuntimeError: If no suitable tray implementation is available.
    """
    system = platform.system()

    if system == "Windows":
        # Windows: Use PyQt6
        from .qt6_tray import Qt6Tray

        return Qt6Tray(app_name)

    elif system == "Linux":
        desktop = detect_desktop_environment()

        if desktop == "kde":
            # KDE Plasma: Use PyQt6 (native integration)
            from .qt6_tray import Qt6Tray

            return Qt6Tray(app_name)

        elif desktop == "gnome":
            # GNOME: Use AppIndicator3 (requires extension)
            try:
                from .gtk4_tray import Gtk4Tray

                return Gtk4Tray(app_name)
            except ImportError:
                # Fallback to Qt if GTK not available
                from .qt6_tray import Qt6Tray

                return Qt6Tray(app_name)

        elif desktop in ("xfce", "cinnamon", "mate"):
            # Other GTK-based DEs: Try GTK first
            try:
                from .gtk4_tray import Gtk4Tray

                return Gtk4Tray(app_name)
            except ImportError:
                from .qt6_tray import Qt6Tray

                return Qt6Tray(app_name)

        else:
            # Unknown Linux DE: Try Qt first (more widely compatible)
            try:
                from .qt6_tray import Qt6Tray

                return Qt6Tray(app_name)
            except ImportError:
                from .gtk4_tray import Gtk4Tray

                return Gtk4Tray(app_name)

    elif system == "Darwin":
        # macOS: Could use rumps or PyQt6
        raise RuntimeError(
            "macOS is not currently supported. "
            "Consider using PyQt6 or rumps for macOS tray support."
        )

    else:
        raise RuntimeError(f"Unsupported platform: {system}")
