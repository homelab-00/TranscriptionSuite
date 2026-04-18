"""
Model capability helpers for STT translation support.
"""

from __future__ import annotations

import re

_PARAKEET_PATTERN = re.compile(r"^nvidia/(parakeet|nemotron-speech)", re.IGNORECASE)
_CANARY_PATTERN = re.compile(r"^nvidia/canary", re.IGNORECASE)
_VIBEVOICE_ASR_PATTERN = re.compile(r"^[^/]+/vibevoice-asr(?:-[^/]+)?$", re.IGNORECASE)
_MLX_PARAKEET_PATTERN = re.compile(r"^mlx-community/parakeet", re.IGNORECASE)
_MLX_CANARY_PATTERN = re.compile(r"^[^/]+/canary[^/]*-mlx", re.IGNORECASE)


def normalize_model_name(model_name: str | None) -> str:
    """Normalize model name for capability checks."""
    return (model_name or "").strip().lower()


def supports_auto_detect(model_name: str | None) -> bool:
    """
    Return True if the model supports source-language auto-detection.

    Canary models (NVIDIA and the MLX community ports) require an explicit
    ``source_lang`` and have no built-in language detection — exposing an
    "Auto Detect" option for them silently coerces to English and translates
    everything (see GitHub issue #81). Mirrors ``supportsAutoDetect`` in
    dashboard/src/services/modelCapabilities.ts.
    """
    name = normalize_model_name(model_name)
    if not name:
        return True
    if _CANARY_PATTERN.match(name):
        return False
    if _MLX_CANARY_PATTERN.match(name):
        return False
    return True


def supports_english_translation(model_name: str | None) -> bool:
    """
    Return True if the model name likely supports Whisper translate task.

    This is a conservative guard used by UI and backend validation.
    """
    name = normalize_model_name(model_name)
    if not name:
        return True

    # NVIDIA Parakeet and MLX Parakeet are English-only ASR (no translation).
    if _PARAKEET_PATTERN.match(name):
        return False
    if _MLX_PARAKEET_PATTERN.match(name):
        return False
    # MLX Canary port supports ASR only — no translation task.
    if _MLX_CANARY_PATTERN.match(name):
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

    # English-only Whisper variants. The original check only matched names
    # ending literally with ".en" (e.g. OpenAI HF IDs like
    # ``openai/whisper-base.en``), but GGML filenames use the ``.en.bin`` /
    # ``.en.gguf`` convention (``ggml-base.en.bin``) which ends with the
    # extension, not with ``.en``. Match ``.en`` at end-of-string OR followed
    # by a ``.`` so both forms are recognised.
    if re.search(r"\.en($|\.)", name):
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
