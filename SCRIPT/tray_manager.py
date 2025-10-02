# tray_manager.py
#!/usr/bin/env python3
"""
System Tray Icon Manager for the Speech-to-Text system.

This module provides a system tray icon using PyQt6 to display the application's
status. It handles icon creation, state changes, and the main application
event loop.
"""

import sys
from typing import Callable, Optional, cast

try:
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
    from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen
    from PyQt6.QtCore import Qt, QCoreApplication
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

class TrayIconManager:
    """Manages the system tray icon and the application event loop."""

    def __init__(self, name: str, quit_callback: Optional[Callable] = None):
        """
        Initialize the TrayIconManager.

        Args:
            name: The name of the application, shown as a tooltip.
            quit_callback: A function to call when the quit menu item is clicked.
        """
        if not HAS_PYQT:
            raise ImportError("PyQt6 is required for the system tray icon. Please install it.")

        # Get or create the application instance, using a local variable for type narrowing
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        self.app = app

        # --- FIX: Address 'reportAttributeAccessIssue' ---
        # Use the local variable `app` within the isinstance check to help Pylance.
        if isinstance(app, QApplication):
            # Prevent the app from quitting when the last window is closed
            cast(QApplication, app).setQuitOnLastWindowClosed(False)

        self.icon = QSystemTrayIcon()
        self.icon.setToolTip(name)
        self.quit_callback = quit_callback

        self._setup_context_menu()

        self.colors = {
            "standby": (0, 255, 0),      # Green
            "recording": (255, 255, 0),  # Yellow
            "transcribing": (255, 0, 0)  # Red
        }

    def _setup_context_menu(self):
        """Create a context menu for the tray icon with a Quit button."""
        menu = QMenu()
        if self.quit_callback:
            quit_action = menu.addAction("Quit")
            # --- FIX 2: Address 'reportOptionalMemberAccess' ---
            # Pylance warns that addAction could theoretically return None.
            # We add a check to ensure quit_action is valid before using it.
            if quit_action:
                quit_action.triggered.connect(self.quit_callback)
        self.icon.setContextMenu(menu)

    def _create_icon(self, color_rgb: tuple) -> QIcon:
        """
        Generates a circular QIcon with a specified fill color and black border.

        Args:
            color_rgb: A tuple (r, g, b) for the icon's fill color.
        
        Returns:
            A QIcon object.
        """
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen_width = 2
        margin = pen_width // 2
        circle_rect = pixmap.rect().adjusted(margin, margin, -margin, -margin)

        # Draw the solid color circle
        painter.setBrush(QColor(*color_rgb))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(circle_rect)

        # Draw the black border
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(pen_width)
        painter.setPen(pen)
        painter.drawEllipse(circle_rect)

        painter.end()
        return QIcon(pixmap)

    def set_state(self, state: str):
        """
        Set the icon's appearance based on the application state.

        Args:
            state: The current state ('standby', 'recording', 'transcribing').
        """
        color = self.colors.get(state)
        if color:
            new_icon = self._create_icon(color)
            self.icon.setIcon(new_icon)

    def run(self):
        """Show the icon and start the application event loop."""
        self.set_state("standby")
        self.icon.show()
        if self.app:
            return self.app.exec()
        return 1

    def stop(self):
        """Hide the icon and quit the application event loop."""
        self.icon.hide()
        if self.app:
            self.app.quit()