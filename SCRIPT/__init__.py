"""
SCRIPT package for TranscriptionSuite.

This package contains the core transcription engine components:
- orchestrator: Main application controller
- model_manager: AI model lifecycle management
- recorder: Recording session management
- stt_engine: Speech-to-text engine with VAD
- static_transcriber: File-based transcription
- tray_manager: System tray interface
- console_display: Terminal UI with Rich
- config_manager: Configuration handling
- platform_utils: Cross-platform utilities
- shared: Common utilities and types

Note: This package uses absolute imports. When importing from within
the package, use the full module path:
    from SCRIPT.shared import safe_print
    from SCRIPT.config_manager import ConfigManager
"""

# Re-export commonly used items from shared for convenience
from .shared import (
    safe_print,
    format_timestamp,
    clear_gpu_cache,
    convert_to_wav,
    TranscriptSegment,
    WordSegment,
    DiarizationSegment,
)

__all__ = [
    "safe_print",
    "format_timestamp",
    "clear_gpu_cache",
    "convert_to_wav",
    "TranscriptSegment",
    "WordSegment",
    "DiarizationSegment",
]
