"""
Audio processing utilities for TranscriptionSuite server.

Provides common audio operations:
- Format conversion using FFmpeg
- Audio normalization
- Sample rate conversion
- GPU memory management
"""

import gc
import logging
import os
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    HAS_TORCH = False

try:
    import soundfile as sf

    HAS_SOUNDFILE = True
except ImportError:
    sf = None  # type: ignore
    HAS_SOUNDFILE = False

try:
    # Suppress pkg_resources deprecation warning from webrtcvad
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
        import webrtcvad

    HAS_WEBRTCVAD = True
except ImportError:
    webrtcvad = None  # type: ignore
    HAS_WEBRTCVAD = False


def clear_gpu_cache() -> None:
    """
    Clear GPU cache and run garbage collection.

    Use this after unloading models to free GPU memory.
    """
    try:
        gc.collect()
        gc.collect()

        if HAS_TORCH and torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            logger.debug("GPU cache cleared")
    except Exception as e:
        logger.debug(f"Could not clear GPU cache: {e}")


def check_cuda_available() -> bool:
    """Check if CUDA is available for GPU acceleration."""
    if not HAS_TORCH or torch is None:
        return False
    return torch.cuda.is_available()


def get_gpu_memory_info() -> dict:
    """Get GPU memory usage information."""
    if not check_cuda_available():
        return {"available": False}

    try:
        allocated = torch.cuda.memory_allocated() / (1024**3)  # GB
        reserved = torch.cuda.memory_reserved() / (1024**3)  # GB
        total = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB

        return {
            "available": True,
            "allocated_gb": round(allocated, 2),
            "reserved_gb": round(reserved, 2),
            "total_gb": round(total, 2),
            "free_gb": round(total - reserved, 2),
        }
    except Exception as e:
        logger.error(f"Error getting GPU memory info: {e}")
        return {"available": True, "error": str(e)}


def convert_to_wav(
    input_path: str,
    output_path: Optional[str] = None,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Optional[str]:
    """
    Convert any media file to a WAV file using FFmpeg.

    Args:
        input_path: Path to the input audio/video file
        output_path: Path for the output WAV file (auto-generated if None)
        sample_rate: Target sample rate (default 16000 for Whisper)
        channels: Number of audio channels (default 1 for mono)

    Returns:
        Path to the converted WAV file, or None if conversion failed
    """
    if not shutil.which("ffmpeg"):
        logger.error("FFmpeg executable not found")
        raise RuntimeError("ffmpeg is not installed or not in PATH")

    if output_path is None:
        output_path = tempfile.mkstemp(suffix=".wav")[1]

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                input_path,
                "-y",  # Overwrite output file
                "-vn",  # No video
                "-ac",
                str(channels),
                "-ar",
                str(sample_rate),
                "-acodec",
                "pcm_s16le",
                output_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info(f"Converted {input_path} to WAV")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed: {e.stderr}")
        raise RuntimeError(f"Audio conversion failed: {e.stderr}")


def convert_to_mp3(
    input_path: str,
    output_path: Optional[str] = None,
    bitrate: str = "192k",
) -> Optional[str]:
    """
    Convert any audio file to MP3 format using FFmpeg.

    Args:
        input_path: Path to the input audio file
        output_path: Path for the output MP3 file (auto-generated if None)
        bitrate: MP3 bitrate (default 192k for good quality/size balance)

    Returns:
        Path to the converted MP3 file, or None if conversion failed
    """
    if not shutil.which("ffmpeg"):
        logger.error("FFmpeg executable not found")
        raise RuntimeError("ffmpeg is not installed or not in PATH")

    if output_path is None:
        output_path = tempfile.mkstemp(suffix=".mp3")[1]

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                input_path,
                "-y",  # Overwrite output file
                "-vn",  # No video
                "-acodec",
                "libmp3lame",
                "-b:a",
                bitrate,
                output_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info(f"Converted {input_path} to MP3")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg MP3 conversion failed: {e.stderr}")
        raise RuntimeError(f"MP3 conversion failed: {e.stderr}")


def load_audio(
    file_path: str,
    target_sample_rate: int = 16000,
) -> Tuple[np.ndarray, int]:
    """
    Load an audio file and return as numpy array.

    Args:
        file_path: Path to audio file
        target_sample_rate: Target sample rate for resampling

    Returns:
        Tuple of (audio_data as float32 array, sample_rate)
    """
    if not HAS_SOUNDFILE or sf is None:
        raise ImportError("soundfile library is required for audio loading")

    path = Path(file_path)
    temp_wav = None

    try:
        # If not a WAV file, convert first
        if path.suffix.lower() not in [".wav", ".wave"]:
            temp_wav = convert_to_wav(str(path), sample_rate=target_sample_rate)
            if temp_wav is None:
                raise RuntimeError(f"Could not convert {path} to WAV")
            file_path = temp_wav

        # Load audio
        audio_data, sample_rate = sf.read(file_path, dtype="float32")

        # Handle stereo by averaging channels
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)

        # Resample if needed
        if sample_rate != target_sample_rate:
            from scipy import signal

            num_samples = int(len(audio_data) * target_sample_rate / sample_rate)
            audio_data = signal.resample(audio_data, num_samples)
            sample_rate = target_sample_rate

        return audio_data.astype(np.float32), sample_rate

    finally:
        # Clean up temporary file
        if temp_wav and os.path.exists(temp_wav):
            os.unlink(temp_wav)


