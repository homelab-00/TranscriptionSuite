"""
Model capability helpers for STT translation support.
"""

from __future__ import annotations

import re

_PARAKEET_PATTERN = re.compile(r"^nvidia/(parakeet|nemotron-speech)", re.IGNORECASE)
_CANARY_PATTERN = re.compile(r"^nvidia/canary", re.IGNORECASE)
_VIBEVOICE_ASR_PATTERN = re.compile(r"^[^/]+/vibevoice-asr(?:-[^/]+)?$", re.IGNORECASE)


def normalize_model_name(model_name: str | None) -> str:
    """Normalize model name for capability checks."""
    return (model_name or "").strip().lower()


def supports_english_translation(model_name: str | None) -> bool:
    """
    Return True if the model name likely supports Whisper translate task.

    This is a conservative guard used by UI and backend validation.
    """
    name = normalize_model_name(model_name)
    if not name:
        return True

    # NVIDIA Parakeet / NeMo ASR-only models (no translation).
    if _PARAKEET_PATTERN.match(name):
        return False

    # NVIDIA Canary models support X↔English translation.
    if _CANARY_PATTERN.match(name):
        return True

    # VibeVoice-ASR is ASR + diarization only (no translation support in v1 integration).
    if _VIBEVOICE_ASR_PATTERN.match(name):
        return False

    # Whisper turbo is not intended for translation.
    if "turbo" in name:
        return False

    # English-only Whisper variants.
    if name.endswith(".en") or "/whisper-" in name and name.endswith(".en"):
        return False

    # Distil large-v3 is English-focused ASR.
    if "distil-whisper/distil-large-v3" in name or "distil-large-v3" in name:
        return False

    return True


def validate_translation_request(
    *,
    model_name: str | None,
    task: str,
    translation_target_language: str | None,
) -> str:
    """
    Validate translation request and return normalized target language.

    Raises ValueError for invalid translation settings.
    """
    normalized_task = (task or "transcribe").strip().lower()
    if normalized_task != "translate":
        return "en"

    if not supports_english_translation(model_name):
        raise ValueError(
            "Selected model does not support translation. Choose a multilingual Whisper or Canary model."
        )

    target = (translation_target_language or "en").strip().lower()

    # Canary supports bidirectional translation: any EU language is a valid target.
    if _CANARY_PATTERN.match(normalize_model_name(model_name)):
        return target

    # All other models (Whisper) only support English as the translation target.
    if target != "en":
        raise ValueError(
            "Translation target language must be 'en' for this model (English-only translation)."
        )

    return target
