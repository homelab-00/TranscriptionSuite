"""
Shared utilities and types for TranscriptionSuite.

This module provides common functionality used across the SCRIPT, DIARIZATION,
and AUDIO_NOTEBOOK packages, including:
- Console output utilities (safe_print)
- GPU memory management (clear_gpu_cache)
- Time formatting utilities
- Audio conversion utilities
- Shared data types for transcription segments

Usage:
    from SCRIPT.shared import safe_print, clear_gpu_cache, format_timestamp
    from SCRIPT.shared.types import TranscriptSegment, WordSegment
"""

from .utils import (
    safe_print,
    format_timestamp,
    clear_gpu_cache,
    convert_to_wav,
)

from .types import (
    TranscriptSegment,
    WordSegment,
    DiarizationSegment,
)

__all__ = [
    # Console/Output utilities
    "safe_print",
    "format_timestamp",
    # GPU utilities
    "clear_gpu_cache",
    # Audio utilities
    "convert_to_wav",
    # Types
    "TranscriptSegment",
    "WordSegment",
    "DiarizationSegment",
]
