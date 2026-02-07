"""
Apple-style physical toggle switch widget.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPalette
from PyQt6.QtWidgets import QCheckBox, QSizePolicy, QWidget


class AppleSwitch(QCheckBox):
    """A compact iOS-style toggle switch with optional label text."""

    _SWITCH_WIDTH = 50.0
    _SWITCH_HEIGHT = 30.0
    _TEXT_GAP = 10.0

    def __init__(self, text: str | QWidget | None = "", parent=None):
        if parent is None and text is not None and not isinstance(text, str):
            parent = text
            text = ""
        super().__init__(text or "", parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._position = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_to_state)

    def sizeHint(self) -> QSize:
        text = self.text()
        text_width = self.fontMetrics().horizontalAdvance(text) if text else 0
        text_height = self.fontMetrics().height() if text else 0
        width = int(self._SWITCH_WIDTH + (self._TEXT_GAP + text_width if text else 0))
        height = int(max(self._SWITCH_HEIGHT, float(text_height)))
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

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

    def _switch_rect(self) -> QRectF:
        y = (self.height() - self._SWITCH_HEIGHT) / 2.0
        return QRectF(0.0, y, self._SWITCH_WIDTH, self._SWITCH_HEIGHT)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event

        switch_rect = self._switch_rect()
        track_margin = 2.0
        knob_margin = 2.0
        track_radius = (switch_rect.height() / 2.0) - track_margin
        knob_diameter = (track_radius * 2.0) - (knob_margin * 2.0)
        knob_min_x = switch_rect.x() + track_margin + knob_margin
        knob_max_x = (
            switch_rect.x()
            + switch_rect.width()
            - knob_diameter
            - track_margin
            - knob_margin
        )
        knob_x = knob_min_x + (knob_max_x - knob_min_x) * self._position
        knob_y = switch_rect.y() + (switch_rect.height() - knob_diameter) / 2.0

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
            QRectF(
                switch_rect.x() + track_margin,
                switch_rect.y() + track_margin,
                switch_rect.width() - (track_margin * 2.0),
                switch_rect.height() - (track_margin * 2.0),
            ),
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

        text = self.text()
        if not text:
            return

        painter.setPen(
            self.palette().color(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText
            )
            if not self.isEnabled()
            else self.palette().color(QPalette.ColorRole.WindowText)
        )
        text_rect = QRectF(
            self._SWITCH_WIDTH + self._TEXT_GAP,
            0.0,
            max(0.0, self.width() - (self._SWITCH_WIDTH + self._TEXT_GAP)),
            float(self.height()),
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text,
        )
