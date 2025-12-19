"""
Client configuration management for TranscriptionSuite.

Handles loading and saving client configuration from:
- Platform-specific config directories
- Command line arguments
"""

import os
import platform
from pathlib import Path
from typing import Any

import yaml


def get_config_dir() -> Path:
    """Get platform-specific configuration directory."""
    system = platform.system()

    if system == "Windows":
        base = Path(os.environ.get("APPDATA", "~"))
        config_dir = base / "TranscriptionSuite"
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
            self.config_path = get_config_dir() / "client.yaml"

        self.config = get_default_config()
        self._load()

    def _load(self) -> None:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    loaded = yaml.safe_load(f) or {}
                self._deep_merge(self.config, loaded)
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
        """Save configuration to file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                yaml.dump(self.config, f, default_flow_style=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
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
            return self.get("server", "remote_host") or self.get("server", "host")
        return self.get("server", "host", default="localhost")

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
        return self.get("server", "token", default="")

    @token.setter
    def token(self, value: str) -> None:
        """Set authentication token."""
        self.set("server", "token", value=value)
        self.save()
