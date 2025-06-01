"""
Real-time speech-to-text transcription module.

This module provides continuous speech-to-text transcription capabilities
using the RealtimeSTT library with voice activity detection and real-time
processing features.
"""

import os
import sys
import io
import logging
import time

# Import RealtimeSTT at module level to avoid import-outside-toplevel warning
try:
    from RealtimeSTT import AudioToTextRecorder

    REALTIME_STT_AVAILABLE = True
except ImportError:
    # Will be handled when needed
    AudioToTextRecorder = None
    REALTIME_STT_AVAILABLE = False

# Import Rich for better terminal display with Unicode support
try:
    from rich.console import Console
    from rich.text import Text  # type: ignore[reportAssignmentType]
    from rich.panel import Panel  # type: ignore[reportAssignmentType]

    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

    # Create a simple console that falls back to print
    class _FallbackConsole:
        """Simple console fallback when Rich is not available."""

        def print(self, *args, **kwargs):
            """Print function that handles Rich objects gracefully."""
            # Handle Rich Text objects and other content
            output = []
            for arg in args:
                if hasattr(arg, "text"):  # Rich Text object
                    output.append(str(arg.text))
                elif hasattr(arg, "content"):  # Rich Panel object
                    output.append(str(arg.content))
                else:
                    output.append(str(arg))
            print(" ".join(output), **kwargs)

        def get_terminal_size(self):
            """Get terminal size for compatibility with Rich."""
            return (80, 24)

    console = _FallbackConsole()

    # Create simple fallback classes
    class Text:
        """Simple fallback for Rich Text objects."""

        def __init__(self, text, style=None):
            self.text = text
            self.style = style

        def __str__(self):
            return self.text

    class Panel:
        """Simple fallback for Rich Panel objects."""

        def __init__(self, content, title=None, border_style=None):
            self.content = content
            self.title = title
            self.border_style = border_style

        def __str__(self):
            if self.title:
                return f"{self.title}\n{'-' * 30}\n{self.content}\n{'-' * 30}"
            return f"{'-' * 30}\n{self.content}\n{'-' * 30}"


# Import platform utilities for cross-platform compatibility
from platform_utils import ensure_platform_init

# Initialize platform-specific settings (console encoding, PyTorch audio, etc.)
ensure_platform_init()


