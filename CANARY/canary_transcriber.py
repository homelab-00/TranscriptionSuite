#!/usr/bin/env python3
"""
Core Canary transcription module.

This module handles loading the NeMo Canary-1B-v2 model and performing
transcription with word-level timestamps.

Now integrated directly into _core (Python 3.11) - no subprocess needed!

NOTE: TMPDIR is configured in orchestrator.py's startup block before this
module is imported. This ensures NeMo uses a project-local temp directory
instead of /tmp (which may have user quotas on tmpfs).
"""

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger("canary_transcriber")

# Project root for cache directory reference in error messages
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NEMO_CACHE_DIR = _PROJECT_ROOT / ".cache" / "nemo_tmp"


@dataclass
class WordTimestamp:
    """Represents a word with timing information."""

    word: str
    start: float
    end: float
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    text: str
    language: str
    duration: float
    word_timestamps: List[WordTimestamp] = field(default_factory=list)
    processing_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration": round(self.duration, 3),
            "word_timestamps": [w.to_dict() for w in self.word_timestamps],
            "processing_time": round(self.processing_time, 3),
        }


class CanaryTranscriber:
    """
    Transcriber using NeMo Canary-1B-v2 model.

    This class manages the model lifecycle and provides transcription
    with word-level timestamps.
    """

    MODEL_NAME = "nvidia/canary-1b-v2"
    SUPPORTED_LANGUAGES = [
        "en",
        "de",
        "es",
        "fr",
        "hi",
        "ja",
        "ko",
        "pt",
        "zh",
        "ar",
        "cs",
        "el",
        "fi",
        "hu",
        "it",
        "nl",
        "no",
        "pl",
        "ro",
        "ru",
        "sv",
        "tr",
        "uk",
        "vi",
    ]

    # Chunking parameters for long audio
    CHUNK_LENGTH_SECS = 30.0  # Process audio in 30-second chunks
    CHUNK_OVERLAP_SECS = 1.0  # 1 second overlap between chunks
    MAX_SINGLE_PASS_SECS = 40.0  # Max duration for single-pass transcription

    def __init__(
        self,
        device: str = "cuda",
        beam_size: int = 1,
        default_language: str = "en",
    ):
        """
        Initialize the Canary transcriber.

        Args:
            device: Device to run model on ("cuda" or "cpu")
            beam_size: Beam size for decoding (1 = greedy, faster)
            default_language: Default language code for transcription
        """
        self.device = device
        self.beam_size = beam_size
        self.default_language = default_language
        self.model: Optional[Any] = None
        self._model_loaded = False

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model_loaded and self.model is not None

    def load_model(self) -> None:
        """Load the Canary model into memory."""
        if self._model_loaded:
            logger.info("Model already loaded")
            return

        logger.info(f"Loading Canary model: {self.MODEL_NAME}")
        start_time = time.time()

        try:
            from nemo.collections.asr.models import ASRModel

            # Load model from HuggingFace
            self.model = ASRModel.from_pretrained(self.MODEL_NAME)

            # Move to device
            if self.device == "cuda" and torch.cuda.is_available():
                self.model = self.model.cuda()
                logger.info(
                    f"Model loaded on CUDA device: {torch.cuda.get_device_name(0)}"
                )
            else:
                self.model = self.model.cpu()
                logger.info("Model loaded on CPU")

            # Set to evaluation mode
            self.model.eval()

            # Configure decoding
            decode_cfg = self.model.cfg.decoding
            decode_cfg.beam.beam_size = self.beam_size
            self.model.change_decoding_strategy(decode_cfg)

            self._model_loaded = True
            load_time = time.time() - start_time
            logger.info(f"Model loaded successfully in {load_time:.2f}s")

            # Log VRAM usage
            if self.device == "cuda" and torch.cuda.is_available():
                vram_used = torch.cuda.memory_allocated() / 1024**3
                logger.info(f"VRAM used: {vram_used:.2f} GB")

        except OSError as e:
            if "Disk quota exceeded" in str(e) or e.errno == 122:
                logger.error(
                    f"Disk quota exceeded while loading NeMo model. "
                    f"Try clearing the cache: rm -rf {_NEMO_CACHE_DIR} ~/.cache/huggingface/hub/*canary*"
                )
            raise
        except TypeError as e:
            if "abstract class" in str(e):
                logger.error(
                    f"NeMo model instantiation failed. This usually indicates a corrupted "
                    f"model cache or disk quota issue during download. "
                    f"Try: rm -rf {_NEMO_CACHE_DIR} ~/.cache/huggingface/hub/*canary*"
                )
            raise
        except Exception as e:
            logger.error(f"Failed to load model: {e}", exc_info=True)
            raise

    def unload_model(self) -> None:
        """Unload the model to free memory."""
        if self.model is not None:
            del self.model
            self.model = None
            self._model_loaded = False

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("Model unloaded")

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        pnc: bool = True,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.

        For audio longer than 40 seconds, automatically uses chunked
        transcription to avoid CUDA OOM errors.

        Args:
            audio_path: Path to audio file (16kHz mono WAV recommended)
            language: Language code (e.g., "el" for Greek, "en" for English)
                     If None, uses default_language
            pnc: Include punctuation and capitalization

        Returns:
            TranscriptionResult with text and word timestamps
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # Validate audio file exists
        audio_path_obj = Path(audio_path)
        if not audio_path_obj.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Use default language if not specified
        lang = language or self.default_language

        # Validate language
        if lang not in self.SUPPORTED_LANGUAGES:
            logger.warning(
                f"Language '{lang}' not in supported list. "
                f"Supported: {self.SUPPORTED_LANGUAGES}"
            )

        logger.info(f"Transcribing: {audio_path} (language: {lang})")
        start_time = time.time()

        try:
            # Get audio data and duration
            audio_data, sample_rate = sf.read(str(audio_path))
            duration = len(audio_data) / sample_rate

            # Decide whether to use chunked transcription
            if duration > self.MAX_SINGLE_PASS_SECS:
                logger.info(
                    f"Audio is {duration:.1f}s (>{self.MAX_SINGLE_PASS_SECS}s), "
                    f"using chunked transcription"
                )
                text = self._transcribe_chunked(audio_data, sample_rate, lang, pnc)
            else:
                # Short audio - single pass
                text = self._transcribe_single(str(audio_path), lang, pnc)

            processing_time = time.time() - start_time

            # Estimate word timestamps
            word_timestamps = self._estimate_word_timestamps(text, duration)

            result = TranscriptionResult(
                text=text.strip(),
                language=lang,
                duration=duration,
                word_timestamps=word_timestamps,
                processing_time=processing_time,
            )

            logger.info(
                f"Transcription complete: {len(text)} chars, "
                f"{len(word_timestamps)} words in {processing_time:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            raise

    def _transcribe_single(
        self,
        audio_path: str,
        lang: str,
        pnc: bool,
    ) -> str:
        """Transcribe a short audio file in a single pass."""
        outputs = self.model.transcribe(
            [audio_path],
            batch_size=1,
            source_lang=lang,
            target_lang=lang,
            pnc="yes" if pnc else "no",
        )

        if outputs and len(outputs) > 0:
            output = outputs[0]
            return output.text if hasattr(output, "text") else str(output)
        return ""

    def _transcribe_chunked(
        self,
        audio_data: np.ndarray,
        sample_rate: int,
        lang: str,
        pnc: bool,
    ) -> str:
        """
        Transcribe long audio using chunked processing.

        Splits audio into overlapping chunks, transcribes each,
        and merges results.
        """
        chunk_samples = int(self.CHUNK_LENGTH_SECS * sample_rate)
        overlap_samples = int(self.CHUNK_OVERLAP_SECS * sample_rate)
        step_samples = chunk_samples - overlap_samples

        total_samples = len(audio_data)
        num_chunks = max(1, (total_samples - overlap_samples) // step_samples + 1)

        logger.info(f"Splitting into {num_chunks} chunks of {self.CHUNK_LENGTH_SECS}s")

        transcripts = []

        for i in range(num_chunks):
            start_sample = i * step_samples
            end_sample = min(start_sample + chunk_samples, total_samples)

            chunk_data = audio_data[start_sample:end_sample]

            # Skip very short chunks (less than 0.5 seconds)
            if len(chunk_data) < sample_rate * 0.5:
                continue

            # Save chunk to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                sf.write(tmp_file.name, chunk_data, sample_rate)
                tmp_path = tmp_file.name

            try:
                # Transcribe chunk
                chunk_text = self._transcribe_single(tmp_path, lang, pnc)
                transcripts.append(chunk_text)

                logger.debug(
                    f"Chunk {i + 1}/{num_chunks}: "
                    f"{start_sample / sample_rate:.1f}s - {end_sample / sample_rate:.1f}s"
                )

                # Clear CUDA cache between chunks to prevent memory buildup
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            finally:
                # Clean up temp file
                Path(tmp_path).unlink(missing_ok=True)

        # Merge transcripts with overlap handling
        merged_text = self._merge_transcripts(transcripts)

        return merged_text

    def _merge_transcripts(self, transcripts: List[str]) -> str:
        """
        Merge overlapping transcripts using simple concatenation.

        For overlapping chunks, we use a simple heuristic:
        - Remove potential duplicate words at chunk boundaries
        """
        if not transcripts:
            return ""

        if len(transcripts) == 1:
            return transcripts[0]

        merged_parts = [transcripts[0]]

        for i in range(1, len(transcripts)):
            prev_text = merged_parts[-1]
            curr_text = transcripts[i]

            if not curr_text.strip():
                continue

            # Try to find overlap and remove duplicate words
            prev_words = prev_text.split()
            curr_words = curr_text.split()

            if prev_words and curr_words:
                # Check if last few words of prev match first few of curr
                for overlap_len in range(min(5, len(prev_words), len(curr_words)), 0, -1):
                    prev_end = " ".join(prev_words[-overlap_len:]).lower()
                    curr_start = " ".join(curr_words[:overlap_len]).lower()

                    if prev_end == curr_start:
                        # Found overlap, skip those words in current
                        curr_text = " ".join(curr_words[overlap_len:])
                        logger.debug(
                            f"Found {overlap_len}-word overlap at chunk boundary"
                        )
                        break

            if curr_text.strip():
                merged_parts.append(curr_text)

        return " ".join(merged_parts)

    def _estimate_word_timestamps(
        self,
        text: str,
        duration: float,
    ) -> List[WordTimestamp]:
        """
        Estimate word timestamps based on text length.

        This is a fallback when the model doesn't provide word-level timestamps.
        The timestamps are estimated proportionally based on word length.

        Args:
            text: Transcribed text
            duration: Audio duration in seconds

        Returns:
            List of WordTimestamp objects with estimated times
        """
        if not text.strip():
            return []

        words = text.split()
        if not words:
            return []

        # Calculate total character count (for proportional timing)
        total_chars = sum(len(w) for w in words)
        if total_chars == 0:
            return []

        timestamps = []
        current_time = 0.0

        for word in words:
            # Estimate word duration based on character proportion
            word_duration = (len(word) / total_chars) * duration

            timestamps.append(
                WordTimestamp(
                    word=word,
                    start=current_time,
                    end=current_time + word_duration,
                    confidence=0.5,  # Lower confidence for estimated timestamps
                )
            )

            current_time += word_duration

        return timestamps

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the transcriber."""
        status = {
            "model_loaded": self._model_loaded,
            "model_name": self.MODEL_NAME,
            "device": self.device,
            "beam_size": self.beam_size,
            "default_language": self.default_language,
        }

        if self._model_loaded and torch.cuda.is_available():
            status["vram_used_gb"] = round(torch.cuda.memory_allocated() / 1024**3, 2)
            status["vram_total_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / 1024**3, 2
            )

        return status


# Singleton instance
_transcriber_instance: Optional[CanaryTranscriber] = None


def get_transcriber(
    device: str = "cuda",
    beam_size: int = 1,
    default_language: str = "en",
) -> CanaryTranscriber:
    """
    Get or create the singleton transcriber instance.

    Args:
        device: Device to run model on
        beam_size: Beam size for decoding
        default_language: Default language code

    Returns:
        CanaryTranscriber instance
    """
    global _transcriber_instance

    if _transcriber_instance is None:
        _transcriber_instance = CanaryTranscriber(
            device=device,
            beam_size=beam_size,
            default_language=default_language,
        )

    return _transcriber_instance
