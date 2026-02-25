"""WhisperX STT backend.

Wraps the WhisperX library (faster-whisper + wav2vec2 alignment + pyannote
diarization) behind the STTBackend interface.  Provides improved word-level
timestamps via forced alignment and optional single-pass diarization.
"""

from __future__ import annotations

import gc
import importlib
import inspect
import logging
import os
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)

# Target sample rate for Whisper (technical requirement)
SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)

_PYANNOTE_TORCHCODEC_WARNING_RE = (
    r"torchcodec is not installed correctly so built-in audio decoding will fail\..*"
)


def _import_whisperx_modules(
    *,
    include_diarize: bool = False,
) -> tuple[Any, Any | None]:
    """Import WhisperX while silencing pyannote's optional torchcodec warning.

    PyAnnote 4.x emits a noisy import-time warning when TorchCodec is present but
    incompatible with the current Torch/FFmpeg runtime. Our WhisperX paths pass
    in-memory audio arrays to diarization, so this decoder warning is non-fatal
    during backend import/model load.
    """

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_PYANNOTE_TORCHCODEC_WARNING_RE,
            category=UserWarning,
        )
        whisperx = importlib.import_module("whisperx")
        diarize_module = importlib.import_module("whisperx.diarize") if include_diarize else None
    return whisperx, diarize_module


