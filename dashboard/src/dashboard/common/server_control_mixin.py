"""
Mixin class for server control operations shared across tray implementations.

This mixin provides common functionality for starting, stopping, and managing
the Docker server across different platform-specific tray implementations.
"""

import logging
from typing import Any, Callable, Protocol

from dashboard.common.docker_manager import DockerManager, ServerMode

logger = logging.getLogger(__name__)


class _ServerControlHost(Protocol):
    """Protocol defining required attributes for ServerControlMixin."""

    _docker_manager: DockerManager

    def show_notification(self, title: str, message: str) -> None: ...

    def _run_server_operation(
        self, operation: Callable[[], Any], progress_msg: str
    ) -> None: ...


class ServerControlMixin:
    """
    Mixin providing server control operations for tray implementations.

    Requires:
        - self._docker_manager: DockerManager instance
        - self.show_notification(title: str, message: str): method to show notifications
        - self._run_server_operation(operation, progress_msg): platform-specific method for async ops
    """

    def _on_server_start_local(self: _ServerControlHost) -> None:
        """Start Docker server in local (HTTP) mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(
                mode=ServerMode.LOCAL,
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Starting server (local mode)...",
        )

    def _on_server_start_remote(self: _ServerControlHost) -> None:
        """Start Docker server in remote (HTTPS) mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(
                mode=ServerMode.REMOTE,
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Starting server (remote mode)...",
        )

    def _on_server_stop(self: _ServerControlHost) -> None:
        """Stop the Docker server."""
        self._run_server_operation(
            lambda: self._docker_manager.stop_server(
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Stopping server...",
        )

    def _on_server_status(self: _ServerControlHost) -> None:
        """Check Docker server status."""
        try:
            available, docker_msg = self._docker_manager.is_docker_available()
            if not available:
                self.show_notification("Docker Server", docker_msg)
                return

            running, status_msg = self._docker_manager.is_server_running()
            self.show_notification("Docker Server", status_msg)

        except Exception as e:
            logger.error(f"Failed to check server status: {e}")
            self.show_notification("Error", f"Failed to check server status: {e}")
