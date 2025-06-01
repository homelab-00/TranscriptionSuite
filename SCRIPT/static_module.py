#!/usr/bin/env python3
"""
Static module for transcribing pre-recorded audio/video files.

This module provides functionality to:
- Select audio/video files through a GUI dialog
- Convert various media formats to 16kHz mono WAV using FFmpeg
- Apply Voice Activity Detection to remove silence
- Transcribe using Faster Whisper models
- Save transcription results alongside the original file
- Manage temporary files and resource cleanup
- Support abortion of in-progress transcription
"""

import os
import sys
import threading
import subprocess
import shutil
import wave
import time
import tempfile
import ctypes
from typing import Optional, Callable, Any
from dataclasses import dataclass
import tkinter as tk
from tkinter import filedialog

# Configure logging
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="static_transcription.log",
    filemode="a",
)

# Try to import Rich for prettier console output
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    CONSOLE = Console()
    HAS_RICH = True
    RICH_PANEL = Panel
    RICH_TEXT = Text
except ImportError:
    HAS_RICH = False
    CONSOLE = None
    RICH_PANEL = None
    RICH_TEXT = None

# Try to import required libraries, with graceful fallbacks
try:
    import torch
    from faster_whisper import WhisperModel

    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    torch = None
    WhisperModel = None
    print(
        "Warning: faster-whisper not installed. "
        "Install with: pip install faster-whisper"
    )

try:
    import webrtcvad

    HAS_WEBRTC_VAD = True
except ImportError:
    HAS_WEBRTC_VAD = False
    webrtcvad = None
    print(
        "Warning: webrtcvad not installed. Install with: pip install webrtcvad"
    )


@dataclass
class ModelConfig:
    """Configuration for the Whisper model."""

    name: str = "Systran/faster-whisper-large-v3"
    language: str = "en"
    compute_type: str = "float16"
    device: str = "cuda"
    device_index: int = 0
    download_root: Optional[str] = None
    task: str = "transcribe"


@dataclass
class TranscriptionState:
    """State variables for transcription process."""

    transcribing: bool = False
    abort_requested: bool = False
    transcription_thread: Optional[threading.Thread] = None


@dataclass
class UIConfig:
    """Configuration for UI components."""

    use_tk_mainloop: bool = False
    callback_on_progress: Optional[Callable[[str], None]] = None


@dataclass
class Resources:
    """Resource management for the transcriber."""

    whisper_model: Optional[Any] = None
    root: Optional[tk.Tk] = None
    temp_dir: Optional[str] = None


