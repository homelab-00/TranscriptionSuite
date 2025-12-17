"""
Logging setup for the Remote Transcription Server.

When running via orchestrator, logs go to transcription_suite.log.
When running standalone (run_server.py), creates server_mode.log for backward compatibility.
"""

import logging
from logging import FileHandler
from pathlib import Path
from typing import Optional

_server_logging_configured = False
_server_logger: Optional[logging.Logger] = None


def setup_server_logging(use_main_log: bool = False) -> logging.Logger:
    """
    Initialize logging for the remote transcription server.

    Args:
        use_main_log: If True, uses the main transcription_suite.log.
                      If False (standalone mode), creates server_mode.log.

    Returns the server logger.
    """
    global _server_logging_configured, _server_logger

    if _server_logging_configured and _server_logger:
        return _server_logger

    # Find project root (REMOTE_SERVER -> TranscriptionSuite)
    module_dir = Path(__file__).resolve().parent
    project_root = module_dir.parent

    if use_main_log:
        # Use the main application logger (transcription_suite.log)
        # Just create a child logger that inherits the root logger's handlers
        logger = logging.getLogger("server")
        logger.setLevel(logging.DEBUG)
        # Don't add new handlers - inherit from root logger configured by logging_setup.py
        logger.propagate = True
        log_path = project_root / "transcription_suite.log"
    else:
        # Standalone mode - create separate log file
        log_path = project_root / "server_mode.log"

        logger = logging.getLogger("server")
        logger.setLevel(logging.DEBUG)

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

        # Don't propagate to root logger in standalone mode
        logger.propagate = False

    _server_logging_configured = True
    _server_logger = logger

    logger.info("=" * 60)
    logger.info("Remote Transcription Server started")
    logger.info(f"Log file: {log_path}")
    logger.info("=" * 60)

    return logger


def get_server_logger(use_main_log: bool = False) -> logging.Logger:
    """Get the server logger, initializing if needed."""
    global _server_logger
    if _server_logger is None:
        return setup_server_logging(use_main_log)
    return _server_logger


def reset_server_logging() -> None:
    """Reset server logging state. Call this when restarting server mode."""
    global _server_logging_configured, _server_logger
    _server_logging_configured = False
    _server_logger = None


def get_websocket_logger() -> logging.Logger:
    """Get a child logger for WebSocket interactions."""
    server_logger = get_server_logger()
    return server_logger.getChild("websocket")


def get_api_logger() -> logging.Logger:
    """Get a child logger for API requests."""
    server_logger = get_server_logger()
    return server_logger.getChild("api")
