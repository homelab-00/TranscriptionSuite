"""
First-time setup wizard for TranscriptionSuite client.

Handles initial configuration when the user runs the client for the first time,
including Docker image setup and connection mode selection.
"""

import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import requests

from dashboard.common.config import get_config_dir

logger = logging.getLogger(__name__)


class ConnectionMode(Enum):
    """Connection mode for the client."""

    LOCAL = "local"
    REMOTE = "remote"


@dataclass
class SetupResult:
    """Result of a setup operation."""

    success: bool
    message: str
    needs_settings: bool = False  # If True, open settings dialog after setup


# Embedded file contents
DOCKER_COMPOSE_YML = '''# TranscriptionSuite Docker Compose Configuration
# Unified local + remote deployment with GPU support
#
# Build:
#   docker compose build
#
# Run (local HTTP):
#   docker compose up -d
#
# Run (remote HTTPS with Tailscale):
#   1. Generate certs: tailscale cert your-machine.tailnet-name.ts.net
#   2. Start with env vars:
#      TLS_ENABLED=true \\
#      TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \\
#      TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \\
#      docker compose up -d
#
# Switch between modes:
#   NOTE: Use "docker compose up -d" (not "start") to apply env var changes!
#   - Local:  docker compose up -d
#   - Remote: TLS_ENABLED=true TLS_CERT_PATH=... TLS_KEY_PATH=... docker compose up -d
#
# Optional environment variables:
#   HUGGINGFACE_TOKEN=xxx  # For downloading diarization models
#
# User Configuration & Logs:
#   The server looks for custom config and writes logs to a user config directory.
#   Mount your local config directory to enable custom settings and persistent logs:
#
#   Linux:
#     USER_CONFIG_DIR=~/.config/TranscriptionSuite docker compose up -d
#
#   Windows (PowerShell):
#     $env:USER_CONFIG_DIR="$env:USERPROFILE\\Documents\\TranscriptionSuite"
#     docker compose up -d
#
#   To customize settings, copy config.yaml from the repo to your USER_CONFIG_DIR
#   and edit as needed. The server will use your custom config instead of defaults.

services:
  transcription-suite:
    image: ghcr.io/homelab-00/transcriptionsuite-server:latest
    container_name: transcription-suite
    
    # Use host network mode for direct access to host services (LM Studio)
    # Note: Ports are exposed directly on host (no port mapping needed)
    network_mode: "host"
    
    # GPU support (NVIDIA)
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    
    # Environment variables
    environment:
      - DATA_DIR=/data
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8000
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      # HuggingFace token for downloading models (optional)
      - HF_TOKEN=${HUGGINGFACE_TOKEN:-}
      - HF_HOME=/models
      # LM Studio URL for chat features (localhost works with host network mode)
      - LM_STUDIO_URL=${LM_STUDIO_URL:-http://127.0.0.1:1234}
      # TLS settings for remote access (optional)
      - TLS_ENABLED=${TLS_ENABLED:-false}
      - TLS_CERT_FILE=/certs/cert.crt
      - TLS_KEY_FILE=/certs/cert.key
    
    # Volume mounts for persistent data
    volumes:
      - transcription-data:/data  # Database, audio files, tokens, logs
      - huggingface-models:/models  # Whisper and diarization models cache
      # User config directory (optional - for custom config.yaml and logs)
      # Set USER_CONFIG_DIR to mount your local config directory:
      #   Linux: USER_CONFIG_DIR=~/.config/TranscriptionSuite
      #   Windows: USER_CONFIG_DIR=$HOME/Documents/TranscriptionSuite
      - ${USER_CONFIG_DIR:-./.empty}:/user-config
      # TLS certificates (bind-mounted from host when TLS_CERT_PATH/TLS_KEY_PATH are set)
      - ${TLS_CERT_PATH:-./.empty}:/certs/cert.crt:ro
      - ${TLS_KEY_PATH:-./.empty}:/certs/cert.key:ro
    
    # Restart policy
    restart: unless-stopped
    
    # Health check - works with both HTTP and HTTPS modes
    healthcheck:
      test: ["CMD", "sh", "-c", "if [ \\"$$TLS_ENABLED\\" = \\"true\\" ]; then curl -f -k https://localhost:8443/health; else curl -f http://localhost:8000/health; fi"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

volumes:
  transcription-data:
    name: transcription-suite-data
  huggingface-models:
    name: transcription-suite-models
'''

ENV_EXAMPLE = '''# TranscriptionSuite - Environment variables
# =====================================================
#
# Fill in your values below and then rename this file
# to just `.env`
#
# [Contains config for HuggingFace token and debug printouts]
# =====================================================

# HuggingFace Token (required for speaker diarization)
# Get your token from: https://huggingface.co/settings/tokens
# You must also accept the model license at:
#   https://huggingface.co/pyannote/speaker-diarization-community-1
# Leave empty if you don't need diarization.
HUGGINGFACE_TOKEN=

# Log level (optional)
# Options: DEBUG, INFO, WARNING, ERROR
# Default: INFO
# LOG_LEVEL=INFO
'''

