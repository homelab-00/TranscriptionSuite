"""
Shared Whisper language options for Dashboard UI controls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QComboBox


WHISPER_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("Afrikaans", "af"),
    ("Amharic", "am"),
    ("Arabic", "ar"),
    ("Assamese", "as"),
    ("Azerbaijani", "az"),
    ("Bashkir", "ba"),
    ("Belarusian", "be"),
    ("Bulgarian", "bg"),
    ("Bengali", "bn"),
    ("Tibetan", "bo"),
    ("Breton", "br"),
    ("Bosnian", "bs"),
    ("Catalan", "ca"),
    ("Czech", "cs"),
    ("Welsh", "cy"),
    ("Danish", "da"),
    ("German", "de"),
    ("Greek", "el"),
    ("English", "en"),
    ("Spanish", "es"),
    ("Estonian", "et"),
    ("Basque", "eu"),
    ("Persian", "fa"),
    ("Finnish", "fi"),
    ("Faroese", "fo"),
    ("French", "fr"),
    ("Galician", "gl"),
    ("Gujarati", "gu"),
    ("Hausa", "ha"),
    ("Hawaiian", "haw"),
    ("Hebrew", "he"),
    ("Hindi", "hi"),
    ("Croatian", "hr"),
    ("Haitian Creole", "ht"),
    ("Hungarian", "hu"),
    ("Armenian", "hy"),
    ("Indonesian", "id"),
    ("Icelandic", "is"),
    ("Italian", "it"),
    ("Japanese", "ja"),
    ("Javanese", "jw"),
    ("Georgian", "ka"),
    ("Kazakh", "kk"),
    ("Khmer", "km"),
    ("Kannada", "kn"),
    ("Korean", "ko"),
    ("Latin", "la"),
    ("Luxembourgish", "lb"),
    ("Lingala", "ln"),
    ("Lao", "lo"),
    ("Lithuanian", "lt"),
    ("Latvian", "lv"),
    ("Malagasy", "mg"),
    ("Maori", "mi"),
    ("Macedonian", "mk"),
    ("Malayalam", "ml"),
    ("Mongolian", "mn"),
    ("Marathi", "mr"),
    ("Malay", "ms"),
    ("Maltese", "mt"),
    ("Burmese", "my"),
    ("Nepali", "ne"),
    ("Dutch", "nl"),
    ("Norwegian Nynorsk", "nn"),
    ("Norwegian", "no"),
    ("Occitan", "oc"),
    ("Punjabi", "pa"),
    ("Polish", "pl"),
    ("Pashto", "ps"),
    ("Portuguese", "pt"),
    ("Romanian", "ro"),
    ("Russian", "ru"),
    ("Sanskrit", "sa"),
    ("Sindhi", "sd"),
    ("Sinhala", "si"),
    ("Slovak", "sk"),
    ("Slovenian", "sl"),
    ("Shona", "sn"),
    ("Somali", "so"),
    ("Albanian", "sq"),
    ("Serbian", "sr"),
    ("Sundanese", "su"),
    ("Swedish", "sv"),
    ("Swahili", "sw"),
    ("Tamil", "ta"),
    ("Telugu", "te"),
    ("Tajik", "tg"),
    ("Thai", "th"),
    ("Turkmen", "tk"),
    ("Tagalog", "tl"),
    ("Turkish", "tr"),
    ("Tatar", "tt"),
    ("Ukrainian", "uk"),
    ("Urdu", "ur"),
    ("Uzbek", "uz"),
    ("Vietnamese", "vi"),
    ("Yiddish", "yi"),
    ("Yoruba", "yo"),
    ("Chinese", "zh"),
    ("Cantonese", "yue"),
)


def get_whisper_languages(
    include_auto_detect: bool = True,
) -> tuple[tuple[str, str], ...]:
    """Return the full Whisper language list used by dashboard dropdowns."""
    if include_auto_detect:
        return (("Auto-detect", ""), *WHISPER_LANGUAGES)
    return WHISPER_LANGUAGES


def populate_language_combo(
    combo: "QComboBox", include_auto_detect: bool = True
) -> None:
    """Populate a QComboBox with Whisper languages."""
    combo.clear()
    for name, code in get_whisper_languages(include_auto_detect=include_auto_detect):
        combo.addItem(name, code)


def set_combo_language(combo: "QComboBox", language_code: str | None) -> None:
    """Set combo to the given language code (None/empty = auto-detect)."""
    target = language_code or ""
    for i in range(combo.count()):
        if combo.itemData(i) == target:
            combo.setCurrentIndex(i)
            return
    combo.setCurrentIndex(0)
