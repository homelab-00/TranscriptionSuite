"""
Server configuration management for TranscriptionSuite.

Handles loading configuration from YAML files.
Provides typed configuration access for all server components.

Configuration Priority (highest to lowest):
    1. User config: ~/.config/TranscriptionSuite/config.yaml (Linux)
                    or Documents/TranscriptionSuite/config.yaml (Windows)
                    or /user-config/config.yaml (Docker with mounted volume)
    2. Default config: /app/config.yaml (Docker container)
    3. Dev config: server/config.yaml (development)
    4. Fallback: ./config.yaml (current directory)
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

FALLBACK_MAIN_TRANSCRIBER_MODEL = "Systran/faster-whisper-large-v3"
DISABLED_MODEL_SENTINEL = "__none__"


def get_user_config_dir() -> Path:
    """
    Get the user configuration directory based on platform.

    Returns:
        Path to user config directory:
        - Linux: ~/.config/TranscriptionSuite/
        - Windows: ~/Documents/TranscriptionSuite/
        - Docker: /user-config/ (if exists and is mounted)
    """
    # In Docker, check for mounted user config directory first
    docker_user_config = Path("/user-config")
    if docker_user_config.exists() and docker_user_config.is_dir():
        return docker_user_config

    # Platform-specific user config directories
    if sys.platform == "win32":
        # Windows: Documents/TranscriptionSuite/
        documents = Path.home() / "Documents"
        return documents / "TranscriptionSuite"
    else:
        # Linux/macOS: ~/.config/TranscriptionSuite/
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "TranscriptionSuite"
        return Path.home() / ".config" / "TranscriptionSuite"


class ServerConfig:
    """
    Server configuration manager.

    Loads configuration from YAML file.
    User config takes precedence over default config.
    """

    def __init__(self, config_path: Path | None = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config file. If None, searches in priority order.
        """
        self.config: dict[str, Any] = {}
        self._config_path = config_path
        self._loaded_from: Path | None = None
        self._load_config()

    def _find_config_file(self) -> Path | None:
        """
        Find the configuration file in priority order.

        Priority:
            1. Explicitly provided path
            2. User config directory (platform-specific or Docker mount)
            3. /app/config.yaml (Docker container default)
            4. server/config.yaml (development)
            5. ./config.yaml (current directory fallback)
        """
        if self._config_path and self._config_path.exists():
            return self._config_path

        # Build search paths in priority order
        user_config_dir = get_user_config_dir()
        candidates = [
            user_config_dir / "config.yaml",  # User custom config
            Path("/app/config.yaml"),  # Docker container default
            Path(__file__).parent.parent / "config.yaml",  # server/config.yaml
            Path.cwd() / "config.yaml",  # Current directory fallback
        ]

        for path in candidates:
            if path.exists() and path.is_file():
                # Check if file is readable by attempting to open it
                try:
                    with path.open("r", encoding="utf-8"):
                        pass
                    return path
                except (PermissionError, OSError):
                    # Skip unreadable config files and try next candidate
                    continue

        return None

    def _find_config_candidates(self) -> list[Path]:
        """Return readable config file candidates in priority order."""
        if self._config_path:
            if self._config_path.exists():
                try:
                    with self._config_path.open("r", encoding="utf-8"):
                        pass
                    return [self._config_path]
                except (PermissionError, OSError):
                    return []
            return []

        user_config_dir = get_user_config_dir()
        candidates = [
            user_config_dir / "config.yaml",
            Path("/app/config.yaml"),
            Path(__file__).parent.parent / "config.yaml",
            Path.cwd() / "config.yaml",
        ]

        readable: list[Path] = []
        for path in candidates:
            if not (path.exists() and path.is_file()):
                continue
            try:
                with path.open("r", encoding="utf-8"):
                    pass
                readable.append(path)
            except (PermissionError, OSError):
                continue

        return readable

    def _load_config(self) -> None:
        """Load configuration from file."""
        candidates = self._find_config_candidates()

        if not candidates:
            raise RuntimeError(
                "No configuration file found. "
                "Expected one of:\n"
                f"  - {get_user_config_dir() / 'config.yaml'} (user config)\n"
                "  - /app/config.yaml (Docker default)\n"
                "  - server/config.yaml (development)\n"
                "  - ./config.yaml (current directory)"
            )

        errors: list[tuple[Path, Exception]] = []
        for config_file in candidates:
            try:
                with config_file.open("r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                self._loaded_from = config_file
                if errors:
                    print(
                        "WARNING: Skipped invalid config file(s): "
                        + ", ".join(str(path) for path, _ in errors)
                    )
                self._apply_env_overrides()
                print(f"Loaded configuration from: {config_file}")
                return
            except (yaml.YAMLError, OSError) as e:
                print(f"ERROR: Could not load config file {config_file}: {e}")
                errors.append((config_file, e))
                if self._config_path:
                    break

        if errors:
            details = "\n".join(f"  - {path}: {err}" for path, err in errors)
            raise RuntimeError("Failed to load configuration. Tried:\n" + details)
        raise RuntimeError("Failed to load configuration for unknown reasons.")

    _ENV_MODEL_OVERRIDES = (
        ("MAIN_TRANSCRIBER_MODEL", ("main_transcriber", "model")),
        ("LIVE_TRANSCRIBER_MODEL", ("live_transcriber", "model")),
        ("DIARIZATION_MODEL", ("diarization", "model")),
    )

    _ENV_LOGGING_OVERRIDES = (
        # LOG_LEVEL overrides logging.level (DEBUG, INFO, WARNING, ERROR)
        ("LOG_LEVEL", ("logging", "level")),
        # LOG_DIR overrides logging.directory (path to log file directory)
        ("LOG_DIR", ("logging", "directory")),
    )

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides for model selection and logging.

        Environment variables (set by the dashboard via docker-compose) take
        precedence over config.yaml values.  Only non-empty values are applied.
        """
        for env_key, config_path in self._ENV_MODEL_OVERRIDES:
            value = os.environ.get(env_key, "").strip()
            if not value:
                continue
            # Ensure the nested dict structure exists
            section = self.config
            for key in config_path[:-1]:
                section = section.setdefault(key, {})
            section[config_path[-1]] = value

        for env_key, config_path in self._ENV_LOGGING_OVERRIDES:
            value = os.environ.get(env_key, "").strip()
            if not value:
                continue
            section = self.config
            for key in config_path[:-1]:
                section = section.setdefault(key, {})
            section[config_path[-1]] = value

    @property
    def loaded_from(self) -> Path | None:
        """Return the path of the loaded configuration file."""
        return self._loaded_from

    def set(self, *keys: str, value: Any) -> None:
        """
        Set a configuration value by nested key path and persist to disk.

        Usage:
            config.set("diarization", "parallel", value=False)

        Updates the in-memory config dict, then writes the full config
        back to the YAML file it was loaded from.

        Raises:
            RuntimeError: If no config file was loaded (nothing to write to).
            TypeError: If any key argument is not a string.
        """
        if not keys:
            raise ValueError("At least one key is required")

        for i, key in enumerate(keys):
            if not isinstance(key, str):
                raise TypeError(
                    f"All configuration keys must be strings, got {type(key).__name__} "
                    f"for keys[{i}]: {repr(key)}."
                )

        if self._loaded_from is None:
            raise RuntimeError("Cannot persist config: no config file was loaded")

        # Update in-memory config
        section = self.config
        for key in keys[:-1]:
            section = section.setdefault(key, {})
        section[keys[-1]] = value

        # Write back to disk
        try:
            with self._loaded_from.open("w", encoding="utf-8") as f:
                yaml.dump(
                    self.config,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
        except PermissionError:
            fallback_candidates = [
                Path("/user-config/config.yaml"),
                Path("/data/config/config.yaml"),
            ]
            written = False
            for fallback in fallback_candidates:
                try:
                    fallback.parent.mkdir(parents=True, exist_ok=True)
                    with fallback.open("w", encoding="utf-8") as f:
                        yaml.dump(
                            self.config,
                            f,
                            default_flow_style=False,
                            allow_unicode=True,
                            sort_keys=False,
                        )
                    logger.warning(
                        "Config file %s is read-only; persisted to fallback %s",
                        self._loaded_from,
                        fallback,
                    )
                    self._loaded_from = fallback
                    written = True
                    break
                except Exception:
                    continue
            if not written:
                raise PermissionError(
                    f"Cannot write config to {self._loaded_from} or any fallback path"
                ) from None

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get a configuration value by dot-separated path.

        Supports nested key access with multiple arguments:
            config.get("transcription", "model")  # Returns config["transcription"]["model"]
            config.get("logging", "level", default="INFO")  # Nested with default
            config.get("audio_processing", default={})  # Single key with default

        Args:
            *keys: One or more string configuration keys for nested access
            default: Default value to return if any key in the path is not found

        Returns:
            Configuration value at the specified path, or default if not found

        Raises:
            TypeError: If any key argument is not a string
        """
        if not keys:
            return self.config

        # Validate all keys are strings (catches cfg.get("key", {}) mistake early)
        for i, key in enumerate(keys):
            if not isinstance(key, str):
                # Provide helpful error message for common mistake
                raise TypeError(
                    f"All configuration keys must be strings, got {type(key).__name__} "
                    f"for keys[{i}]: {repr(key)}. "
                    f"If you want to provide a default value, use the 'default=' keyword argument: "
                    f"cfg.get({', '.join(repr(k) for k in keys[:i] if isinstance(k, str))}, default={repr(key)})"
                )

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
    def transcription(self) -> dict[str, Any]:
        """Get transcription configuration."""
        return self.config.get("transcription", {})

    @property
    def server(self) -> dict[str, Any]:
        """Get server configuration."""
        return self.config.get("server", {})

    @property
    def logging(self) -> dict[str, Any]:
        """Get logging configuration."""
        return self.config.get("logging", {})

    @property
    def audio_notebook(self) -> dict[str, Any]:
        """Get audio notebook configuration."""
        return self.config.get("audio_notebook", {})

    @property
    def llm(self) -> dict[str, Any]:
        """Get LLM configuration."""
        return self.config.get("llm", {})

    @property
    def auth(self) -> dict[str, Any]:
        """Get authentication configuration."""
        return self.config.get("auth", {})

    @property
    def stt(self) -> dict[str, Any]:
        """Get STT (speech-to-text) configuration."""
        return self.config.get("stt", {})


def _non_empty_string(value: Any) -> str | None:
    """Return a trimmed string only when value is a non-empty string."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


def is_disabled_model_value(value: Any) -> bool:
    """Return True when *value* intentionally disables a model slot."""
    if not isinstance(value, str):
        return False
    return value.strip() == DISABLED_MODEL_SENTINEL


def _dict_get(payload: dict[str, Any], *keys: str) -> Any:
    """Safely fetch a nested value from a plain dict."""
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve_main_transcriber_model(config: ServerConfig | dict[str, Any]) -> str:
    """
    Resolve the main transcription model from config with a single fallback.

    This is the canonical resolver used across backend modules so defaults are
    not duplicated in multiple files.
    """
    if isinstance(config, ServerConfig):
        main_model = _non_empty_string(config.get("main_transcriber", "model"))
        legacy_model = _non_empty_string(config.get("transcription", "model"))
    else:
        main_model = _non_empty_string(_dict_get(config, "main_transcriber", "model"))
        legacy_model = _non_empty_string(_dict_get(config, "transcription", "model"))

    if is_disabled_model_value(main_model) or is_disabled_model_value(legacy_model):
        return ""

    return main_model or legacy_model or FALLBACK_MAIN_TRANSCRIBER_MODEL


def resolve_live_transcriber_model(config: ServerConfig | dict[str, Any]) -> str:
    """
    Resolve the live transcription model from config.

    Per server/config.yaml, live_transcriber.model defaults to
    main_transcriber.model when not explicitly set.
    """
    if isinstance(config, ServerConfig):
        live_model = _non_empty_string(config.get("live_transcriber", "model"))
        legacy_live_model = _non_empty_string(config.get("live_transcription", "model"))
    else:
        live_model = _non_empty_string(_dict_get(config, "live_transcriber", "model"))
        legacy_live_model = _non_empty_string(_dict_get(config, "live_transcription", "model"))

    if is_disabled_model_value(live_model) or is_disabled_model_value(legacy_live_model):
        return ""

    return live_model or legacy_live_model or resolve_main_transcriber_model(config)


# Global config instance
_config: ServerConfig | None = None


def get_config(config_path: Path | None = None) -> ServerConfig:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = ServerConfig(config_path)
    return _config
