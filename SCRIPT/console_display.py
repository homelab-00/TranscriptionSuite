#!/usr/bin/env python3
"""
Console UI management for TranscriptionSuite.

This module handles all visual feedback during recording in the console,
such as the live timer and audio waveform, using the 'rich' library.
It is designed to be decoupled from the core recording logic.
"""

from __future__ import annotations

import subprocess
import os
import threading
import time
from collections import deque
from typing import Any, Optional, cast

from utils import safe_print

# Import Rich for better terminal display
try:
    from rich.align import Align
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    _console = Console()
    _has_rich = True
except ImportError:  # pragma: no cover - graceful fallback when Rich is absent
    _has_rich = False
    _console = None
    Live = cast(Any, None)
    Panel = cast(Any, None)
    Align = cast(Any, None)
    Text = cast(Any, None)
    Layout = cast(Any, None)


class ConsoleDisplay:
    """Manages the live display of recording status in the console."""

    def __init__(self, show_waveform: bool):
        if not _has_rich:
            safe_print(
                "Warning: 'rich' library not found. Console display will be minimal.",
                "warning",
            )
            return

        self._show_waveform = show_waveform
        self._recording_started_at: Optional[float] = None
        self._live_display: Optional[Any] = None
        self._display_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # --- CAVA Process Management ---
        self._cava_process: Optional[subprocess.Popen] = None
        self._cava_thread: Optional[threading.Thread] = None

        # --- Waveform Rendering Attributes ---
        self._waveform_lock = threading.Lock()
        # Set the desired height of the waveform in terminal rows.
        self._waveform_display_rows = 5
        self._latest_waveform_str = self._default_waveform_display()

        # --- Preview Rendering Attributes ---
        self._preview_lock = threading.Lock()
        self._preview_sentences: deque[str] = deque(maxlen=10)
        self._latest_preview_text: Any = self._default_preview_display()
        self._preview_panel_height = 5  # 3 lines for text, 2 for panel borders

    def start(self, start_time: float):
        """Starts the live display thread, showing an error if CAVA fails."""
        if not _has_rich:
            return

        min_width = 80
        min_height = 16 if self._show_waveform else 9  # Adjust height requirement
        if _console and (_console.width < min_width or _console.height < min_height):
            raise RuntimeError(
                f"Terminal too small for live display. "
                f"Minimum required: {min_width}x{min_height}."
            )

        self._recording_started_at = start_time
        self._stop_event.clear()

        # Conditionally start the CAVA subprocess
        if self._show_waveform:
            self._start_cava_process()

        # Always start the main display thread.
        self._display_thread = threading.Thread(
            target=self._run_live_display, daemon=True
        )
        self._display_thread.start()

    def stop(self):
        """Stops the live display thread and the CAVA subprocess."""
        if not _has_rich:
            return

        self._stop_event.set()

        # Terminate CAVA process
        if self._cava_process and self._cava_process.poll() is None:
            try:
                self._cava_process.terminate()
                self._cava_process.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if self._cava_process:
                    self._cava_process.kill()
            except Exception:
                pass  # Ignore other errors during shutdown
        self._cava_process = None

        # Join CAVA reader thread
        if self._cava_thread and self._cava_thread.is_alive():
            self._cava_thread.join(timeout=0.5)
        self._cava_thread = None

        # Join main display thread
        if self._display_thread and self._display_thread.is_alive():
            self._display_thread.join(timeout=0.5)
        self._display_thread = None

        self._reset_display_state()

    def _start_cava_process(self):
        """
        Tries to launch the CAVA subprocess. On failure, it updates the
        waveform display with an error message instead of stopping the UI.
        """
        script_dir = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(script_dir, "cava.config")

        if not os.path.exists(config_path):
            error_text = Text(
                f"CAVA config not found at:\n{config_path}",
                style="bold red",
                justify="center",
            )
            self._latest_waveform_str = Align.center(error_text, vertical="middle")
            return

        command = ["cava", "-p", config_path]

        try:
            self._cava_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self._cava_thread = threading.Thread(
                target=self._read_cava_output, daemon=True
            )
            self._cava_thread.start()

        except FileNotFoundError:
            # CAVA is not installed or not in PATH. Prepare an error message.
            error_text = Text(
                "Command 'cava' not found.\n"
                "Please ensure CAVA is installed and in your system's PATH.",
                style="bold red",
                justify="center",
            )
            # Update the waveform string with the rich error object.
            with self._waveform_lock:
                self._latest_waveform_str = Align.center(error_text, vertical="middle")

        except Exception as e:
            # Handle other potential errors
            error_text = Text(
                f"Failed to start CAVA:\n{e}", style="bold red", justify="center"
            )
            with self._waveform_lock:
                self._latest_waveform_str = Align.center(error_text, vertical="middle")

    def _read_cava_output(self):
        """
        Reads raw ASCII data from CAVA's stdout and renders it into a centered,
        multi-row visual waveform string.
        """
        if not self._cava_process or not self._cava_process.stdout:
            return

        glyphs = " ▂▃▄▅▆▇█"
        glyph_count = len(glyphs)
        ascii_max_range = 255.0
        panel_height = self._waveform_display_rows

        while self._cava_process.poll() is None and not self._stop_event.is_set():
            try:
                line = self._cava_process.stdout.readline()
                if not line:
                    break

                parts = line.strip().split(";")
                if not parts:
                    continue

                bar_count = len(parts)

                # --- Centering Logic ---
                # Get the total width of the console.
                console_width = _console.width if _console else 80
                # Calculate the available space inside the panel
                # (console width - 4 for borders/padding).
                panel_content_width = console_width - 4

                # Calculate the total padding needed.
                total_padding = panel_content_width - bar_count

                # The left padding is half of the total, ensuring it's at least 0.
                left_padding = max(0, total_padding // 2)

                # Create the padding string.
                padding_str = " " * left_padding
                # --- End of Centering Logic ---

                bar_levels = []
                for part in parts:
                    try:
                        value = int(part)
                        level = min(1.0, value / ascii_max_range)
                        bar_levels.append(level)
                    except (ValueError, IndexError):
                        bar_levels.append(0.0)

                output_rows = []
                for i in range(panel_height):
                    # Start each row with the calculated padding.
                    row_str = padding_str

                    pos_from_bottom = panel_height - i
                    for level in bar_levels:
                        bar_height = level * panel_height
                        if bar_height >= pos_from_bottom:
                            row_str += glyphs[-1]
                        elif bar_height >= pos_from_bottom - 1:
                            fractional_part = bar_height - (pos_from_bottom - 1)
                            glyph_index = int(fractional_part * glyph_count)
                            row_str += glyphs[min(glyph_count - 1, glyph_index)]
                        else:
                            row_str += " "
                    output_rows.append(row_str)

                final_waveform_string = "\n".join(output_rows)

                with self._waveform_lock:
                    self._latest_waveform_str = (
                        f"[#4caf50]{final_waveform_string}[/#4caf50]"
                    )

            except Exception:
                break

        with self._waveform_lock:
            self._latest_waveform_str = "[grey50]CAVA has stopped.[/grey50]"

    def add_preview_sentence(self, sentence: str):
        """Adds a new sentence to the live preview display."""
        if not _has_rich or not sentence:
            return

        with self._preview_lock:
            self._preview_sentences.append(sentence.strip())

    def display_final_transcription(self, text: str):
        """Displays the final transcription in a formatted panel."""
        if not _has_rich or not text:
            safe_print(f"\n--- Transcription ---\n{text}\n---------------------\n")
            return

        panel = Panel(
            Text(text, style="bold green"),
            title="Transcription",
            border_style="green",
        )
        safe_print(panel)
        safe_print("[yellow]Transcription copied to the clipboard.[/yellow]")

    def display_metrics(self, audio_duration: float, processing_time: float):
        """Displays performance metrics of the transcription."""
        speed_ratio = (
            audio_duration / processing_time if processing_time > 0 else float("inf")
        )

        def format_duration(seconds: float) -> str:
            if seconds <= 0:
                return "0.00s"
            m, s = divmod(seconds, 60.0)
            return f"{int(m)}m {s:04.1f}s" if m >= 1 else f"{s:.2f}s"

        if _has_rich:
            metrics_text = (
                f"[grey58]  Audio duration: {format_duration(audio_duration)}\n"
                f"  Processing time: {format_duration(processing_time)}\n"
                f"  Speed ratio: {speed_ratio:.2f}x[/grey58]"
            )
            safe_print(
                Panel(
                    metrics_text,
                    title="[bold white]Metrics[/bold white]",
                    border_style="blue",
                )
            )
        else:
            safe_print(
                f"Metrics: Audio={format_duration(audio_duration)}, "
                f"Processing={format_duration(processing_time)}"
            )

    def _run_live_display(self):
        """The main loop for rendering the live display, executed in a thread."""
        if not _has_rich or not all([_console, Live, Layout, Panel]):
            return

        self._live_display = Live(
            self._generate_layout(),
            console=_console,
            screen=True,
            transient=True,
            redirect_stderr=False,
            refresh_per_second=10,
        )
        live_display = self._live_display
        if live_display is None:
            return

        with live_display:
            while not self._stop_event.is_set():
                self._render_preview()
                live_display.update(self._generate_layout())
                time.sleep(0.1)

    def _generate_layout(self) -> Any:
        """Generates the Rich Layout for the live display."""
        layout = Layout()

        # Conditionally define the layout structure
        if self._show_waveform:
            layout.split(
                Layout(name="header", size=3),
                Layout(name="waveform", size=self._waveform_display_rows + 2),
                Layout(name="preview", ratio=1),
            )
        else:
            layout.split(
                Layout(name="header", size=3),
                Layout(name="preview", ratio=1),
            )

        elapsed = time.monotonic() - (self._recording_started_at or time.monotonic())
        minutes, seconds = divmod(elapsed, 60)
        time_str = f"{int(minutes):02d}:{int(seconds):02d}"

        header_panel = Panel(
            Align.center(f"[bold #ff5722]Recording Time: {time_str}[/bold #ff5722]"),
            title="[bold white]Status[/bold white]",
            border_style="green",
        )
        layout["header"].update(header_panel)

        # Conditionally create and update the waveform panel
        if self._show_waveform:
            waveform_panel = Panel(
                self._latest_waveform_str,
                title="[white]Waveform[/white]",
                border_style="blue",
                height=self._waveform_display_rows + 2,
            )
            layout["waveform"].update(waveform_panel)

        preview_panel = Panel(
            self._latest_preview_text,
            title="[white]Live Preview[/white]",
            border_style="blue",
            height=self._preview_panel_height,
        )
        layout["preview"].update(preview_panel)

        return layout

    def _reset_display_state(self):
        """Resets waveform and preview buffers to a neutral state."""
        with self._waveform_lock:
            self._latest_waveform_str = self._default_waveform_display()
        with self._preview_lock:
            self._preview_sentences.clear()
            self._latest_preview_text = self._default_preview_display()

    def _default_waveform_display(self) -> str:
        return (
            "[grey50]Waiting for audio...[/grey50]"
            if _has_rich
            else "Waiting for audio..."
        )

    def _default_preview_display(self) -> Any:
        return (
            Text("[grey50]Live preview will appear here...[/grey50]")
            if _has_rich
            else "Waiting for preview..."
        )

    def _render_preview(self):
        """Renders the preview text and updates the internal Rich Text object."""
        if not _has_rich or not _console:
            return

        with self._preview_lock:
            if not self._preview_sentences:
                self._latest_preview_text = self._default_preview_display()
                return

            sentences_copy = list(self._preview_sentences)
            full_text = " ".join(sentences_copy)

            # Calculate the available space for text inside the panel.
            # We subtract 4 for left/right borders and padding.
            panel_text_width = _console.width - 4
            panel_text_height = self._preview_panel_height - 2  # 3 lines
            max_chars = panel_text_width * panel_text_height

            display_text = full_text
            if len(full_text) > max_chars:
                prefix = "... "
                # Calculate the starting point for the slice
                cutoff_point = len(full_text) - max_chars + len(prefix)
                display_text = prefix + full_text[cutoff_point:]

            # Create the base Text object with the dimmer style
            text_obj = Text(display_text, style="grey70")

            # Highlight the last (most recent) sentence to make it stand out
            if sentences_copy:
                last_sentence = sentences_copy[-1]
                # Use highlight_words which is robust and finds all occurrences
                # (though we only expect one at the end).
                text_obj.highlight_words(
                    [last_sentence], style="bold white", case_sensitive=True
                )

            # Ensure the text is aligned to the top-left of the panel
            self._latest_preview_text = Align.left(
                text_obj, vertical="top", height=panel_text_height
            )
