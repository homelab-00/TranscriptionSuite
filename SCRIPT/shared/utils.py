#!/usr/bin/env python3
"""
Shared utility functions for TranscriptionSuite.

Provides common functionality used across all modules:
- Console output with optional Rich formatting
- GPU memory management
- Time formatting
- Audio conversion
"""

import gc
import logging
import os
import shutil
import subprocess
from typing import Any, Optional

# Try to import Rich for console output
try:
    from rich.console import Console as RichConsole

    _CONSOLE = RichConsole()
    HAS_RICH = True
except ImportError:
    _CONSOLE = None
    HAS_RICH = False

# Try to import torch for GPU operations
try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False


def safe_print(message: Any, style: str = "default") -> None:
    """
    Print messages safely with optional Rich styling.

    Handles I/O errors on closed files gracefully.

    Args:
        message: The message to print
        style: Style hint - one of "error", "warning", "success", "info", or "default"
    """
    try:
        if HAS_RICH and _CONSOLE:
            style_map = {
                "error": "bold red",
                "warning": "bold yellow",
                "success": "bold green",
                "info": "bold blue",
            }
            if style in style_map and isinstance(message, str):
                _CONSOLE.print(f"[{style_map[style]}]{message}[/]")
            else:
                _CONSOLE.print(message)
        else:
            print(message)
    except ValueError as e:
        if "I/O operation on closed file" not in str(e):
            logging.error("Error in safe_print: %s", e)
    except Exception as e:
        logging.error("Error in safe_print: %s", e)


def format_timestamp(seconds: float) -> str:
    """
    Convert seconds to a formatted timestamp string (HH:MM:SS.mmm).

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string like "00:01:23.456"
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def clear_gpu_cache() -> None:
    """
    Clear GPU cache and run garbage collection.

    This function:
    1. Runs Python garbage collection twice
    2. Empties CUDA cache if available
    3. Synchronizes CUDA operations

    Use this after unloading models to free GPU memory.
    """
    try:
        gc.collect()
        gc.collect()

        if HAS_TORCH and torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            logging.debug("GPU cache cleared")
    except Exception as e:
        logging.debug(f"Could not clear GPU cache: {e}")


def convert_to_wav(
    input_path: str,
    output_path: Optional[str] = None,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Optional[str]:
    """
    Convert any media file to a 16kHz mono WAV file using FFmpeg.

    Args:
        input_path: Path to the input audio/video file
        output_path: Path for the output WAV file (auto-generated if None)
        sample_rate: Target sample rate (default 16000 for Whisper)
        channels: Number of audio channels (default 1 for mono)

    Returns:
        Path to the converted WAV file, or None if conversion failed
    """
    if not shutil.which("ffmpeg"):
        safe_print(
            "Error: `ffmpeg` is not installed or not in your PATH. Cannot process file.",
            "error",
        )
        logging.error("FFmpeg executable not found.")
        return None

    if output_path is None:
        import tempfile

        fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

    safe_print("Converting file to 16kHz mono WAV for processing...", "info")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                input_path,
                "-y",  # Overwrite output file if it exists
                "-vn",  # No video
                "-ac",
                str(channels),  # Mono channel
                "-ar",
                str(sample_rate),  # Sample rate
                "-acodec",
                "pcm_s16le",  # Standard WAV format
                output_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        logging.info(f"FFmpeg conversion successful for {input_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        safe_print(f"FFmpeg conversion failed. Error: {e.stderr}", "error")
        logging.error(f"FFmpeg error for {input_path}:\n{e.stderr}")
        return None