# GitHub raw URL for downloading config.yaml
GITHUB_RAW_URL = "https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main"
DOCKER_IMAGE = "ghcr.io/homelab-00/transcriptionsuite-server:latest"


def is_first_time_setup() -> bool:
    """
    Check if this is the first time the user is running the application.

    Returns:
        True if config directory doesn't exist or is empty
    """
    config_dir = get_config_dir()

    # Check if directory exists
    if not config_dir.exists():
        return True

    # Check if it has the essential files
    essential_files = ["docker-compose.yml"]
    for filename in essential_files:
        if not (config_dir / filename).exists():
            return True

    return False


def needs_server_setup() -> bool:
    """
    Check if Docker server setup is needed.

    Returns:
        True if docker-compose.yml doesn't exist in config directory
    """
    config_dir = get_config_dir()
    return not (config_dir / "docker-compose.yml").exists()


class SetupWizard:
    """
    First-time setup wizard for TranscriptionSuite.

    Handles:
    - Docker availability check
    - Configuration directory setup
    - Docker image pull
    - Connection mode selection
    """

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize setup wizard.

        Args:
            config_dir: Path to config directory. If None, uses platform default.
        """
        self.config_dir = config_dir or get_config_dir()
        self.system = platform.system()

    def _run_command(
        self,
        args: list[str],
        capture_output: bool = True,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess:
        """Run a command and return the result."""
        return subprocess.run(
            args,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
        )

    def check_docker(self) -> tuple[bool, str]:
        """
        Check if Docker is installed and running.

        Returns:
            Tuple of (available, message)
        """
        # Check if Docker is installed
        if not shutil.which("docker"):
            if self.system == "Windows":
                return False, (
                    "Docker is not installed.\n\n"
                    "Please install Docker Desktop from:\n"
                    "https://docs.docker.com/desktop/install/windows-install/"
                )
            else:
                return False, (
                    "Docker is not installed.\n\n"
                    "Please install Docker:\n"
                    "  Arch Linux: sudo pacman -S docker\n"
                    "  Ubuntu/Debian: sudo apt install docker.io\n"
                    "  Or download from: https://docs.docker.com/get-docker/"
                )

        # Check if Docker daemon is running
        try:
            result = self._run_command(["docker", "info"], timeout=10)
            if result.returncode != 0:
                if self.system == "Windows":
                    return False, "Docker daemon is not running.\n\nPlease start Docker Desktop."
                else:
                    return False, (
                        "Docker daemon is not running.\n\n"
                        "Please start Docker:\n"
                        "  sudo systemctl start docker\n\n"
                        "To enable Docker at boot:\n"
                        "  sudo systemctl enable docker"
                    )
            return True, "Docker is available"
        except subprocess.TimeoutExpired:
            return False, "Docker command timed out"
        except Exception as e:
            return False, f"Docker check failed: {e}"

    def check_gpu(self) -> tuple[bool, str]:
        """
        Check if NVIDIA GPU is available.

        Returns:
            Tuple of (available, message)
        """
        if not shutil.which("nvidia-smi"):
            return False, "NVIDIA GPU not detected. Server will run on CPU (slow)."

        try:
            result = self._run_command(["nvidia-smi"], timeout=10)
            if result.returncode != 0:
                return False, "NVIDIA GPU not available. Server will run on CPU (slow)."

            # Check if nvidia-container-toolkit is configured
            docker_info = self._run_command(["docker", "info"], timeout=10)
            if docker_info.returncode == 0 and "nvidia" not in docker_info.stdout.lower():
                return True, (
                    "NVIDIA GPU detected, but nvidia-container-toolkit might not be configured.\n"
                    "GPU acceleration may not work until toolkit is installed."
                )

            return True, "NVIDIA GPU detected and configured"
        except Exception:
            return False, "GPU check failed. Server will run on CPU."

    def create_config_directory(self) -> bool:
        """Create the configuration directory."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Create .empty directory for Docker compose placeholder
            empty_dir = self.config_dir / ".empty"
            empty_dir.mkdir(exist_ok=True)

            return True
        except Exception as e:
            logger.error(f"Failed to create config directory: {e}")
            return False

    def download_config_yaml(self) -> bool:
        """Download config.yaml from GitHub."""
        config_file = self.config_dir / "config.yaml"
        if config_file.exists():
            logger.info("config.yaml already exists, skipping download")
            return True

        try:
            url = f"{GITHUB_RAW_URL}/server/config.yaml"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            config_file.write_text(response.text)
            logger.info(f"Downloaded config.yaml to {config_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to download config.yaml: {e}")
            return False

    def create_docker_compose(self) -> bool:
        """Create docker-compose.yml from embedded content."""
        compose_file = self.config_dir / "docker-compose.yml"
        if compose_file.exists():
            logger.info("docker-compose.yml already exists, skipping")
            return True

        try:
            compose_file.write_text(DOCKER_COMPOSE_YML)
            logger.info(f"Created docker-compose.yml at {compose_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to create docker-compose.yml: {e}")
            return False

    def create_env_file(self) -> bool:
        """Create .env file from embedded content."""
        env_file = self.config_dir / ".env"
        if env_file.exists():
            logger.info(".env file already exists, keeping existing secrets")
            return True

        try:
            env_file.write_text(ENV_EXAMPLE)
            logger.info(f"Created .env file at {env_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to create .env file: {e}")
            return False

    def pull_docker_image(
        self, progress_callback: Callable[[str], None] | None = None
    ) -> tuple[bool, str]:
        """
        Pull the Docker image from GitHub Container Registry.

        Args:
            progress_callback: Optional callback for progress messages

        Returns:
            Tuple of (success, message)
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        log(f"Pulling Docker image: {DOCKER_IMAGE}")
        log("This may take a few minutes on first run...")

        try:
            result = self._run_command(
                ["docker", "pull", DOCKER_IMAGE],
                capture_output=True,
                timeout=600,  # 10 minute timeout for large image
            )

            if result.returncode == 0:
                return True, "Docker image pulled successfully"
            else:
                # Image might not be published yet
                return False, (
                    "Could not pull from GitHub Container Registry.\n"
                    "The image may not be published yet.\n"
                    "You can build locally instead if you have the source code."
                )
        except subprocess.TimeoutExpired:
            return False, "Docker pull timed out. Please try again or check your internet connection."
        except Exception as e:
            return False, f"Docker pull failed: {e}"

    def run_setup(
        self,
        pull_image: bool = True,
        progress_callback: Callable[[str], None] | None = None,
    ) -> SetupResult:
        """
        Run the complete first-time setup.

        Args:
            pull_image: Whether to pull the Docker image
            progress_callback: Optional callback for progress messages

        Returns:
            SetupResult with success status and message
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        log("Running first-time setup...")

        # Check Docker
        docker_ok, docker_msg = self.check_docker()
        if not docker_ok:
            return SetupResult(False, docker_msg)
        log(docker_msg)

        # Check GPU
        gpu_ok, gpu_msg = self.check_gpu()
        log(gpu_msg)

        # Create config directory
        log(f"Creating config directory: {self.config_dir}")
        if not self.create_config_directory():
            return SetupResult(False, f"Failed to create config directory: {self.config_dir}")

        # Create docker-compose.yml
        log("Setting up Docker files...")
        if not self.create_docker_compose():
            return SetupResult(False, "Failed to create docker-compose.yml")

        # Download config.yaml
        log("Downloading configuration...")
        if not self.download_config_yaml():
            # Non-fatal - container has defaults
            log("Warning: Could not download config.yaml, using container defaults")

        # Create .env file
        if not self.create_env_file():
            log("Warning: Could not create .env file")

        # Pull Docker image
        if pull_image:
            pull_ok, pull_msg = self.pull_docker_image(progress_callback)
            log(pull_msg)
            if not pull_ok:
                # Non-fatal - can still work with local image
                log("Warning: Image pull failed, but setup can continue")

        # Success
        return SetupResult(
            True,
            (
                f"Setup complete!\n\n"
                f"All files are in: {self.config_dir}\n\n"
                f"Next steps:\n"
                f"1. Edit .env file to add HuggingFace token (for diarization)\n"
                f"2. Use 'Start Server (Local)' from the tray menu\n"
                f"3. Wait ~10 seconds for the server to initialize"
            ),
        )


def configure_for_remote_mode(config) -> None:
    """
    Configure the client for remote server connection.

    Sets:
    - port to 8443
    - use_https to True
    - use_remote to True

    Args:
        config: ClientConfig instance
    """
    config.set("server", "port", value=8443)
    config.set("server", "use_https", value=True)
    config.set("server", "use_remote", value=True)
    config.save()


def configure_for_local_mode(config) -> None:
    """
    Configure the client for local server connection (defaults).

    Sets:
    - host to localhost
    - port to 8000
    - use_https to False
    - use_remote to False

    Args:
        config: ClientConfig instance
    """
    config.set("server", "host", value="localhost")
    config.set("server", "port", value=8000)
    config.set("server", "use_https", value=False)
    config.set("server", "use_remote", value=False)
    config.save()
