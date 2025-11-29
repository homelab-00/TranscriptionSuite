#!/usr/bin/env python3
"""
General-purpose helper functions for TranscriptionSuite.
"""

import logging
from typing import Any

from platform_utils import HAS_RICH, get_rich_console

# Get the Rich console from platform_utils
CONSOLE = get_rich_console()


def safe_print(message: Any, style: str = "default"):
    """
    Prints messages safely (ignores I/O errors on closed files)
    and with optional styling via the Rich library.
    """
    try:
        if HAS_RICH and CONSOLE:
            style_map = {
                "error": "bold red",
                "warning": "bold yellow",
                "success": "bold green",
                "info": "bold blue",
            }
            if style in style_map and isinstance(message, str):
                CONSOLE.print(f"[{style_map[style]}]{message}[/]")
            else:
                CONSOLE.print(message)
        else:
            print(message)
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            pass  # Silently ignore closed file errors
        else:
            # For other ValueErrors, log them
            logging.error("Error in safe_print: %s", e)


def format_timestamp(seconds: float) -> str:
    """
    Convert seconds to a formatted timestamp string (HH:MM:SS.mmm).

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
