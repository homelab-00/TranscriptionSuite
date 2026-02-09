"""Helpers for Live Mode language/task configuration."""

from __future__ import annotations

from typing import Any, Protocol


class LiveModeConfigSource(Protocol):
    """Config interface required by Live Mode config helpers."""

    def get(self, *keys: str, default: Any = None) -> Any: ...

    def get_server_config(self, *keys: str, default: Any = None) -> Any: ...


def resolve_live_mode_language(config: LiveModeConfigSource) -> str:
    """
    Resolve the Live Mode language code.

    Priority:
    1. live_transcriber.live_language
    2. longform_recording.language
    3. Auto-detect (empty string)
    """
    live_language = config.get_server_config(
        "live_transcriber", "live_language", default=None
    )
    if live_language is None:
        live_language = config.get_server_config(
            "longform_recording", "language", default=None
        )
    return live_language or ""


def resolve_live_mode_translation_config(
    config: LiveModeConfigSource,
) -> tuple[bool, str]:
    """Resolve Live Mode translation flags."""
    enabled = bool(
        config.get_server_config(
            "live_transcriber",
            "translation_enabled",
            default=False,
        )
    )
    target = config.get_server_config(
        "live_transcriber", "translation_target_language", default="en"
    )
    return enabled, (target or "en")


def build_live_mode_start_config(
    config: LiveModeConfigSource,
) -> tuple[dict[str, Any], str]:
    """Build Live Mode websocket start config and effective Whisper task."""
    main_model = config.get_server_config(
        "main_transcriber",
        "model",
        default="Systran/faster-whisper-large-v3",
    )
    live_model = config.get_server_config("live_transcriber", "model", default=None)
    translation_enabled, translation_target = resolve_live_mode_translation_config(
        config
    )

    payload = {
        "model": live_model or main_model,
        "language": resolve_live_mode_language(config),
        "translation_enabled": translation_enabled,
        "translation_target_language": translation_target,
        "post_speech_silence_duration": config.get(
            "live_mode",
            "grace_period",
            default=1.0,
        ),
    }
    task = "translate" if translation_enabled else "transcribe"
    return payload, task
