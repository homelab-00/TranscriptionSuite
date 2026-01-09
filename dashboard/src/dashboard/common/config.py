"""
Client configuration management for TranscriptionSuite.

Handles loading and saving client configuration from:
- Platform-specific config directories
- Command line arguments

Thread/process safety:
- Uses file locking (fcntl on Linux, skipped on Windows)
- Uses atomic writes (write to temp file, then rename)
"""

import os
import platform
from pathlib import Path
from typing import Any

import yaml

# File locking support (Linux/Unix only)
# Windows doesn't have fcntl - skip locking there
# (Windows uses single-process PyQt6, so no race condition)
fcntl = None  # type: ignore[assignment]
try:
    import fcntl as _fcntl

    fcntl = _fcntl
except ImportError:
    pass


def get_config_dir() -> Path:
    """
    Get platform-specific configuration directory.

    Returns:
        Path to user config directory:
        - Linux: ~/.config/TranscriptionSuite/
        - Windows: ~/Documents/TranscriptionSuite/
        - macOS: ~/Library/Application Support/TranscriptionSuite/
    """
    system = platform.system()

    if system == "Windows":
        # Windows: Documents/TranscriptionSuite/ (matches backend config location)
        config_dir = Path.home() / "Documents" / "TranscriptionSuite"
    elif system == "Darwin":  # macOS
        config_dir = (
            Path.home() / "Library" / "Application Support" / "TranscriptionSuite"
        )
    else:  # Linux and others
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            config_dir = Path(xdg_config) / "TranscriptionSuite"
        else:
            config_dir = Path.home() / ".config" / "TranscriptionSuite"

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_default_config() -> dict[str, Any]:
    """Get default client configuration."""
    return {
        "server": {
            "host": "localhost",
            "port": 8000,
            "use_https": False,
            "token": "",
            "remote_host": "",
            "use_remote": False,
            "timeout": 30,
            "transcription_timeout": 300,
            "auto_reconnect": True,
            "reconnect_interval": 10,
            "tls_verify": True,  # Verify TLS certificates (disable for self-signed)
            "allow_insecure_http": False,  # Allow HTTP to non-localhost hosts
        },
        "recording": {
            "sample_rate": 16000,
            "device_index": None,
        },
        "clipboard": {
            "auto_copy": True,
        },
        "ui": {
            "notifications": True,
            "start_minimized": False,
            "left_click": "start_recording",
            "middle_click": "stop_transcribe",
        },
        "behavior": {
            "auto_start_client": False,  # Start client when app launches
        },
        "dashboard": {
            "stop_server_on_quit": True,  # Stop Docker server when quitting
        },
    }


class ClientConfig:
    """Client configuration manager."""

    def __init__(self, config_path: Path | None = None):
        """
        Initialize client configuration.

        Args:
            config_path: Optional path to config file
        """
        if config_path:
            self.config_path = config_path
        else:
            self.config_path = get_config_dir() / "dashboard.yaml"

        self.config = get_default_config()
        self._load()

    def _load(self) -> None:
        """Load configuration from file with shared lock for thread/process safety."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    # Acquire shared lock for reading (Linux only)
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        loaded = yaml.safe_load(f) or {}
                        self._deep_merge(self.config, loaded)
                    finally:
                        if fcntl is not None:
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception as e:
                print(f"Warning: Could not load config: {e}")

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Deep merge override into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self) -> bool:
        """
        Save configuration to file with exclusive lock and atomic write.

        Uses atomic write pattern (write to temp file, then rename) to prevent
        file corruption if the process is interrupted during write.
        """
        tmp_path = None
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first for atomic write
            tmp_path = self.config_path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                # Acquire exclusive lock for writing (Linux only)
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    yaml.dump(self.config, f, default_flow_style=False)
                finally:
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Atomic rename (overwrites existing file)
            os.replace(tmp_path, self.config_path)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            # Clean up temp file if it exists
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return False

    def get(self, *keys: str, default: Any = None) -> Any:
        """Get a configuration value by path."""
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value

    def set(self, *keys: str, value: Any) -> None:
        """Set a configuration value by path."""
        d = self.config
        for key in keys[:-1]:
            if key not in d:
                d[key] = {}
            d = d[key]
        d[keys[-1]] = value

    @property
    def server_host(self) -> str:
        """Get effective server host."""
        if self.get("server", "use_remote"):
            remote_host = self.get("server", "remote_host") or self.get(
                "server", "host"
            )
            # Sanitize remote_host: strip protocol, port, and trailing slashes
            return self._sanitize_hostname(remote_host)
        return self.get("server", "host", default="localhost")

    def _sanitize_hostname(self, hostname: str) -> str:
        """
        Sanitize hostname by removing protocol, port, and trailing slashes.

        Examples:
            https://example.com:8443/ -> example.com
            http://example.com -> example.com
            example.com:8080 -> example.com
            example.com/ -> example.com
        """
        if not hostname:
            return "localhost"

        # Remove protocol (http://, https://, ws://, wss://)
        if "://" in hostname:
            hostname = hostname.split("://", 1)[1]

        # Remove port (anything after the first colon)
        if ":" in hostname:
            hostname = hostname.split(":", 1)[0]

        # Remove trailing slashes and whitespace
        hostname = hostname.rstrip("/").strip()

        return hostname or "localhost"

    @property
    def server_port(self) -> int:
        """Get server port."""
        return self.get("server", "port", default=8000)

    @property
    def use_https(self) -> bool:
        """Check if HTTPS should be used."""
        return self.get("server", "use_https", default=False)

    @property
    def token(self) -> str:
        """Get authentication token."""
        return self.get("server", "token", default="").strip()

    @token.setter
    def token(self, value: str) -> None:
        """Set authentication token."""
        self.set("server", "token", value=value)
        self.save()
