"""
Docker server management for TranscriptionSuite client.

Provides embedded Docker control functionality to start, stop, and manage
the TranscriptionSuite server container directly from the client.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from client.common.config import get_config_dir

logger = logging.getLogger(__name__)


class ServerMode(Enum):
    """Server startup mode."""

    LOCAL = "local"  # HTTP on port 8000
    REMOTE = "remote"  # HTTPS on port 8443


class ServerStatus(Enum):
    """Current server status."""

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not_found"  # Container doesn't exist
    ERROR = "error"


@dataclass
class DockerResult:
    """Result of a Docker operation."""

    success: bool
    message: str
    status: ServerStatus | None = None


class DockerManager:
    """
    Manages Docker server operations for TranscriptionSuite.

    Provides methods to start, stop, and check status of the Docker container
    without requiring external shell scripts.
    """

    DOCKER_IMAGE = "ghcr.io/homelab-00/transcriptionsuite-server:latest"
    CONTAINER_NAME = "transcription-suite"

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize Docker manager.

        Args:
            config_dir: Path to config directory. If None, uses platform default.
        """
        self.config_dir = config_dir or get_config_dir()
        self.system = platform.system()

    def _run_command(
        self,
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a command and return the result."""
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        return subprocess.run(
            args,
            cwd=cwd,
            env=full_env,
            capture_output=capture_output,
            text=True,
            timeout=60,
        )

    def is_docker_available(self) -> tuple[bool, str]:
        """
        Check if Docker is installed and running.

        Returns:
            Tuple of (available, message)
        """
        # Check if Docker is installed
        if not shutil.which("docker"):
            return False, "Docker is not installed"

        # Check if Docker daemon is running
        try:
            result = self._run_command(["docker", "info"])
            if result.returncode != 0:
                return False, "Docker daemon is not running"
            return True, "Docker is available"
        except subprocess.TimeoutExpired:
            return False, "Docker command timed out"
        except Exception as e:
            return False, f"Docker check failed: {e}"

    def get_server_status(self) -> ServerStatus:
        """Get the current status of the server container."""
        try:
            result = self._run_command(
                ["docker", "ps", "-a", "--format", "{{.Names}}:{{.State}}"]
            )
            if result.returncode != 0:
                return ServerStatus.ERROR

            for line in result.stdout.strip().split("\n"):
                if line.startswith(f"{self.CONTAINER_NAME}:"):
                    state = line.split(":", 1)[1]
                    if state == "running":
                        return ServerStatus.RUNNING
                    else:
                        return ServerStatus.STOPPED

            return ServerStatus.NOT_FOUND
        except Exception as e:
            logger.error(f"Failed to get server status: {e}")
            return ServerStatus.ERROR

    def get_container_health(self) -> str | None:
        try:
            result = self._run_command(
                [
                    "docker",
                    "inspect",
                    self.CONTAINER_NAME,
                    "--format",
                    "{{.State.Health.Status}}",
                ]
            )
            if result.returncode != 0:
                return None

            health = result.stdout.strip()
            if not health or health in ("<no value>", "null"):
                return None
            return health
        except Exception:
            return None

    def get_current_mode(self) -> ServerMode | None:
        """Get the current mode of the running container."""
        try:
            result = self._run_command(
                [
                    "docker",
                    "inspect",
                    self.CONTAINER_NAME,
                    "--format",
                    "{{range .Config.Env}}{{println .}}{{end}}",
                ]
            )
            if result.returncode != 0:
                return None

            for line in result.stdout.strip().split("\n"):
                if line.startswith("TLS_ENABLED="):
                    value = line.split("=", 1)[1]
                    if value.lower() == "true":
                        return ServerMode.REMOTE
                    else:
                        return ServerMode.LOCAL

            return ServerMode.LOCAL  # Default
        except Exception:
            return None

    def _find_config_file(self) -> Path | None:
        """Find the config.yaml file."""
        config_file = self.config_dir / "config.yaml"
        if config_file.exists():
            return config_file
        return None

    def _find_env_file(self) -> Path | None:
        """Find the .env file."""
        env_file = self.config_dir / ".env"
        if env_file.exists():
            return env_file
        return None

    def _find_compose_file(self) -> Path | None:
        """Find the docker-compose.yml file."""
        compose_file = self.config_dir / "docker-compose.yml"
        if compose_file.exists():
            return compose_file
        return None

    def _parse_tls_paths_from_config(self, config_path: Path) -> tuple[str | None, str | None]:
        """Parse TLS certificate paths from config.yaml."""
        try:
            content = config_path.read_text()

            # Extract host_cert_path
            cert_match = re.search(r'host_cert_path:\s*[\'"]?([^\'"#\r\n]+)[\'"]?', content)
            cert_path = cert_match.group(1).strip() if cert_match else None

            # Extract host_key_path
            key_match = re.search(r'host_key_path:\s*[\'"]?([^\'"#\r\n]+)[\'"]?', content)
            key_path = key_match.group(1).strip() if key_match else None

            # Expand ~ to home directory
            if cert_path and cert_path.startswith("~"):
                cert_path = str(Path.home() / cert_path[2:])
            if key_path and key_path.startswith("~"):
                key_path = str(Path.home() / key_path[2:])

            return cert_path, key_path
        except Exception as e:
            logger.error(f"Failed to parse TLS paths: {e}")
            return None, None

    def image_exists_locally(self) -> bool:
        """Check if the Docker image exists locally."""
        try:
            result = self._run_command(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"]
            )
            if result.returncode != 0:
                return False
            return self.DOCKER_IMAGE in result.stdout
        except Exception:
            return False

    def get_image_created_date(self) -> str | None:
        """Get the creation date of the local Docker image."""
        try:
            result = self._run_command(
                ["docker", "images", self.DOCKER_IMAGE, "--format", "{{.CreatedAt}}"]
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split()[0]  # Return just the date part
            return None
        except Exception:
            return None

    def remove_container(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> DockerResult:
        """
        Remove the server container (for recreating from fresh image).

        Args:
            progress_callback: Optional callback for progress messages

        Returns:
            DockerResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # Check if container exists
        status = self.get_server_status()
        if status == ServerStatus.NOT_FOUND:
            return DockerResult(True, "Container does not exist.")

        # Stop container if running
        if status == ServerStatus.RUNNING:
            log("Stopping container before removal...")
            self.stop_server(progress_callback=progress_callback)

        # Remove container
        log("Removing container...")
        compose_file = self._find_compose_file()
        if compose_file:
            result = self._run_command(
                ["docker", "compose", "down", "-v"],
                cwd=self.config_dir,
            )
        else:
            result = self._run_command(["docker", "rm", self.CONTAINER_NAME])

        if result.returncode == 0:
            return DockerResult(True, "Container removed. You can now start fresh from the image.")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to remove container: {error_msg}")

    def start_server(
        self,
        mode: ServerMode = ServerMode.LOCAL,
        progress_callback: Callable[[str], None] | None = None,
    ) -> DockerResult:
        """
        Start the TranscriptionSuite server.

        Args:
            mode: Server mode (local HTTP or remote HTTPS)
            progress_callback: Optional callback for progress messages

        Returns:
            DockerResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # Pre-flight checks
        available, msg = self.is_docker_available()
        if not available:
            return DockerResult(False, msg)

        # Check for docker-compose.yml
        compose_file = self._find_compose_file()
        if not compose_file:
            return DockerResult(
                False,
                f"docker-compose.yml not found in {self.config_dir}. Run setup first.",
            )

        # Find config and env files
        config_file = self._find_config_file()
        env_file = self._find_env_file()

        # Build environment variables
        env = {}

        # Set USER_CONFIG_DIR for the compose file
        env["USER_CONFIG_DIR"] = str(self.config_dir)

        # Handle env file
        env_file_args = []
        if env_file:
            log(f"Using secrets from: {env_file}")
            env_file_args = ["--env-file", str(env_file)]
        else:
            log("No .env file found (diarization may not work without HF token)")

        # Handle mode-specific configuration
        if mode == ServerMode.REMOTE:
            if not config_file:
                return DockerResult(
                    False,
                    "config.yaml required for remote mode. Run setup first.",
                )

            # Parse TLS paths from config
            cert_path, key_path = self._parse_tls_paths_from_config(config_file)

            if not cert_path:
                return DockerResult(
                    False,
                    "remote_server.tls.host_cert_path not set in config.yaml",
                )
            if not key_path:
                return DockerResult(
                    False,
                    "remote_server.tls.host_key_path not set in config.yaml",
                )
            if not Path(cert_path).exists():
                return DockerResult(False, f"Certificate file not found: {cert_path}")
            if not Path(key_path).exists():
                return DockerResult(False, f"Key file not found: {key_path}")

            log(f"Certificate: {cert_path}")
            log(f"Key: {key_path}")

            env["TLS_ENABLED"] = "true"
            env["TLS_CERT_PATH"] = cert_path
            env["TLS_KEY_PATH"] = key_path
        else:
            log("Using config: " + (str(config_file) if config_file else "container defaults"))

        # Check for existing container with mode conflict
        current_status = self.get_server_status()
        if current_status in (ServerStatus.RUNNING, ServerStatus.STOPPED):
            current_mode = self.get_current_mode()
            if current_mode and current_mode != mode:
                log(f"Mode conflict: container is in {current_mode.value} mode, switching to {mode.value}")
                log("Removing existing container...")
                self._run_command(
                    ["docker", "compose", "down"],
                    cwd=self.config_dir,
                    env=env,
                )

        # Check if image exists
        if self.image_exists_locally():
            log(f"Using existing image: {self.DOCKER_IMAGE}")
        else:
            log("Image will be pulled on first run")

        # Start the container
        log(f"Starting TranscriptionSuite server ({mode.value} mode)...")

        cmd = ["docker", "compose"] + env_file_args + ["up", "-d"]
        result = self._run_command(cmd, cwd=self.config_dir, env=env)

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to start server: {error_msg}")

        # Success message
        if mode == ServerMode.LOCAL:
            msg = (
                "Server started (Local Mode)\n\n"
                "Server URL: http://localhost:8000\n"
                "Web UI: http://localhost:8000/record\n"
                "Notebook: http://localhost:8000/notebook"
            )
        else:
            msg = (
                "Server started (Remote/TLS Mode)\n\n"
                "HTTPS URL: https://localhost:8443\n"
                "Web UI: https://localhost:8443/record\n"
                "Notebook: https://localhost:8443/notebook"
            )

        return DockerResult(True, msg, ServerStatus.RUNNING)

    def stop_server(
        self, progress_callback: Callable[[str], None] | None = None
    ) -> DockerResult:
        """
        Stop the TranscriptionSuite server.

        Args:
            progress_callback: Optional callback for progress messages

        Returns:
            DockerResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # Check Docker availability
        available, msg = self.is_docker_available()
        if not available:
            return DockerResult(False, msg)

        # Check for docker-compose.yml
        compose_file = self._find_compose_file()
        if not compose_file:
            # Try to stop container directly if compose file not found
            log("docker-compose.yml not found, stopping container directly...")
            result = self._run_command(["docker", "stop", self.CONTAINER_NAME])
            if result.returncode == 0:
                return DockerResult(True, "Server stopped.")
            else:
                return DockerResult(False, "Container not found or already stopped.")

        log("Stopping TranscriptionSuite server...")

        result = self._run_command(
            ["docker", "compose", "stop"],
            cwd=self.config_dir,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to stop server: {error_msg}")

        return DockerResult(
            True,
            "TranscriptionSuite server stopped.\n\n"
            "To restart:\n"
            "  • Start Local (HTTP)\n"
            "  • Start Remote (HTTPS)",
            ServerStatus.STOPPED,
        )

    def get_logs(self, lines: int = 50) -> str:
        """
        Get recent server logs.

        Args:
            lines: Number of log lines to retrieve

        Returns:
            Log output as string
        """
        compose_file = self._find_compose_file()
        if not compose_file:
            return "No docker-compose.yml found"

        try:
            result = self._run_command(
                ["docker", "compose", "logs", "--tail", str(lines)],
                cwd=self.config_dir,
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e:
            return f"Failed to get logs: {e}"

    def get_admin_token(self) -> str | None:
        """
        Extract admin token from server logs.

        Returns:
            Admin token if found, None otherwise
        """
        logs = self.get_logs(lines=100)
        for line in logs.split("\n"):
            if "Admin Token:" in line:
                # Extract token after "Admin Token:"
                match = re.search(r"Admin Token:\s*(\S+)", line)
                if match:
                    return match.group(1)
        return None
