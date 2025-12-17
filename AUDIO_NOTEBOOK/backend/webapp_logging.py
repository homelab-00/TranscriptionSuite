"""
Logging setup for the Audio Notebook webapp.

Creates audio_notebook_webapp.log in project root, wiped on each startup.
Also logs LLM interactions.
"""

import logging
from logging import FileHandler
from pathlib import Path
from typing import Optional

_webapp_logging_configured = False
_webapp_logger: Optional[logging.Logger] = None


def setup_webapp_logging() -> logging.Logger:
    """
    Initialize webapp logging.

    Creates audio_notebook_webapp.log in project root with mode='w' to wipe on each start.
    Returns the webapp logger.
    """
    global _webapp_logging_configured, _webapp_logger

    if _webapp_logging_configured and _webapp_logger:
        return _webapp_logger

    # Find project root (backend -> AUDIO_NOTEBOOK -> TranscriptionSuite)
    backend_dir = Path(__file__).resolve().parent
    project_root = backend_dir.parent.parent

    log_path = project_root / "audio_notebook_webapp.log"

    # Create webapp logger
    logger = logging.getLogger("webapp")
    logger.setLevel(logging.INFO)

    # Remove any existing handlers
    logger.handlers.clear()

    # Create file handler with mode='w' to wipe on each start
    file_handler = FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(file_handler)

    # Don't propagate to root logger
    logger.propagate = False

    _webapp_logging_configured = True
    _webapp_logger = logger

    logger.info("=" * 60)
    logger.info("Audio Notebook webapp started")
    logger.info("=" * 60)

    return logger


def get_webapp_logger() -> logging.Logger:
    """Get the webapp logger, initializing if needed."""
    global _webapp_logger
    if _webapp_logger is None:
        return setup_webapp_logging()
    return _webapp_logger


def get_llm_logger() -> logging.Logger:
    """Get a child logger for LLM interactions."""
    webapp_logger = get_webapp_logger()
    return webapp_logger.getChild("llm")


def get_api_logger() -> logging.Logger:
    """Get a child logger for API requests."""
    webapp_logger = get_webapp_logger()
    return webapp_logger.getChild("api")
