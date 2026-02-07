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
import threading
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


@dataclass
class DockerImageInfo:
    """Information about a local Docker image."""

    repository: str
    tag: str
    image_id: str
    created: str  # ISO format datetime string
    size: str
    full_name: str  # repository:tag

    def display_name(self) -> str:
        """Return a user-friendly display name with tag, date, and size."""
        # Parse date to show just YYYY-MM-DD
        date_part = self.created.split()[0] if self.created else "unknown"
        return f"{self.tag} - {date_part} - {self.size}"


class DockerPullWorker(threading.Thread):
    """
    Background worker for Docker pull operations.

    Runs docker pull in a separate thread with real-time progress streaming
    and cancellation support.
    """

    def __init__(
        self,
        image_name: str,
        progress_callback: Callable[[str], None],
        complete_callback: Callable[[DockerResult], None],
        system: str = "Linux",
    ):
        """
        Initialize the pull worker.

        Args:
            image_name: Docker image to pull
            progress_callback: Called with progress messages (from worker thread)
            complete_callback: Called when complete with result (from worker thread)
            system: Operating system name for platform-specific handling
        """
        super().__init__(daemon=True, name="DockerPullWorker")
        self._image_name = image_name
        self._progress_callback = progress_callback
        self._complete_callback = complete_callback
        self._system = system
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    def run(self) -> None:
        """Execute pull in background thread with progress streaming."""
        try:
            self._progress_callback(f"Pulling Docker image {self._image_name}...")
            self._progress_callback(
                "This may take several minutes depending on your connection..."
            )

            # Build command
            cmd = ["docker", "pull", self._image_name]

            # Hide console window on Windows
            startupinfo = None
            creationflags = 0
            if self._system == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            # Start process with pipes for output streaming
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
                startupinfo=startupinfo,
                creationflags=creationflags if self._system == "Windows" else 0,
            )

            # Stream output line by line
            if self._process.stdout:
                try:
                    for line in iter(self._process.stdout.readline, ""):
                        if self._cancelled:
                            break

                        line = line.strip()
                        if line:
                            # Parse and report progress
                            parsed = self._parse_docker_output(line)
                            if parsed:
                                self._progress_callback(parsed)
                except ValueError:
                    # stdout was closed during cancel - this is expected
                    logger.debug("stdout closed during read (cancel requested)")

            # Wait for completion (if not already terminated)
            try:
                returncode = self._process.wait()
            except Exception:
                # Process already terminated
                returncode = -1

            with self._lock:
                if self._cancelled:
                    self._complete_callback(
                        DockerResult(False, "Docker pull cancelled by user.")
                    )
                elif returncode == 0:
                    self._progress_callback("Docker image pulled successfully!")
                    self._complete_callback(
                        DockerResult(True, "Fresh Docker image pulled successfully.")
                    )
                else:
                    self._complete_callback(
                        DockerResult(
                            False, f"Docker pull failed with exit code {returncode}"
                        )
                    )

        except FileNotFoundError:
            self._complete_callback(
                DockerResult(False, "Docker is not installed or not in PATH.")
            )
        except Exception as e:
            logger.exception("Docker pull failed")
            self._complete_callback(DockerResult(False, f"Docker pull error: {e}"))
        finally:
            self._process = None

    def _parse_docker_output(self, line: str) -> str | None:
        """
        Parse Docker pull output into user-friendly progress messages.

        Docker outputs various formats:
        - "latest: Pulling from repo/image"
        - "abc123: Pulling fs layer"
        - "abc123: Downloading [==>      ] 12.5MB/100MB"
        - "abc123: Download complete"
        - "abc123: Pull complete"
        - "Digest: sha256:..."
        - "Status: Downloaded newer image for..."
        """
        if not line:
            return None

        # Skip certain noisy lines (Digest lines are not useful progress info)
        if line.startswith("Digest:"):
            return None

        # Extract meaningful progress from download lines
        if "Downloading" in line and "[" in line:
            # Parse progress bar like "[==>      ] 12.5MB/100MB"
            try:
                # Extract the size info
                parts = line.split("]")
                if len(parts) > 1:
                    size_info = parts[1].strip()
                    # Get layer ID (first 12 chars usually)
                    layer_id = line.split(":")[0][:12] if ":" in line else "layer"
                    return f"Downloading {layer_id}: {size_info}"
            except Exception:
                logger.debug("Failed to parse docker pull output line: %s", line)
            return line

        # Report status messages
        if line.startswith("Status:"):
            return line

        # Report pull complete
        if "Pull complete" in line:
            layer_id = line.split(":")[0][:12] if ":" in line else "layer"
            return f"Layer {layer_id}: complete"

        # Report downloading state change
        if "Pulling fs layer" in line:
            layer_id = line.split(":")[0][:12] if ":" in line else "layer"
            return f"Layer {layer_id}: starting download"

        # Report extracting
        if "Extracting" in line:
            layer_id = line.split(":")[0][:12] if ":" in line else "layer"
            return f"Layer {layer_id}: extracting"

        # Pass through other meaningful lines
        if "Pulling from" in line or "Already exists" in line:
            return line

        return None

    def cancel(self) -> None:
        """Cancel the pull operation."""
        with self._lock:
            self._cancelled = True
            if self._process and self._process.poll() is None:
                logger.info("Cancelling Docker pull operation...")
                try:
                    # Close stdout to unblock the readline() loop in the thread
                    if self._process.stdout:
                        try:
                            self._process.stdout.close()
                        except Exception:
                            logger.debug(
                                "Failed to close docker pull stdout during cancel"
                            )

                    # Terminate the process
                    self._process.terminate()

                    # Give it a moment to terminate gracefully
                    try:
                        self._process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        # Force kill if it didn't terminate
                        logger.warning("Docker pull didn't terminate, killing...")
                        self._process.kill()
                        # Wait for kill to complete
                        try:
                            self._process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            logger.error("Failed to kill Docker pull process")
                except Exception as e:
                    logger.warning(f"Error terminating Docker pull: {e}")

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        with self._lock:
            return self._cancelled


