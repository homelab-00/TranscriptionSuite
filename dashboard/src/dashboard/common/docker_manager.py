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

from dashboard.common.config import get_config_dir

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
    AUTH_TOKEN_FILE = "docker_server_auth_token.txt"

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize Docker manager.

        Args:
            config_dir: Path to config directory. If None, uses platform default.
        """
        self.config_dir = config_dir or get_config_dir()
        self.system = platform.system()
        self._cached_auth_token: str | None = None

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

        # Hide console window on Windows
        startupinfo = None
        if self.system == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        return subprocess.run(
            args,
            cwd=cwd,
            env=full_env,
            capture_output=capture_output,
            text=True,
            timeout=60,
            startupinfo=startupinfo,
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

    def _parse_tls_paths_from_config(
        self, config_path: Path
    ) -> tuple[str | None, str | None]:
        """Parse TLS certificate paths from config.yaml."""
        try:
            content = config_path.read_text()

            # Extract host_cert_path
            cert_match = re.search(
                r'host_cert_path:\s*[\'"]?([^\'"#\r\n]+)[\'"]?', content
            )
            cert_path = cert_match.group(1).strip() if cert_match else None

            # Extract host_key_path
            key_match = re.search(
                r'host_key_path:\s*[\'"]?([^\'"#\r\n]+)[\'"]?', content
            )
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

    def get_image_size(self) -> str | None:
        """Get the size of the local Docker image."""
        try:
            result = self._run_command(
                ["docker", "images", self.DOCKER_IMAGE, "--format", "{{.Size}}"]
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return None
        except Exception:
            return None

    def volume_exists(self, volume_name: str) -> bool:
        """
        Check if a Docker volume exists.

        Args:
            volume_name: Name of the volume

        Returns:
            True if volume exists, False otherwise
        """
        try:
            result = self._run_command(
                ["docker", "volume", "ls", "--format", "{{.Name}}"]
            )
            if result.returncode != 0:
                return False
            return volume_name in result.stdout
        except Exception:
            return False

    def get_volume_size(self, volume_name: str) -> str | None:
        """
        Get the size of a Docker volume.

        Args:
            volume_name: Name of the volume

        Returns:
            Size of the volume as a string, or None if not found
        """
        try:
            result = self._run_command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    volume_name,
                    "--format",
                    "{{.Mountpoint}}",
                ]
            )
            if result.returncode != 0:
                return None

            mountpoint = result.stdout.strip()
            if not mountpoint:
                return None

            # Use du command to get directory size
            # We need to run this with sudo privileges on Linux
            du_result = self._run_command(["du", "-sh", mountpoint])

            if du_result.returncode == 0:
                # Parse output like "1.5G\t/path/to/volume"
                size = du_result.stdout.strip().split("\t")[0]
                return size
            return None
        except Exception:
            return None

    def get_volumes_base_path(self) -> str:
        """
        Get platform-specific Docker volumes base path.

        Returns:
            Path to Docker volumes directory
        """
        if self.system == "Windows":
            # Docker Desktop WSL2 backend
            return r"\\wsl$\docker-desktop-data\data\docker\volumes"
        else:
            return "/var/lib/docker/volumes"

    def list_downloaded_models(self) -> list[dict[str, str]]:
        """
        List downloaded models from the models volume.

        This requires the container to be running (uses docker exec).

        Returns:
            List of dicts with 'name' and 'size' keys, or empty list if unavailable
        """
        models = []
        try:
            # Check if container is running
            status = self.get_server_status()
            if status != ServerStatus.RUNNING:
                logger.debug("Container not running, cannot list models")
                return []

            # Use docker exec to list models from inside the container
            result = self._run_command(
                [
                    "docker",
                    "exec",
                    self.CONTAINER_NAME,
                    "sh",
                    "-c",
                    "for d in /models/hub/models--*/; do "
                    'if [ -d "$d" ]; then '
                    'name=$(basename "$d"); '
                    'size=$(du -sh "$d" 2>/dev/null | cut -f1); '
                    'echo "$name|$size"; '
                    "fi; done",
                ]
            )

            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    if "|" in line:
                        parts = line.split("|")
                        # Parse models--org--name format
                        raw_name = parts[0]
                        name_parts = raw_name.replace("models--", "").split("--")
                        if len(name_parts) >= 2:
                            display_name = f"{name_parts[0]}/{name_parts[1]}"
                        else:
                            display_name = raw_name
                        models.append(
                            {
                                "name": display_name,
                                "size": parts[1] if len(parts) > 1 else "?",
                            }
                        )
            return models
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

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

        # Remove container (without -v flag to preserve volumes)
        log("Removing container...")
        compose_file = self._find_compose_file()
        if compose_file:
            result = self._run_command(
                ["docker", "compose", "down"],
                cwd=self.config_dir,
            )
        else:
            result = self._run_command(["docker", "rm", self.CONTAINER_NAME])

        if result.returncode == 0:
            return DockerResult(
                True, "Container removed. You can now start fresh from the image."
            )
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to remove container: {error_msg}")

    def remove_image(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> DockerResult:
        """
        Remove the Docker server image.

        Args:
            progress_callback: Optional callback for progress messages

        Returns:
            DockerResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # Check if container exists and is running
        status = self.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            return DockerResult(
                False,
                "Container must be removed before removing the image. Remove container first.",
            )

        # Check if image exists
        if not self.image_exists_locally():
            return DockerResult(True, "Image does not exist locally.")

        log(f"Removing Docker image {self.DOCKER_IMAGE}...")
        result = self._run_command(["docker", "rmi", self.DOCKER_IMAGE])

        if result.returncode == 0:
            return DockerResult(True, "Docker image removed successfully.")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to remove image: {error_msg}")

    def pull_fresh_image(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> DockerResult:
        """
        Pull a fresh copy of the Docker server image.

        Args:
            progress_callback: Optional callback for progress messages

        Returns:
            DockerResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        log(f"Pulling fresh Docker image {self.DOCKER_IMAGE}...")
        log("This may take several minutes depending on your connection...")

        result = self._run_command(["docker", "pull", self.DOCKER_IMAGE])

        if result.returncode == 0:
            return DockerResult(True, "Fresh Docker image pulled successfully.")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to pull image: {error_msg}")

    def remove_data_volume(
        self,
        progress_callback: Callable[[str], None] | None = None,
        also_remove_config: bool = False,
    ) -> DockerResult:
        """
        Remove the data volume (contains server data and SQLite database).

        Args:
            progress_callback: Optional callback for progress messages
            also_remove_config: If True, also remove the config directory

        Returns:
            DockerResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # Check if container exists
        status = self.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            return DockerResult(
                False,
                "Container must be removed before deleting volumes. Remove the container first.",
            )

        volume_name = "transcription-suite-data"
        log(f"Removing data volume {volume_name}...")

        result = self._run_command(["docker", "volume", "rm", volume_name])

        messages = []
        if result.returncode == 0:
            # Clear the cached auth token since data is being deleted
            self.clear_server_auth_token()
            messages.append("Data volume removed successfully.")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            # Volume might not exist
            if "No such volume" in error_msg or "not found" in error_msg.lower():
                messages.append("Data volume does not exist.")
            else:
                return DockerResult(False, f"Failed to remove data volume: {error_msg}")

        # Also remove config directory if requested
        if also_remove_config:
            config_result = self.remove_config_directory(progress_callback)
            messages.append(config_result.message)

        return DockerResult(True, " ".join(messages))

    def remove_config_directory(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> DockerResult:
        """
        Remove the TranscriptionSuite config directory.

        This removes:
        - Linux: ~/.config/TranscriptionSuite/
        - Windows: ~/Documents/TranscriptionSuite/
        - macOS: ~/Library/Application Support/TranscriptionSuite/

        Args:
            progress_callback: Optional callback for progress messages

        Returns:
            DockerResult with success status and message
        """
        import shutil

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        log(f"Removing config directory {self.config_dir}...")

        try:
            if self.config_dir.exists():
                shutil.rmtree(self.config_dir)
                return DockerResult(True, "Config directory removed successfully.")
            else:
                return DockerResult(True, "Config directory does not exist.")
        except PermissionError as e:
            return DockerResult(False, f"Permission denied: {e}")
        except Exception as e:
            return DockerResult(False, f"Failed to remove config directory: {e}")

    def remove_models_volume(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> DockerResult:
        """
        Remove the models volume (contains Whisper models).

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
        if status != ServerStatus.NOT_FOUND:
            return DockerResult(
                False,
                "Container must be removed before deleting volumes. Remove the container first.",
            )

        volume_name = "transcription-suite-models"
        log(f"Removing models volume {volume_name}...")

        result = self._run_command(["docker", "volume", "rm", volume_name])

        if result.returncode == 0:
            return DockerResult(True, "Models volume removed successfully.")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            # Volume might not exist
            if "No such volume" in error_msg or "not found" in error_msg.lower():
                return DockerResult(True, "Models volume does not exist.")
            return DockerResult(False, f"Failed to remove models volume: {error_msg}")

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
            log(
                "Using config: "
                + (str(config_file) if config_file else "container defaults")
            )

        # Check for existing container with mode conflict
        current_status = self.get_server_status()
        if current_status in (ServerStatus.RUNNING, ServerStatus.STOPPED):
            current_mode = self.get_current_mode()
            if current_mode and current_mode != mode:
                log(
                    f"Mode conflict: container is in {current_mode.value} mode, switching to {mode.value}"
                )
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

    def get_logs(self, lines: int = 300) -> str:
        """
        Get recent server logs.

        Args:
            lines: Number of log lines to retrieve (default: 300)

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

    def get_admin_token(self, check_logs: bool = True) -> str | None:
        """
        Extract admin token from server logs or cached storage.

        Args:
            check_logs: If True, check logs for token. If False, only return cached token.

        Returns:
            Admin token if found, None otherwise
        """
        # First try cached token
        if self._cached_auth_token:
            return self._cached_auth_token

        # Try loading from file
        saved_token = self.load_server_auth_token()
        if saved_token:
            self._cached_auth_token = saved_token
            return saved_token

        # If requested, check logs for new token
        if check_logs:
            logs = self.get_logs(lines=1000)
            for line in logs.split("\n"):
                if "Admin Token:" in line:
                    # Extract token after "Admin Token:"
                    match = re.search(r"Admin Token:\s*(\S+)", line)
                    if match:
                        token = match.group(1)
                        # Save token for future use
                        self.save_server_auth_token(token)
                        self._cached_auth_token = token
                        return token

        return None

    def refresh_admin_token(self) -> str | None:
        """
        Force refresh admin token from container logs (ignores cache).

        This should be called after starting a new container to get the fresh token.

        Returns:
            Admin token if found, None otherwise
        """
        # Clear caches
        self._cached_auth_token = None

        # Check logs for token
        logs = self.get_logs(lines=1000)
        for line in logs.split("\n"):
            if "Admin Token:" in line:
                match = re.search(r"Admin Token:\s*(\S+)", line)
                if match:
                    token = match.group(1)
                    self.save_server_auth_token(token)
                    self._cached_auth_token = token
                    logger.info("Refreshed admin token from logs")
                    return token

        logger.warning("Could not find admin token in logs")
        return None

    def save_server_auth_token(self, token: str) -> None:
        """
        Save Docker server authentication token to persistent storage.

        Args:
            token: The authentication token to save
        """
        try:
            token_file = self.config_dir / self.AUTH_TOKEN_FILE
            token_file.write_text(token.strip())
            logger.info(f"Saved Docker server auth token to {token_file}")
        except Exception as e:
            logger.error(f"Failed to save auth token: {e}")

    def load_server_auth_token(self) -> str | None:
        """
        Load Docker server authentication token from persistent storage.

        Returns:
            The saved authentication token, or None if not found
        """
        try:
            token_file = self.config_dir / self.AUTH_TOKEN_FILE
            if token_file.exists():
                token = token_file.read_text().strip()
                if token:
                    logger.info("Loaded Docker server auth token from file")
                    return token
        except Exception as e:
            logger.error(f"Failed to load auth token: {e}")
        return None

    def clear_server_auth_token(self) -> None:
        """Clear the cached and stored authentication token."""
        self._cached_auth_token = None
        try:
            token_file = self.config_dir / self.AUTH_TOKEN_FILE
            if token_file.exists():
                token_file.unlink()
                logger.info("Cleared Docker server auth token")
        except Exception as e:
            logger.error(f"Failed to clear auth token: {e}")

    def open_volumes_location(self) -> bool:
        """
        Open file explorer at the Docker volumes location.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Default Docker volume location on Linux
            volumes_path = Path("/var/lib/docker/volumes")

            if not volumes_path.exists():
                logger.warning(f"Volumes path does not exist: {volumes_path}")
                return False

            # Open file manager based on desktop environment
            if self.system == "Linux":
                # Try common Linux file managers (check if they exist first)
                file_managers = [
                    "xdg-open",  # Standard
                    "dolphin",  # KDE
                    "nautilus",  # GNOME
                    "thunar",  # XFCE
                    "nemo",  # Cinnamon
                    "caja",  # MATE
                    "pcmanfm",  # LXDE
                ]

                for fm in file_managers:
                    if shutil.which(fm):
                        try:
                            subprocess.Popen(
                                [fm, str(volumes_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            logger.info(f"Opened volumes location with {fm}")
                            return True
                        except Exception as e:
                            logger.debug(f"Failed to open with {fm}: {e}")
                            continue

                logger.error("No file manager found")
                return False
            elif self.system == "Darwin":  # macOS
                subprocess.Popen(["open", str(volumes_path)])
                return True
            elif self.system == "Windows":
                subprocess.Popen(["explorer", str(volumes_path)])
                return True
            else:
                logger.error(f"Unsupported system: {self.system}")
                return False
        except Exception as e:
            logger.error(f"Failed to open volumes location: {e}")
            return False

    def open_config_file(self) -> bool:
        """
        Open config.yaml in the default editor.

        Returns:
            True if successful, False otherwise
        """
        try:
            config_file = self._find_config_file()
            if not config_file:
                logger.warning("config.yaml not found")
                return False

            # Open file with default editor
            if self.system == "Linux":
                # Detect desktop environment for better editor selection
                desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
                kde_session = os.environ.get("KDE_SESSION_VERSION", "")

                # Build priority list based on desktop environment
                if "kde" in desktop or kde_session:
                    editors = ["kate", "kwrite"]
                elif "gnome" in desktop or "unity" in desktop:
                    editors = ["gedit", "gnome-text-editor"]
                elif "xfce" in desktop:
                    editors = ["mousepad", "gedit"]
                elif "mate" in desktop:
                    editors = ["pluma", "gedit"]
                elif "cinnamon" in desktop:
                    editors = ["xed", "gedit"]
                else:
                    editors = []

                # Add common fallbacks
                editors.extend(["geany", "leafpad", "featherpad"])
                # Add xdg-open as last resort (unreliable on some systems)
                editors.append("xdg-open")

                for editor in editors:
                    if shutil.which(editor):
                        try:
                            proc = subprocess.Popen(
                                [editor, str(config_file)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                            )
                            # Give it a moment to fail immediately
                            try:
                                proc.wait(timeout=0.5)
                                if proc.returncode != 0:
                                    logger.debug(f"{editor} returned {proc.returncode}")
                                    continue  # Failed immediately
                            except subprocess.TimeoutExpired:
                                pass  # Still running, probably working
                            logger.info(f"Opened config file with {editor}")
                            return True
                        except Exception as e:
                            logger.debug(f"Failed to open with {editor}: {e}")
                            continue

                logger.error("No editor found")
                return False
            elif self.system == "Darwin":  # macOS
                subprocess.Popen(["open", str(config_file)])
                return True
            elif self.system == "Windows":
                # Use os.startfile for default association, fallback to notepad
                try:
                    os.startfile(str(config_file))  # type: ignore[attr-defined]  # Windows-only
                    return True
                except AttributeError:
                    # os.startfile only exists on Windows
                    subprocess.Popen(["notepad", str(config_file)])
                    return True
                except Exception:
                    subprocess.Popen(["notepad", str(config_file)])
                    return True
            else:
                logger.error(f"Unsupported system: {self.system}")
                return False
        except Exception as e:
            logger.error(f"Failed to open config file: {e}")
            return False