def normalize_audio(audio: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    """
    Normalize audio to a target dB level.

    Args:
        audio: Audio data as numpy array
        target_db: Target level in dB (default -3.0)

    Returns:
        Normalized audio array
    """
    if audio.size == 0:
        return audio

    # Calculate current peak
    peak = np.max(np.abs(audio))
    if peak == 0:
        return audio

    # Target amplitude (convert from dB)
    target_amplitude = 10 ** (target_db / 20)

    # Normalize
    return (audio / peak) * target_amplitude


def get_audio_duration(file_path: str) -> float:
    """
    Get the duration of an audio file in seconds.

    Args:
        file_path: Path to audio file

    Returns:
        Duration in seconds
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.error(f"Could not get duration for {file_path}: {e}")
        return 0.0


def format_timestamp(seconds: float) -> str:
    """
    Convert seconds to formatted timestamp (HH:MM:SS.mmm).

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def apply_webrtc_vad(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    aggressiveness: int = 3,
) -> np.ndarray:
    """
    Apply WebRTC VAD preprocessing to remove silence from audio.

    This is Stage 1 of two-stage VAD: physically removes silence before
    transcription. Stage 2 is faster_whisper_vad_filter during transcription.

    Args:
        audio_data: Audio samples as float32 numpy array (16kHz, mono)
        sample_rate: Sample rate (must be 16000 for WebRTC VAD)
        aggressiveness: VAD aggressiveness level (0-3, higher = more aggressive)

    Returns:
        Audio with silence removed as float32 numpy array
    """
    if not HAS_WEBRTCVAD or webrtcvad is None:
        logger.debug("webrtcvad not installed, skipping VAD preprocessing")
        return audio_data

    if len(audio_data) == 0:
        return audio_data

    original_duration = len(audio_data) / sample_rate

    try:
        vad = webrtcvad.Vad(aggressiveness)

        # Convert float32 [-1, 1] to int16 PCM for WebRTC VAD
        audio_int16 = (audio_data * 32767).astype(np.int16)

        # Process 30ms frames (480 samples at 16kHz)
        frame_duration_ms = 30
        frame_size = int(sample_rate * frame_duration_ms / 1000)

        voiced_frames = []
        for i in range(0, len(audio_int16) - frame_size + 1, frame_size):
            frame = audio_int16[i : i + frame_size]
            frame_bytes = frame.tobytes()

            try:
                if vad.is_speech(frame_bytes, sample_rate):
                    voiced_frames.append(frame)
            except Exception:
                # Frame processing error, keep the frame
                voiced_frames.append(frame)

        if not voiced_frames:
            logger.warning("WebRTC VAD found no speech, returning original audio")
            return audio_data

        # Concatenate voiced frames and convert back to float32
        voiced_audio_int16 = np.concatenate(voiced_frames)
        voiced_audio = voiced_audio_int16.astype(np.float32) / 32767.0

        new_duration = len(voiced_audio) / sample_rate
        removed_duration = original_duration - new_duration

        if removed_duration > 0.1:  # Only log if significant silence removed
            logger.info(
                f"VAD preprocessing: removed {removed_duration:.1f}s of silence "
                f"({original_duration:.1f}s -> {new_duration:.1f}s)"
            )

        return voiced_audio

    except Exception as e:
        logger.warning(f"WebRTC VAD preprocessing failed: {e}, using original audio")
        return audio_data
