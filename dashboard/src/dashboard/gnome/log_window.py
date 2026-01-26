"""
Log Window for GNOME Dashboard.

This module contains the LogWindow class for displaying logs with syntax
highlighting using GTK4/Adwaita.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Import GTK4 and related modules
HAS_GTK4 = False
HAS_GTKSOURCEVIEW = False
try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    HAS_GTK4 = True

    try:
        gi.require_version("GtkSource", "5")
        from gi.repository import GtkSource

        HAS_GTKSOURCEVIEW = True
    except (ImportError, ValueError) as e:
        logger.debug(f"GtkSourceView not available, line numbers disabled: {e}")
        GtkSource = None  # type: ignore

except (ImportError, ValueError) as e:
    logger.warning(f"GTK4/Adwaita not available: {e}")
    Adw = None  # type: ignore
    Gdk = None  # type: ignore
    Gtk = None  # type: ignore
    GtkSource = None  # type: ignore


def _get_log_window_base():
    """Get the base class for LogWindow."""
    if HAS_GTK4:
        return Adw.Window
    return object


class LogWindow(_get_log_window_base()):
    """Separate window for displaying logs with syntax highlighting and line numbers."""

    def __init__(self, title: str, app: Any = None):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for LogWindow")

        super().__init__(title=title)
        if app:
            self.set_application(app)
        self.set_default_size(800, 600)

        # Track displayed content to avoid unnecessary redraws
        self._current_line_count = 0
        self._current_content_hash = 0

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=title))
        content.append(header)

        # Log view in a scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # Use GtkSourceView if available (for line numbers), otherwise fallback to TextView
        if HAS_GTKSOURCEVIEW and GtkSource:
            self._text_view = GtkSource.View()
            self._text_view.set_show_line_numbers(True)
            self._text_view.set_background_pattern(GtkSource.BackgroundPatternType.NONE)
            self._buffer = self._text_view.get_buffer()
        else:
            self._text_view = Gtk.TextView()
            self._buffer = self._text_view.get_buffer()

        self._text_view.set_editable(False)
        self._text_view.set_monospace(True)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.add_css_class("log-view")

        # Setup text tags for syntax highlighting
        self._setup_text_tags()

        scrolled.set_child(self._text_view)
        content.append(scrolled)

        self.set_content(content)
        self._apply_styles()

    def _setup_text_tags(self) -> None:
        """Create text tags for syntax highlighting."""
        # DEBUG - Gray
        self._buffer.create_tag("DEBUG", foreground="#808080")
        # INFO - Cyan
        self._buffer.create_tag("INFO", foreground="#4EC9B0")
        # WARNING - Yellow
        self._buffer.create_tag("WARNING", foreground="#DCDCAA")
        # ERROR - Red + Bold
        self._buffer.create_tag("ERROR", foreground="#F48771", weight=700)
        # CRITICAL - Bright Red + Bold
        self._buffer.create_tag("CRITICAL", foreground="#FF6B6B", weight=700)
        # Date format - Cyan
        self._buffer.create_tag("date", foreground="#4EC9B0")
        # Time format - Light blue
        self._buffer.create_tag("time", foreground="#9CDCFE")
        # Milliseconds format - Gray/blue
        self._buffer.create_tag("milliseconds", foreground="#6A9FB5")
        # Brackets format - Dim gray
        self._buffer.create_tag("bracket", foreground="#808080")
        # Module names - Light blue
        self._buffer.create_tag("module", foreground="#9CDCFE")
        # Separator (pipes) - Dim
        self._buffer.create_tag("separator", foreground="#6A6A6A")
        # Container name - Purple
        self._buffer.create_tag("container", foreground="#C586C0")

    def _apply_highlighting(self, start_iter, text: str) -> None:
        """Apply syntax highlighting to newly added text."""
        if not text:
            return

        def apply_tag(tag_name: str, start_pos: int, length: int) -> None:
            tag_start = start_iter.copy()
            tag_start.forward_chars(start_pos)
            tag_end = tag_start.copy()
            tag_end.forward_chars(length)
            self._buffer.apply_tag_by_name(tag_name, tag_start, tag_end)

        # Highlight container name first (if present at start)
        container_match = re.match(r"^([\w-]+)\s*(\|)", text)
        if container_match:
            apply_tag(
                "container", container_match.start(1), len(container_match.group(1))
            )
            apply_tag("separator", container_match.start(2), 1)

        # Pattern for bracketed timestamp with milliseconds
        bracket_ts_match = re.match(
            r"^(\[)(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(,\d{3})?(\])", text
        )
        if bracket_ts_match:
            apply_tag("bracket", bracket_ts_match.start(1), 1)
            apply_tag("date", bracket_ts_match.start(2), len(bracket_ts_match.group(2)))
            apply_tag("time", bracket_ts_match.start(3), len(bracket_ts_match.group(3)))
            if bracket_ts_match.group(4):
                apply_tag(
                    "milliseconds",
                    bracket_ts_match.start(4),
                    len(bracket_ts_match.group(4)),
                )
            apply_tag("bracket", bracket_ts_match.start(5), 1)

        # Pattern for date/time in server logs
        datetime_match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", text)
        if datetime_match:
            apply_tag("date", datetime_match.start(1), len(datetime_match.group(1)))
            apply_tag("time", datetime_match.start(2), len(datetime_match.group(2)))

        # Highlight all pipe separators
        for match in re.finditer(r"\|", text):
            apply_tag("separator", match.start(), 1)

        # Highlight log level
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            for match in re.finditer(rf"\b{level}\b", text):
                apply_tag(level, match.start(), len(level))

        # Highlight module names
        if " - " in text:
            parts = text.split(" - ")
            if len(parts) >= 2:
                module_part = parts[1]
                if ":" in module_part:
                    module_name = module_part.split(":")[0].strip()
                    module_idx = text.index(module_name)
                    apply_tag("module", module_idx, len(module_name))

    def append_log(self, message: str) -> None:
        """Append a log message to the view with syntax highlighting."""
        vadj = self._text_view.get_vadjustment()
        old_value = vadj.get_value()
        old_upper = vadj.get_upper()
        was_at_bottom = old_value >= (old_upper - vadj.get_page_size() - 1)

        end_iter = self._buffer.get_end_iter()
        start_offset = end_iter.get_offset()
        self._buffer.insert(end_iter, message + "\n")

        start_iter = self._buffer.get_iter_at_offset(start_offset)
        self._apply_highlighting(start_iter, message)

        if not was_at_bottom:
            vadj.set_value(old_value)

    def set_logs(self, logs: str) -> None:
        """Set the entire log content, only updating if content changed."""
        new_hash = hash(logs)
        if new_hash == self._current_content_hash:
            return

        new_lines = logs.rstrip("\n").split("\n") if logs.strip() else []
        new_line_count = len(new_lines)

        if new_line_count > self._current_line_count and self._current_line_count > 0:
            current_text = self._buffer.get_text(
                self._buffer.get_start_iter(), self._buffer.get_end_iter(), False
            )
            current_lines = (
                current_text.rstrip("\n").split("\n") if current_text.strip() else []
            )

            if new_lines[: len(current_lines)] == current_lines:
                lines_to_add = new_lines[len(current_lines) :]
                for line in lines_to_add:
                    self.append_log(line)
                self._current_line_count = new_line_count
                self._current_content_hash = new_hash
                return

        vadj = self._text_view.get_vadjustment()
        old_value = vadj.get_value()

        self._buffer.set_text("")

        for line in logs.split("\n"):
            if line:
                end_iter = self._buffer.get_end_iter()
                start_offset = end_iter.get_offset()
                self._buffer.insert(end_iter, line + "\n")
                start_iter = self._buffer.get_iter_at_offset(start_offset)
                self._apply_highlighting(start_iter, line)

        vadj.set_value(old_value)

        self._current_line_count = new_line_count
        self._current_content_hash = new_hash

    def clear_logs(self) -> None:
        """Clear all logs."""
        self._buffer.set_text("")
        self._current_line_count = 0
        self._current_content_hash = 0

    def _apply_styles(self) -> None:
        """Apply dark theme styling."""
        css = b"""
        .log-view {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: "CaskaydiaCove Nerd Font", monospace;
            font-size: 9pt;
        }
        .log-view:selected {
            background-color: #264f78;
        }
        .log-view text {
            background-color: #1e1e1e;
        }
        .log-view border {
            background-color: #252526;
        }
        .log-view .line-numbers {
            background-color: #252526;
            color: #858585;
            padding-left: 4px;
            padding-right: 8px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
