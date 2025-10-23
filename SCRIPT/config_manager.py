#!/usr/bin/env python3
"""
Configuration management for the TranscriptionSuite.

Handles loading the config file from disk, creating a default if it doesn't exist,
and saving changes.
"""

try:
    import yaml
except ImportError as import_error:
    raise ImportError(
        "PyYAML is required for configuration. Please run 'pip install pyyaml'."
    ) from import_error

import os
import logging
import copy
from typing import Any, Dict, Mapping, MutableMapping, cast
from pathlib import Path

from platform_utils import get_platform_manager
from utils import safe_print


class ConfigManager:
    """Manages loading, saving, and accessing configuration settings."""

    def __init__(self, config_path: str):
        """Initialize with configuration file path."""
        self.config_path_str = config_path
        self.config: Dict[str, Any] = {}
        self.platform_manager = get_platform_manager()
        self.config_path: Path

    def load_or_create_config(self) -> Dict[str, Any]:
        """Load configuration from file or create it if it doesn't exist."""
        script_dir = Path(__file__).resolve().parent
        # Define default configuration
        default_config: Dict[str, Any] = {
            "transcription_options": {
                "language": "en",
                "enable_preview_transcriber": True,
            },
            "display": {
                "show_waveform": True,
            },
            "main_transcriber": {
                "model": "Systran/faster-whisper-large-v3",
                "compute_type": "default",
                "device": self.platform_manager.get_optimal_device_config()["device"],
                "gpu_device_index": 0,
                "batch_size": 16,
                "beam_size": 5,
                "initial_prompt": None,
                "faster_whisper_vad_filter": True,
                "no_log_file": True,
            },
            "preview_transcriber": {
                "model": "Systran/faster-whisper-base",
                "compute_type": "default",
                "device": self.platform_manager.get_optimal_device_config()["device"],
                "gpu_device_index": 0,
                "batch_size": 16,
                "beam_size": 3,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": False,
                "post_speech_silence_duration": 0.5,
                "min_length_of_recording": 1.0,
                "no_log_file": True,
            },
            "audio": {
                "input_device_index": None,
                "use_default_input": True,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
            },
            "formatting": {
                "ensure_sentence_starting_uppercase": True,
                "ensure_sentence_ends_with_period": True,
            },
            "logging": {
                "level": "INFO",
                "console_output": False,
                "file_name": "stt_orchestrator.log",
                "directory": str(script_dir.parent),  # Project root
            },
        }

        # Ensure config directory exists
        config_dir = self.platform_manager.get_config_dir()
        self.config_path = Path(self.config_path_str)
        if not self.config_path.is_absolute():
            self.config_path = config_dir / self.config_path

        # Try to load existing config
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as config_file:
                    loaded_config_raw = yaml.safe_load(config_file)

                loaded_config: Dict[str, Any] = {}
                if isinstance(loaded_config_raw, dict):
                    loaded_config = cast(Dict[str, Any], loaded_config_raw)
                elif loaded_config_raw is not None:
                    logging.warning(
                        "Loaded configuration is not a mapping. "
                        "Ignoring unexpected value of type %s.",
                        type(loaded_config_raw).__name__,
                    )

                # Deep merge loaded config into defaults to ensure all keys exist
                merged_config: Dict[str, Any] = copy.deepcopy(default_config)
                for key, value in loaded_config.items():
                    merged_value = merged_config.get(key)
                    if isinstance(merged_value, MutableMapping) and isinstance(
                        value, Mapping
                    ):
                        merged_value_map = cast(MutableMapping[str, Any], merged_value)
                        incoming_mapping = cast(Mapping[str, Any], value)
                        merged_value_map.update(incoming_mapping)
                    else:
                        merged_config[key] = value

                self.config = merged_config

                logging.info("Configuration loaded from %s", self.config_path)

            except (yaml.YAMLError, OSError) as exception:
                logging.error(
                    "Error loading configuration, using defaults: %s",
                    exception,
                )
                self.config = default_config
                self.save_config()
        else:
            # Config file does not exist, which is a critical error.
            error_message = f"Configuration file not found at: {self.config_path}"
            logging.critical(error_message)
            safe_print(f"\n[bold red]FATAL ERROR:[/bold red] {error_message}")
            safe_print(
                "Please create a 'config.yaml' file at that location.", style="warning"
            )
            safe_print(
                "You can copy the example from the project repository as a template.",
                style="info",
            )
            raise FileNotFoundError(error_message)

        self.config = cast(Dict[str, Any], self._expand_config_paths(self.config))
        self._apply_global_settings()
        return self.config

    def _apply_global_settings(self):
        """
        Apply global settings to the respective transcriber configurations.
        """
        global_options = self.config.get("transcription_options", {})
        language = global_options.get("language")

        if language:
            if "main_transcriber" in self.config:
                self.config["main_transcriber"]["language"] = language
            if "preview_transcriber" in self.config:
                self.config["preview_transcriber"]["language"] = language

    def _expand_config_paths(self, value: Any) -> Any:
        """Recursively expand environment variables and user home in config values."""
        if isinstance(value, dict):
            typed_value = cast(Dict[str, Any], value)
            return {
                key: self._expand_config_paths(item) for key, item in typed_value.items()
            }
        if isinstance(value, list):
            typed_list = cast(list[Any], value)
            return [self._expand_config_paths(item) for item in typed_list]
        if isinstance(value, str):
            expanded = os.path.expandvars(value)
            return os.path.expanduser(expanded)
        return value

    def save_config(self) -> bool:
        """Save the current configuration to a file."""
        try:
            with self.config_path.open("w", encoding="utf-8") as config_file:
                yaml.dump(
                    self.config,
                    config_file,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
            logging.info("Configuration saved to %s", self.config_path)
            return True
        except (OSError, TypeError) as exception:
            logging.error("Error saving configuration: %s", exception)
            return False
