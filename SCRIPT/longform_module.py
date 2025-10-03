"""
Long-form speech transcription module using RealtimeSTT.

This module provides a LongFormTranscriber class for manual control over
speech recording and transcription with keyboard shortcuts and clipboard integration.
"""

import contextlib
import io
import logging
import os
import sys
import threading
import time
from typing import Callable, Iterable, List, Optional, Union

import keyboard
import pyperclip

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

    def _initialize_recorder(self):
        """Lazy initialization of the recorder."""
        if self.recorder is not None:
            return self.recorder  # Return the recorder if already initialized

        # Create custom recording callbacks that update our internal state
        def on_rec_start():
            self.recording = True
            if self.external_on_recording_start:
                self.external_on_recording_start()

        def on_rec_stop():
            self.recording = False
            if self.external_on_recording_stop:
                self.external_on_recording_stop()

        # Set the custom callbacks
        self.config["on_recording_start"] = on_rec_start
        self.config["on_recording_stop"] = on_rec_stop

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
                CONSOLE.print("[bold green]Starting recording...[/bold green]")
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
                CONSOLE.print(
                    "[bold yellow]Stopping recording...[/bold yellow]"
                )
            else:
                print("\nStopping recording...")

            self._abort_requested = False  # reset flag for this cycle
            self.recorder.stop()

            # Display a spinner while transcribing
            if HAS_RICH and CONSOLE:
                with CONSOLE.status("[bold blue]Transcribing...[/bold blue]"):
                    transcription = None if self._abort_requested else self.recorder.text()
            else:
                print("Transcribing...")
                transcription = None if self._abort_requested else self.recorder.text()

            # If aborted, skip producing/pasting any text
            if self._abort_requested:
                self.last_transcription = ""
                return

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

    def abort(self):
        """Abort current recording or transcription safely without blocking.

        Returns:
            bool: True if abort completed cleanly, False if timed out and a
                  more aggressive shutdown was requested instead.
        """
        self._abort_requested = True
        self.last_transcription = ""

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


def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = LongFormTranscriber()
    transcriber.run()
    return transcriber.get_last_transcription()


if __name__ == "__main__":
    main()
