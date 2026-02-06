"""
Model capability helpers for STT translation support.
"""

from __future__ import annotations


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

    target = (translation_target_language or "en").strip().lower()
    if target != "en":
        raise ValueError(
            "Translation target language must be 'en' for v1 (English-only translation)."
        )

    if not supports_english_translation(model_name):
        raise ValueError(
            "Selected model does not support translation. Choose a multilingual non-turbo Whisper model."
        )

    return target
