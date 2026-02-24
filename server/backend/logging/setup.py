"""
Centralized logging configuration for TranscriptionSuite server.

Provides:
- Unified logging for all server components
- Structured JSON output for log aggregation
- Service tagging for filtering
- Log rotation and persistence
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Any

import structlog

_logging_configured = False


def setup_logging(
    config: dict[str, Any] | None = None,
    log_dir: Path | None = None,
) -> logging.Logger:
    """
    Initialize unified logging for all server components via structlog.

    Args:
        config: Logging configuration dict with keys:
            - level: Log level (default: INFO)
            - directory: Log directory path
            - max_size_mb: Max log file size before rotation (default: 10)
            - backup_count: Number of backup files to keep (default: 5)
            - structured: Use JSON format for file output (default: True)
            - console_output: Also log to console (default: True)
        log_dir: Override log directory

    Returns:
        Root logger instance
    """
    global _logging_configured

    root_logger = logging.getLogger()
    if _logging_configured:
        return root_logger

    # Default configuration
    default_config: dict[str, Any] = {
        "level": "INFO",
        "directory": "/data/logs",
        "max_size_mb": 10,
        "backup_count": 5,
        "structured": True,
        "console_output": True,
    }

    resolved_config = default_config.copy()
    if config:
        resolved_config.update(config.get("logging", config))

    log_directory = Path(log_dir or resolved_config.get("directory", "/data/logs"))
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "server.log"

    level_name = str(resolved_config.get("level", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    # Processors shared between structlog and the stdlib bridge
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    # File renderer: JSON for machine parsing
    file_renderer = (
        structlog.processors.JSONRenderer()
        if resolved_config.get("structured", True)
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            file_renderer,
        ],
    )

    # Console renderer: human-readable
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
    )

    max_bytes = int(resolved_config.get("max_size_mb", 10)) * 1_000_000
    backup_count = int(resolved_config.get("backup_count", 5))

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(file_formatter)

    handlers: list = [file_handler]

    if resolved_config.get("console_output", True):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        handlers.append(console_handler)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)
    logging.captureWarnings(True)

    # Configure structlog to bridge to stdlib
    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _logging_configured = True

    structlog.get_logger("main").info(
        "Logging initialized", log_path=str(log_path), level=level_name
    )

    return root_logger


def get_logger(service_name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger bound with a service name.

    Args:
        service_name: Name of the service (e.g., "api", "transcription")

    Returns:
        structlog BoundLogger with service context bound
    """
    return structlog.get_logger(service_name).bind(service=service_name)
