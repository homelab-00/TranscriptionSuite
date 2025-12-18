#!/usr/bin/env python3
"""
General-purpose helper functions for TranscriptionSuite.

NOTE: This module re-exports utilities from MAIN.shared for backward
compatibility. New code should import directly from MAIN.shared.
"""

# Re-export everything from shared.utils for backward compatibility
from .shared.utils import (
    safe_print,
    format_timestamp,
    clear_gpu_cache,
    convert_to_wav,
    HAS_RICH,
    HAS_TORCH,
)
