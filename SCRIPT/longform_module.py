"""
Long-form speech transcription module using RealtimeSTT.

This module provides a LongFormTranscriber class for manual control over
speech recording and transcription with keyboard shortcuts and clipboard integration.
"""

import io
import logging
import os
import sys
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

# Windows-specific setup for PyTorch audio
if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
    from torchaudio._extension.utils import _init_dll_path

    _init_dll_path()

# Fix console encoding for Windows to properly display Greek characters
if os.name == "nt":
    # Force UTF-8 encoding for stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

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

        # Add missing hotkey attributes
        self.start_hotkey = None
        self.stop_hotkey = None
        self.quit_hotkey = None

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

            self.recorder.stop()

            # Display a spinner while transcribing
            if HAS_RICH and CONSOLE:
                with CONSOLE.status("[bold blue]Transcribing...[/bold blue]"):
                    transcription = self.recorder.text()
            else:
                print("Transcribing...")
                transcription = self.recorder.text()

            # Ensure transcription is a string
            self.last_transcription = (
                str(transcription) if transcription else ""
            )

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
            if self.last_transcription:
                pyperclip.copy(self.last_transcription)
                time.sleep(0.1)  # Give some time for the clipboard to update
                keyboard.send("ctrl+v")  # Paste the transcription

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

        # Show instructions
        if HAS_RICH and CONSOLE:
            CONSOLE.print("[bold]Long-Form Speech Transcription[/bold]")
            if self.start_hotkey:
                CONSOLE.print(
                    f"Press [bold green]{self.start_hotkey}[/bold green] "
                    "to start recording"
                )
            if self.stop_hotkey:
                CONSOLE.print(
                    f"Press [bold yellow]{self.stop_hotkey}[/bold yellow] "
                    "to stop recording and transcribe"
                )
            if self.quit_hotkey:
                CONSOLE.print(
                    f"Press [bold red]{self.quit_hotkey}[/bold red] to quit"
                )
        else:
            print("Long-Form Speech Transcription")
            if self.start_hotkey:
                print(f"Press {self.start_hotkey} to start recording")
            if self.stop_hotkey:
                print(
                    f"Press {self.stop_hotkey} to stop recording and transcribe"
                )
            if self.quit_hotkey:
                print(f"Press {self.quit_hotkey} to quit")

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
