"""VibeVoice-ASR backend family (experimental).

This backend wraps the VibeVoice-ASR model behind the shared ``STTBackend``
interface. VibeVoice-ASR produces sentence-level transcription with integrated
speaker diarization, so v1 normalizes those sentence segments and leaves
word-level timestamps empty.
"""

from __future__ import annotations

import gc
import importlib
import logging
import math
from typing import Any

import numpy as np
import torch
from server.config import get_config
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)

INPUT_SAMPLE_RATE = 16000
DEFAULT_TARGET_SAMPLE_RATE = 24000
DEFAULT_LANGUAGE_MODEL = "Qwen/Qwen2.5-7B"
DEFAULT_MAX_NEW_TOKENS = 0

logger = logging.getLogger(__name__)

_VIBEVOICE_ASR_IMPORT_CANDIDATES: tuple[
    tuple[str, str, str, str, str],
    ...,
] = (
    (
        "legacy",
        "vibevoice.modeling_vibevoice_asr",
        "VibeVoiceASRForConditionalGeneration",
        "vibevoice.processor.vibevoice_asr_processing",
        "VibeVoiceASRProcessor",
    ),
    (
        "modular",
        "vibevoice.modular.modeling_vibevoice_asr",
        "VibeVoiceASRForConditionalGeneration",
        "vibevoice.processor.vibevoice_asr_processor",
        "VibeVoiceASRProcessor",
    ),
)


def _attempted_vibevoice_import_paths() -> list[str]:
    return [
        f"{model_module}:{model_symbol} + {processor_module}:{processor_symbol}"
        for (
            _variant,
            model_module,
            model_symbol,
            processor_module,
            processor_symbol,
        ) in _VIBEVOICE_ASR_IMPORT_CANDIDATES
    ]


def _import_vibevoice_asr_classes() -> tuple[type[Any], type[Any]]:
    errors: list[str] = []
    last_error: Exception | None = None
    top_level_vibevoice_importable = False
    top_level_error: str | None = None

    try:
        importlib.import_module("vibevoice")
        top_level_vibevoice_importable = True
    except Exception as exc:
        top_level_error = f"{type(exc).__name__}: {exc}"

    for (
        variant,
        model_module,
        model_symbol,
        processor_module,
        processor_symbol,
    ) in _VIBEVOICE_ASR_IMPORT_CANDIDATES:
        try:
            model_mod = importlib.import_module(model_module)
            processor_mod = importlib.import_module(processor_module)
            model_cls = getattr(model_mod, model_symbol)
            processor_cls = getattr(processor_mod, processor_symbol)
            logger.info(
                "Resolved VibeVoice-ASR imports via %s layout (%s / %s)",
                variant,
                model_module,
                processor_module,
            )
            return model_cls, processor_cls
        except Exception as exc:
            last_error = exc
            errors.append(
                f"{variant}: {model_module}:{model_symbol} + "
                f"{processor_module}:{processor_symbol} -> "
                f"{type(exc).__name__}: {exc}"
            )

    attempted = "; ".join(_attempted_vibevoice_import_paths())
    details = " | ".join(errors) if errors else "no import candidates attempted"

    if not top_level_vibevoice_importable:
        message = (
            "VibeVoice-ASR backend selected but VibeVoice is not installed in the backend runtime. "
            "Enable INSTALL_VIBEVOICE_ASR=true for the server container (experimental), "
            "or install the VibeVoice package in the backend runtime. "
            f"Top-level import error: {top_level_error or 'unknown'}. "
            f"Attempted ASR imports: {attempted}. "
            "If upstream packaging changed, set VIBEVOICE_ASR_PACKAGE_SPEC to a known-good revision."
        )
    else:
        message = (
            "VibeVoice-ASR backend selected but compatible VibeVoice-ASR modules could not be "
            "imported from the installed `vibevoice` package (possible upstream package layout drift). "
            f"Attempted ASR imports: {attempted}. "
            "Set VIBEVOICE_ASR_PACKAGE_SPEC to a known-good revision/commit if needed. "
            f"Import errors: {details}"
        )

    if last_error is not None:
        raise ImportError(message) from last_error
    raise ImportError(message)


