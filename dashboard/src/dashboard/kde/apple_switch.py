"""
Apple-style physical toggle switch widget.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QAbstractButton


class AppleSwitch(QAbstractButton):
    """A compact iOS-style toggle switch with animated knob."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(50, 30)

        self._position = 0.0
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_to_state)

    def sizeHint(self) -> QSize:
        return QSize(50, 30)

    def _animate_to_state(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._position)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = max(0.0, min(1.0, float(value)))
        self.update()

    position = pyqtProperty(float, get_position, set_position)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        track_margin = 2.0
        knob_margin = 2.0
        track_radius = (self.height() / 2.0) - track_margin
        knob_diameter = (track_radius * 2.0) - (knob_margin * 2.0)
        knob_min_x = track_margin + knob_margin
        knob_max_x = self.width() - knob_diameter - track_margin - knob_margin
        knob_x = knob_min_x + (knob_max_x - knob_min_x) * self._position
        knob_y = (self.height() - knob_diameter) / 2.0

        if not self.isEnabled():
            track_color = QColor("#4b4b4b") if self.isChecked() else QColor("#333333")
            knob_color = QColor("#9a9a9a")
        else:
            track_color = QColor("#34C759") if self.isChecked() else QColor("#5A5A5F")
            knob_color = QColor("#FFFFFF")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(
            track_margin,
            track_margin,
            self.width() - (track_margin * 2.0),
            self.height() - (track_margin * 2.0),
            track_radius,
            track_radius,
        )

        painter.setBrush(knob_color)
        painter.drawEllipse(
            int(knob_x),
            int(knob_y),
            int(knob_diameter),
            int(knob_diameter),
        )
