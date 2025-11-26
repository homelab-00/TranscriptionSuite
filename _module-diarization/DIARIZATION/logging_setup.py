#!/usr/bin/env python3
"""
Logging setup for the diarization module.

Configures application-wide logging with both file and console output.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """
    Set up logging configuration for the diarization module.

    Args:
        config: Configuration dictionary with logging settings
    """
    # Default logging configuration
    default_level = logging.INFO
    default_log_file = "diarization.log"
    console_output = True

    # Override with config if provided
    if config and "logging" in config:
        log_config = config["logging"]
        level_str = log_config.get("level", "INFO").upper()
        default_level = getattr(logging, level_str, logging.INFO)
        default_log_file = log_config.get("log_file", default_log_file)
        console_output = log_config.get("console_output", True)

    # Create log directory if needed
    if default_log_file:
        log_path = Path(default_log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    simple_formatter = logging.Formatter("%(levelname)s - %(message)s")

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(default_level)

    # Remove existing handlers
    root_logger.handlers = []

    # Add file handler
    if default_log_file:
        file_handler = logging.FileHandler(default_log_file, encoding="utf-8")
        file_handler.setLevel(default_level)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)

    # Add console handler if enabled (use stderr to keep stdout clean for JSON output)
    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(default_level)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)

    # Set specific loggers to WARNING to reduce noise
    logging.getLogger("pyannote").setLevel(logging.WARNING)
    logging.getLogger("torch").setLevel(logging.WARNING)
    logging.getLogger("torchaudio").setLevel(logging.WARNING)

    logging.info("Logging initialized for diarization module")
