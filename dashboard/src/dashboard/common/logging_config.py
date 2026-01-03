"""
Unified logging configuration for TranscriptionSuite client and dashboard.

This module provides a centralized logging setup that can be used by both
the main client process and the GNOME dashboard subprocess.
"""

import logging
import sys
from pathlib import Path

from dashboard.common.config import get_config_dir


# Shared log file name for unified logging
LOG_FILENAME = "dashboard.log"


def get_log_file() -> Path:
    """Get platform-specific log file path."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / LOG_FILENAME


def setup_logging(
    verbose: bool = False,
    component: str = "client",
    wipe_on_startup: bool = True,
) -> logging.Logger:
    """
    Set up unified logging configuration with file and console handlers.

    Args:
        verbose: Enable verbose debug logging
        component: Component name for log messages (e.g., "client", "dashboard")
        wipe_on_startup: Whether to wipe the log file on startup (only for first caller)

    Returns:
        Logger instance for the component
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Create formatters
    verbose_formatter = logging.Formatter(
        f"%(asctime)s - [{component}] %(name)s - %(levelname)s - "
        f"[%(filename)s:%(lineno)d] - %(message)s"
    )
    console_formatter = logging.Formatter(
        f"%(asctime)s - [{component}] %(name)s - %(levelname)s - %(message)s"
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Check if file handler already exists to avoid duplicates
    has_file_handler = any(
        isinstance(h, logging.FileHandler) for h in root_logger.handlers
    )

    # Clear existing handlers only if we're the first setup
    if not has_file_handler:
        root_logger.handlers.clear()

    # Console handler (always add if not present)
    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stdout
        for h in root_logger.handlers
    )
    if not has_console_handler:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # File handler (shared log file)
    if not has_file_handler:
        try:
            log_file = get_log_file()

            # Wipe log file on startup for clean logs each session
            # Only the first caller should wipe
            if wipe_on_startup and log_file.exists():
                log_file.unlink()

            # Simple file handler
            file_handler = logging.FileHandler(
                log_file,
                mode="a",  # Append mode for shared logging
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
            file_handler.setFormatter(verbose_formatter)
            root_logger.addHandler(file_handler)

            print(f"Logs written to: {log_file}")

        except Exception as e:
            print(f"Warning: Could not set up file logging: {e}")

    # Set up verbose logging for key modules
    if verbose:
        logging.getLogger("aiohttp").setLevel(logging.DEBUG)
        logging.getLogger("aiohttp.client").setLevel(logging.DEBUG)

        logger = logging.getLogger(component)
        logger.info("=" * 60)
        logger.info("VERBOSE MODE ENABLED - Detailed connection diagnostics active")
        logger.info("=" * 60)

    return logging.getLogger(component)


def get_component_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific component.

    This is a convenience wrapper around logging.getLogger() that ensures
    the logging is properly configured.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