class DirectFileTranscriber:
    """
    A class that directly transcribes audio and video files using Faster Whisper,
    without relying on the RealtimeSTT library.
    """

    def __init__(
        self,
        use_tk_mainloop: bool = False,
        callback_on_progress: Optional[Callable[[str], None]] = None,
        preinitialized_model: Optional[Any] = None,
        **kwargs: Any,
    ):
        """Initialize the transcriber with basic parameters."""
        # Configuration objects
        self.model_config = ModelConfig(
            name=kwargs.get("model", "Systran/faster-whisper-large-v3"),
            language=kwargs.get("language", "en"),
            compute_type=kwargs.get("compute_type", "float16"),
            device=kwargs.get("device", "cuda"),
            device_index=kwargs.get("device_index", 0),
            download_root=kwargs.get("download_root", None),
            task=kwargs.get("task", "transcribe"),
        )

        self.ui_config = UIConfig(
            use_tk_mainloop=use_tk_mainloop,
            callback_on_progress=callback_on_progress,
        )

        self.resources = Resources()
        self.resources.whisper_model = preinitialized_model

        # State management
        self.state = TranscriptionState()

        # Initialize resources
        self._setup_temp_dir()
        if HAS_WHISPER:
            self._initialize_model()

    def _safe_print(self, message: str, style: str = "default") -> None:
        """Print with Rich if available, otherwise use regular print."""
        if HAS_RICH and CONSOLE is not None:
            if style == "error":
                CONSOLE.print(f"[bold red]{message}[/bold red]")
            elif style == "warning":
                CONSOLE.print(f"[bold yellow]{message}[/bold yellow]")
            elif style == "success":
                CONSOLE.print(f"[bold green]{message}[/bold green]")
            elif style == "info":
                CONSOLE.print(f"[bold blue]{message}[/bold blue]")
            else:
                CONSOLE.print(message)
        else:
            print(message)

    def _setup_temp_dir(self) -> None:
        """Set up the temporary directory for intermediate files."""
        try:
            self.resources.temp_dir = tempfile.mkdtemp(
                prefix="static_transcription_"
            )
            logging.info(
                "Created temporary directory: %s", self.resources.temp_dir
            )
        except (OSError, IOError) as e:
            logging.error("Failed to create temporary directory: %s", e)
            self._safe_print(
                f"Failed to create temporary directory: {e}", "error"
            )
            # Fall back to current directory
            self.resources.temp_dir = os.getcwd()

    def _initialize_model(self) -> bool:
        """Initialize the Whisper model."""
        if self.resources.whisper_model is not None:
            return True

        if not HAS_WHISPER or WhisperModel is None:
            self._safe_print(
                "Faster Whisper not installed. Cannot initialize model.",
                "error",
            )
            return False

        try:
            # If we have a preinitialized model, use it directly
            if self.resources.whisper_model:
                self._safe_print("Using pre-initialized Whisper model", "info")
                return True

            # Otherwise, initialize a new model
            config = self.model_config
            self._safe_print(f"Loading Whisper model: {config.name}...", "info")
            logging.info("Initializing Whisper model: %s", config.name)

            # Determine device and compute type
            device, compute_type = self._get_device_config()

            # Initialize the model
            self.resources.whisper_model = WhisperModel(
                config.name,
                device=device,
                device_index=config.device_index,
                compute_type=compute_type,
                download_root=config.download_root,
            )

            self._safe_print(
                f"Whisper model {config.name} loaded successfully",
                "success",
            )
            logging.info("Model %s initialized successfully", config.name)
            return True

        except (ImportError, RuntimeError, OSError) as e:
            self._safe_print(
                f"Failed to initialize Whisper model: {e}", "error"
            )
            logging.error("Model initialization error: %s", e)
            return False

    def _get_device_config(self) -> tuple[str, str]:
        """Get device and compute type configuration."""
        device = self.model_config.device
        if (
            device == "cuda"
            and torch is not None
            and not torch.cuda.is_available()
        ):
            self._safe_print(
                "CUDA not available, falling back to CPU", "warning"
            )
            device = "cpu"

        compute_type = self.model_config.compute_type
        if device == "cpu" and compute_type == "float16":
            compute_type = "float32"

        return device, compute_type

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files."""
        if self.resources.temp_dir and os.path.exists(self.resources.temp_dir):
            try:
                shutil.rmtree(self.resources.temp_dir)
                logging.info(
                    "Removed temporary directory: %s", self.resources.temp_dir
                )
            except (OSError, IOError) as e:
                logging.error("Failed to remove temp directory: %s", e)
                self._safe_print(
                    f"Warning: Failed to clean up temporary files: {e}",
                    "warning",
                )

    @property
    def transcribing(self) -> bool:
        """Get transcription status."""
        return self.state.transcribing

    @transcribing.setter
    def transcribing(self, value: bool) -> None:
        """Set transcription status."""
        self.state.transcribing = value

    @property
    def abort_requested(self) -> bool:
        """Get abort request status."""
        return self.state.abort_requested

    @abort_requested.setter
    def abort_requested(self, value: bool) -> None:
        """Set abort request status."""
        self.state.abort_requested = value

    @property
    def callback_on_progress(self) -> Optional[Callable[[str], None]]:
        """Get progress callback."""
        return self.ui_config.callback_on_progress

    @property
    def whisper_model(self) -> Optional[Any]:
        """Get Whisper model."""
        return self.resources.whisper_model

    @whisper_model.setter
    def whisper_model(self, value: Optional[Any]) -> None:
        """Set Whisper model."""
        self.resources.whisper_model = value

    @property
    def root(self) -> Optional[tk.Tk]:
        """Get Tkinter root."""
        return self.resources.root

    @root.setter
    def root(self, value: Optional[tk.Tk]) -> None:
        """Set Tkinter root."""
        self.resources.root = value

    @property
    def temp_dir(self) -> Optional[str]:
        """Get temporary directory."""
        return self.resources.temp_dir

    @temp_dir.setter
    def temp_dir(self, value: Optional[str]) -> None:
        """Set temporary directory."""
        self.resources.temp_dir = value

    def select_file(self) -> None:
        """Open a file dialog to select a file for transcription."""
        if self.transcribing:
            self._safe_print(
                "A transcription is already in progress", "warning"
            )
            return

        # Initialize tkinter if not already done
        if not self.root:
            self.root = tk.Tk()
            self.root.withdraw()  # Hide the main window

        # Make sure the root window is properly prepared
        self.root.update()

        # Show the file dialog
        file_path = self._show_file_dialog()

        if file_path:
            # Reset abort flag
            self.abort_requested = False

            # Start transcription in a separate thread
            self.state.transcription_thread = threading.Thread(
                target=self._process_file, args=(file_path,), daemon=True
            )
            self.state.transcription_thread.start()
        else:
            self._safe_print("No file selected", "warning")
            self.transcribing = False

    def _show_file_dialog(self) -> str:
        """Show file selection dialog."""
        return filedialog.askopenfilename(
            title="Select an Audio or Video File",
            filetypes=[
                (
                    "Audio/Video files",
                    "*.mp3;*.wav;*.flac;*.ogg;*.m4a;*.mp4;*.avi;*.mkv;*.mov",
                ),
                ("Audio files", "*.mp3;*.wav;*.flac;*.ogg;*.m4a"),
                ("Video files", "*.mp4;*.avi;*.mkv;*.mov"),
                ("All files", "*.*"),
            ],
            parent=self.root,
        )

    def _ensure_wav_format(self, input_path: str) -> Optional[str]:
        """Convert input file (audio or video) to 16kHz mono WAV."""
        if not os.path.exists(input_path):
            self._safe_print(f"File not found: {input_path}", "error")
            return None

        if self.resources.temp_dir is None:
            self._safe_print("Temporary directory not available", "error")
            return None

        temp_wav = os.path.join(self.resources.temp_dir, "temp_static_file.wav")

        # Check if the file is already a WAV in the correct format
        if self._is_correct_wav_format(input_path, temp_wav):
            return temp_wav

        return self._convert_with_ffmpeg(input_path, temp_wav)

    def _is_correct_wav_format(self, input_path: str, temp_wav: str) -> bool:
        """Check if input is already correct WAV format."""
        try:
            with wave.open(input_path, "rb") as wf:
                channels = wf.getnchannels()
                rate = wf.getframerate()
                if channels == 1 and rate == 16000:
                    self._safe_print(
                        "No conversion needed, copying to temp file", "info"
                    )
                    shutil.copy(input_path, temp_wav)
                    return True
        except wave.Error:
            # Not a valid WAV file, needs conversion
            pass
        except (OSError, IOError) as e:
            logging.warning("File check error: %s. Will try conversion.", e)

        return False

    def _convert_with_ffmpeg(
        self, input_path: str, output_path: str
    ) -> Optional[str]:
        """Convert file using FFmpeg."""
        # Get file extension to determine if it's video or audio
        _, ext = os.path.splitext(input_path)
        ext = ext.lower()

        # Common video extensions
        video_exts = [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"]
        is_video = ext in video_exts

        # Convert using FFmpeg
        if is_video:
            self._safe_print(
                f"Converting video file '{os.path.basename(input_path)}' "
                "to 16kHz mono WAV",
                "info",
            )
        else:
            self._safe_print(
                f"Converting audio file '{os.path.basename(input_path)}' "
                "to 16kHz mono WAV",
                "info",
            )

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",  # Overwrite output file if it exists
                    "-i",
                    input_path,  # Input file
                    "-vn",  # Skip video stream (needed for video files)
                    "-ac",
                    "1",  # Mono
                    "-ar",
                    "16000",  # 16kHz
                    output_path,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self._safe_print("Conversion successful", "success")
            return output_path
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            self._safe_print(f"FFmpeg conversion error: {e}", "error")
            logging.error("FFmpeg conversion error: %s", e)
            return None

    def _apply_vad(self, in_wav_path: str, aggressiveness: int = 2) -> str:
        """Apply Voice Activity Detection to keep only speech frames."""
        if not HAS_WEBRTC_VAD or webrtcvad is None:
            self._safe_print(
                "webrtcvad not installed. Skipping VAD.", "warning"
            )
            return in_wav_path

        if self.resources.temp_dir is None:
            self._safe_print("Temporary directory not available", "error")
            return in_wav_path

        out_wav = os.path.join(
            self.resources.temp_dir, "temp_static_silence_removed.wav"
        )

        try:
            return self._process_vad(in_wav_path, out_wav, aggressiveness)
        except (OSError, IOError, ValueError) as e:
            self._safe_print(f"VAD processing error: {e}", "error")
            logging.error("VAD processing error: %s", e)
            return in_wav_path

    def _process_vad(
        self, in_wav_path: str, out_wav: str, aggressiveness: int
    ) -> str:
        """Process VAD on the audio file."""
        # Read audio parameters
        audio_params = self._read_audio_params(in_wav_path)
        if not audio_params:
            return in_wav_path

        channels, rate, audio_data = audio_params

        # Check if file format is compatible with VAD
        if not self._is_vad_compatible(channels, rate):
            return in_wav_path

        # Initialize VAD and process audio - check webrtcvad availability
        if webrtcvad is None:
            self._safe_print("webrtcvad not available", "error")
            return in_wav_path

        vad = webrtcvad.Vad(aggressiveness)
        voiced_bytes = self._extract_speech_frames(vad, audio_data, rate)

        if not voiced_bytes:
            self._safe_print(
                "VAD found no voice frames. Using original audio.", "warning"
            )
            return in_wav_path

        # Write output file
        self._write_vad_output(out_wav, voiced_bytes, rate)
        return out_wav

    def _read_audio_params(
        self, in_wav_path: str
    ) -> Optional[tuple[int, int, bytes]]:
        """Read audio parameters from WAV file."""
        try:
            with wave.open(in_wav_path, "rb") as wf_in:
                channels = wf_in.getnchannels()
                rate = wf_in.getframerate()
                audio_data = wf_in.readframes(wf_in.getnframes())
                return channels, rate, audio_data
        except (wave.Error, OSError) as e:
            self._safe_print(f"Error reading audio file: {e}", "error")
            return None

    def _is_vad_compatible(self, channels: int, rate: int) -> bool:
        """Check if audio format is compatible with VAD."""
        if channels != 1:
            self._safe_print(
                "VAD requires mono audio. Skipping VAD.", "warning"
            )
            return False

        if rate not in [8000, 16000, 32000, 48000]:
            self._safe_print(
                "VAD requires specific sample rates. Skipping VAD.", "warning"
            )
            return False

        return True

    def _extract_speech_frames(
        self, vad: Any, audio_data: bytes, rate: int
    ) -> bytearray:
        """Extract speech frames using VAD."""
        frame_ms = 30
        frame_bytes = int(rate * 2 * (frame_ms / 1000.0))
        voiced_bytes = bytearray()
        frames_total = len(audio_data) // frame_bytes
        frames_speech = 0

        self._safe_print(
            "Processing audio with Voice Activity Detection...", "info"
        )

        for i in range(0, len(audio_data) - frame_bytes + 1, frame_bytes):
            if self.state.abort_requested:
                self._safe_print("VAD processing aborted by user", "warning")
                return bytearray()

            frame = audio_data[i : i + frame_bytes]
            is_speech = vad.is_speech(frame, rate)
            if is_speech:
                voiced_bytes.extend(frame)
                frames_speech += 1

            # Progress update
            frame_num = i // frame_bytes + 1
            if frame_num % max(1, frames_total // 20) == 0:
                progress = int(100 * frame_num / frames_total)
                self._update_progress(f"VAD processing: {progress}% complete")

        self._safe_print(
            f"VAD processing complete: Retained {frames_speech} voice frames "
            f"out of {frames_total} total frames",
            "success",
        )
        return voiced_bytes

    def _write_vad_output(
        self, out_wav: str, voiced_bytes: bytearray, rate: int
    ) -> None:
        """Write VAD output to file."""
        with wave.open(out_wav, "wb") as wf_out:
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)  # 16-bit
            wf_out.setframerate(rate)
            wf_out.writeframes(voiced_bytes)

    def _update_progress(self, message: str) -> None:
        """Update progress message."""
        logging.info("%s", message)
        self._safe_print(message, "info")
        if self.ui_config.callback_on_progress is not None:
            self.ui_config.callback_on_progress(message)

    def _process_file(self, file_path: str) -> None:
        """Process and transcribe the selected file."""
        try:
            self.transcribing = True
            logging.info("Processing file: %s", file_path)
            self._safe_print(
                f"Processing file: {os.path.basename(file_path)}", "info"
            )

            # Check if model is initialized
            if not self._initialize_model():
                self._safe_print(
                    "Failed to initialize transcription model, aborting",
                    "error",
                )
                return

            # Process the file through conversion and VAD
            processed_wav = self._prepare_audio(file_path)
            if not processed_wav:
                return

            # Transcribe the processed audio
            self._transcribe_audio(processed_wav, file_path)

        except SystemExit:
            self._safe_print(
                "Transcription thread was terminated by user request", "warning"
            )
        except (OSError, IOError, RuntimeError) as e:
            self._safe_print(f"Static transcription failed: {e}", "error")
            logging.error("Static transcription failed: %s", e)

        finally:
            self._cleanup_temp_files()
            self.transcribing = False
            self._safe_print("Transcription process complete", "success")

    def _prepare_audio(self, file_path: str) -> Optional[str]:
        """Prepare audio file for transcription."""
        # Step 1: Convert to WAV format if needed
        self._update_progress("Converting file to WAV format...")
        wav_path = self._ensure_wav_format(file_path)
        if not wav_path or not os.path.exists(wav_path):
            self._safe_print("Failed to convert audio file. Aborting.", "error")
            return None

        # Check abort flag after conversion
        if self.abort_requested:
            self._safe_print(
                "Transcription aborted after conversion", "warning"
            )
            return None

        # Step 2: Apply VAD to remove non-speech sections
        self._update_progress("Applying Voice Activity Detection...")
        voice_wav = self._apply_vad(wav_path, aggressiveness=2)

        # Check abort flag after VAD
        if self.abort_requested:
            self._safe_print("Transcription aborted after VAD", "warning")
            return None

        return voice_wav

    def _transcribe_audio(
        self, voice_wav: str, original_file_path: str
    ) -> None:
        """Transcribe the prepared audio file."""
        if self.resources.whisper_model is None:
            self._safe_print("Whisper model not available", "error")
            return

        # Step 3: Transcribe the processed audio
        self._update_progress("Beginning transcription...")

        # Determine if we should translate or transcribe
        task = self.model_config.task
        if task != "translate" and self.model_config.language not in [
            "en",
            "el",
        ]:
            # If not English or Greek, we likely want to translate to English
            task = "translate"
            self._safe_print(
                f"Language '{self.model_config.language}' - using translation mode",
                "info",
            )
        else:
            self._safe_print(
                f"Language '{self.model_config.language}' - using transcription mode",
                "info",
            )

        try:
            segments, _ = self.resources.whisper_model.transcribe(
                voice_wav,
                language=self.model_config.language,
                task=task,
                beam_size=5,
            )

            # Combine all segments into final text
            final_text = self._process_segments(segments)

            # Check abort flag after transcription
            if self.state.abort_requested:
                self._safe_print(
                    "Transcription completed but results discarded due to abort request",
                    "warning",
                )
                return

            # Display and save results
            self._display_and_save_results(final_text, original_file_path)

        except (RuntimeError, OSError, ValueError) as e:
            self._safe_print(f"Transcription failed: {e}", "error")
            logging.error("Transcription error: %s", e)

    def _process_segments(self, segments: Any) -> str:
        """Process transcription segments into final text."""
        final_text = ""
        segment_count = 0

        for segment in segments:
            # Check for abort
            if self.state.abort_requested:
                self._safe_print(
                    "Transcription aborted during processing", "warning"
                )
                return ""

            final_text += segment.text
            segment_count += 1

            # Update progress every few segments
            if segment_count % 5 == 0:
                self._update_progress(f"Processed {segment_count} segments...")

        return final_text.strip()

    def _display_and_save_results(
        self, final_text: str, file_path: str
    ) -> None:
        """Display and save transcription results."""
        # Display results
        if (
            HAS_RICH
            and CONSOLE is not None
            and RICH_PANEL is not None
            and RICH_TEXT is not None
        ):
            panel = RICH_PANEL(
                RICH_TEXT(final_text, style="bold magenta"),
                title="Static File Transcription",
                border_style="yellow",
            )
            CONSOLE.print(panel)
        else:
            self._safe_print("---- Transcription Result ----", "success")
            self._safe_print(final_text)
            self._safe_print("-----------------------------", "success")

        # Save .txt alongside the original file
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        dir_name = os.path.dirname(file_path)
        out_txt_path = os.path.join(dir_name, base_name + ".txt")

        try:
            with open(out_txt_path, "w", encoding="utf-8") as f:
                f.write(final_text)

            self._safe_print(
                f"Saved transcription to: {out_txt_path}", "success"
            )
        except (OSError, IOError) as e:
            self._safe_print(f"Failed to save transcription: {e}", "error")
            logging.error("Failed to save transcription: %s", e)

    def request_abort(self) -> None:
        """Request abortion of any in-progress transcription."""
        if not self.state.transcribing:
            self._safe_print("No transcription in progress to abort", "warning")
            return

        self._safe_print("Aborting transcription...", "warning")
        self.state.abort_requested = True

        # Try to terminate the thread if it's stuck
        if (
            self.state.transcription_thread
            and self.state.transcription_thread.is_alive()
        ):
            self._terminate_thread()

    def _terminate_thread(self) -> None:
        """Terminate the transcription thread using cross-platform approach."""
        try:
            # Give it a moment to abort gracefully
            time.sleep(0.5)

            # Use threading.Event for graceful shutdown instead of forced termination
            if (
                    self.state.transcription_thread is not None
                    and self.state.transcription_thread.is_alive()
            ):
                # The thread should check self.state.abort_requested regularly
                # and exit on its own. We've already set abort_requested = True
                # So we just wait a bit longer for graceful shutdown
                self.state.transcription_thread.join(timeout=2.0)

                if self.state.transcription_thread.is_alive():
                    logging.warning("Transcription thread did not shutdown gracefully")
                    # Instead of forced termination, we'll let it run
                    # The thread will eventually finish on its own
                else:
                    logging.info("Transcription thread shutdown gracefully")

        except Exception as e:
            logging.error(f"Error during thread shutdown: {e}")

    def cleanup(self) -> None:
        """Clean up resources before exiting."""
        # Request abort if transcription is in progress
        if self.state.transcribing:
            self.request_abort()

        # Clean up temp files
        self._cleanup_temp_files()

        # Clean up Tkinter resources
        if self.resources.root:
            try:
                self.resources.root.destroy()
                self.resources.root = None
            except tk.TclError as e:
                logging.error("Error destroying Tkinter root: %s", e)


# For standalone testing
if __name__ == "__main__":
    transcriber = DirectFileTranscriber()
    transcriber.select_file()

    try:
        # Keep the script running until transcription completes
        while transcriber.transcribing:
            time.sleep(0.1)
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        if transcriber.transcribing:
            print("\nAbort requested. Cleaning up...")
            transcriber.request_abort()
        print("Exiting")
