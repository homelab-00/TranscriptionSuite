"""
Long-form speech transcription module using RealtimeSTT.

This module provides a LongFormTranscriber class for manual control over
speech recording and transcription with keyboard shortcuts and clipboard integration.
"""

import array
import contextlib
import logging
import math
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable, List, Optional, Tuple, Union, cast

import pyperclip

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

# Import RealtimeSTT at module level to avoid import-outside-toplevel warning
try:
    from RealtimeSTT import AudioToTextRecorder

    HAS_REALTIME_STT = True
except ImportError:
    AudioToTextRecorder = None
    HAS_REALTIME_STT = False

# Import platform utilities for cross-platform compatibility
from platform_utils import ensure_platform_init

# Ensure compatibility with faster-whisper's disabled_tqdm helper on newer
# tqdm releases that no longer expose a global `_lock` attribute.
try:  # pragma: no cover - defensive compatibility shim
    from tqdm import tqdm as _tqdm_class  # type: ignore
except ImportError:  # pragma: no cover
    _tqdm_class = None  # type: ignore[assignment]
else:  # pragma: no cover
    if _tqdm_class is not None and not hasattr(_tqdm_class, "_lock"):
        setattr(_tqdm_class, "_lock", threading.RLock())

# Initialize platform-specific settings (console encoding, PyTorch audio, etc.)
PLATFORM_MANAGER = ensure_platform_init()

# Import Rich for better terminal display with Unicode support
try:
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    CONSOLE = None
    Live = None
    Group = None
    Panel = None
    Align = None
    HAS_RICH = False

    def _rich_text_placeholder(*args: Any, **kwargs: Any) -> str:
        return ""

    Text = cast(Any, _rich_text_placeholder)

# Waveform graph: Max Y-axis value
DEFAULT_WAVEFORM_CLIPPING_THRESHOLD_DB = -25.0

_MISSING = object()


