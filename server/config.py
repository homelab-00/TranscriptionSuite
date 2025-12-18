"""
Server configuration management for TranscriptionSuite.

Handles loading configuration from YAML files and environment variables.
Provides typed configuration access for all server components.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class ServerConfig:
    """
    Server configuration manager.

    Loads configuration from YAML file and environment variables.
    Environment variables take precedence over file settings.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config file. If None, looks for:
                1. /app/config.yaml (in container)
                2. config.yaml (in project root)
        """
        self.config: Dict[str, Any] = {}
        self._config_path = config_path
        self._load_config()

    def _find_config_file(self) -> Optional[Path]:
        """Find the configuration file."""
        if self._config_path and self._config_path.exists():
            return self._config_path

        # Check common locations
        candidates = [
            Path("/app/config.yaml"),  # Docker container
            Path(__file__).parent.parent / "config.yaml",  # Project root
            Path.cwd() / "config.yaml",  # Current directory
        ]

        for path in candidates:
            if path.exists():
                return path

        return None

    def _load_config(self) -> None:
        """Load configuration from file and environment."""
        # Start with defaults
        self.config = self._get_defaults()

        # Load from file
        config_file = self._find_config_file()
        if config_file:
            try:
                with config_file.open("r", encoding="utf-8") as f:
                    file_config = yaml.safe_load(f) or {}
                self._deep_merge(self.config, file_config)
            except (yaml.YAMLError, OSError) as e:
                print(f"Warning: Could not load config file: {e}")

        # Apply environment overrides
        self._apply_env_overrides()

    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration values."""
        return {
            "server": {
                "host": "0.0.0.0",
                "port": 8000,
                "workers": 1,
                "tls": {
                    "enabled": False,
                    "cert_file": "/data/certs/server.crt",
                    "key_file": "/data/certs/server.key",
                    "auto_generate": True,
                },
                "remote": {
                    "enabled": False,
                    "tailscale_hostname": "",
                },
            },
            "transcription": {
                "model": "Systran/faster-whisper-large-v3",
                "device": "cuda",
                "compute_type": "float16",
                "language": None,  # Auto-detect
                "beam_size": 5,
                "batch_size": 16,
                "vad": {
                    "enabled": True,
                    "silero_sensitivity": 0.4,
                },
                "diarization": {
                    "enabled": False,
                    "hf_token": "",
                },
            },
            "audio_notebook": {
                "database_path": "/data/database/notebook.db",
                "audio_storage": "/data/audio",
                "audio_format": "mp3",
                "audio_bitrate": 160,
            },
            "llm": {
                "enabled": True,
                "base_url": "http://host.docker.internal:1234",
                "model": "",
                "max_tokens": 4096,
                "temperature": 0.7,
            },
            "logging": {
                "level": "INFO",
                "directory": "/data/logs",
                "max_size_mb": 10,
                "backup_count": 5,
                "structured": True,
                "console_output": True,
            },
            "auth": {
                "token_store": "/data/tokens/tokens.json",
                "token_expiry_days": 30,
            },
        }

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        env_mappings = {
            "LOG_LEVEL": ("logging", "level"),
            "HF_TOKEN": ("transcription", "diarization", "hf_token"),
            "SERVER_HOST": ("server", "host"),
            "SERVER_PORT": ("server", "port"),
            "DATA_DIR": None,  # Special handling
        }

        for env_var, config_path in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None and config_path is not None:
                self._set_nested(self.config, config_path, value)

        # Special handling for DATA_DIR
        data_dir = os.environ.get("DATA_DIR")
        if data_dir:
            self.config["audio_notebook"]["database_path"] = (
                f"{data_dir}/database/notebook.db"
            )
            self.config["audio_notebook"]["audio_storage"] = f"{data_dir}/audio"
            self.config["logging"]["directory"] = f"{data_dir}/logs"
            self.config["auth"]["token_store"] = f"{data_dir}/tokens/tokens.json"

    def _deep_merge(self, base: Dict, override: Dict) -> None:
        """Deep merge override into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _set_nested(self, d: Dict, keys: tuple, value: Any) -> None:
        """Set a nested dictionary value."""
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get a configuration value by dot-separated path.

        Example:
            config.get("transcription", "model")
            config.get("logging", "level", default="INFO")
        """
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value

    @property
    def transcription(self) -> Dict[str, Any]:
        """Get transcription configuration."""
        return self.config.get("transcription", {})

    @property
    def server(self) -> Dict[str, Any]:
        """Get server configuration."""
        return self.config.get("server", {})

    @property
    def logging(self) -> Dict[str, Any]:
        """Get logging configuration."""
        return self.config.get("logging", {})

    @property
    def audio_notebook(self) -> Dict[str, Any]:
        """Get audio notebook configuration."""
        return self.config.get("audio_notebook", {})

    @property
    def llm(self) -> Dict[str, Any]:
        """Get LLM configuration."""
        return self.config.get("llm", {})

    @property
    def auth(self) -> Dict[str, Any]:
        """Get authentication configuration."""
        return self.config.get("auth", {})


# Global config instance
_config: Optional[ServerConfig] = None


def get_config(config_path: Optional[Path] = None) -> ServerConfig:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = ServerConfig(config_path)
    return _config
