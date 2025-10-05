"""
Long-form speech transcription module using RealtimeSTT.

This module provides a LongFormTranscriber class for manual control over
speech recording and transcription with keyboard shortcuts and clipboard integration.
"""

import array
import contextlib
import io
import logging
import math
import os
import queue
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable, List, Optional, Tuple, Union

import keyboard
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

# Initialize platform-specific settings (console encoding, PyTorch audio, etc.)
PLATFORM_MANAGER = ensure_platform_init()

# Import Rich for better terminal display with Unicode support
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    CONSOLE = None
    Panel = None
    Text = None
    HAS_RICH = False


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
        # Additional parameters
        preinitialized_model=None,
        preload_model=True,
    ):
        """
        Initialize the transcriber with all available parameters.
        """
        if suppress_tokens is None:
            suppress_tokens = [-1]

        self.recording = False
        self.running = False
        self.last_transcription = ""
        self._abort_requested = False

        self._recording_started_at = None
        self._last_recording_duration = 0.0
        self._last_transcription_duration = 0.0

        self._timer_thread: Optional[threading.Thread] = None
        self._timer_stop_event = threading.Event()
        self._timer_lines_rendered = False

        self._waveform_lock = threading.Lock()
        self._waveform_window_seconds = 10.0
        self._waveform_slot_count = 32
        self._waveform_samples: deque[Tuple[float, float]] = deque(maxlen=512)
        self._waveform_last_levels: List[float] = [0.0] * self._waveform_slot_count
        self._waveform_last_update = 0.0
        self._waveform_decay_seconds = 2.5
        self._latest_waveform = self._default_waveform_display()
        self._progress_block_interval = 10.0

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
        }

        # External callbacks
        self.external_on_recording_start = on_recording_start
        self.external_on_recording_stop = on_recording_stop

        # Lazy-loaded recorder
        self.recorder = None

        # If preload_model is True, initialize the recorder immediately
        if preload_model:
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

    def _build_progress_bar(self, elapsed: float) -> str:
        """Build a segmented progress bar for the recording timeline."""
        block_interval = max(self._progress_block_interval, 1.0)
        total_blocks = max(1, int(elapsed // block_interval) + 1)
        # Cap total blocks to avoid overly long lines (roughly 10 minutes at 10s intervals)
        total_blocks = min(total_blocks, 60)

        segments: List[str] = []
        for index in range(total_blocks):
            mark_seconds = index * block_interval
            is_minute_marker = index == 0 or math.isclose(mark_seconds % 60, 0.0, abs_tol=1e-6)

            if HAS_RICH and CONSOLE:
                if index == 0:
                    segments.append("[grey58]▆[/grey58]")
                elif is_minute_marker:
                    segments.append("[dark_orange3]▆[/dark_orange3]")
                else:
                    segments.append("[grey65]─[/grey65]")
            else:
                if is_minute_marker:
                    segments.append("|")
                else:
                    segments.append("-")

        return "".join(segments)

    def _render_waveform(self) -> str:
        """Render a waveform bar based on recent audio levels."""
        now = time.monotonic()
        with self._waveform_lock:
            samples = list(self._waveform_samples)
            last_update = self._waveform_last_update
            previous_levels = self._waveform_last_levels[:]
            slot_count = self._waveform_slot_count
            window = self._waveform_window_seconds

        if not samples or (now - last_update > self._waveform_decay_seconds):
            display = self._default_waveform_display()
            with self._waveform_lock:
                self._latest_waveform = display
                self._waveform_last_levels = [0.0] * self._waveform_slot_count
            return display

        if slot_count <= 0 or window <= 0:
            return self._default_waveform_display()

        window_start = now - window
        slot_duration = window / slot_count
        slot_values = [0.0] * slot_count

        if len(previous_levels) != slot_count:
            previous_levels = [0.0] * slot_count

        for timestamp, level in samples:
            if timestamp < window_start:
                continue
            slot_index = int((timestamp - window_start) / slot_duration)
            if slot_index >= slot_count:
                slot_index = slot_count - 1
            slot_values[slot_index] = max(slot_values[slot_index], level)

        peak_level = max(slot_values) if slot_values else 0.0
        if peak_level <= 1e-6:
            normalised_levels = [0.0] * slot_count
        else:
            normalised_levels = [min(1.0, value / peak_level) for value in slot_values]

        # Apply light smoothing so the bar doesn't jitter excessively
        smoothed_levels = [
            (prev * 0.4) + (current * 0.6)
            for prev, current in zip(previous_levels, normalised_levels)
        ]

        glyphs = "▁▂▃▄▅▆▇█"
        glyph_count = len(glyphs) - 1
        bar_chars: List[str] = []

        for level in smoothed_levels:
            clamped = max(0.0, min(1.0, level))
            glyph_index = min(glyph_count, int(round(clamped * glyph_count)))
            bar_chars.append(glyphs[glyph_index])

        bar = "".join(bar_chars)

        if HAS_RICH and CONSOLE:
            display = f"[#4caf50]{bar}[/#4caf50]"
        else:
            display = bar

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
        with self._waveform_lock:
            if self._waveform_samples and now < self._waveform_samples[-1][0]:
                self._waveform_samples.clear()
            self._waveform_samples.append((now, level))
            cutoff = now - self._waveform_window_seconds
            while self._waveform_samples and self._waveform_samples[0][0] < cutoff:
                self._waveform_samples.popleft()
            self._waveform_last_update = now

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

    def _safe_paste(self):
        """Safely paste using keyboard simulation with platform detection."""
        try:
            from platform_utils import get_platform_manager
            platform_manager = get_platform_manager()

            if platform_manager.is_linux:
                # On Linux, try Ctrl+Shift+V first (works in many terminals)
                # then fall back to Ctrl+V
                try:
                    keyboard.send("ctrl+shift+v")
                except:
                    keyboard.send("ctrl+v")
            else:
                # Windows and macOS
                keyboard.send("ctrl+v")

        except Exception as e:
            if HAS_RICH and CONSOLE:
                CONSOLE.print(f"[yellow]Paste error: {e}[/yellow]")
            else:
                print(f"Paste error: {e}")

    def force_initialize(self):
        """Force initialization of the recorder to preload the model."""
        try:
            return self._initialize_recorder() is not None
        except (ImportError, RuntimeError) as e:
            if HAS_RICH and CONSOLE:
                CONSOLE.print(
                    f"[bold red]Error in force initialization: {str(e)}[/bold red]"
                )
            else:
                print(f"Error in force initialization: {str(e)}")
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
        self._timer_lines_rendered = False
        self._reset_waveform_state()

    def _run_recording_timer(self) -> None:
        """Print elapsed recording time and progress indicators."""
        while not self._timer_stop_event.is_set():
            if not self.recording or self._recording_started_at is None:
                time.sleep(0.1)
                continue

            elapsed = time.monotonic() - self._recording_started_at
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            time_str = f"{minutes:02d},{seconds:02d}"

            progress_bar = self._build_progress_bar(elapsed)
            waveform_display = self._render_waveform()

            if HAS_RICH and CONSOLE:
                timer_line = f"[#ff5722]Recording time: {time_str}[/#ff5722]"
                progress_line = f"[white]Progress:[/white] {progress_bar}"
                waveform_line = f"[white]Waveform:[/white] {waveform_display}"

                if self._timer_lines_rendered:
                    CONSOLE.file.write("\033[3F")
                    for line in (timer_line, progress_line, waveform_line):
                        CONSOLE.file.write("\033[K")
                        CONSOLE.file.flush()
                        CONSOLE.print(line)
                else:
                    for line in (timer_line, progress_line, waveform_line):
                        CONSOLE.print(line)
                    self._timer_lines_rendered = True
                CONSOLE.file.flush()
            else:
                timer_line = f"Recording time: {time_str}"
                progress_line = f"Progress: {progress_bar}"
                waveform_line = f"Waveform: {waveform_display}"

                if self._timer_lines_rendered:
                    sys.stdout.write("\033[3F")
                    for line in (timer_line, progress_line, waveform_line):
                        sys.stdout.write("\033[K")
                        sys.stdout.write(line + "\n")
                    sys.stdout.flush()
                else:
                    for line in (timer_line, progress_line, waveform_line):
                        print(line)
                    self._timer_lines_rendered = True

            time.sleep(0.2)

    def _initialize_recorder(self):
        """Lazy initialization of the recorder."""
        if self.recorder is not None:
            return self.recorder  # Return the recorder if already initialized

        # Create custom recording callbacks that update our internal state
        def on_rec_start():
            self.recording = True
            self._recording_started_at = time.monotonic()
            self._last_recording_duration = 0.0
            self._last_transcription_duration = 0.0
            self._timer_lines_rendered = False
            self._reset_waveform_state()
            self._start_timer_thread()
            if self.external_on_recording_start:
                self.external_on_recording_start()

        def on_rec_stop():
            self.recording = False
            if self._recording_started_at is not None:
                self._last_recording_duration = (
                    time.monotonic() - self._recording_started_at
                )
                self._recording_started_at = None
            self._stop_timer_thread()
            if self.external_on_recording_stop:
                self.external_on_recording_stop()

        # Set the custom callbacks
        self.config["on_recording_start"] = on_rec_start
        self.config["on_recording_stop"] = on_rec_stop
        self.config["on_recorded_chunk"] = self._handle_recorded_chunk

        try:
            if not HAS_REALTIME_STT or AudioToTextRecorder is None:
                raise ImportError("RealtimeSTT not available")

            # If we have a preinitialized model, we would use it here
            # However, RealtimeSTT doesn't directly support passing a model object
            # so we'll still use the model name but log that we're reusing
            if self.preinitialized_model:
                if HAS_RICH and CONSOLE:
                    CONSOLE.print(
                        "[bold green]Using pre-initialized model[/bold green]"
                    )
                else:
                    print("Using pre-initialized model")

            # Initialize the recorder with all parameters
            suppress_ctx = getattr(PLATFORM_MANAGER, "suppress_audio_warnings", None)
            if suppress_ctx:
                with suppress_ctx():
                    self.recorder = AudioToTextRecorder(**self.config)
            else:
                self.recorder = AudioToTextRecorder(**self.config)

            if HAS_RICH and CONSOLE:
                CONSOLE.print(
                    "[bold green]Long-form transcription system initialized.[/bold green]"
                )
            else:
                print("Long-form transcription system initialized.")

            return (
                self.recorder
            )  # Return the recorder if initialization succeeded
        except (ImportError, RuntimeError) as e:
            if HAS_RICH and CONSOLE:
                CONSOLE.print(
                    f"[bold red]Error initializing recorder: {str(e)}[/bold red]"
                )
            else:
                print(f"Error initializing recorder: {str(e)}")
            return None

    def start_recording(self):
        """
        Start recording audio for transcription.
        """
        # Initialize recorder if needed
        self._initialize_recorder()

        if not self.recording and self.recorder:
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[green]Starting recording...[/green]")
            else:
                print("\nStarting recording...")
            self.recorder.start()

    def stop_recording(self):
        """
        Stop recording audio and process the transcription.
        """
        if not self.recorder:
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[yellow]No active recorder to stop.[/yellow]")
            else:
                print("\nNo active recorder to stop.")
            return

        if self.recording:
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[yellow]Stopping recording...[/yellow]")
            else:
                print("\nStopping recording...")

            self._abort_requested = False  # reset flag for this cycle
            self.recorder.stop()
            self._stop_timer_thread()

            transcription = None
            transcription_start = time.monotonic()

            # Display a spinner while transcribing
            if HAS_RICH and CONSOLE:
                with CONSOLE.status("[bold blue]Transcribing...[/bold blue]"):
                    transcription = (
                        None
                        if self._abort_requested
                        else self.recorder.text()
                    )
            else:
                print("Transcribing...")
                transcription = (
                    None
                    if self._abort_requested
                    else self.recorder.text()
                )

            self._last_transcription_duration = (
                time.monotonic() - transcription_start
            )

            # If aborted, skip producing/pasting any text
            if self._abort_requested:
                self.last_transcription = ""
                self._last_transcription_duration = 0.0
                self._last_recording_duration = 0.0
                return

            if self._recording_started_at is not None:
                self._last_recording_duration = (
                    time.monotonic() - self._recording_started_at
                )
                self._recording_started_at = None

            # Ensure transcription is a string
            self.last_transcription = (str(transcription) if transcription else "")

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

            # Copy and Paste the transcription to the active window
            if self.last_transcription and not self._abort_requested:
                if self._safe_clipboard_copy(self.last_transcription):
                    time.sleep(0.1)  # Give some time for the clipboard to update
                    self._safe_paste()
                else:
                    # Fallback: just display the text for manual copying
                    if HAS_RICH and CONSOLE:
                        CONSOLE.print("\n[yellow]Clipboard not available. Please copy manually:[/yellow]")
                        CONSOLE.print(f"[bold]{self.last_transcription}[/bold]")
                    else:
                        print("\nClipboard not available. Please copy manually:")
                        print(f"TEXT: {self.last_transcription}")

            self._print_transcription_metrics()

    def abort(self):
        """Abort current recording or transcription safely without blocking.

        Returns:
            bool: True if abort completed cleanly, False if timed out and a
                  more aggressive shutdown was requested instead.
        """
        self._abort_requested = True
        self.last_transcription = ""
        self._stop_timer_thread()
        self._recording_started_at = None

        rec = self.recorder
        if not rec:
            self.recording = False
            self._abort_requested = False
            return True

        # Run recorder.abort() in a worker thread and wait with a timeout
        import threading

        result = {"ok": False}
        abort_complete = threading.Event()

        def _do_abort():
            try:
                rec.abort()
                result["ok"] = True
            except Exception as e:
                if HAS_RICH and CONSOLE:
                    CONSOLE.print(f"[yellow]Abort error: {e}[/yellow]")
                else:
                    print(f"Abort error: {e}")
            finally:
                abort_complete.set()

        t = threading.Thread(target=_do_abort, daemon=True)
        t.start()

        graceful_wait = 5.0
        check_interval = 0.1
        waited = 0.0

        while waited < graceful_wait and not abort_complete.is_set():
            if not self.recording:
                result["ok"] = True
                abort_complete.set()
                break
            time.sleep(check_interval)
            waited += check_interval

        # Attempt a gentle stop if abort is still running
        if not abort_complete.is_set():
            try:
                if hasattr(rec, "stop"):
                    rec.stop()
            except Exception:
                pass

            extra_wait = 2.0
            while extra_wait > 0 and not abort_complete.is_set():
                time.sleep(check_interval)
                extra_wait -= check_interval

        forced_reset = False

        if not abort_complete.is_set():
            forced_reset = True
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[yellow]Abort still active after grace period; performing forced recorder reset...[/yellow]")
            else:
                print("Abort still active after grace period; performing forced recorder reset...")
            self._force_reset_recorder(rec)
            abort_complete.set()

        # Allow the worker thread to wind down but don't block shutdown
        t.join(timeout=0.2)

        self.recording = False
        self._abort_requested = False

        if forced_reset:
            return False

        return result["ok"]

    def _force_reset_recorder(self, recorder):
        """Forcefully drop the recorder while suppressing noisy shutdown output."""
        if not recorder:
            return

        # Detach immediately so orchestrator can spawn a fresh instance
        self.recorder = None

        cleanup_done = threading.Event()

        def _cleanup():
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    for attr in ("stop", "abort", "shutdown"):
                        method = getattr(recorder, attr, None)
                        if callable(method):
                            try:
                                method()
                            except Exception:
                                pass
            finally:
                buffer.close()
                cleanup_done.set()

        worker = threading.Thread(target=_cleanup, daemon=True)
        worker.start()

        # Allow up to 5 seconds for cleanup; afterwards, abandon the worker
        if not cleanup_done.wait(timeout=5.0):
            if HAS_RICH and CONSOLE:
                CONSOLE.print("[yellow]Recorder cleanup thread still running; continuing anyway.[/yellow]")
            else:
                print("Recorder cleanup thread still running; continuing anyway.")

    def quit(self):
        """
        Stop the transcription process and exit.
        """
        self.running = False
        if self.recording and self.recorder:
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
        if self._abort_requested:
            return

        audio_duration = self._last_recording_duration
        processing_time = self._last_transcription_duration
        speed_ratio = (
            audio_duration / processing_time if processing_time > 0 else 0.0
        )
        realtime_factor = (
            processing_time / audio_duration if audio_duration > 0 else 0.0
        )

        if HAS_RICH and CONSOLE:
            CONSOLE.print("[bold white]Transcription metrics:[/bold white]")
            CONSOLE.print(
                f"[grey58]  Audio duration: {self._format_duration(audio_duration)}[/grey58]"
            )
            CONSOLE.print(
                f"[grey58]  Processing time: {self._format_duration(processing_time)}[/grey58]"
            )
            CONSOLE.print(
                f"[grey58]  Speed ratio: {speed_ratio:.2f}x[/grey58]"
            )
            CONSOLE.print(
                f"[grey58]  Real-time factor: {realtime_factor:.2f}[/grey58]"
            )
        else:
            print("Transcription metrics:")
            print(
                f"  Audio duration: {self._format_duration(audio_duration)}"
            )
            print(
                f"  Processing time: {self._format_duration(processing_time)}"
            )
            print(f"  Speed ratio: {speed_ratio:.2f}x")
            print(f"  Real-time factor: {realtime_factor:.2f}")

        logging.info(
            "Long-form transcription metrics | audio: %.2fs | processing: %.2fs | speed: %.2fx | RTF: %.2f",
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
