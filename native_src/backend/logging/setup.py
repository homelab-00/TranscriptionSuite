"""
Centralized logging configuration for TranscriptionSuite server.

Provides:
- Unified logging for all server components
- Structured JSON output for log aggregation
- Service tagging for filtering
- Log rotation and persistence
"""

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "main"),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add any extra fields
        extra_keys = set(record.__dict__.keys()) - {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "service",
            "message",
        }
        for key in extra_keys:
            if not key.startswith("_"):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter for console output."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(service)-12s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # Ensure service attribute exists
        if not hasattr(record, "service"):
            record.service = "main"
        return super().format(record)


class ServiceFilter(logging.Filter):
    """Filter that adds service name to all log records."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service_name
        return True


_logging_configured = False
_loggers: Dict[str, logging.Logger] = {}


def setup_logging(
    config: Optional[Dict[str, Any]] = None,
    log_dir: Optional[Path] = None,
) -> logging.Logger:
    """
    Initialize unified logging for all server components.

    Args:
        config: Logging configuration dict with keys:
            - level: Log level (default: INFO)
            - directory: Log directory path
            - max_size_mb: Max log file size before rotation (default: 10)
            - backup_count: Number of backup files to keep (default: 5)
            - structured: Use JSON format (default: True in container)
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
    default_config: Dict[str, Any] = {
        "level": "INFO",
        "directory": "/data/logs",
        "max_size_mb": 10,
        "backup_count": 5,
        "structured": True,
        "console_output": True,
    }

    # Merge with provided config
    resolved_config = default_config.copy()
    if config:
        resolved_config.update(config.get("logging", config))

    # Resolve log directory
    if log_dir:
        log_directory = log_dir
    else:
        log_directory = Path(resolved_config.get("directory", "/data/logs"))

    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "server.log"

    # Get log level
    level_name = str(resolved_config.get("level", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    # Configure root logger
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # File handler with rotation
    max_bytes = int(resolved_config.get("max_size_mb", 10)) * 1_000_000
    backup_count = int(resolved_config.get("backup_count", 5))

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )

    # Choose formatter based on structured setting
    if resolved_config.get("structured", True):
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(HumanReadableFormatter())

    file_handler.addFilter(ServiceFilter("main"))
    root_logger.addHandler(file_handler)

    # Console handler (always human-readable)
    if resolved_config.get("console_output", True):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(HumanReadableFormatter())
        console_handler.addFilter(ServiceFilter("main"))
        root_logger.addHandler(console_handler)

    # Capture warnings
    logging.captureWarnings(True)

    _logging_configured = True
    root_logger.info(
        "Logging initialized",
        extra={"log_path": str(log_path), "level": level_name},
    )

    return root_logger


def get_logger(service_name: str) -> logging.Logger:
    """
    Get a logger for a specific service.

    The service name is added to all log records for filtering.

    Args:
        service_name: Name of the service (e.g., "api", "transcription", "database")

    Returns:
        Logger instance with service filter
    """
    if service_name in _loggers:
        return _loggers[service_name]

    logger = logging.getLogger(f"transcriptionsuite.{service_name}")
    logger.addFilter(ServiceFilter(service_name))
    _loggers[service_name] = logger

    return logger