class VibeVoiceASRBackend(STTBackend):
    """In-process VibeVoice-ASR backend (experimental)."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._processor: Any | None = None
        self._model_name: str | None = None
        self._device: str = "cpu"
        self._target_sample_rate: int = DEFAULT_TARGET_SAMPLE_RATE
        self._max_new_tokens: int | None = None

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        cfg = get_config()
        vv_cfg = cfg.get("vibevoice_asr", default={}) or {}
        if not isinstance(vv_cfg, dict):
            vv_cfg = {}

        VibeVoiceASRForConditionalGeneration, VibeVoiceASRProcessor = (
            _import_vibevoice_asr_classes()
        )

        gpu_device_index = int(kwargs.get("gpu_device_index", 0) or 0)
        self._device = f"cuda:{gpu_device_index}" if device == "cuda" else "cpu"
        self._target_sample_rate = int(
            vv_cfg.get("target_sample_rate_hz", DEFAULT_TARGET_SAMPLE_RATE)
            or DEFAULT_TARGET_SAMPLE_RATE
        )
        raw_max_new_tokens = vv_cfg.get("max_new_tokens", DEFAULT_MAX_NEW_TOKENS)
        try:
            parsed_max_new_tokens = int(raw_max_new_tokens or 0)
        except (TypeError, ValueError):
            parsed_max_new_tokens = 0
        self._max_new_tokens = parsed_max_new_tokens if parsed_max_new_tokens > 0 else None
        attn_impl = str(vv_cfg.get("attn_implementation", "eager") or "eager")
        lm_model = str(
            vv_cfg.get("language_model_pretrained_name", DEFAULT_LANGUAGE_MODEL)
            or DEFAULT_LANGUAGE_MODEL
        )

        dtype: torch.dtype
        if self._device.startswith("cuda"):
            # Prefer bf16 when available; fall back to fp16 for broader GPU support.
            if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16
            else:
                dtype = torch.float16
        else:
            dtype = torch.float32

        logger.info(
            "Loading VibeVoice-ASR model: %s (device=%s, target_sr=%s)",
            model_name,
            self._device,
            self._target_sample_rate,
        )

        self._processor = VibeVoiceASRProcessor.from_pretrained(
            model_name,
            language_model_pretrained_name=lm_model,
        )

        model_kwargs: dict[str, Any] = {
            "attn_implementation": attn_impl,
            "trust_remote_code": True,
        }
        # Upstream examples use ``dtype=...`` but some Transformers stacks still use ``torch_dtype``.
        try:
            self._model = VibeVoiceASRForConditionalGeneration.from_pretrained(
                model_name,
                dtype=dtype,
                **model_kwargs,
            )
        except TypeError:
            self._model = VibeVoiceASRForConditionalGeneration.from_pretrained(
                model_name,
                torch_dtype=dtype,
                **model_kwargs,
            )

        if hasattr(self._model, "to"):
            self._model = self._model.to(self._device)
        if hasattr(self._model, "eval"):
            self._model.eval()

        self._model_name = model_name
        logger.info("VibeVoice-ASR model loaded")

    def unload(self) -> None:
        self._model = None
        self._processor = None
        self._model_name = None
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as e:
            logger.debug("Could not clear GPU cache: %s", e)

    def is_loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    def warmup(self) -> None:
        # VibeVoice-ASR is heavy; avoid additional warmup by default.
        logger.debug("Skipping VibeVoice-ASR warmup (no-op)")

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = INPUT_SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        del (
            initial_prompt,
            suppress_tokens,
            vad_filter,
            word_timestamps,
            translation_target_language,
        )
        if task.strip().lower() == "translate":
            raise ValueError(
                "VibeVoice-ASR translation is not supported in TranscriptionSuite v1 integration."
            )

        raw_segments = self._generate_segments(
            audio,
            audio_sample_rate=audio_sample_rate,
            language=language,
            beam_size=beam_size,
        )
        backend_segments = [
            BackendSegment(
                text=str(seg.get("text", "")).strip(),
                start=float(seg.get("start", 0.0) or 0.0),
                end=float(seg.get("end", 0.0) or 0.0),
                words=[],
            )
            for seg in raw_segments
        ]
        return backend_segments, BackendTranscriptionInfo(
            language=language, language_probability=0.0
        )

    def transcribe_with_diarization(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = INPUT_SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        num_speakers: int | None = None,
        hf_token: str | None = None,
    ) -> DiarizedTranscriptionResult | None:
        del num_speakers, hf_token
        if task.strip().lower() == "translate":
            raise ValueError(
                "VibeVoice-ASR translation is not supported in TranscriptionSuite v1 integration."
            )

        segments = self._generate_segments(
            audio,
            audio_sample_rate=audio_sample_rate,
            language=language,
            beam_size=beam_size,
        )
        speakers = {
            str(seg.get("speaker", "")).strip()
            for seg in segments
            if str(seg.get("speaker", "")).strip()
        }

        return DiarizedTranscriptionResult(
            segments=segments,
            words=[],
            num_speakers=len(speakers),
            language=language,
            language_probability=0.0,
        )

    def supports_translation(self) -> bool:
        return False

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return self._target_sample_rate

    @property
    def backend_name(self) -> str:
        return "vibevoice_asr"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_segments(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int,
        language: str | None,
        beam_size: int,
    ) -> list[dict[str, Any]]:
        if self._model is None or self._processor is None:
            raise RuntimeError("VibeVoice-ASR model is not loaded")

        audio_target = _resample_audio(
            audio, src_rate=audio_sample_rate, dst_rate=self._target_sample_rate
        )
        audio_target = np.asarray(audio_target, dtype=np.float32)

        inputs, processor_input_mode = _call_vibevoice_processor(
            self._processor,
            audio=audio_target,
            sample_rate=self._target_sample_rate,
        )
        logger.debug("VibeVoice-ASR processor input mode: %s", processor_input_mode)
        inputs = _move_inputs_to_device(inputs, self._device)

        generate_kwargs: dict[str, Any] = {
            "do_sample": False,
            "num_beams": max(1, int(beam_size or 1)),
        }
        if self._max_new_tokens is not None:
            generate_kwargs["max_new_tokens"] = self._max_new_tokens

        tokenizer = getattr(self._processor, "tokenizer", None)
        eos_token_id = getattr(tokenizer, "eos_token_id", None)
        pad_token_id = getattr(tokenizer, "pad_token_id", None)
        if eos_token_id is not None:
            generate_kwargs["eos_token_id"] = eos_token_id
        if pad_token_id is not None:
            generate_kwargs["pad_token_id"] = pad_token_id
        elif eos_token_id is not None:
            generate_kwargs["pad_token_id"] = eos_token_id

        output = self._model.generate(**inputs, **generate_kwargs)
        sequences = getattr(output, "sequences", output)

        if not isinstance(sequences, torch.Tensor):
            raise RuntimeError(f"Unexpected VibeVoice generate output: {type(sequences)!r}")
        if sequences.ndim != 2 or sequences.shape[0] < 1:
            raise RuntimeError(
                f"Unexpected VibeVoice output tensor shape: {tuple(sequences.shape)}"
            )

        generated_ids = sequences[0]
        input_ids = inputs.get("input_ids")
        if isinstance(input_ids, torch.Tensor) and input_ids.ndim == 2 and input_ids.shape[0] >= 1:
            prefix_len = int(input_ids.shape[1])
            if prefix_len < generated_ids.shape[0]:
                generated_ids = generated_ids[prefix_len:]

        decoded_text = _decode_generated_text(self._processor, generated_ids)
        structured = self._processor.post_process_transcription(decoded_text)
        normalized = _normalize_vibevoice_segments(structured)
        if not normalized and decoded_text.strip():
            # Fallback if upstream output formatting changes.
            normalized = [{"text": decoded_text.strip(), "start": 0.0, "end": 0.0, "speaker": None}]
        return normalized


def _call_vibevoice_processor(
    processor: Any,
    *,
    audio: np.ndarray,
    sample_rate: int,
) -> tuple[Any, str]:
    kwargs = {
        "return_tensors": "pt",
        "padding": True,
        "add_generation_prompt": True,
    }

    try:
        return (
            processor(
                audio=[audio],
                sampling_rate=sample_rate,
                **kwargs,
            ),
            "raw-array",
        )
    except (TypeError, ValueError) as exc:
        logger.debug(
            "VibeVoice processor rejected raw-array audio input, retrying tuple format: %s",
            exc,
        )

    return (
        processor(
            audio=[(audio, sample_rate)],
            sampling_rate=None,
            **kwargs,
        ),
        "tuple+sr",
    )


def _resample_audio(audio: np.ndarray, *, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample mono float audio with scipy polyphase filtering."""
    if src_rate == dst_rate:
        return np.asarray(audio, dtype=np.float32)

    from scipy.signal import resample_poly

    gcd = math.gcd(int(src_rate), int(dst_rate))
    up = dst_rate // gcd
    down = src_rate // gcd
    return resample_poly(np.asarray(audio, dtype=np.float32), up, down).astype(np.float32)