class DockerServerWorker(threading.Thread):
    """
    Background worker for Docker server start operations.

    Runs docker compose up -d in a separate thread with progress streaming
    and cancellation support.
    """

    def __init__(
        self,
        cmd: list[str],
        config_dir: Path,
        env: dict[str, str],
        mode: ServerMode,
        progress_callback: Callable[[str], None],
        complete_callback: Callable[[DockerResult], None],
        system: str = "Linux",
    ):
        """
        Initialize the server start worker.

        Args:
            cmd: Docker compose command to execute
            config_dir: Working directory for the command
            env: Environment variables to set
            mode: Server mode (for success message)
            progress_callback: Called with progress messages (from worker thread)
            complete_callback: Called when complete with result (from worker thread)
            system: Operating system name for platform-specific handling
        """
        super().__init__(daemon=True, name="DockerServerWorker")
        self._cmd = cmd
        self._config_dir = config_dir
        self._env = env
        self._mode = mode
        self._progress_callback = progress_callback
        self._complete_callback = complete_callback
        self._system = system
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    def run(self) -> None:
        """Execute docker compose up -d in background thread."""
        try:
            self._progress_callback("Starting Docker container...")

            # Build full environment
            full_env = os.environ.copy()
            full_env.update(self._env)

            # Hide console window on Windows
            startupinfo = None
            creationflags = 0
            if self._system == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            # Start process with pipes for output streaming
            self._process = subprocess.Popen(
                self._cmd,
                cwd=self._config_dir,
                env=full_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
                startupinfo=startupinfo,
                creationflags=creationflags if self._system == "Windows" else 0,
            )

            # Stream output line by line
            if self._process.stdout:
                try:
                    for line in iter(self._process.stdout.readline, ""):
                        if self._cancelled:
                            break

                        line = line.strip()
                        if line:
                            self._progress_callback(line)
                except ValueError:
                    # stdout was closed during cancel - this is expected
                    logger.debug("stdout closed during read (cancel requested)")

            # Wait for completion (if not already terminated)
            try:
                returncode = self._process.wait()
            except Exception:
                # Process already terminated
                returncode = -1

            with self._lock:
                if self._cancelled:
                    self._complete_callback(
                        DockerResult(False, "Server start cancelled by user.")
                    )
                elif returncode == 0:
                    # Success message based on mode
                    if self._mode == ServerMode.LOCAL:
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
                    self._progress_callback("Server started successfully!")
                    self._complete_callback(
                        DockerResult(True, msg, ServerStatus.RUNNING)
                    )
                else:
                    self._complete_callback(
                        DockerResult(
                            False, f"Server start failed with exit code {returncode}"
                        )
                    )

        except FileNotFoundError:
            self._complete_callback(
                DockerResult(False, "Docker is not installed or not in PATH.")
            )
        except Exception as e:
            logger.exception("Server start failed")
            self._complete_callback(DockerResult(False, f"Server start error: {e}"))
        finally:
            self._process = None

    def cancel(self) -> None:
        """Cancel the server start operation."""
        with self._lock:
            self._cancelled = True
            if self._process and self._process.poll() is None:
                logger.info("Cancelling Docker server start...")
                try:
                    # Close stdout to unblock the readline() loop in the thread
                    if self._process.stdout:
                        try:
                            self._process.stdout.close()
                        except Exception:
                            logger.debug(
                                "Failed to close docker compose stdout during cancel"
                            )

                    # Terminate the process
                    self._process.terminate()

                    # Give it a moment to terminate gracefully
                    try:
                        self._process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        # Force kill if it didn't terminate
                        logger.warning("Docker compose didn't terminate, killing...")
                        self._process.kill()
                        try:
                            self._process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            logger.error("Failed to kill Docker compose process")
                except Exception as e:
                    logger.warning(f"Error terminating Docker compose: {e}")

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        with self._lock:
            return self._cancelled


