"""
Log window components for the Dashboard.

This module contains the log display window and its supporting classes:
- LogSyntaxHighlighter: Syntax highlighting for log messages
- LineNumberArea: Line number display widget
- LogWindow: Separate window for displaying logs
"""

import logging
import re

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class LogSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for log messages with color-coded log levels."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Define text formats for different log levels
        self.formats = {}

        # DEBUG - Gray
        debug_format = QTextCharFormat()
        debug_format.setForeground(QColor("#808080"))
        self.formats["DEBUG"] = debug_format

        # INFO - Cyan
        info_format = QTextCharFormat()
        info_format.setForeground(QColor("#4EC9B0"))
        self.formats["INFO"] = info_format

        # WARNING - Yellow
        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor("#DCDCAA"))
        self.formats["WARNING"] = warning_format

        # ERROR - Red
        error_format = QTextCharFormat()
        error_format.setForeground(QColor("#F48771"))
        error_format.setFontWeight(QFont.Weight.Bold)
        self.formats["ERROR"] = error_format

        # CRITICAL - Bright Red + Bold
        critical_format = QTextCharFormat()
        critical_format.setForeground(QColor("#FF6B6B"))
        critical_format.setFontWeight(QFont.Weight.Bold)
        self.formats["CRITICAL"] = critical_format

        # Date format - Cyan
        self.date_format = QTextCharFormat()
        self.date_format.setForeground(QColor("#4EC9B0"))

        # Time format - Light blue
        self.time_format = QTextCharFormat()
        self.time_format.setForeground(QColor("#9CDCFE"))

        # Milliseconds format - Gray/blue
        self.milliseconds_format = QTextCharFormat()
        self.milliseconds_format.setForeground(QColor("#6A9FB5"))

        # Brackets format - Dim gray
        self.bracket_format = QTextCharFormat()
        self.bracket_format.setForeground(QColor("#808080"))

        # Module/file names - Light blue
        self.module_format = QTextCharFormat()
        self.module_format.setForeground(QColor("#9CDCFE"))

        # Separator (pipes, dashes) - Dim
        self.separator_format = QTextCharFormat()
        self.separator_format.setForeground(QColor("#6A6A6A"))

        # Container name - Purple
        self.container_format = QTextCharFormat()
        self.container_format.setForeground(QColor("#C586C0"))

    def highlightBlock(self, text):
        """Apply syntax highlighting to a block of text."""
        if not text:
            return

        # Highlight container name first (if present at start)
        # Server format: container-name | ...
        container_match = re.match(r"^([\w-]+)\s*(\|)", text)
        if container_match:
            # Container name
            self.setFormat(
                container_match.start(1),
                len(container_match.group(1)),
                self.container_format,
            )
            # First pipe
            self.setFormat(container_match.start(2), 1, self.separator_format)

        # Highlight timestamp patterns
        # Client format: [2026-01-07 15:35:24,321]
        # Server format: container | 2026-01-07 13:27:12 | INFO | main | ...

        # Pattern for bracketed timestamp with milliseconds [YYYY-MM-DD HH:MM:SS,mmm]
        bracket_ts_match = re.match(
            r"^(\[)(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(,\d{3})?(\])", text
        )
        if bracket_ts_match:
            # Opening bracket
            self.setFormat(bracket_ts_match.start(1), 1, self.bracket_format)
            # Date
            self.setFormat(
                bracket_ts_match.start(2),
                len(bracket_ts_match.group(2)),
                self.date_format,
            )
            # Time
            self.setFormat(
                bracket_ts_match.start(3),
                len(bracket_ts_match.group(3)),
                self.time_format,
            )
            # Milliseconds (if present)
            if bracket_ts_match.group(4):
                self.setFormat(
                    bracket_ts_match.start(4),
                    len(bracket_ts_match.group(4)),
                    self.milliseconds_format,
                )
            # Closing bracket
            self.setFormat(bracket_ts_match.start(5), 1, self.bracket_format)

        # Pattern for date/time in server logs: YYYY-MM-DD HH:MM:SS
        # This will match timestamps after the container name
        datetime_match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", text)
        if datetime_match:
            # Date
            self.setFormat(
                datetime_match.start(1),
                len(datetime_match.group(1)),
                self.date_format,
            )
            # Time
            self.setFormat(
                datetime_match.start(2),
                len(datetime_match.group(2)),
                self.time_format,
            )

        # Highlight all pipe separators
        for match in re.finditer(r"\|", text):
            self.setFormat(match.start(), 1, self.separator_format)

        # Highlight log level
        for level_name, level_format in self.formats.items():
            # Match level as a standalone word
            for match in re.finditer(rf"\b{level_name}\b", text):
                self.setFormat(match.start(), len(level_name), level_format)

        # Highlight module names (text after " - " before ":")
        # Pattern: [timestamp] LEVEL - module.name: message
        if " - " in text:
            parts = text.split(" - ")
            if len(parts) >= 2:
                module_part = parts[1]
                if ":" in module_part:
                    module_name = module_part.split(":")[0].strip()
                    module_idx = text.index(module_name)
                    self.setFormat(module_idx, len(module_name), self.module_format)


