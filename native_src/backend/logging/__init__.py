"""
Centralized logging for TranscriptionSuite server.

Provides structured JSON logging with service tagging,
log rotation, and queryable log storage.
"""

from server.logging.setup import get_logger, setup_logging

__all__ = ["setup_logging", "get_logger"]