def _move_inputs_to_device(inputs: Any, device: str) -> Any:
    if hasattr(inputs, "to"):
        try:
            return inputs.to(device)
        except Exception:
            pass

    if isinstance(inputs, dict):
        moved: dict[str, Any] = {}
        for key, value in inputs.items():
            if isinstance(value, torch.Tensor):
                moved[key] = value.to(device)
            else:
                moved[key] = value
        return moved
    return inputs


def _decode_generated_text(processor: Any, token_ids: torch.Tensor) -> str:
    token_ids = token_ids.detach().cpu()
    if hasattr(processor, "decode"):
        try:
            return str(processor.decode(token_ids, skip_special_tokens=True))
        except TypeError:
            return str(processor.decode(token_ids))

    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is None or not hasattr(tokenizer, "decode"):
        raise RuntimeError("VibeVoice processor does not expose a decode method")
    return str(tokenizer.decode(token_ids, skip_special_tokens=True))


def _normalize_vibevoice_segments(payload: Any) -> list[dict[str, Any]]:
    """Normalize VibeVoice structured output into API-compatible diarized segments."""
    if payload is None:
        return []

    # Upstream can return either a list of segments or an object wrapper.
    if isinstance(payload, dict):
        candidates = (
            payload.get("segments")
            or payload.get("transcription")
            or payload.get("transcriptions")
            or payload.get("items")
            or []
        )
    else:
        candidates = payload

    if not isinstance(candidates, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue

        text = str(item.get("text", "") or "").strip()
        start = _to_float(item.get("start", item.get("start_time", 0.0)))
        end = _to_float(item.get("end", item.get("end_time", start)))
        if end < start:
            end = start

        speaker = item.get("speaker")
        if speaker is None:
            speaker = item.get("speaker_id")
        speaker_label = _normalize_speaker_label(speaker)

        normalized.append(
            {
                "text": text,
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": speaker_label,
            }
        )

    return normalized


def _normalize_speaker_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return f"SPEAKER_{value:02d}"
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return f"SPEAKER_{int(raw):02d}"
    return raw


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