class LineNumberArea(QWidget):
    """Widget to display line numbers for a QPlainTextEdit."""

    def __init__(self, log_window: "LogWindow"):
        super().__init__(log_window._log_view)
        self.log_window = log_window

    def sizeHint(self):
        """Return the size hint for the line number area."""
        return self.log_window.lineNumberAreaWidth()

    def paintEvent(self, event):
        """Paint the line numbers."""
        self.log_window.lineNumberAreaPaintEvent(event)


class LogWindow(QMainWindow):
    """
    Separate window for displaying logs.

    This window displays logs in a terminal-like view with CaskydiaCove Nerd Font,
    syntax highlighting, and line numbers.
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        """
        Initialize the log window.

        Args:
            title: Window title (e.g., "Server Logs" or "Client Logs")
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 600)

        # Track displayed content to avoid unnecessary redraws
        self._current_line_count = 0
        self._current_content_hash = 0

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Log view with line numbers
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        # Set font to CaskydiaCove Nerd Font 9pt
        font = QFont("CaskydiaCove Nerd Font", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._log_view.setFont(font)

        # Setup line number area
        self._line_number_area = LineNumberArea(self)

        # Connect signals for line number updates
        self._log_view.blockCountChanged.connect(self._update_line_number_area_width)
        self._log_view.updateRequest.connect(self._update_line_number_area)

        self._update_line_number_area_width(0)

        # Setup syntax highlighter
        self._highlighter = LogSyntaxHighlighter(self._log_view.document())

        layout.addWidget(self._log_view)

        # Apply dark theme styling
        self._apply_styles()

        # Update line number area geometry after everything is set up
        self._update_line_number_area_geometry()

    def lineNumberAreaWidth(self):
        """Calculate the width needed for the line number area."""
        digits = 1
        max_num = max(1, self._log_view.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1

        space = 10 + self._log_view.fontMetrics().horizontalAdvance("9") * digits
        return space

    def _update_line_number_area_width(self, _):
        """Update the viewport margins to make room for line numbers."""
        self._log_view.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        """Update the line number area when scrolling or text changes."""
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )

        if rect.contains(self._log_view.viewport().rect()):
            self._update_line_number_area_width(0)

        # Update geometry to ensure it stays aligned
        self._update_line_number_area_geometry()

    def _update_line_number_area_geometry(self):
        """Update the geometry of the line number area to match the text view."""
        cr = self._log_view.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height())
        )

    def lineNumberAreaPaintEvent(self, event):
        """Paint the line numbers in the line number area."""
        painter = QPainter(self._line_number_area)
        painter.fillRect(
            event.rect(), QColor("#252526")
        )  # Darker background for line numbers

        block = self._log_view.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(
            self._log_view.blockBoundingGeometry(block)
            .translated(self._log_view.contentOffset())
            .top()
        )
        bottom = top + int(self._log_view.blockBoundingRect(block).height())

        painter.setPen(QColor("#858585"))  # Gray color for line numbers

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 5,
                    self._log_view.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + int(self._log_view.blockBoundingRect(block).height())
            block_number += 1

    def resizeEvent(self, event):
        """Handle resize events to update line number area."""
        super().resizeEvent(event)
        self._update_line_number_area_geometry()

    def append_log(self, message: str) -> None:
        """Append a log message to the view while preserving scroll position."""
        # Save current scroll position
        scrollbar = self._log_view.verticalScrollBar()
        old_value = scrollbar.value()
        was_at_bottom = old_value == scrollbar.maximum()

        # Append the message
        self._log_view.appendPlainText(message)

        # Restore scroll position (unless user was at bottom)
        if not was_at_bottom:
            scrollbar.setValue(old_value)

    def set_logs(self, logs: str) -> None:
        """Set the entire log content, only updating if content changed."""
        # Check if content actually changed using hash
        new_hash = hash(logs)
        if new_hash == self._current_content_hash:
            return  # No change, skip update entirely

        # Split into lines for comparison
        new_lines = logs.rstrip("\n").split("\n") if logs.strip() else []
        new_line_count = len(new_lines)

        # If new content has more lines and starts with same content, just append
        if new_line_count > self._current_line_count and self._current_line_count > 0:
            current_text = self._log_view.toPlainText()
            current_lines = (
                current_text.rstrip("\n").split("\n") if current_text.strip() else []
            )

            # Check if current content matches the beginning of new content
            if new_lines[: len(current_lines)] == current_lines:
                # Just append the new lines
                lines_to_add = new_lines[len(current_lines) :]
                for line in lines_to_add:
                    self.append_log(line)
                self._current_line_count = new_line_count
                self._current_content_hash = new_hash
                return

        # Content changed significantly - need full replacement
        # Save scroll position
        scrollbar = self._log_view.verticalScrollBar()
        old_value = scrollbar.value()

        # Block signals to prevent unnecessary repaints during update
        self._log_view.blockSignals(True)
        self._log_view.setPlainText(logs)
        self._log_view.blockSignals(False)

        # Restore scroll position
        scrollbar.setValue(old_value)

        # Update tracking
        self._current_line_count = new_line_count
        self._current_content_hash = new_hash

        # Force single repaint of line numbers
        self._line_number_area.update()

    def clear_logs(self) -> None:
        """Clear all logs."""
        self._log_view.clear()
        self._current_line_count = 0
        self._current_content_hash = 0

    def _apply_styles(self) -> None:
        """Apply dark theme matching the Dashboard UI."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QPlainTextEdit {
                background-color: #1e1e1e;
                border: none;
                color: #d4d4d4;
            }
        """)