class DockerManager:
    """
    Manages Docker server operations for TranscriptionSuite.

    Provides methods to start, stop, and check status of the Docker container
    without requiring external shell scripts.
    """

    DOCKER_IMAGE = "ghcr.io/homelab-00/transcriptionsuite-server:latest"
    CONTAINER_NAME = "transcriptionsuite-container"
    AUTH_TOKEN_FILE = "docker_server_auth_token.txt"
    HF_TOKEN_KEY = "HUGGINGFACE_TOKEN"
    HF_TOKEN_DECISION_KEY = "HUGGINGFACE_TOKEN_DECISION"
    HF_TOKEN_DECISIONS = {"unset", "provided", "skipped"}

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
        timeout: float | None = 60,
    ) -> subprocess.CompletedProcess:
        """
        Run a command and return the result.

        Args:
            args: Command arguments
            cwd: Working directory
            env: Environment variables to add
            capture_output: Whether to capture stdout/stderr
            timeout: Timeout in seconds (None for no timeout)
        """
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
            timeout=timeout,
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
        except FileNotFoundError:
            # Docker not installed - log at debug level to avoid spam
            logger.debug("Docker command not found (not installed)")
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

    def _read_env_map(self, env_file: Path) -> dict[str, str]:
        """Parse key/value pairs from a .env file (best-effort)."""
        values: dict[str, str] = {}
        if not env_file.exists():
            return values

        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def _upsert_env_values(self, env_file: Path, updates: dict[str, str]) -> None:
        """Update or append keys in a .env file while preserving unrelated lines."""
        lines = []
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()
        else:
            env_file.parent.mkdir(parents=True, exist_ok=True)

        seen: set[str] = set()
        updated_lines: list[str] = []

        for line in lines:
            if "=" not in line or line.strip().startswith("#"):
                updated_lines.append(line)
                continue
            key, _ = line.split("=", 1)
            key = key.strip()
            if key in updates:
                if key in seen:
                    # Drop duplicate definitions for managed keys
                    continue
                updated_lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                updated_lines.append(line)

        for key, value in updates.items():
            if key not in seen:
                updated_lines.append(f"{key}={value}")

        env_file.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")

    def ensure_hf_env_defaults(self) -> Path:
        """
        Ensure .env exists and contains HuggingFace token decision defaults.

        Returns:
            Path to the .env file.
        """
        env_file = self.config_dir / ".env"
        values = self._read_env_map(env_file)

        token = values.get(self.HF_TOKEN_KEY, "").strip()
        decision = values.get(self.HF_TOKEN_DECISION_KEY, "").strip().lower()

        if decision not in self.HF_TOKEN_DECISIONS:
            decision = "provided" if token else "unset"

        if token and decision != "provided":
            decision = "provided"

        self._upsert_env_values(
            env_file,
            {
                self.HF_TOKEN_KEY: token,
                self.HF_TOKEN_DECISION_KEY: decision,
            },
        )
        return env_file

    def get_hf_token_state(self) -> tuple[str, str, Path]:
        """
        Get the persisted HuggingFace token onboarding state.

        Returns:
            Tuple of (token, decision, env_file_path).
        """
        env_file = self.ensure_hf_env_defaults()
        values = self._read_env_map(env_file)

        token = values.get(self.HF_TOKEN_KEY, "").strip()
        decision = values.get(self.HF_TOKEN_DECISION_KEY, "unset").strip().lower()
        if decision not in self.HF_TOKEN_DECISIONS:
            decision = "provided" if token else "unset"
            self._upsert_env_values(env_file, {self.HF_TOKEN_DECISION_KEY: decision})

        return token, decision, env_file

    def update_hf_token_state(self, token: str, decision: str) -> Path:
        """
        Persist HuggingFace token onboarding state in .env.

        Args:
            token: Token value (empty string allowed)
            decision: One of unset|provided|skipped

        Returns:
            Path to the .env file.
        """
        normalized_decision = decision.strip().lower()
        if normalized_decision not in self.HF_TOKEN_DECISIONS:
            raise ValueError(f"Invalid HF token decision: {decision}")

        env_file = self.ensure_hf_env_defaults()
        clean_token = token.strip()
        if clean_token:
            normalized_decision = "provided"

        self._upsert_env_values(
            env_file,
            {
                self.HF_TOKEN_KEY: clean_token,
                self.HF_TOKEN_DECISION_KEY: normalized_decision,
            },
        )
        return env_file

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
        """Check if any transcriptionsuite-server Docker image exists locally."""
        try:
            # Check if any image with our repository exists (any tag)
            images = self.list_local_images()
            return len(images) > 0
        except Exception:
            return False

    def get_image_created_date(self) -> str | None:
        """Get the creation date of the most recent local Docker image."""
        try:
            most_recent = self.get_most_recent_image()
            if most_recent:
                # Return just the date part (YYYY-MM-DD)
                return most_recent.created.split()[0] if most_recent.created else None
            return None
        except Exception:
            return None

    def get_image_size(self) -> str | None:
        """Get the size of the most recent local Docker image."""
        try:
            most_recent = self.get_most_recent_image()
            if most_recent:
                return most_recent.size
            return None
        except Exception:
            return None

    def list_local_images(
        self, repository_filter: str = "transcriptionsuite-server"
    ) -> list[DockerImageInfo]:
        """
        List all local Docker images matching the repository filter.

        Args:
            repository_filter: Substring to filter repository names (default: transcriptionsuite-server)

        Returns:
            List of DockerImageInfo sorted by creation date (newest first)
        """
        images: list[DockerImageInfo] = []
        try:
            # Get image info with detailed format
            result = self._run_command(
                [
                    "docker",
                    "images",
                    "--format",
                    "{{.Repository}}|{{.Tag}}|{{.ID}}|{{.CreatedAt}}|{{.Size}}",
                ]
            )
            if result.returncode != 0:
                return images

            for line in result.stdout.strip().split("\n"):
                if not line or "|" not in line:
                    continue
                parts = line.split("|")
                if len(parts) < 5:
                    continue

                repository, tag, image_id, created, size = parts[:5]

                # Filter by repository name
                if repository_filter not in repository:
                    continue

                # Skip <none> tags
                if tag == "<none>":
                    continue

                images.append(
                    DockerImageInfo(
                        repository=repository,
                        tag=tag,
                        image_id=image_id,
                        created=created,
                        size=size,
                        full_name=f"{repository}:{tag}",
                    )
                )

            # Sort by created date (newest first)
            # CreatedAt format: "2025-01-20 15:30:45 +0200 EET"
            def parse_date(img: DockerImageInfo) -> str:
                # Return created string for sorting (ISO-ish format sorts correctly)
                return img.created

            images.sort(key=parse_date, reverse=True)
            return images

        except Exception as e:
            logger.error(f"Failed to list local images: {e}")
            return images

    def get_most_recent_image(self) -> DockerImageInfo | None:
        """
        Get the most recent local image by build date.

        Returns:
            DockerImageInfo for the newest image, or None if no images found
        """
        images = self.list_local_images()
        return images[0] if images else None

    def get_image_for_selection(self, selection: str) -> str:
        """
        Get the full image name for a given selection.

        Args:
            selection: Either "auto" for most recent, or a specific tag

        Returns:
            Full image name (repository:tag) to use
        """
        if selection == "auto" or not selection:
            # Use most recent by build date
            most_recent = self.get_most_recent_image()
            if most_recent:
                logger.info(f"Auto-selected most recent image: {most_recent.full_name}")
                return most_recent.full_name
            # Fallback to default
            return self.DOCKER_IMAGE

        # Find image with matching tag
        images = self.list_local_images()
        for img in images:
            if img.tag == selection:
                return img.full_name

        # Fallback to default
        return self.DOCKER_IMAGE

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
            shell_script = "".join(
                [
                    "for d in /models/hub/models--*/; do ",
                    'if [ -d "$d" ]; then ',
                    'name=$(basename "$d"); ',
                    'size=$(du -sh "$d" 2>/dev/null | cut -f1); ',
                    'echo "$name|$size"; ',
                    "fi; done",
                ]
            )
            result = self._run_command(
                [
                    "docker",
                    "exec",
                    self.CONTAINER_NAME,
                    "sh",
                    "-c",
                    shell_script,
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
        Pull a fresh copy of the Docker server image (synchronous).

        NOTE: This method blocks the calling thread. For GUI applications,
        use start_pull_worker() instead for async operation.

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

        # No timeout - image pulls can take a very long time for large images
        result = self._run_command(
            ["docker", "pull", self.DOCKER_IMAGE],
            timeout=None,  # No timeout for image pulls
        )

        if result.returncode == 0:
            return DockerResult(True, "Fresh Docker image pulled successfully.")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return DockerResult(False, f"Failed to pull image: {error_msg}")

    def start_pull_worker(
        self,
        progress_callback: Callable[[str], None],
        complete_callback: Callable[[DockerResult], None],
    ) -> DockerPullWorker:
        """
        Start an asynchronous Docker image pull operation.

        This method starts a background thread that pulls the Docker image
        with real-time progress reporting. The UI remains responsive during
        the pull.

        Args:
            progress_callback: Called with progress messages (from worker thread).
                              The caller is responsible for thread-safe UI updates.
            complete_callback: Called when operation completes with result
                              (from worker thread). The caller is responsible
                              for thread-safe UI updates.

        Returns:
            DockerPullWorker instance. Call .cancel() to abort the operation.

        Example (PyQt6/KDE):
            def on_progress(msg: str) -> None:
                # Use QMetaObject.invokeMethod for thread-safe UI update
                QMetaObject.invokeMethod(widget, "update_status",
                    Qt.ConnectionType.QueuedConnection, Q_ARG(str, msg))

            def on_complete(result: DockerResult) -> None:
                QMetaObject.invokeMethod(widget, "pull_finished",
                    Qt.ConnectionType.QueuedConnection)

            worker = docker_manager.start_pull_worker(on_progress, on_complete)
            # Later: worker.cancel() to abort
        """
        worker = DockerPullWorker(
            image_name=self.DOCKER_IMAGE,
            progress_callback=progress_callback,
            complete_callback=complete_callback,
            system=self.system,
        )
        worker.start()
        logger.info(f"Started async Docker pull for {self.DOCKER_IMAGE}")
        return worker

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

        volume_name = "transcriptionsuite-data"
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

        volume_name = "transcriptionsuite-models"
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
        image_selection: str = "auto",
    ) -> DockerResult:
        """
        Start the TranscriptionSuite server.

        Args:
            mode: Server mode (local HTTP or remote HTTPS)
            progress_callback: Optional callback for progress messages
            image_selection: Image to use - "auto" for most recent by build date,
                           or a specific tag name

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
        env_file = self.ensure_hf_env_defaults()

        # Build environment variables
        env = {}

        # Set USER_CONFIG_DIR for the compose file
        env["USER_CONFIG_DIR"] = str(self.config_dir)

        # Determine which image to use based on selection
        selected_image = self.get_image_for_selection(image_selection)
        # Extract just the tag from the full image name for the TAG env var
        if ":" in selected_image:
            tag = selected_image.split(":")[-1]
        else:
            tag = "latest"
        env["TAG"] = tag
        log(f"Using image tag: {tag}")

        # Handle env file
        env_file_args = []
        if env_file:
            log(f"Using secrets from: {env_file}")
            env_file_args = ["--env-file", str(env_file)]

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

        # Check if selected image exists
        images = self.list_local_images()
        image_found = any(img.full_name == selected_image for img in images)
        if image_found:
            log(f"Using image: {selected_image}")
        else:
            log(
                f"Image {selected_image} not found locally, will be pulled on first run"
            )

        # Start the container
        log(f"Starting TranscriptionSuite server ({mode.value} mode)...")

        cmd = ["docker", "compose"] + env_file_args + ["up", "-d"]
        # No timeout - may need to pull image on first run which can take a long time
        result = self._run_command(cmd, cwd=self.config_dir, env=env, timeout=None)

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

    def start_server_async(
        self,
        mode: ServerMode,
        progress_callback: Callable[[str], None],
        complete_callback: Callable[[DockerResult], None],
        image_selection: str = "auto",
    ) -> DockerServerWorker | DockerResult:
        """
        Start the TranscriptionSuite server asynchronously.

        This method starts a background thread that executes docker compose up -d
        with real-time progress reporting. The UI remains responsive during startup.

        Pre-flight validation is done synchronously (fast), and if it fails,
        a DockerResult is returned immediately instead of a worker.

        Args:
            mode: Server mode (local HTTP or remote HTTPS)
            progress_callback: Called with progress messages (from worker thread).
                              Caller is responsible for thread-safe UI updates.
            complete_callback: Called when operation completes with result
                              (from worker thread). Caller is responsible for
                              thread-safe UI updates.
            image_selection: Image to use - "auto" for most recent by build date,
                           or a specific tag name

        Returns:
            DockerServerWorker instance if validation passed (call .cancel() to abort),
            or DockerResult if pre-flight validation failed.
        """

        def log(msg: str) -> None:
            logger.info(msg)
            progress_callback(msg)

        # Pre-flight checks (synchronous - these are fast)
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
        env_file = self.ensure_hf_env_defaults()

        # Build environment variables
        env = {}

        # Set USER_CONFIG_DIR for the compose file
        env["USER_CONFIG_DIR"] = str(self.config_dir)

        # Determine which image to use based on selection
        selected_image = self.get_image_for_selection(image_selection)
        # Extract just the tag from the full image name for the TAG env var
        if ":" in selected_image:
            tag = selected_image.split(":")[-1]
        else:
            tag = "latest"
        env["TAG"] = tag
        log(f"Using image tag: {tag}")

        # Handle env file
        env_file_args: list[str] = []
        if env_file:
            log(f"Using secrets from: {env_file}")
            env_file_args = ["--env-file", str(env_file)]

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

        # Check if selected image exists
        images = self.list_local_images()
        image_found = any(img.full_name == selected_image for img in images)
        if image_found:
            log(f"Using image: {selected_image}")
        else:
            log(
                f"Image {selected_image} not found locally, will be pulled on first run"
            )

        # Build the command
        cmd = ["docker", "compose"] + env_file_args + ["up", "-d"]
        log(f"Starting TranscriptionSuite server ({mode.value} mode)...")

        # Create and start the worker
        worker = DockerServerWorker(
            cmd=cmd,
            config_dir=self.config_dir,
            env=env,
            mode=mode,
            progress_callback=progress_callback,
            complete_callback=complete_callback,
            system=self.system,
        )
        worker.start()
        logger.info(f"Started async server start for {mode.value} mode")
        return worker

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
