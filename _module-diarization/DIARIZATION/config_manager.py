#!/usr/bin/env python3
"""
Configuration manager for the diarization module.

Handles loading and validating configuration from YAML file,
providing defaults for missing values.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

# Load .env file from the project root
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)


class ConfigManager:
    """Manages configuration loading and validation for the diarization module."""

    DEFAULT_CONFIG = {
        "diarization": {
            "model": "pyannote/speaker-diarization-3.1",
            "device": "cuda",
            "min_speakers": None,
            "max_speakers": None,
            "min_duration_on": 0.0,
            "min_duration_off": 0.0,
            "merge_gap_threshold": 0.5,
        },
        "processing": {
            "temp_dir": "/tmp/transcription-suite",
            "keep_temp_files": False,
            "sample_rate": 16000,
        },
        "logging": {
            "level": "INFO",
            "file_name": "transcription_suite.log",
            "console_output": False,
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the configuration manager.

        Args:
            config_path: Path to the configuration file. If None, uses unified config at project root.
        """
        if config_path is None:
            # Look for unified config.yaml at project root
            script_dir = Path(__file__).parent
            project_root = (
                script_dir.parent.parent
            )  # DIARIZATION -> _module-diarization -> TranscriptionSuite
            config_path = str(project_root / "config.yaml")

        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file, merging with defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    file_config = yaml.safe_load(f) or {}
                # Merge with defaults
                self.config = self._deep_merge(self.DEFAULT_CONFIG.copy(), file_config)
                logging.info(f"Configuration loaded from {self.config_path}")
            except Exception as e:
                logging.error(f"Error loading configuration: {e}")
                logging.info("Using default configuration")
                self.config = self.DEFAULT_CONFIG.copy()
        else:
            logging.warning(f"Configuration file not found at {self.config_path}")
            logging.info("Using default configuration")
            self.config = self.DEFAULT_CONFIG.copy()
            # Create the config file with defaults
            self._save_default_config()

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """
        Deep merge two dictionaries, with override values taking precedence.

        Args:
            base: The base dictionary
            override: The dictionary with values to override

        Returns:
            Merged dictionary
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _save_default_config(self) -> None:
        """Save the default configuration to file."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w") as f:
                yaml.dump(
                    self.DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False
                )
            logging.info(f"Default configuration saved to {self.config_path}")
        except Exception as e:
            logging.error(f"Could not save default configuration: {e}")

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation or nested keys.

        For the HuggingFace token, this method will:
        1. First check the HF_TOKEN environment variable
        2. Then check the cached token from huggingface-cli login

        Args:
            *keys: Configuration keys to traverse
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        # Handle legacy pyannote.* keys by mapping to diarization.*
        if keys and keys[0] == "pyannote":
            keys = ("diarization",) + keys[1:]

        # Special handling for HuggingFace token - always from env or cached
        if keys == ("diarization", "hf_token"):
            # 1. Check HF_TOKEN environment variable
            env_token = os.environ.get("HF_TOKEN")
            if env_token:
                return env_token

            # 2. Try to get cached token from huggingface-cli login
            try:
                from huggingface_hub import get_token

                cached_token = get_token()
                if cached_token:
                    logging.debug("Using cached HuggingFace token from huggingface-cli")
                    return cached_token
            except ImportError:
                pass
            except Exception as e:
                logging.debug(f"Could not get cached HF token: {e}")

            return None

        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    def validate(self) -> bool:
        """
        Validate the configuration for required values.

        Returns:
            True if configuration is valid, False otherwise
        """
        # Check for HuggingFace token
        hf_token = self.get("diarization", "hf_token")
        if not hf_token:
            logging.error("HuggingFace token is required but not set")
            logging.error("Please run: huggingface-cli login")
            logging.error("Get a token from: https://huggingface.co/settings/tokens")
            return False

        # Check device availability
        device = self.get("diarization", "device")
        if device == "cuda":
            try:
                import torch

                if not torch.cuda.is_available():
                    logging.warning(
                        "CUDA requested but not available, falling back to CPU"
                    )
                    self.config["diarization"]["device"] = "cpu"
            except ImportError:
                logging.error("PyTorch not installed")
                return False

        return True
