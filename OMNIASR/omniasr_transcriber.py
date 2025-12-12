#!/usr/bin/env python3
"""
Core OmniASR transcription module.

This module handles loading Facebook's OmniASR-LLM models and performing
transcription. Supports 1600+ languages with excellent accuracy.

Note: OmniASR does NOT provide word-level timestamps natively.
This implementation focuses on pure transcription output.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

logger = logging.getLogger("omniasr_transcriber")

# Project root for reference
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# =============================================================================
# Language Code Mapping
# =============================================================================
# OmniASR uses {language_code}_{script} format (e.g., eng_Latn, ell_Grek)
# This maps ISO 639-1 codes to OmniASR format for convenience

ISO_TO_OMNIASR: Dict[str, str] = {
    # Major European languages
    "en": "eng_Latn",
    "el": "ell_Grek",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "cs": "ces_Latn",
    "sk": "slk_Latn",
    "hu": "hun_Latn",
    "ro": "ron_Latn",
    "bg": "bul_Cyrl",
    "hr": "hrv_Latn",
    "sr": "srp_Cyrl",
    "sl": "slv_Latn",
    "da": "dan_Latn",
    "sv": "swe_Latn",
    "no": "nob_Latn",
    "fi": "fin_Latn",
    "et": "est_Latn",
    "lv": "lvs_Latn",
    "lt": "lit_Latn",
    # Asian languages
    "zh": "cmn_Hans",  # Simplified Chinese (Mandarin)
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "vi": "vie_Latn",
    "th": "tha_Thai",
    "hi": "hin_Deva",
    "bn": "ben_Beng",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "mr": "mar_Deva",
    "ur": "urd_Arab",
    # Middle Eastern
    "ar": "arb_Arab",
    "he": "heb_Hebr",
    "fa": "pes_Arab",
    "tr": "tur_Latn",
    # Other
    "id": "ind_Latn",
    "ms": "zsm_Latn",
    "tl": "tgl_Latn",
    "sw": "swh_Latn",
}

# Reverse mapping
OMNIASR_TO_ISO: Dict[str, str] = {v: k for k, v in ISO_TO_OMNIASR.items()}


def convert_language_code(lang: str) -> str:
    """
    Convert language code to OmniASR format if needed.

    Args:
        lang: Either ISO 639-1 code (e.g., "el") or OmniASR format (e.g., "ell_Grek")

    Returns:
        Language code in OmniASR format
    """
    # Already in OmniASR format (contains underscore)
    if "_" in lang:
        return lang

    # Try to convert from ISO 639-1
    if lang in ISO_TO_OMNIASR:
        return ISO_TO_OMNIASR[lang]

    # Unknown format, return as-is and let OmniASR handle it
    logger.warning(
        f"Unknown language code '{lang}', passing to OmniASR as-is. "
        f"Supported ISO codes: {list(ISO_TO_OMNIASR.keys())}"
    )
    return lang


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    text: str
    language: str
    duration: float
    processing_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration": round(self.duration, 3),
            "processing_time": round(self.processing_time, 3),
        }


class OmniASRTranscriber:
    """
    Transcriber using Facebook's OmniASR-LLM models.

    This class manages the model lifecycle and provides transcription
    for 1600+ languages.

    Available models:
        - omniASR_LLM_3B: Highest accuracy, ~10GB VRAM
        - omniASR_LLM_1B: Smaller, faster, lower VRAM
    """

    AVAILABLE_MODELS = ["omniASR_LLM_3B", "omniASR_LLM_1B"]
    DEFAULT_MODEL = "omniASR_LLM_3B"

    def __init__(
        self,
        model: str = "omniASR_LLM_3B",
        device: str = "cuda",
        default_language: str = "eng_Latn",
        batch_size: int = 1,
    ):
        """
        Initialize the OmniASR transcriber.

        Args:
            model: Model card name ("omniASR_LLM_3B" or "omniASR_LLM_1B")
            device: Device to run model on ("cuda" or "cpu")
            default_language: Default language code for transcription
            batch_size: Batch size for inference
        """
        self.model_name = model
        self.device = device
        self.default_language = convert_language_code(default_language)
        self.batch_size = batch_size
        self.pipeline: Optional[Any] = None
        self._model_loaded = False

        if model not in self.AVAILABLE_MODELS:
            logger.warning(
                f"Model '{model}' not in known models {self.AVAILABLE_MODELS}. "
                f"Proceeding anyway."
            )

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model_loaded and self.pipeline is not None

    def load_model(self) -> None:
        """Load the OmniASR model into memory."""
        if self._model_loaded:
            logger.info("Model already loaded")
            return

        logger.info(f"Loading OmniASR model: {self.model_name}")
        start_time = time.time()

        try:
            from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline

            # Initialize the pipeline
            self.pipeline = ASRInferencePipeline(model_card=self.model_name)

            self._model_loaded = True
            load_time = time.time() - start_time
            logger.info(f"Model loaded successfully in {load_time:.2f}s")

            # Log VRAM usage
            if self.device == "cuda" and torch.cuda.is_available():
                vram_used = torch.cuda.memory_allocated() / 1024**3
                logger.info(f"VRAM used: {vram_used:.2f} GB")

        except ImportError as e:
            logger.error(
                f"Failed to import omnilingual_asr. "
                f"Install with: uv add omnilingual-asr\n{e}"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to load model: {e}", exc_info=True)
            raise

    def unload_model(self) -> None:
        """Unload the model to free memory."""
        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None
            self._model_loaded = False

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("Model unloaded")

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (ISO 639-1 or OmniASR format)
                     If None, uses default_language

        Returns:
            TranscriptionResult with transcribed text
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # Validate audio file exists
        audio_path_obj = Path(audio_path)
        if not audio_path_obj.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Convert language code
        lang = convert_language_code(language) if language else self.default_language

        logger.info(f"Transcribing: {audio_path} (language: {lang})")
        start_time = time.time()

        try:
            # Get audio duration
            import soundfile as sf

            audio_data, sample_rate = sf.read(str(audio_path))
            duration = len(audio_data) / sample_rate

            # Run transcription
            transcriptions = self.pipeline.transcribe(
                [str(audio_path)],
                lang=[lang],
                batch_size=self.batch_size,
            )

            # Extract text from result
            text = ""
            if transcriptions and len(transcriptions) > 0:
                text = (
                    transcriptions[0]
                    if isinstance(transcriptions[0], str)
                    else str(transcriptions[0])
                )

            processing_time = time.time() - start_time

            result = TranscriptionResult(
                text=text.strip(),
                language=lang,
                duration=duration,
                processing_time=processing_time,
            )

            logger.info(
                f"Transcription complete: {len(text)} chars in {processing_time:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            raise

    def transcribe_batch(
        self,
        audio_paths: List[str],
        languages: Optional[List[str]] = None,
    ) -> List[TranscriptionResult]:
        """
        Transcribe multiple audio files in a batch.

        Args:
            audio_paths: List of paths to audio files
            languages: List of language codes (one per file, or single for all)

        Returns:
            List of TranscriptionResult objects
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # Validate files exist
        for path in audio_paths:
            if not Path(path).exists():
                raise FileNotFoundError(f"Audio file not found: {path}")

        # Handle language codes
        if languages is None:
            langs = [self.default_language] * len(audio_paths)
        elif len(languages) == 1:
            langs = [convert_language_code(languages[0])] * len(audio_paths)
        else:
            langs = [convert_language_code(lang) for lang in languages]

        logger.info(f"Batch transcribing {len(audio_paths)} files")
        start_time = time.time()

        try:
            import soundfile as sf

            # Get durations
            durations = []
            for path in audio_paths:
                audio_data, sample_rate = sf.read(str(path))
                durations.append(len(audio_data) / sample_rate)

            # Run batch transcription
            transcriptions = self.pipeline.transcribe(
                [str(p) for p in audio_paths],
                lang=langs,
                batch_size=self.batch_size,
            )

            processing_time = time.time() - start_time

            # Build results
            results = []
            for i, text in enumerate(transcriptions or []):
                text_str = text if isinstance(text, str) else str(text)
                results.append(
                    TranscriptionResult(
                        text=text_str.strip(),
                        language=langs[i],
                        duration=durations[i],
                        processing_time=processing_time / len(audio_paths),
                    )
                )

            logger.info(
                f"Batch transcription complete: {len(results)} files in {processing_time:.2f}s"
            )

            return results

        except Exception as e:
            logger.error(f"Batch transcription failed: {e}", exc_info=True)
            raise

    def get_status(self) -> Dict[str, Any]:
        """Get transcriber status information."""
        status = {
            "model": self.model_name,
            "device": self.device,
            "default_language": self.default_language,
            "batch_size": self.batch_size,
            "is_loaded": self.is_loaded,
        }

        if self.is_loaded and torch.cuda.is_available():
            status["vram_used_gb"] = round(torch.cuda.memory_allocated() / 1024**3, 2)

        return status


# =============================================================================
# Module-level singleton
# =============================================================================

_transcriber_instance: Optional[OmniASRTranscriber] = None


def get_transcriber(
    model: str = "omniASR_LLM_3B",
    device: str = "cuda",
    default_language: str = "eng_Latn",
    batch_size: int = 1,
) -> OmniASRTranscriber:
    """
    Get or create the singleton transcriber instance.

    Args:
        model: Model card name
        device: Device for inference
        default_language: Default language code
        batch_size: Batch size for inference

    Returns:
        OmniASRTranscriber instance
    """
    global _transcriber_instance

    if _transcriber_instance is None:
        _transcriber_instance = OmniASRTranscriber(
            model=model,
            device=device,
            default_language=default_language,
            batch_size=batch_size,
        )

    return _transcriber_instance


def reset_transcriber() -> None:
    """Reset the singleton transcriber instance."""
    global _transcriber_instance
    if _transcriber_instance is not None:
        _transcriber_instance.unload_model()
        _transcriber_instance = None