class WhisperXBackend(STTBackend):
    """WhisperX backend — faster-whisper + wav2vec2 alignment + pyannote diarization."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._device: str = "cuda"
        self._batch_size: int = 16
        self._align_model: Any | None = None
        self._align_metadata: Any | None = None
        self._align_language: str | None = None
        self._transcribe_param_names: set[str] | None = None
        self._compat_mode_logged: bool = False

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        whisperx, _ = _import_whisperx_modules()

        compute_type: str = kwargs.get("compute_type", "default")
        download_root: str | None = kwargs.get("download_root")
        self._batch_size: int = kwargs.get("batch_size", 16)

        logger.info(f"Loading WhisperX model: {model_name}")

        # Suppress pyannote's torchcodec warning during model loading
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=_PYANNOTE_TORCHCODEC_WARNING_RE,
                category=UserWarning,
            )
            self._model = whisperx.load_model(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=download_root,
            )
        self._model_name = model_name
        self._device = device
        self._transcribe_param_names = None
        self._compat_mode_logged = False
        logger.info("WhisperX model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        self._align_model = None
        self._align_metadata = None
        self._align_language = None
        self._transcribe_param_names = None
        self._compat_mode_logged = False
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as e:
            logger.debug(f"Could not clear GPU cache: {e}")

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        try:
            warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"

            if not warmup_path.exists():
                logger.warning("Warmup audio not found, using silent audio")
                warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            else:
                warmup_audio, _ = sf.read(str(warmup_path), dtype="float32")

            self._model.transcribe(warmup_audio, batch_size=1)
            logger.debug("WhisperX model warmup complete")

        except Exception as e:
            logger.warning(f"WhisperX model warmup failed (non-critical): {e}")

        # Pre-load wav2vec2 alignment model so the first real transcription
        # doesn't pay the download/load cost.
        try:
            whisperx, _ = _import_whisperx_modules()
            align_lang = "en"
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=align_lang,
                device=self._device,
            )
            self._align_language = align_lang
            logger.debug("WhisperX alignment model pre-loaded (lang=%s)", align_lang)
        except Exception as e:
            logger.warning(f"WhisperX alignment model pre-load failed (non-critical): {e}")

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        if self._model is None:
            raise RuntimeError("WhisperX model is not loaded")

        # WhisperX transcribe returns a dict with "segments" and "language"
        wx_result = self._whisperx_transcribe(
            audio,
            language=language,
            task=task,
            beam_size=beam_size,
            initial_prompt=initial_prompt,
            suppress_tokens=suppress_tokens,
        )

        detected_language = wx_result.get("language", language)

        # Run wav2vec2 alignment for precise word timestamps (longform only)
        if word_timestamps and wx_result.get("segments"):
            try:
                wx_result = self._align(wx_result, audio, detected_language)
            except Exception as e:
                logger.warning(f"WhisperX alignment failed, using raw timestamps: {e}")

        # Convert to BackendSegment format
        result_segments: list[BackendSegment] = []
        for seg in wx_result.get("segments", []):
            words: list[dict[str, Any]] = []
            if word_timestamps and "words" in seg:
                words = [
                    {
                        "word": w.get("word", ""),
                        "start": w.get("start", 0.0),
                        "end": w.get("end", 0.0),
                        "probability": w.get("score", 0.0),
                    }
                    for w in seg["words"]
                    if "start" in w and "end" in w
                ]
            result_segments.append(
                BackendSegment(
                    text=seg.get("text", ""),
                    start=seg.get("start", 0.0),
                    end=seg.get("end", 0.0),
                    words=words,
                )
            )

        backend_info = BackendTranscriptionInfo(
            language=detected_language,
            language_probability=0.0,
        )
        return result_segments, backend_info

    def transcribe_with_diarization(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        num_speakers: int | None = None,
        hf_token: str | None = None,
    ) -> DiarizedTranscriptionResult | None:
        """Full single-pass pipeline: transcribe → align → diarize → assign speakers."""
        whisperx, diarize_module = _import_whisperx_modules(include_diarize=True)
        if diarize_module is None:
            raise RuntimeError("WhisperX diarization module failed to import")
        DiarizationPipeline = diarize_module.DiarizationPipeline

        if self._model is None:
            raise RuntimeError("WhisperX model is not loaded")

        # Resolve HF token
        token = hf_token or os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
        if not token:
            raise ValueError(
                "HuggingFace token required for diarization. "
                "Set HUGGINGFACE_TOKEN or HF_TOKEN environment variable."
            )

        # 1. Transcribe
        logger.info("WhisperX: transcribing audio")
        wx_result = self._whisperx_transcribe(
            audio,
            language=language,
            task=task,
            beam_size=beam_size,
            initial_prompt=None,
            suppress_tokens=None,
        )
        detected_language = wx_result.get("language", language)

        # 2. Align (wav2vec2 forced alignment for precise word timestamps)
        if wx_result.get("segments"):
            try:
                logger.info("WhisperX: aligning with wav2vec2")
                wx_result = self._align(wx_result, audio, detected_language)
            except Exception as e:
                logger.warning(f"WhisperX alignment failed, continuing with raw timestamps: {e}")

        # 3. Diarize
        logger.info("WhisperX: running diarization")
        diarize_model = DiarizationPipeline(use_auth_token=token, device=self._device)

        diarize_kwargs: dict[str, Any] = {}
        if num_speakers is not None:
            diarize_kwargs["min_speakers"] = num_speakers
            diarize_kwargs["max_speakers"] = num_speakers

        diarize_segments = diarize_model(audio, **diarize_kwargs)

        # 4. Assign word-level speakers
        logger.info("WhisperX: assigning word speakers")
        wx_result = whisperx.assign_word_speakers(diarize_segments, wx_result)

        # Build output
        all_segments: list[dict[str, Any]] = []
        all_words: list[dict[str, Any]] = []
        speakers_seen: set[str] = set()

        for seg in wx_result.get("segments", []):
            speaker = seg.get("speaker", "SPEAKER_00")
            speakers_seen.add(speaker)

            seg_words: list[dict[str, Any]] = []
            if "words" in seg:
                for w in seg["words"]:
                    if "start" not in w or "end" not in w:
                        continue
                    word_dict = {
                        "word": w.get("word", ""),
                        "start": round(w.get("start", 0.0), 3),
                        "end": round(w.get("end", 0.0), 3),
                        "probability": round(w.get("score", 0.0), 3),
                        "speaker": w.get("speaker", speaker),
                    }
                    seg_words.append(word_dict)
                    all_words.append(word_dict)

            all_segments.append(
                {
                    "text": seg.get("text", "").strip(),
                    "start": round(seg.get("start", 0.0), 3),
                    "end": round(seg.get("end", 0.0), 3),
                    "speaker": speaker,
                    "words": seg_words,
                }
            )

        num_speakers_found = len(speakers_seen)
        logger.info(
            "WhisperX diarization complete: %s speakers, %s segments",
            num_speakers_found,
            len(all_segments),
        )

        return DiarizedTranscriptionResult(
            segments=all_segments,
            words=all_words,
            num_speakers=num_speakers_found,
            language=detected_language,
            language_probability=0.0,
        )

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "whisperx"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_transcribe_param_names(self) -> set[str]:
        if self._model is None:
            raise RuntimeError("WhisperX model is not loaded")

        if self._transcribe_param_names is None:
            try:
                self._transcribe_param_names = set(
                    inspect.signature(self._model.transcribe).parameters
                )
            except (TypeError, ValueError) as e:
                logger.debug(
                    "Could not inspect WhisperX transcribe signature, using fallback: %s", e
                )
                # Conservative fallback matching WhisperX 3.8.x public kwargs.
                self._transcribe_param_names = {
                    "audio",
                    "batch_size",
                    "num_workers",
                    "language",
                    "task",
                    "chunk_size",
                    "print_progress",
                    "combined_progress",
                    "verbose",
                }
        return self._transcribe_param_names

    def _whisperx_transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None,
        task: str,
        beam_size: int,
        initial_prompt: str | None,
        suppress_tokens: list[int] | None,
    ) -> dict[str, Any]:
        """Call WhisperX transcribe across old/new signatures.

        WhisperX 3.8.x moved decode params like beam size and initial prompt off
        ``FasterWhisperPipeline.transcribe()`` and into ``pipeline.options``.
        """
        if self._model is None:
            raise RuntimeError("WhisperX model is not loaded")

        param_names = self._get_transcribe_param_names()
        kwargs: dict[str, Any] = {
            "language": language,
            "task": task,
        }

        # batch_size is a top-level WhisperX transcribe kwarg (not a decode option)
        if "batch_size" in param_names:
            kwargs["batch_size"] = self._batch_size

        patch_fields: dict[str, Any] = {}
        compat_fields: set[str] = set()

        if "beam_size" in param_names:
            kwargs["beam_size"] = beam_size
        else:
            patch_fields["beam_size"] = beam_size
            compat_fields.add("beam_size")

        if "initial_prompt" in param_names:
            kwargs["initial_prompt"] = initial_prompt
        else:
            patch_fields["initial_prompt"] = initial_prompt
            compat_fields.add("initial_prompt")

        if suppress_tokens is not None:
            if "suppress_tokens" in param_names:
                kwargs["suppress_tokens"] = suppress_tokens
            else:
                patch_fields["suppress_tokens"] = suppress_tokens
                compat_fields.add("suppress_tokens")

        previous_options: Any | None = None
        options_patched = False
        if compat_fields:
            if not self._compat_mode_logged:
                logger.info(
                    "WhisperX compatibility mode enabled: patching decode options via "
                    "pipeline.options (%s)",
                    ", ".join(sorted(compat_fields)),
                )
                self._compat_mode_logged = True

            options_obj = getattr(self._model, "options", None)
            if options_obj is not None and patch_fields:
                available_fields = getattr(options_obj, "__dataclass_fields__", None)
                if isinstance(available_fields, dict):
                    patch_fields = {
                        key: value for key, value in patch_fields.items() if key in available_fields
                    }

                if patch_fields:
                    try:
                        previous_options = options_obj
                        self._model.options = replace(options_obj, **patch_fields)
                        options_patched = True
                    except Exception as e:
                        logger.warning(
                            "Failed to patch WhisperX decode options for compatibility: %s", e
                        )
                else:
                    logger.debug(
                        "WhisperX compatibility mode active but pipeline.options is missing "
                        "expected fields"
                    )
            elif patch_fields:
                logger.debug(
                    "WhisperX compatibility mode active but model has no pipeline.options; "
                    "decode option patch skipped"
                )

        try:
            return self._model.transcribe(audio, **kwargs)
        finally:
            if options_patched:
                self._model.options = previous_options

    def _align(
        self,
        wx_result: dict[str, Any],
        audio: np.ndarray,
        language: str | None,
    ) -> dict[str, Any]:
        """Run wav2vec2 forced alignment, caching the alignment model per-language."""
        whisperx, _ = _import_whisperx_modules()

        lang = language or "en"

        # Load or reuse alignment model for this language
        if self._align_model is None or self._align_language != lang:
            if self._align_model is not None:
                del self._align_model
                del self._align_metadata
                gc.collect()
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=lang,
                device=self._device,
            )
            self._align_language = lang

        result = whisperx.align(
            wx_result["segments"],
            self._align_model,
            self._align_metadata,
            audio,
            self._device,
            return_char_alignments=False,
        )
        return result
