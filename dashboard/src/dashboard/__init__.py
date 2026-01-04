"""
TranscriptionSuite Native Client Package.

Platform-specific tray applications for:
- KDE Plasma (PyQt6)
- GNOME (GTK + AppIndicator)
- Windows 11 (PyQt6)

Handles microphone recording, clipboard, and server communication.
"""

from dashboard.common.version import get_version

__version__ = get_version()
