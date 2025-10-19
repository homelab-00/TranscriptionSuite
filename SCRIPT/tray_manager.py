#!/usr/bin/env python3
"""
System Tray Icon Manager for the Speech-to-Text system.

This module provides a system tray icon using PyQt6 to display the application's
status. It handles icon creation, state changes, and the main application
event loop.
"""

import sys
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

if TYPE_CHECKING:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
    from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    HAS_PYQT = True
else:
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
        from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

        HAS_PYQT = True
    except ImportError:
        HAS_PYQT = False
        # Provide stubs for type checking when PyQt is not available
        QApplication = None  # type: ignore[assignment, misc]
        QSystemTrayIcon = None  # type: ignore[assignment, misc]
        QMenu = None  # type: ignore[assignment, misc]
        QIcon = None  # type: ignore[assignment, misc]
        QPixmap = None  # type: ignore[assignment, misc]
        QPainter = None  # type: ignore[assignment, misc]
        QColor = None  # type: ignore[assignment, misc]
        QPen = None  # type: ignore[assignment, misc]
        QAction = None  # type: ignore[assignment, misc]
        Qt = None  # type: ignore[assignment, misc]


class TrayIconManager:
    """Manages the system tray icon and the application event loop."""

    def __init__(
        self,
        name: str,
        start_callback: Optional[Callable[[], None]] = None,
        stop_callback: Optional[Callable[[], None]] = None,
        quit_callback: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the TrayIconManager.

        Args:
            name: The name of the application, shown as a tooltip.
            start_callback: Function to call on left-click.
            stop_callback: Function to call on right-click.
            quit_callback: A function to call to quit.
        """
        if not HAS_PYQT:
            raise ImportError(
                "PyQt6 is required for the system tray icon. Please install it."
            )

        # Get or create the application instance, using a local variable
        # for type narrowing
        app_instance = QApplication.instance()
        if not app_instance:
            app_instance = QApplication(sys.argv)

        # Type assertion: we know app_instance is QApplication at this point
        self.app: QApplication = cast(QApplication, app_instance)

        # Prevent the app from quitting when the last window is closed
        self.app.setQuitOnLastWindowClosed(False)

        self.icon: QSystemTrayIcon = QSystemTrayIcon()
        self.icon.setToolTip(name)

        # Store callbacks
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.quit_callback = quit_callback

        self._setup_context_menu()
        # Connect to the 'activated' signal to handle clicks
        cast(Any, self.icon.activated).connect(self._handle_activation)

        # New color scheme reflecting the new states
        self.colors = {
            "loading": (128, 128, 128),  # Grey
            "standby": (0, 255, 0),  # Green
            "recording": (255, 255, 0),  # Yellow
            "transcribing": (255, 128, 0),  # Orange during transcription
            "error": (255, 0, 0),  # Red
        }

    def _setup_context_menu(self) -> None:
        """Create a context menu for the tray icon."""
        menu: QMenu = QMenu()

        if self.start_callback:
            start_action: QAction = QAction("Start Recording", menu)
            menu.addAction(start_action)  # type: ignore[call-overload]
            cast(Any, start_action.triggered).connect(self._on_start_triggered)

        if self.stop_callback:
            stop_action: QAction = QAction("Stop Recording", menu)
            menu.addAction(stop_action)  # type: ignore[call-overload]
            cast(Any, stop_action.triggered).connect(self._on_stop_triggered)

        menu.addSeparator()

        if self.quit_callback:
            quit_action: QAction = QAction("Quit", menu)
            menu.addAction(quit_action)  # type: ignore[call-overload]
            cast(Any, quit_action.triggered).connect(self._on_quit_triggered)

        self.icon.setContextMenu(menu)

    def _handle_activation(
        self, reason: "QSystemTrayIcon.ActivationReason"
    ) -> None:  # type: ignore[name-defined]
        """Handle various click events on the tray icon."""
        # App is guaranteed to be QApplication at this point
        # No need for type guard since we set it in __init__

        if (
            reason == QSystemTrayIcon.ActivationReason.Trigger and self.start_callback
        ):  # Left-click
            self.start_callback()
        elif (
            reason == QSystemTrayIcon.ActivationReason.MiddleClick and self.stop_callback
        ):  # Middle-click
            self.stop_callback()

    def _create_icon(
        self, color_rgb: tuple[int, int, int]
    ) -> "QIcon":  # type: ignore[name-defined]
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

    def _on_start_triggered(self, checked: bool) -> None:
        if self.start_callback:
            self.start_callback()

    def _on_stop_triggered(self, checked: bool) -> None:
        if self.stop_callback:
            self.stop_callback()

    def _on_quit_triggered(self, checked: bool) -> None:
        if self.quit_callback:
            self.quit_callback()

    def set_state(self, state: str) -> None:
        """
        Set the icon's appearance based on the application state.

        Args:
            state: The current state (
                'loading', 'standby', 'recording', 'transcribing', 'error').
        """
        color = self.colors.get(state)
        if color:
            new_icon = self._create_icon(color)
            self.icon.setIcon(new_icon)

    def run(self) -> int:
        """Show the icon and start the application event loop."""
        self.set_state("loading")  # Start with grey icon
        self.icon.show()
        if self.app:
            return self.app.exec()
        return 1

    def stop(self) -> None:
        """Hide the icon and quit the application event loop."""
        self.icon.hide()
        if self.app:
            self.app.quit()
