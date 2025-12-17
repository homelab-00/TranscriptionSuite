"""
Configuration management for the native client.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .server_connection import ServerConfig

logger = logging.getLogger(__name__)

# Default config file location
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "transcription-suite" / "client.yaml"


@dataclass
class RecordingConfig:
    """Recording configuration."""

    sample_rate: int = 16000
    device_index: Optional[int] = None


@dataclass
class UIConfig:
    """UI configuration."""

    notifications: bool = True
    notification_duration: int = 3000


@dataclass
class ClipboardConfig:
    """Clipboard configuration."""

    auto_copy: bool = True


@dataclass
class ClientConfig:
    """Complete native client configuration."""

    server: ServerConfig = field(default_factory=ServerConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    clipboard: ClipboardConfig = field(default_factory=ClipboardConfig)


def load_config(config_path: Optional[Path] = None) -> ClientConfig:
    """
    Load configuration from file.

    Args:
        config_path: Path to config file. Uses default if not specified.

    Returns:
        ClientConfig instance
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.info(f"Config file not found at {path}, using defaults")
        return ClientConfig()

    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        return _parse_config(data)

    except Exception as e:
        logger.error(f"Failed to load config from {path}: {e}")
        return ClientConfig()


def save_config(config: ClientConfig, config_path: Optional[Path] = None) -> bool:
    """
    Save configuration to file.

    Args:
        config: Configuration to save
        config_path: Path to config file. Uses default if not specified.

    Returns:
        True if successful
    """
    path = config_path or DEFAULT_CONFIG_PATH

    try:
        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        data = _config_to_dict(config)

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

        logger.info(f"Config saved to {path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save config to {path}: {e}")
        return False


def _parse_config(data: Dict[str, Any]) -> ClientConfig:
    """Parse config dictionary into ClientConfig."""
    server_data = data.get("server", {})
    server = ServerConfig(
        host=server_data.get("host", "localhost"),
        audio_notebook_port=server_data.get("audio_notebook_port", 8000),
        remote_server_port=server_data.get("remote_server_port", 8443),
        use_https=server_data.get("use_https", False),
        timeout=server_data.get("timeout", 30),
        auto_reconnect=server_data.get("auto_reconnect", True),
        reconnect_interval=server_data.get("reconnect_interval", 5),
    )

    recording_data = data.get("recording", {})
    recording = RecordingConfig(
        sample_rate=recording_data.get("sample_rate", 16000),
        device_index=recording_data.get("device_index"),
    )

    ui_data = data.get("ui", {})
    ui = UIConfig(
        notifications=ui_data.get("notifications", True),
        notification_duration=ui_data.get("notification_duration", 3000),
    )

    clipboard_data = data.get("clipboard", {})
    clipboard = ClipboardConfig(
        auto_copy=clipboard_data.get("auto_copy", True),
    )

    return ClientConfig(
        server=server,
        recording=recording,
        ui=ui,
        clipboard=clipboard,
    )


def _config_to_dict(config: ClientConfig) -> Dict[str, Any]:
    """Convert ClientConfig to dictionary."""
    return {
        "server": {
            "host": config.server.host,
            "audio_notebook_port": config.server.audio_notebook_port,
            "remote_server_port": config.server.remote_server_port,
            "use_https": config.server.use_https,
            "timeout": config.server.timeout,
            "auto_reconnect": config.server.auto_reconnect,
            "reconnect_interval": config.server.reconnect_interval,
        },
        "recording": {
            "sample_rate": config.recording.sample_rate,
            "device_index": config.recording.device_index,
        },
        "ui": {
            "notifications": config.ui.notifications,
            "notification_duration": config.ui.notification_duration,
        },
        "clipboard": {
            "auto_copy": config.clipboard.auto_copy,
        },
    }