class LongFormTranscriber:
    """
    A class that provides manual control over speech recording and transcription.
    """

    def __init__(
        self,
        # General Parameters
        model: str = "Systran/faster-whisper-large-v3",
        download_root: Optional[str] = None,
        language: str = "en",
        compute_type: str = "default",
        input_device_index: Optional[int] = None,
        gpu_device_index: Union[int, List[int]] = 0,
        device: str = "cuda",
        on_recording_start: Optional[Callable] = None,
        on_recording_stop: Optional[Callable] = None,
        on_transcription_start: Optional[Callable] = None,
        ensure_sentence_starting_uppercase: bool = True,
        ensure_sentence_ends_with_period: bool = True,
        use_microphone: bool = True,
        spinner: bool = False,
        level: int = logging.WARNING,
        batch_size: int = 16,
        # Voice Activation Parameters
        silero_sensitivity: float = 0.4,
        silero_use_onnx: bool = False,
        silero_deactivity_detection: bool = False,
        webrtc_sensitivity: int = 3,
        post_speech_silence_duration: float = 0.6,
        min_length_of_recording: float = 0.5,
        min_gap_between_recordings: float = 0,
        pre_recording_buffer_duration: float = 1.0,
        on_vad_detect_start: Optional[Callable] = None,
        on_vad_detect_stop: Optional[Callable] = None,
        # Advanced Parameters
        debug_mode: bool = False,
        handle_buffer_overflow: bool = True,
        beam_size: int = 5,
        buffer_size: int = 512,
        sample_rate: int = 16000,
        initial_prompt: Optional[Union[str, Iterable[int]]] = None,
        suppress_tokens: Optional[List[int]] = None,
        print_transcription_time: bool = False,
        early_transcription_on_silence: int = 0,
        allowed_latency_limit: int = 100,
        no_log_file: bool = True,
        use_extended_logging: bool = False,
        faster_whisper_vad_filter: bool = True,
        preinitialized_model=None,
    ):
        """
        Initialize the transcriber with all available parameters.
        """
        if suppress_tokens is None:
            suppress_tokens = [-1]

        self.recording = False
        self.running = False

        self._recording_started_at = None
        self._last_recording_duration = 0.0
        self._last_transcription_duration = 0.0

        self._waveform_lock = threading.Lock()
        self._waveform_window_seconds = 60.0
        self._waveform_display_seconds = 10.0
        self._waveform_slot_count = 32
        self._waveform_samples: deque[Tuple[float, float]] = deque(maxlen=512)
        self._waveform_last_levels: List[float] = [0.0] * self._waveform_slot_count
        self._waveform_last_update = 0.0
        self._waveform_decay_seconds = 2.5
        self._latest_waveform = self._default_waveform_display()
        self._waveform_amplitude_threshold = 0.7
        self._waveform_display_rows = 4
        self._waveform_clipping_threshold_db = DEFAULT_WAVEFORM_CLIPPING_THRESHOLD_DB
        self._waveform_clipping_threshold = 10 ** (
            self._waveform_clipping_threshold_db / 20.0
        )
        self._waveform_scale_target = max(
            self._waveform_clipping_threshold,
            1e-3,
        )
        self._waveform_scale_last_update = time.monotonic()

        self._timer_thread: Optional[threading.Thread] = None
        self._timer_stop_event = threading.Event()

        # Hotkey attributes removed; control is via orchestrator's tray only

        # Store preinitialized model if provided
        self.preinitialized_model = preinitialized_model

        # Store all configuration for lazy loading
        self.config = {
            # General Parameters
            "model": model,
            "download_root": download_root,
            "language": language,
            "compute_type": compute_type,
            "input_device_index": input_device_index,
            "gpu_device_index": gpu_device_index,
            "device": device,
            "on_recording_start": None,  # Will set custom callbacks
            "on_recording_stop": None,  # Will set custom callbacks
            "on_transcription_start": on_transcription_start,
            "ensure_sentence_starting_uppercase": ensure_sentence_starting_uppercase,
            "ensure_sentence_ends_with_period": ensure_sentence_ends_with_period,
            "use_microphone": use_microphone,
            "spinner": spinner,
            "level": level,
            "batch_size": batch_size,
            # Voice Activation Parameters
            "silero_sensitivity": silero_sensitivity,
            "silero_use_onnx": silero_use_onnx,
            "silero_deactivity_detection": silero_deactivity_detection,
            "webrtc_sensitivity": webrtc_sensitivity,
            "post_speech_silence_duration": post_speech_silence_duration,
            "min_length_of_recording": min_length_of_recording,
            "min_gap_between_recordings": min_gap_between_recordings,
            "pre_recording_buffer_duration": pre_recording_buffer_duration,
            "on_vad_detect_start": on_vad_detect_start,
            "on_vad_detect_stop": on_vad_detect_stop,
            # Advanced Parameters
            "debug_mode": debug_mode,
            "handle_buffer_overflow": handle_buffer_overflow,
            "beam_size": beam_size,
            "buffer_size": buffer_size,
            "sample_rate": sample_rate,
            "initial_prompt": initial_prompt,
            "suppress_tokens": suppress_tokens,
            "print_transcription_time": print_transcription_time,
            "early_transcription_on_silence": early_transcription_on_silence,
            "allowed_latency_limit": allowed_latency_limit,
            "no_log_file": no_log_file,
            "use_extended_logging": use_extended_logging,
            "faster_whisper_vad_filter": faster_whisper_vad_filter,
        }

        # External callbacks
        self.external_on_recording_start = on_recording_start
        self.external_on_recording_stop = on_recording_stop

        # Initialize the recorder instance.
        self.recorder = None
        self._initialize_recorder()

    def _default_waveform_display(self) -> str:
        """Return a friendly placeholder for waveform output."""
        idle_message = "Waiting for audio input…"

        if HAS_RICH and CONSOLE:
            return f"[grey50]{idle_message}[/grey50]"

        return idle_message

    def _reset_waveform_state(self) -> None:
        """Reset waveform buffers to a neutral state."""
        with self._waveform_lock:
            self._waveform_samples.clear()
            self._waveform_last_levels = [0.0] * self._waveform_slot_count
            self._waveform_last_update = 0.0
            self._latest_waveform = self._default_waveform_display()

    def _render_waveform(self) -> str:
        """Render a waveform bar based on recent audio levels."""
        now = time.monotonic()
        with self._waveform_lock:
            samples = list(self._waveform_samples)
            last_update = self._waveform_last_update
            previous_levels = self._waveform_last_levels[:]
            slot_count = self._waveform_slot_count
            display_window = self._waveform_display_seconds
            rows = self._waveform_display_rows
            amp_threshold = self._waveform_amplitude_threshold
            scale_target = self._waveform_scale_target

        if not samples or (now - last_update > self._waveform_decay_seconds):
            display = self._default_waveform_display()
            with self._waveform_lock:
                self._latest_waveform = display
                self._waveform_last_levels = [0.0] * self._waveform_slot_count
                self._waveform_scale_last_update = now
            return display

        if slot_count <= 0 or display_window <= 0:
            return self._default_waveform_display()

        filtered_samples = [
            (timestamp, min(level, amp_threshold))
            for timestamp, level in samples
            if level > 0.0
        ]

        if not filtered_samples:
            return self._default_waveform_display()

        display_start = now - display_window
        slot_duration = display_window / slot_count
        slot_values = [0.0] * slot_count

        if len(previous_levels) != slot_count:
            previous_levels = [0.0] * slot_count

        for timestamp, level in filtered_samples:
            if timestamp < display_start:
                continue
            slot_index = int((timestamp - display_start) / slot_duration)
            if 0 <= slot_index < slot_count:
                slot_values[slot_index] = max(slot_values[slot_index], level)

        scale_denominator = max(scale_target, 1e-6)
        raw_normalised_levels = [value / scale_denominator for value in slot_values]
        clipped_flags = [value > 1.0 for value in raw_normalised_levels]
        normalised_levels = [min(1.0, value) for value in raw_normalised_levels]

        smoothed_levels = [
            (prev * 0.4) + (current * 0.6)
            for prev, current in zip(previous_levels, normalised_levels)
        ]
        smoothed_clipped_flags = [
            clipped or level >= 0.99
            for clipped, level in zip(clipped_flags, smoothed_levels)
        ]

        if rows <= 1:
            glyphs = "▁▂▃▄▅▆▇█"
            glyph_count = len(glyphs) - 1
            bar_chars: List[str] = []

            for idx, level in enumerate(smoothed_levels):
                clamped = max(0.0, min(1.0, level))
                glyph_index = min(glyph_count, int(round(clamped * glyph_count)))
                bar_chars.append(glyphs[glyph_index])

            bar = "".join(bar_chars)
            if HAS_RICH and CONSOLE:
                coloured = []
                for idx, char in enumerate(bar_chars):
                    if smoothed_clipped_flags[idx]:
                        coloured.append(f"[yellow]{char}[/yellow]")
                    else:
                        coloured.append(f"[#4caf50]{char}[/#4caf50]")
                display = "".join(coloured)
            else:
                display = bar
        else:
            amplitude_row_count = max(1, rows - 1)
            amplitude_rows: List[List[str]] = []

            for row_idx in range(amplitude_row_count):
                row_chars: List[str] = []
                min_threshold = row_idx / amplitude_row_count
                max_threshold = (row_idx + 1) / amplitude_row_count
                glyphs = "▁▂▃▄▅▆▇█"
                glyph_count = len(glyphs) - 1

                for level in smoothed_levels:
                    if level <= min_threshold:
                        row_chars.append(" ")
                    elif level >= max_threshold:
                        row_chars.append(glyphs[-1])
                    else:
                        row_level = (level - min_threshold) / (
                            max_threshold - min_threshold
                        )
                        glyph_index = min(
                            glyph_count, int(round(row_level * glyph_count))
                        )
                        row_chars.append(glyphs[glyph_index])

                amplitude_rows.append(row_chars)

            amplitude_rows.reverse()

            indicator_row = [
                "▁" if smoothed_clipped_flags[col_idx] else " "
                for col_idx in range(len(smoothed_levels))
            ]

            if HAS_RICH and CONSOLE:
                coloured_rows: List[str] = []
                if any(char != " " for char in indicator_row):
                    coloured_indicator = "".join(
                        "[yellow]▁[/yellow]" if char == "▁" else " "
                        for char in indicator_row
                    )
                    coloured_rows.append(coloured_indicator)

                for row_chars in amplitude_rows:
                    coloured_rows.append(
                        "".join(
                            f"[#4caf50]{char}[/#4caf50]" if char != " " else " "
                            for char in row_chars
                        )
                    )

                display = "\n".join(coloured_rows) if coloured_rows else ""
            else:
                lines: List[str] = []
                if any(char != " " for char in indicator_row):
                    lines.append("".join(indicator_row))
                lines.extend("".join(row) for row in amplitude_rows)
                display = "\n".join(lines)

        with self._waveform_lock:
            self._latest_waveform = display
            self._waveform_last_levels = smoothed_levels

        return display

    def _handle_recorded_chunk(self, chunk: bytes) -> None:
        """Tap audio chunks from the recorder to derive waveform levels."""
        if not chunk:
            return

        level = 0.0

        try:
            if HAS_NUMPY and np is not None:
                samples = np.frombuffer(chunk, dtype=np.int16)
                if samples.size == 0:
                    return
                floats = samples.astype(np.float32)
                rms = float(np.sqrt(np.mean(np.square(floats))))
            else:
                samples = array.array("h")
                samples.frombytes(chunk)
                if len(samples) == 0:
                    return
                sum_sq = 0.0
                for sample in samples:
                    sum_sq += float(sample * sample)
                rms = math.sqrt(sum_sq / len(samples))

            level = min(1.0, rms / 32768.0)
        except Exception:
            return

        now = time.monotonic()
        adjusted_level = min(level, self._waveform_amplitude_threshold)

        with self._waveform_lock:
            if self._waveform_samples and now < self._waveform_samples[-1][0]:
                self._waveform_samples.clear()
            self._waveform_samples.append((now, adjusted_level))
            cutoff = now - self._waveform_window_seconds
            while self._waveform_samples and self._waveform_samples[0][0] < cutoff:
                self._waveform_samples.popleft()
            self._waveform_last_update = now
            self._waveform_scale_last_update = now

    def _safe_clipboard_copy(self, text: str) -> bool:
        """Safely copy text to clipboard with error handling."""
        try:
            pyperclip.copy(text)
            # Verify the copy worked
            if pyperclip.paste() == text:
                return True
            else:
                if HAS_RICH and CONSOLE:
                    CONSOLE.print("[yellow]Clipboard copy verification failed[/yellow]")
                return False
        except Exception as e:
            if HAS_RICH and CONSOLE:
                CONSOLE.print(f"[yellow]Clipboard error: {e}[/yellow]")
            else:
                print(f"Clipboard error: {e}")
            return False

    def _start_timer_thread(self) -> None:
        """Start background timer updates during recording."""
        if self._timer_thread and self._timer_thread.is_alive():
            return

        self._timer_stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._run_recording_timer, daemon=True
        )
        self._timer_thread.start()

    def _stop_timer_thread(self) -> None:
        """Stop background timer updates."""
        self._timer_stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=0.5)
        self._timer_thread = None
        self._reset_waveform_state()

    def _run_recording_timer(self) -> None:
        """Render a live status display during recording using Rich."""
        # First check if we have all Rich components available
        rich_components_available = all(
            [HAS_RICH, CONSOLE, Live, Group, Panel, Align, Text]
        )

        if not rich_components_available:
            while not self._timer_stop_event.is_set():
                time.sleep(0.2)
            return

        # Explicitly create local variables that Pylance knows are not None
        rich_group = cast(Any, Group)
        rich_panel = cast(Any, Panel)
        rich_align = cast(Any, Align)
        rich_live = cast(Any, Live)  # Add this line to create a non-None Live reference

        def generate_display() -> Any:
            """Generate the Rich renderable for the live display."""
            if not self.recording or self._recording_started_at is None:
                return rich_group(
                    rich_panel("Waiting to start...", border_style="yellow")
                )

            elapsed = time.monotonic() - self._recording_started_at
            minutes, seconds = divmod(elapsed, 60)
            time_str = f"{int(minutes):02d}:{int(seconds):02d}"

            header_panel = rich_panel(
                rich_align.center(
                    f"[bold #ff5722]Recording Time: {time_str}[/bold #ff5722]"
                ),
                title="[bold white]Status[/bold white]",
                border_style="green",
                height=3,
            )

            waveform_panel = rich_panel(
                self._render_waveform(),
                title="[white]Waveform[/white]",
                border_style="blue",
                height=self._waveform_display_rows + 2,
            )

            return rich_group(header_panel, waveform_panel)

        # Use rich_live instead of Live directly
        with rich_live(
            generate_display(),
            screen=True,
            transient=True,
            redirect_stderr=False,
            refresh_per_second=10,
        ) as live:
            while not self._timer_stop_event.is_set():
                live.update(generate_display())
                time.sleep(0.1)

    def _initialize_recorder(self) -> None:
        """Initialize the single recorder instance used for long-form capture."""
        if not HAS_REALTIME_STT or AudioToTextRecorder is None:
            raise ImportError("RealtimeSTT not available")

        def on_rec_start() -> None:
            self.recording = True
            self._recording_started_at = time.monotonic()
            self._last_recording_duration = 0.0
            self._last_transcription_duration = 0.0
            self._reset_waveform_state()
            self._start_timer_thread()
            if self.external_on_recording_start:
                self.external_on_recording_start()

        def on_rec_stop() -> None:
            self.recording = False
            if self._recording_started_at is not None:
                self._last_recording_duration = (
                    time.monotonic() - self._recording_started_at
                )
                self._recording_started_at = None
            self._stop_timer_thread()
            if self.external_on_recording_stop:
                self.external_on_recording_stop()

        recorder_config = self.config.copy()
        recorder_config["use_microphone"] = True
        recorder_config["on_recording_start"] = on_rec_start
        recorder_config["on_recording_stop"] = on_rec_stop
        recorder_config["on_recorded_chunk"] = self._handle_recorded_chunk

        suppress_ctx: Optional[
            Callable[[], contextlib.AbstractContextManager[Any]]
        ] = getattr(PLATFORM_MANAGER, "suppress_audio_warnings", None)

        try:
            context_manager: contextlib.AbstractContextManager[Any]
            if suppress_ctx is not None and callable(suppress_ctx):
                context_manager = suppress_ctx()
            else:
                context_manager = contextlib.nullcontext()
            with context_manager:
                self.recorder = AudioToTextRecorder(**recorder_config)

            if HAS_RICH and CONSOLE:
                CONSOLE.print(
                    "[bold green]Long-form transcription system initialized.[/bold green]"
                )
            else:
                print("Long-form transcription system initialized.")

        except (ImportError, RuntimeError) as error:
            if HAS_RICH and CONSOLE:
                CONSOLE.print(
                    f"[bold red]Error initializing recorder: {error}[/bold red]"
                )
            else:
                print(f"Error initializing recorder: {error}")

    def force_initialize(self) -> bool:
        """Rebuild the recorder instance after a forced cleanup."""
        try:
            if self.recorder:
                try:
                    self.recorder.shutdown()
                except Exception:
                    pass
            self.recorder = None
            self._initialize_recorder()
            return self.recorder is not None
        except Exception as error:
            if HAS_RICH and CONSOLE:
                CONSOLE.print(
                    f"[bold red]Failed to reinitialize recorder: {error}[/bold red]"
                )
            else:
                print(f"Failed to reinitialize recorder: {error}")
            return False

    def start_recording(self):
        """
        Start recording audio for transcription.
        """
        if HAS_RICH and CONSOLE and Panel and Align:
            min_width = 80
            min_height = 16
            if CONSOLE.width < min_width or CONSOLE.height < min_height:
                CONSOLE.print(
                    Panel(
                        Align.center(
                            f"[bold]Terminal too small![/bold]\n\n"
                            f"Please resize to at least "
                            f"[cyan]{min_width}x{min_height}[/cyan] "
                            f"characters to start recording.\n"
                            f"Current size is "
                            f"[yellow]{CONSOLE.width}x{CONSOLE.height}[/yellow].",
                            vertical="middle",
                        ),
                        title="[bold red]Error[/bold red]",
                        height=7,
                    )
                )
                return

        if not self.recording and self.recorder is not None:
            suppress_ctx: Optional[
                Callable[[], contextlib.AbstractContextManager[Any]]
            ] = getattr(PLATFORM_MANAGER, "suppress_audio_warnings", None)
            context_manager: contextlib.AbstractContextManager[Any]
            if suppress_ctx is not None and callable(suppress_ctx):
                context_manager = suppress_ctx()
            else:
                context_manager = contextlib.nullcontext()
            with context_manager:
                self.recorder.start()

    def stop_recording(self):
        """
        Stop recording audio and process the transcription.
        """
        if not self.recorder:
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[yellow]Recorders not initialized.[/yellow]")
            else:
                print("\nRecorders not initialized.")
            return

        if self.recording:
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[yellow]Stopping recording...[/yellow]")
            else:
                print("\nStopping recording...")

            self.recorder.stop()
            self.recorder.wait_audio()
            audio_data = self.recorder.audio

            transcription = None
            transcription_start = time.monotonic()

            # Display a spinner while transcribing
            if HAS_RICH and CONSOLE:
                with CONSOLE.status("[bold blue]Transcribing...[/bold blue]"):
                    transcription = ""
                    transcription = self.recorder.perform_final_transcription(
                        audio_data
                    )
            else:
                print("Transcribing...")
                transcription = ""
                transcription = self.recorder.perform_final_transcription(audio_data)
            self._last_transcription_duration = time.monotonic() - transcription_start

            if self._recording_started_at is not None:
                self._last_recording_duration = (
                    time.monotonic() - self._recording_started_at
                )
                self._recording_started_at = None

            # Ensure transcription is a string and stop the timer
            self.last_transcription = str(transcription) if transcription else ""
            self._stop_timer_thread()

            # Display the transcription
            if HAS_RICH and CONSOLE and Panel and Text:
                CONSOLE.print(
                    Panel(
                        Text(self.last_transcription, style="bold green"),
                        title="Transcription",
                        border_style="green",
                    )
                )
            else:
                print("\n" + "-" * 60)
                print("Transcription:")
                print(self.last_transcription)
                print("-" * 60 + "\n")

            # Copy the transcription to the clipboard for manual pasting
            if self.last_transcription:
                if self._safe_clipboard_copy(self.last_transcription):
                    if HAS_RICH and CONSOLE:
                        CONSOLE.print(
                            "[yellow]Transcription copied to the clipboard. "
                            "Paste it manually when ready.[/yellow]"
                        )
                    else:
                        print(
                            "Transcription copied to the clipboard. "
                            "Paste it manually when ready."
                        )
                else:
                    # Fallback: just display the text for manual copying
                    if HAS_RICH and CONSOLE:
                        CONSOLE.print(
                            "\n[yellow]Clipboard not available. "
                            "Please copy manually:[/yellow]"
                        )
                        CONSOLE.print(f"[bold]{self.last_transcription}[/bold]")
                    else:
                        print("\nClipboard not available. Please copy manually:")
                        print(f"TEXT: {self.last_transcription}")

            self._print_transcription_metrics()

    def quit(self):
        """
        Stop the transcription process and exit.
        """
        self.running = False
        if self.recording:
            self.stop_recording()

        self._stop_timer_thread()

        if HAS_RICH and CONSOLE:
            CONSOLE.print("[bold red]Exiting...[/bold red]")
        else:
            print("\nExiting...")

        self.clean_up()

    def clean_up(self):
        """Clean up resources."""
        if self.recorder:
            self.recorder.shutdown()
            self.recorder = None

    def run(self):
        """
        Start the long-form transcription process.
        """
        self.running = True

        # Show instructions (without hotkey references)
        if HAS_RICH and CONSOLE:
            CONSOLE.print("[bold]Long-Form Speech Transcription[/bold]")
            CONSOLE.print("Ready for transcription")
        else:
            print("Long-Form Speech Transcription")
            print("Ready for transcription")

        # Keep the program running until quit
        try:
            while self.running:
                time.sleep(0.1)  # Sleep to avoid high CPU usage
        except KeyboardInterrupt:
            self.quit()

        # Show minimal instructions (no hotkey hints; tray controls are used)
        if HAS_RICH and CONSOLE:
            CONSOLE.print("[bold]Long-Form Speech Transcription[/bold]")
        else:
            print("Long-Form Speech Transcription")

        # Keep the program running until quit
        try:
            while self.running:
                time.sleep(0.1)  # Sleep to avoid high CPU usage
        except KeyboardInterrupt:
            self.quit()

    def get_last_transcription(self):
        """
        Return the last transcribed text.
        """
        return self.last_transcription

    def _format_duration(self, seconds: float) -> str:
        """Format seconds as a human-friendly string."""
        if seconds <= 0:
            return "0.00s"
        minutes, secs = divmod(seconds, 60.0)
        if minutes:
            return f"{int(minutes)}m {secs:04.1f}s"
        return f"{secs:.2f}s"

    def _print_transcription_metrics(self) -> None:
        """Display metrics about the last transcription cycle."""
        audio_duration = self._last_recording_duration
        processing_time = self._last_transcription_duration
        speed_ratio = audio_duration / processing_time if processing_time > 0 else 0.0
        realtime_factor = processing_time / audio_duration if audio_duration > 0 else 0.0

        if HAS_RICH and CONSOLE:
            CONSOLE.print("[bold white]Transcription metrics:[/bold white]")
            CONSOLE.print(
                f"[grey58]  Audio duration: "
                f"{self._format_duration(audio_duration)}[/grey58]"
            )
            CONSOLE.print(
                f"[grey58]  Processing time: "
                f"{self._format_duration(processing_time)}[/grey58]"
            )
            CONSOLE.print(f"[grey58]  Speed ratio: {speed_ratio:.2f}x[/grey58]")
            CONSOLE.print(f"[grey58]  Real-time factor: {realtime_factor:.2f}[/grey58]")
        else:
            print("Transcription metrics:")
            print(f"  Audio duration: {self._format_duration(audio_duration)}")
            print(f"  Processing time: {self._format_duration(processing_time)}")
            print(f"  Speed ratio: {speed_ratio:.2f}x")
            print(f"  Real-time factor: {realtime_factor:.2f}")

        logging.info(
            "Long-form transcription metrics | audio: %.2fs | "
            "processing: %.2fs | speed: %.2fx | RTF: %.2f",
            audio_duration,
            processing_time,
            speed_ratio,
            realtime_factor,
        )


def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = LongFormTranscriber()
    transcriber.run()
    return transcriber.get_last_transcription()


if __name__ == "__main__":
    main()
