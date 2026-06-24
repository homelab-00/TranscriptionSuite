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


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *overlay* onto *base*, returning a NEW dict.

    - When a key holds a dict on BOTH sides, merge recursively.
    - Otherwise the overlay value replaces the base value. Scalars, lists,
      ``None`` and type mismatches all replace wholesale; lists are never
      concatenated (every list in config.yaml is an atomic value-list).

    Neither input is mutated.
    """
    merged: dict[str, Any] = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = _deep_merge(base_value, overlay_value)
        else:
            merged[key] = overlay_value
    return merged


def get_user_config_dir() -> Path:
    """
    Get the user configuration directory based on platform.

    Returns:
        Path to user config directory:
        - Linux: ~/.config/TranscriptionSuite/
        - macOS: ~/Library/Application Support/TranscriptionSuite/
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
    elif sys.platform == "darwin":
        # macOS: ~/Library/Application Support/TranscriptionSuite/
        return Path.home() / "Library" / "Application Support" / "TranscriptionSuite"
    else:
        # Linux: ~/.config/TranscriptionSuite/
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
        self._defaults_path: Path | None = None
        self._overlay_path: Path | None = None
        self._load_config()

    @staticmethod
    def _is_readable(path: Path) -> bool:
        """Return True when *path* is an existing, readable file."""
        if not (path.exists() and path.is_file()):
            return False
        try:
            with path.open("r", encoding="utf-8"):
                return True
        except (PermissionError, OSError):
            return False

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        """Parse *path* as a YAML mapping. Empty file -> {}."""
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise yaml.YAMLError(
                f"Config root must be a mapping, got {type(data).__name__}: {path}"
            )
        return data

    def _defaults_candidates(self) -> list[Path]:
        """Readable baked-in default config files (NON-user), priority order."""
        candidates = [
            Path("/app/config.yaml"),  # Docker image default
            Path(__file__).parent.parent / "config.yaml",  # server/config.yaml (dev)
            Path.cwd() / "config.yaml",  # current-directory fallback
        ]
        return [p for p in candidates if self._is_readable(p)]

    def _load_defaults(
        self,
    ) -> tuple[dict[str, Any], Path | None, list[tuple[Path, Exception]]]:
        """Load the highest-priority readable, parseable defaults file."""
        errors: list[tuple[Path, Exception]] = []
        for path in self._defaults_candidates():
            try:
                return self._read_yaml(path), path, errors
            except (yaml.YAMLError, OSError) as e:
                print(f"ERROR: Could not load defaults config {path}: {e}")
                errors.append((path, e))
        return {}, None, errors

    def _load_overlay(self) -> tuple[dict[str, Any], Path | None]:
        """Load the sparse user overlay file if present and valid."""
        path = get_user_config_dir() / "config.yaml"
        if not self._is_readable(path):
            return {}, None
        try:
            return self._read_yaml(path), path
        except (yaml.YAMLError, OSError) as e:
            print(f"WARNING: Ignoring invalid user config overlay {path}: {e}")
            return {}, None

    def _load_config(self) -> None:
        """Load configuration.

        Normal mode: deep-merge a sparse user overlay onto the baked-in
        defaults (defaults < overlay < environment variables). Explicit
        ``config_path`` mode: load that single file as-is (no merge).
        """
        if self._config_path is not None:
            if not self._is_readable(self._config_path):
                raise RuntimeError(
                    f"Configuration file not found or unreadable: {self._config_path}"
                )
            try:
                self.config = self._read_yaml(self._config_path)
            except (yaml.YAMLError, OSError) as e:
                raise RuntimeError(
                    f"Failed to load configuration from {self._config_path}: {e}"
                ) from e
            self._defaults_path = self._config_path
            self._overlay_path = self._config_path
            self._loaded_from = self._config_path
            self._apply_env_overrides()
            print(f"Loaded configuration from: {self._config_path}")
            return

        base_dict, base_path, base_errors = self._load_defaults()
        overlay_dict, overlay_path = self._load_overlay()

        if base_path is None and overlay_path is None:
            details = "\n".join(f"  - {p}: {e}" for p, e in base_errors)
            raise RuntimeError(
                "No configuration file found. Expected baked-in defaults at "
                "/app/config.yaml or server/config.yaml, or a user overlay at "
                f"{get_user_config_dir() / 'config.yaml'}." + ("\n" + details if details else "")
            )

        if base_path is None:
            print(
                "WARNING: No valid defaults config found; using user overlay "
                f"only ({overlay_path})."
            )

        self.config = _deep_merge(base_dict, overlay_dict)
        self._defaults_path = base_path
        self._overlay_path = overlay_path or (get_user_config_dir() / "config.yaml")
        self._loaded_from = self._overlay_path
        self._apply_env_overrides()
        print(
            f"Loaded configuration: defaults={base_path}, "
            f"overlay={overlay_path if overlay_path else '(none)'}"
        )

    _ENV_MODEL_OVERRIDES = (
        ("MAIN_TRANSCRIBER_MODEL", ("main_transcriber", "model")),
        ("LIVE_TRANSCRIBER_MODEL", ("live_transcriber", "model")),
        ("DIARIZATION_MODEL", ("diarization", "model")),
        ("WHISPERCPP_SERVER_URL", ("whisper_cpp", "server_url")),
        ("WHISPERCPP_CHUNK_DURATION_S", ("whisper_cpp", "chunk_duration_s")),
        ("WHISPERCPP_INFERENCE_TIMEOUT_S", ("whisper_cpp", "inference_timeout_s")),
        (
            "WHISPERCPP_TIMEOUT_SECONDS_PER_AUDIO_SECOND",
            ("whisper_cpp", "timeout_seconds_per_audio_second"),
        ),
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

    @property
    def defaults_path(self) -> Path | None:
        """Path of the baked-in defaults file used as the merge base."""
        return self._defaults_path

    @property
    def overlay_path(self) -> Path | None:
        """Path of the writable user overlay file (where set() persists)."""
        return self._overlay_path

    def set(self, *keys: str, value: Any) -> None:
        """Set a nested config value and persist it as a sparse user overlay.

        Usage:
            config.set("diarization", "parallel", value=False)

        Updates the in-memory effective config, then writes ONLY the changed
        key into the overlay file (creating it if needed). Defaults files are
        never modified.

        Raises:
            RuntimeError: If no overlay path is known (nothing to write to).
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

        if self._overlay_path is None:
            raise RuntimeError("Cannot persist config: no overlay path")

        # 1. Update the in-memory effective config.
        self._set_nested(self.config, keys, value)

        # 2. Persist as a sparse overlay (load-or-create, set one key, dump).
        overlay: dict[str, Any] = {}
        if self._overlay_path.exists():
            try:
                overlay = self._read_yaml(self._overlay_path)
            except (yaml.YAMLError, OSError):
                overlay = {}
        self._set_nested(overlay, keys, value)
        self._dump_overlay(overlay)

    @staticmethod
    def _set_nested(target: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
        """Set ``target[keys[0]][...][keys[-1]] = value``, creating dicts."""
        section = target
        for key in keys[:-1]:
            nxt = section.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                section[key] = nxt
            section = nxt
        section[keys[-1]] = value

    def _dump_overlay(self, overlay: dict[str, Any]) -> None:
        """Dump *overlay* to the overlay path, with a read-only fallback chain."""
        fallbacks = [
            p
            for p in (Path("/user-config/config.yaml"), Path("/data/config/config.yaml"))
            if p != self._overlay_path
        ]
        last_error: Exception | None = None
        for target in [self._overlay_path, *fallbacks]:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("w", encoding="utf-8") as f:
                    yaml.dump(
                        overlay,
                        f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                if target != self._overlay_path:
                    logger.warning(
                        "Config overlay %s is not writable; persisted to %s",
                        self._overlay_path,
                        target,
                    )
                    self._overlay_path = target
                    self._loaded_from = target
                return
            except (PermissionError, OSError) as e:
                last_error = e
                continue
        raise PermissionError(
            f"Cannot write config overlay to {self._overlay_path} or any fallback path"
        ) from last_error

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

    @property
    def whisper_cpp(self) -> dict[str, Any]:
        """Get whisper.cpp sidecar configuration."""
        return self.config.get("whisper_cpp", {})


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


def reload_config() -> None:
    """Invalidate the global config singleton, forcing a reload from disk on next access."""
    global _config
    _config = None
