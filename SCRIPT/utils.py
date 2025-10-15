#!/usr/bin/env python3
"""
General-purpose helper functions for TranscriptionSuite.
"""

import logging
from typing import Any

# Attempt to import Rich for enhanced console output
try:
    from rich.console import Console

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    CONSOLE = None


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
