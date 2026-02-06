"""
Client-side model capability checks.
"""

from __future__ import annotations


def normalize_model_name(model_name: str | None) -> str:
    """Normalize model name for capability checks."""
    return (model_name or "").strip().lower()


def translation_unsupported_reason(model_name: str | None) -> str | None:
    """Return reason string if model likely does not support translation."""
    name = normalize_model_name(model_name)
    if not name:
        return None

    if "turbo" in name:
        return "Whisper turbo variants are not intended for translation."

    if name.endswith(".en"):
        return (
            "English-only Whisper models (.en) cannot translate from other languages."
        )

    if "distil-whisper/distil-large-v3" in name or "distil-large-v3" in name:
        return (
            "distil-large-v3 is English-focused and not suitable for translation mode."
        )

    return None


def supports_english_translation(model_name: str | None) -> bool:
    """Return True if model likely supports source-language -> English translation."""
    return translation_unsupported_reason(model_name) is None
