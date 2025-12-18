"""
KDE Plasma system tray implementation using PyQt6.

Provides native system tray integration for KDE Plasma desktop.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client.common.config import ClientConfig

logger = logging.getLogger(__name__)


def run_tray(config: "ClientConfig") -> int:
    """
    Run the KDE Plasma tray application.

    Args:
        config: Client configuration

    Returns:
        Exit code
    """
    try:
        from PyQt6.QtGui import QAction, QIcon
        from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    except ImportError as e:
        logger.error(f"PyQt6 not available: {e}")
        print("Error: PyQt6 is required for KDE tray. Install with: pip install PyQt6")
        return 1

    import sys

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Check system tray availability
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.error("System tray not available")
        print("Error: System tray is not available on this system")
        return 1

    # Create tray icon
    # TODO: Use actual application icon
    tray = QSystemTrayIcon()
    tray.setToolTip("TranscriptionSuite")

    # Create context menu
    menu = QMenu()

    start_action = QAction("Start Recording")
    start_action.triggered.connect(lambda: logger.info("Start recording clicked"))
    menu.addAction(start_action)

    stop_action = QAction("Stop Recording")
    stop_action.triggered.connect(lambda: logger.info("Stop recording clicked"))
    menu.addAction(stop_action)

    menu.addSeparator()

    transcribe_action = QAction("Transcribe File...")
    transcribe_action.triggered.connect(lambda: logger.info("Transcribe file clicked"))
    menu.addAction(transcribe_action)

    menu.addSeparator()

    notebook_action = QAction("Open Audio Notebook")
    notebook_action.triggered.connect(lambda: _open_url(config, "/"))
    menu.addAction(notebook_action)

    menu.addSeparator()

    quit_action = QAction("Quit")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()

    logger.info("KDE tray started")
    print("Tray icon is now running. Right-click for menu.")

    return app.exec()


def _open_url(config: "ClientConfig", path: str) -> None:
    """Open a URL in the default browser."""
    import webbrowser

    scheme = "https" if config.use_https else "http"
    url = f"{scheme}://{config.server_host}:{config.server_port}{path}"
    webbrowser.open(url)
