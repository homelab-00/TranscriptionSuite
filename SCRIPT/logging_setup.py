#!/usr/bin/env python3
"""
System utility functions for the Speech-to-Text system.

This module:
- Sets up application-wide logging.
"""

import os

try:
    import yaml
except ImportError:
    # This is a fallback for the initial pre-config logging setup.
    # The main application will raise a clearer error.
    yaml = None
import logging
from pathlib import Path
from logging import FileHandler
from typing import Dict, Any


class ContextFilter(logging.Filter):
    """A logging filter to add a contextual prefix to log records."""

    def __init__(self, prefix: str):
        super().__init__()
        self.prefix = prefix

    def filter(self, record):
        record.prefix = self.prefix if hasattr(self, "prefix") else ""
        return True


_LOGGING_CONFIGURED = False


def setup_logging(config: Dict[str, Any] | None = None) -> logging.Logger:
    """Initialize application logging once using absolute paths."""

    global _LOGGING_CONFIGURED

    root_logger = logging.getLogger()
    if _LOGGING_CONFIGURED or root_logger.handlers:
        return root_logger

    script_dir = Path(__file__).resolve().parent

    logging_defaults: Dict[str, Any] = {
        "level": "INFO",
        "console_output": False,
        "file_name": "stt_orchestrator.log",
        "directory": str(script_dir.parent),  # Default to the project root
    }

    resolved_config: Dict[str, Any] = logging_defaults.copy()

    if config is None:
        # Try to find a yaml config for early setup
        config_path = script_dir / "config.yaml"
        if yaml and config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as config_file:
                    loaded_config = yaml.safe_load(config_file)
                if loaded_config and "logging" in loaded_config:
                    resolved_config.update(loaded_config["logging"])
            except (yaml.YAMLError, OSError):
                pass
    else:
        resolved_config.update(config.get("logging", {}))

    raw_directory = str(resolved_config.get("directory", script_dir))
    expanded_directory = os.path.expanduser(os.path.expandvars(raw_directory))
    log_dir = Path(expanded_directory).expanduser()
    if not log_dir.is_absolute():
        log_dir = (Path(script_dir) / log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / resolved_config.get("file_name", "stt_orchestrator.log")
    realtimestt_log_path = log_dir / "realtimestt.log"

    # Clean up the RealtimeSTT log from the previous session.
    # Our own log will be overwritten automatically by using mode='w'.
    if realtimestt_log_path.exists():
        try:
            realtimestt_log_path.unlink()
        except OSError as e:
            # Log this minor error but don't stop the application
            logging.warning("Could not remove old realtimestt.log: %s", e)

    level_name = str(resolved_config.get("level", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    # Use FileHandler with mode='w' to overwrite the log on each run
    file_handler = FileHandler(log_path, mode="w", encoding="utf-8")

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s%(prefix)s - %(levelname)s - %(message)s"
    )
    # Add a default, empty filter to ensure 'prefix' always exists
    file_handler.addFilter(ContextFilter(""))
    file_handler.setFormatter(formatter)

    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)

    if resolved_config.get("console_output", False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    logging.captureWarnings(True)
    _LOGGING_CONFIGURED = True
    root_logger.info("Logging initialized for new session at %s", log_path)
    root_logger.info("Previous session logs have been cleared.")

    return root_logger