class LongFormTranscriber:
    """
    A class that provides continuous speech-to-text transcription,
    appending new transcriptions to create a flowing document.
    """

    def __init__(self, **config_params):
        """Initialize the transcriber with configuration parameters."""
        self.text_buffer = ""
        self.running = False

        # Set default configuration
        self.config = self._get_default_config()

        # Update with provided parameters
        self.config.update(config_params)

        # Store preinitialized model if provided
        self.preinitialized_model = self.config.get("preinitialized_model")

        # Lazy-loaded recorder
        self.recorder = None

        # Flag to track if the transcription model is initialized
        self.model_initialized = False

    def _get_default_config(self):
        """Get default configuration parameters."""
        return {
            # General Parameters
            "model": "Systran/faster-whisper-large-v3",
            "download_root": None,
            "language": "en",
            "compute_type": "default",
            "input_device_index": None,
            "gpu_device_index": 0,
            "device": "cuda",
            "on_recording_start": None,
            "on_recording_stop": None,
            "on_transcription_start": None,
            "ensure_sentence_starting_uppercase": True,
            "ensure_sentence_ends_with_period": True,
            "use_microphone": True,
            "spinner": False,
            "level": logging.WARNING,
            "batch_size": 16,
            # Voice Activation Parameters
            "silero_sensitivity": 0.4,
            "silero_use_onnx": False,
            "silero_deactivity_detection": False,
            "webrtc_sensitivity": 3,
            "post_speech_silence_duration": 0.6,
            "min_length_of_recording": 0.5,
            "min_gap_between_recordings": 0,
            "pre_recording_buffer_duration": 1.0,
            "on_vad_detect_start": None,
            "on_vad_detect_stop": None,
            # Advanced Parameters
            "debug_mode": False,
            "handle_buffer_overflow": True,
            "beam_size": 5,
            "buffer_size": 512,
            "sample_rate": 16000,
            "initial_prompt": None,
            "suppress_tokens": [-1],
            "print_transcription_time": False,
            "early_transcription_on_silence": 0,
            "allowed_latency_limit": 100,
            "no_log_file": True,
            "use_extended_logging": False,
            # Realtime specific parameters
            "enable_realtime_transcription": True,
            "realtime_processing_pause": 0.05,
            "on_realtime_transcription_update": self._handle_realtime_update,
        }

    def _get_valid_recorder_config(self):
        """Get configuration parameters valid for AudioToTextRecorder."""
        # Remove parameters that are not valid for AudioToTextRecorder
        invalid_params = {
            "_beam_size_realtime",
            "_enable_realtime_transcription",
            "_realtime_processing_pause",
            "_realtime_model_type",
            "_realtime_batch_size",
            "preinitialized_model",
            "_preload_model",
        }

        return {k: v for k, v in self.config.items() if k not in invalid_params}

    def _initialize_recorder(self):
        """Lazy initialization of the recorder."""
        if self.recorder is not None:
            return self.recorder  # Return the recorder if already initialized

        if not REALTIME_STT_AVAILABLE or AudioToTextRecorder is None:
            self._print_message(
                "RealtimeSTT library is not available. Please install it.",
                style="bold red",
            )
            return None

        # Get valid configuration parameters
        valid_config = self._get_valid_recorder_config()

        # Force disable real-time preview functionality
        valid_config["enable_realtime_transcription"] = False

        # No callbacks needed since we don't want to print anything
        # Remove the previous callbacks completely
        valid_config["on_recording_start"] = None
        valid_config["on_recording_stop"] = None

        try:
            # If we have a preinitialized model, we would use it here
            # Log that we're reusing a model
            if self.preinitialized_model:
                self._print_message(
                    "Using pre-initialized model", style="bold green"
                )

            # Initialize the recorder with valid parameters only
            self.recorder = AudioToTextRecorder(**valid_config)

            self._print_message(
                "Real-time transcription system initialized.",
                style="bold green",
            )

            return self.recorder
        except (ImportError, ValueError, OSError) as e:
            self._print_message(
                f"Error initializing recorder: {str(e)}", style="bold red"
            )
            return None

    def _print_message(self, message, style=None):
        """Helper method to print messages with or without Rich."""
        if HAS_RICH and style:
            console.print(f"[{style}]{message}[/{style}]")
        else:
            console.print(message)

    def _handle_realtime_update(self, text):
        """Handler for real-time transcription updates."""
        # Silently receive updates but don't display them
        # This prevents partial transcripts from being shown

    def process_speech(self, text):
        """
        Process the transcribed speech and display it cleanly.
        """
        if text is None or not text.strip():
            return

        # Display the complete transcription
        if HAS_RICH:
            console.print(Text(text, style="bold cyan"))
        else:
            print(text)

    def start(self):
        """
        Start the continuous transcription process.
        """
        if not self._initialize_recorder():
            self._print_message(
                "Failed to initialize the recorder. Cannot start transcription.",
                style="bold red",
            )
            return

        self.running = True
        self._print_message(
            "Real-time transcription active", style="bold green"
        )

        try:
            while self.running:
                self._process_transcription_loop()
        except KeyboardInterrupt:
            # Handle graceful exit on Ctrl+C
            self._print_message(
                "\nStopping speech recognition...", style="bold red"
            )
        finally:
            self.stop()

    def _process_transcription_loop(self):
        """Process a single iteration of the transcription loop."""
        try:
            # Listen for speech and transcribe it
            if self.recorder is None:
                return

            text_result = self.recorder.text()
            if text_result:
                self.process_speech(text_result)
        except ValueError as e:
            self._handle_transcription_error(e)
        except OSError as e:
            self._handle_transcription_error(e)
        except RuntimeError as e:
            self._handle_transcription_error(e)

    def _handle_transcription_error(self, error):
        """Handle transcription errors."""
        self._print_message(
            f"Error during transcription: {str(error)}", style="bold red"
        )
        time.sleep(0.1)  # Brief pause before retrying

    def stop(self):
        """
        Stop the transcription process and clean up resources.
        """
        self.running = False

        if self.recorder:
            try:
                self.recorder.abort()  # Abort any ongoing recording/transcription
                self.recorder.shutdown()
            except (ValueError, OSError, RuntimeError) as e:
                self._print_message(
                    f"Error during shutdown: {str(e)}", style="bold red"
                )
            self.recorder = None

        # Print a clear footer for the transcription block
        if HAS_RICH:
            console.print(
                Panel(
                    "Transcription has been stopped",
                    title="Real-time Transcription Ended",
                    border_style="yellow",
                )
            )
        else:
            print("\n===== REAL-TIME TRANSCRIPTION ENDED =====\n")

    def get_transcribed_text(self):
        """
        Return the current transcribed text buffer.
        """
        return self.text_buffer


def main():
    """
    Main function to run the transcriber as a standalone script.
    """
    transcriber = LongFormTranscriber()
    transcriber.start()
    return transcriber.get_transcribed_text()


if __name__ == "__main__":
    main()
