"""
OmniASR transcription module using Facebook's OmniASR-LLM models.

This module provides multilingual transcription using Meta's OmniASR model,
which supports 1600+ languages with state-of-the-art accuracy.

Available models:
    - omniASR_LLM_3B: 4.38B parameters, ~10GB VRAM, highest accuracy
    - omniASR_LLM_1B: Smaller variant, lower VRAM requirements

Usage:
    from OMNIASR import OmniASRTranscriber, transcribe_file

    # Quick transcription
    result = transcribe_file("audio.wav", language="ell_Grek")

    # Or use the transcriber for more control
    transcriber = OmniASRTranscriber()
    transcriber.load_model()
    result = transcriber.transcribe("audio.wav", language="ell_Grek")

    # Or use the service for persistent model loading
    from OMNIASR import OmniASRService, transcribe_audio
    result = transcribe_audio("audio.wav", language="ell_Grek")

Language codes use the format: {language_code}_{script}
Examples: eng_Latn (English), ell_Grek (Greek), deu_Latn (German)
"""

from .omniasr_transcriber import (
    OmniASRTranscriber,
    TranscriptionResult,
    get_transcriber,
    ISO_TO_OMNIASR,
    OMNIASR_TO_ISO,
)
from .service import (
    OmniASRService,
    OmniASRTranscriptionResult,
    transcribe_audio,
    get_server_status,
    shutdown_server,
    get_service,
)

__version__ = "1.0.0"


def transcribe_file(
    audio_path: str,
    language: str = "eng_Latn",
) -> TranscriptionResult:
    """
    Quick transcription function for simple use cases.

    Args:
        audio_path: Path to the audio file
        language: Language code in OmniASR format ({lang}_{script})
                  or ISO 639-1 format (auto-converted)

    Returns:
        TranscriptionResult with transcribed text
    """
    transcriber = get_transcriber()
    if not transcriber.is_loaded:
        transcriber.load_model()
    return transcriber.transcribe(audio_path, language=language)


__all__ = [
    "OmniASRTranscriber",
    "OmniASRService",
    "OmniASRTranscriptionResult",
    "TranscriptionResult",
    "transcribe_file",
    "transcribe_audio",
    "get_transcriber",
    "get_service",
    "get_server_status",
    "shutdown_server",
    "ISO_TO_OMNIASR",
    "OMNIASR_TO_ISO",
]
