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
        "diarization": {
            "expected_speakers": None,  # Exact number of speakers (2-10), or None for auto-detect
        },
    }


class ClientConfig:
    """Client configuration manager."""

    _SERVER_CONFIG_DEPRECATED: set[tuple[str, ...]] = {
        ("transcription_options", "enable_live_transcriber"),
    }

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

    def _format_yaml_scalar(self, value: Any) -> str:
        """Format a Python value as a single-line YAML scalar."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, list):
            return yaml.safe_dump(
                value, default_flow_style=True, sort_keys=False
            ).strip()
        if isinstance(value, str):
            if value == "":
                return '""'
            if "\n" in value or "\r" in value:
                normalized = value.replace("\r\n", "\n").replace("\r", "\n")
                escaped = (
                    normalized.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("\t", "\\t")
                    .replace("\n", "\\n")
                )
                return f'"{escaped}"'
            needs_quotes = (
                value.strip() != value
                or value.lower()
                in {"null", "true", "false", "yes", "no", "on", "off", "~"}
                or any(c in value for c in ":#{}[]&*!|>'\"%@`")
            )
            if needs_quotes:
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                return f'"{escaped}"'
            return value
        return str(value)

    def _set_server_config_values(self, updates: dict[tuple[str, ...], Any]) -> bool:
        """
        Update multiple values in the server's config.yaml file.

        Preserves comments and formatting via targeted in-place edits.
        """
        import re

        server_config_path = get_config_dir() / "config.yaml"
        if not server_config_path.exists():
            print(f"Warning: Server config not found at {server_config_path}")
            return False

        tmp_path = None

        try:
            with open(server_config_path, "r") as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    lines = f.readlines()
                finally:
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Build path -> line index mapping (supports commented-out keys)
            line_map: dict[tuple[str, ...], tuple[int, str, bool]] = {}
            stack: list[tuple[int, str]] = []

            for i, line in enumerate(lines):
                stripped = line.lstrip()
                if not stripped:
                    continue

                indent = len(line) - len(stripped)

                # Commented-out key (e.g. "    # live_language: \"en\"")
                if stripped.startswith("#"):
                    match = re.match(r"#\s*([a-z0-9_]+)\s*:(.*)$", stripped)
                    if match:
                        key = match.group(1)
                        while stack and indent <= stack[-1][0]:
                            stack.pop()
                        path = tuple([p for _, p in stack] + [key])
                        line_map[path] = (i, match.group(2), True)
                    continue

                # Active key
                match = re.match(r"(\s*)([A-Za-z0-9_]+)\s*:(.*)$", line)
                if not match:
                    continue
                key = match.group(2)
                value_part = match.group(3)

                while stack and indent <= stack[-1][0]:
                    stack.pop()
                stack.append((indent, key))
                path = tuple([p for _, p in stack])

                # Only map leaf keys (with value on the same line)
                if value_part.strip() != "":
                    line_map[path] = (i, value_part, False)

            indices_to_remove = set()
            for deprecated_path in self._SERVER_CONFIG_DEPRECATED:
                entry = line_map.get(deprecated_path)
                if entry:
                    indices_to_remove.add(entry[0])

            modified = bool(indices_to_remove)

            for path, value in updates.items():
                yaml_value = self._format_yaml_scalar(value)

                entry = line_map.get(path)
                if entry:
                    idx, old_value_and_comment, is_commented = entry
                    # Preserve inline comments (for active keys)
                    inline_comment = ""
                    if "#" in old_value_and_comment:
                        comment_idx = old_value_and_comment.index("#")
                        inline_comment = (
                            "  " + old_value_and_comment[comment_idx:].rstrip()
                        )

                    indent = re.match(r"^(\s*)", lines[idx]).group(1)
                    indent_len = len(indent)
                    key = path[-1]
                    lines[idx] = f"{indent}{key}: {yaml_value}{inline_comment}\n"
                    if old_value_and_comment.lstrip().startswith(("|", ">")):
                        j = idx + 1
                        while j < len(lines):
                            next_line = lines[j]
                            next_indent = len(next_line) - len(next_line.lstrip())
                            if next_indent > indent_len:
                                indices_to_remove.add(j)
                                j += 1
                                continue
                            break
                    modified = True
                    continue

                # If not found, append to end of file (best-effort)
                indent = " " * (4 * (len(path) - 1))
                key = path[-1]
                lines.append(f"{indent}{key}: {yaml_value}\n")
                modified = True

            if not modified:
                return True

            tmp_path = server_config_path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    for i, line in enumerate(lines):
                        if i in indices_to_remove:
                            continue
                        f.write(line)
                finally:
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            os.replace(tmp_path, server_config_path)
            return True

        except Exception as e:
            print(f"Error setting server config: {e}")
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return False

    def set_server_config_values(self, updates: dict[tuple[str, ...], Any]) -> bool:
        """Set multiple server config values at once."""
        return self._set_server_config_values(updates)

    def set_server_config(self, *keys: str, value: Any) -> bool:
        """
        Set a configuration value in the server's config.yaml file.

        This modifies ~/.config/TranscriptionSuite/config.yaml (the server config),
        not the dashboard's dashboard.yaml file.
        """
        if not keys:
            print("Error: set_server_config requires at least one key")
            return False
        return self._set_server_config_values({tuple(keys): value})

    def get_server_config(self, *keys: str, default: Any = None) -> Any:
        """
        Get a configuration value from the server's config.yaml file.

        Args:
            *keys: Path to the configuration key
            default: Default value if not found

        Returns:
            Configuration value or default
        """
        server_config_path = get_config_dir() / "config.yaml"

        if not server_config_path.exists():
            return default

        try:
            with open(server_config_path) as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    server_config = yaml.safe_load(f) or {}
                finally:
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            value: Any = server_config
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return default
                if value is None:
                    return default
            return value

        except Exception as e:
            print(f"Error reading server config: {e}")
            return default
