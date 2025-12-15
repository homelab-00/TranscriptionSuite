"""
Logging setup for the Remote Transcription Server.

Creates server_mode.log in project root, wiped on each startup.
"""

import logging
from logging import FileHandler
from pathlib import Path
from typing import Optional

_server_logging_configured = False
_server_logger: Optional[logging.Logger] = None


def setup_server_logging() -> logging.Logger:
    """
    Initialize logging for the remote transcription server.

    Creates server_mode.log in project root with mode='w' to wipe on each start.
    Returns the server logger.
    """
    global _server_logging_configured, _server_logger

    if _server_logging_configured and _server_logger:
        return _server_logger

    # Find project root (REMOTE_SERVER -> TranscriptionSuite)
    module_dir = Path(__file__).resolve().parent
    project_root = module_dir.parent

    log_path = project_root / "server_mode.log"

    # Create server logger
    logger = logging.getLogger("server")
    logger.setLevel(logging.DEBUG)  # Capture all levels

    # Remove any existing handlers
    logger.handlers.clear()

    # Create file handler with mode='w' to wipe on each start
    file_handler = FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(file_handler)

    # Don't propagate to root logger (avoid duplicate logs)
    logger.propagate = False

    _server_logging_configured = True
    _server_logger = logger

    logger.info("=" * 60)
    logger.info("Remote Transcription Server started")
    logger.info(f"Log file: {log_path}")
    logger.info("=" * 60)

    return logger


def get_server_logger() -> logging.Logger:
    """Get the server logger, initializing if needed."""
    global _server_logger
    if _server_logger is None:
        return setup_server_logging()
    return _server_logger


def get_websocket_logger() -> logging.Logger:
    """Get a child logger for WebSocket interactions."""
    server_logger = get_server_logger()
    return server_logger.getChild("websocket")


def get_api_logger() -> logging.Logger:
    """Get a child logger for API requests."""
    server_logger = get_server_logger()
    return server_logger.getChild("api")
