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

    def __init__(self,
                 name: str,
                 start_callback: Optional[Callable] = None,
                 stop_callback: Optional[Callable] = None,
                 quit_callback: Optional[Callable] = None,
                 open_config_callback: Optional[Callable] = None,
                 run_static_callback: Optional[Callable] = None,
                 reset_callback: Optional[Callable] = None):
        """
        Initialize the TrayIconManager.

        Args:
            name: The name of the application, shown as a tooltip.
            start_callback: Function to call on left-click.
            stop_callback: Function to call on right-click.
            quit_callback: A function to call to quit.
            open_config_callback: Function to open the config dialog.
            run_static_callback: Function to run static transcription.
            reset_callback: Function to reset the current operation.
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
        
        # Store callbacks
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.quit_callback = quit_callback
        self.open_config_callback = open_config_callback
        self.run_static_callback = run_static_callback
        self.reset_callback = reset_callback

        self._setup_context_menu()
        # Connect to the 'activated' signal to handle clicks
        self.icon.activated.connect(self._handle_activation)

        # New color scheme reflecting the new states
        self.colors = {
            "loading": (128, 128, 128),  # Grey
            "standby": (0, 255, 0),      # Green
            "recording": (255, 255, 0),  # Yellow
            "transcribing": (255, 128, 0), # Orange during transcription
            "error": (255, 0, 0)         # Red
        }

    def _setup_context_menu(self):
        """Create a context menu for the tray icon."""
        menu = QMenu()
        
        if self.start_callback:
            start_action = menu.addAction("Start Recording")
            if start_action:
                start_action.triggered.connect(self.start_callback)

        if self.stop_callback:
            stop_action = menu.addAction("Stop Recording")
            if stop_action:
                stop_action.triggered.connect(self.stop_callback)

        if getattr(self, "reset_callback", None):
            reset_action = menu.addAction("Reset")
            if reset_action:
                reset_action.triggered.connect(self.reset_callback)

        menu.addSeparator()

        if self.open_config_callback:
            config_action = menu.addAction("Configuration")
            if config_action:
                config_action.triggered.connect(self.open_config_callback)
        
        if self.run_static_callback:
            static_action = menu.addAction("Transcribe File...")
            if static_action:
                static_action.triggered.connect(self.run_static_callback)

        menu.addSeparator()

        if self.quit_callback:
            quit_action = menu.addAction("Quit")
            if quit_action:
                quit_action.triggered.connect(self.quit_callback)
        
        self.icon.setContextMenu(menu)

    def _handle_activation(self, reason: QSystemTrayIcon.ActivationReason):
        """Handle various click events on the tray icon."""
        # Type guard to ensure we have a QApplication instance
        if not isinstance(self.app, QApplication):
            return
        
        # Now we can safely cast and use QApplication methods
        app = cast(QApplication, self.app)
        # Get keyboard modifiers to check if Shift is pressed
        modifiers = app.keyboardModifiers()
        
        is_shift_pressed = modifiers & Qt.KeyboardModifier.ShiftModifier
        
        if reason == QSystemTrayIcon.ActivationReason.Trigger and self.start_callback: # Left-click
            self.start_callback()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick and self.stop_callback: # Middle-click
            self.stop_callback()

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
            state: The current state ('loading', 'standby', 'recording', 'transcribing', 'error').
        """
        color = self.colors.get(state)
        if color:
            new_icon = self._create_icon(color)
            self.icon.setIcon(new_icon)

    def run(self):
        """Show the icon and start the application event loop."""
        self.set_state("loading") # Start with grey icon
        self.icon.show()
        if self.app:
            return self.app.exec()
        return 1

    def stop(self):
        """Hide the icon and quit the application event loop."""
        self.icon.hide()
        if self.app:
            self.app.quit()