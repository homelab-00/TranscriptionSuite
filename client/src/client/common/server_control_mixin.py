"""
Mixin class for server control operations shared across tray implementations.

This mixin provides common functionality for starting, stopping, and managing
the Docker server across different platform-specific tray implementations.
"""

import logging
import subprocess
from typing import Callable

from client.common.docker_manager import DockerManager, ServerMode

logger = logging.getLogger(__name__)


class ServerControlMixin:
    """
    Mixin providing server control operations for tray implementations.

    Requires:
        - self._docker_manager: DockerManager instance
        - self.show_notification(title: str, message: str): method to show notifications
        - self._run_server_operation(operation, progress_msg): platform-specific method for async ops
    """

    def _on_server_start_local(self) -> None:
        """Start Docker server in local (HTTP) mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(
                mode=ServerMode.LOCAL,
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Starting server (local mode)...",
        )

    def _on_server_start_remote(self) -> None:
        """Start Docker server in remote (HTTPS) mode."""
        self._run_server_operation(
            lambda: self._docker_manager.start_server(
                mode=ServerMode.REMOTE,
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Starting server (remote mode)...",
        )

    def _on_server_stop(self) -> None:
        """Stop the Docker server."""
        self._run_server_operation(
            lambda: self._docker_manager.stop_server(
                progress_callback=lambda msg: logger.info(msg),
            ),
            "Stopping server...",
        )

    def _on_server_status(self) -> None:
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

    def _on_open_lazydocker(self) -> None:
        """Open lazydocker in a terminal."""
        import shutil

        # Check if lazydocker is available
        lazydocker_path = shutil.which("lazydocker")
        if not lazydocker_path:
            self.show_notification(
                "lazydocker",
                "lazydocker not found. Install with: sudo pacman -S lazydocker",
            )
            return

        # Try different terminal emulators
        terminals = [
            ["konsole", "-e", "lazydocker"],
            ["gnome-terminal", "--", "lazydocker"],
            ["xfce4-terminal", "-e", "lazydocker"],
            ["xterm", "-e", "lazydocker"],
        ]

        for terminal_cmd in terminals:
            if shutil.which(terminal_cmd[0]):
                try:
                    subprocess.Popen(
                        terminal_cmd,
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    logger.info(f"Launched lazydocker with {terminal_cmd[0]}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to launch with {terminal_cmd[0]}: {e}")
                    continue

        self.show_notification(
            "lazydocker",
            "No supported terminal emulator found (konsole, gnome-terminal, xfce4-terminal, xterm)",
        )
