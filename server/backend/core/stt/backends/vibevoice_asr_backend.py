"""VibeVoice-ASR backend family (experimental).

This backend wraps the VibeVoice-ASR model behind the shared ``STTBackend``
interface. VibeVoice-ASR produces sentence-level transcription with integrated
speaker diarization, so v1 normalizes those sentence segments and leaves
word-level timestamps empty.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import re
from collections.abc import Callable
from typing import Any

import numpy as np
import torch
from server.config import get_config
from server.core.audio_utils import clear_gpu_cache
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)

INPUT_SAMPLE_RATE = 16000
DEFAULT_TARGET_SAMPLE_RATE = 24000
DEFAULT_MAX_CHUNK_DURATION_S = 60  # 1 minute
DEFAULT_LANGUAGE_MODEL = "Qwen/Qwen2.5-7B"
DEFAULT_MAX_NEW_TOKENS = 32768
DEFAULT_NUM_BEAMS = 1
DEFAULT_TEMPERATURE = 0.0

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
        self._num_beams: int = DEFAULT_NUM_BEAMS
        self._temperature: float = DEFAULT_TEMPERATURE
        self._max_chunk_duration_s: int = DEFAULT_MAX_CHUNK_DURATION_S

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
        try:
            self._num_beams = max(
                1, int(vv_cfg.get("num_beams", DEFAULT_NUM_BEAMS) or DEFAULT_NUM_BEAMS)
            )
        except (TypeError, ValueError):
            self._num_beams = DEFAULT_NUM_BEAMS
        try:
            self._temperature = float(vv_cfg.get("temperature", DEFAULT_TEMPERATURE))
        except (TypeError, ValueError):
            self._temperature = DEFAULT_TEMPERATURE
        if not math.isfinite(self._temperature):
            self._temperature = DEFAULT_TEMPERATURE
        raw_max_new_tokens = vv_cfg.get("max_new_tokens", DEFAULT_MAX_NEW_TOKENS)
        try:
            parsed_max_new_tokens = int(raw_max_new_tokens or 0)
        except (TypeError, ValueError):
            parsed_max_new_tokens = 0
        self._max_new_tokens = parsed_max_new_tokens if parsed_max_new_tokens > 0 else None
        try:
            self._max_chunk_duration_s = max(
                60,
                int(
                    vv_cfg.get("max_chunk_duration_s", DEFAULT_MAX_CHUNK_DURATION_S)
                    or DEFAULT_MAX_CHUNK_DURATION_S
                ),
            )
        except (TypeError, ValueError):
            self._max_chunk_duration_s = DEFAULT_MAX_CHUNK_DURATION_S
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
        clear_gpu_cache()

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
        progress_callback: Callable[[int, int], None] | None = None,
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

        audio_duration = len(audio) / max(audio_sample_rate, 1)
        if audio_duration > self._max_chunk_duration_s:
            return self._transcribe_long(
                audio,
                audio_sample_rate=audio_sample_rate,
                language=language,
                beam_size=beam_size,
                progress_callback=progress_callback,
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
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DiarizedTranscriptionResult | None:
        del num_speakers, hf_token
        if task.strip().lower() == "translate":
            raise ValueError(
                "VibeVoice-ASR translation is not supported in TranscriptionSuite v1 integration."
            )

        audio_duration = len(audio) / max(audio_sample_rate, 1)
        if audio_duration > self._max_chunk_duration_s:
            return self._transcribe_long_diarized(
                audio,
                audio_sample_rate=audio_sample_rate,
                language=language,
                beam_size=beam_size,
                progress_callback=progress_callback,
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
    # Long-audio chunking
    # ------------------------------------------------------------------

    def _transcribe_long(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int,
        language: str | None,
        beam_size: int,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Chunk long audio and concatenate transcription results."""
        chunk_samples = int(self._max_chunk_duration_s * audio_sample_rate)
        total_samples = len(audio)
        num_chunks = math.ceil(total_samples / chunk_samples)

        all_segments: list[BackendSegment] = []
        time_offset = 0.0

        for i in range(num_chunks):
            start = i * chunk_samples
            end = min(start + chunk_samples, total_samples)
            chunk = audio[start:end]
            chunk_duration = len(chunk) / max(audio_sample_rate, 1)

            logger.info(
                "VibeVoice-ASR chunk %d/%d (%.0fs - %.0fs)",
                i + 1,
                num_chunks,
                time_offset,
                time_offset + chunk_duration,
            )
            if progress_callback is not None:
                progress_callback(i + 1, num_chunks)

            raw_segments = self._generate_segments(
                chunk,
                audio_sample_rate=audio_sample_rate,
                language=language,
                beam_size=beam_size,
            )

            for seg in raw_segments:
                seg_start = float(seg.get("start", 0.0) or 0.0)
                seg_end = float(seg.get("end", 0.0) or 0.0)
                all_segments.append(
                    BackendSegment(
                        text=str(seg.get("text", "")).strip(),
                        start=seg_start + time_offset,
                        end=seg_end + time_offset,
                        words=[],
                    )
                )

            time_offset += chunk_duration
            if i < num_chunks - 1:
                clear_gpu_cache()

        return all_segments, BackendTranscriptionInfo(language=language, language_probability=0.0)

    def _transcribe_long_diarized(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int,
        language: str | None,
        beam_size: int,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DiarizedTranscriptionResult:
        """Chunk long audio and concatenate diarized transcription results."""
        chunk_samples = int(self._max_chunk_duration_s * audio_sample_rate)
        total_samples = len(audio)
        num_chunks = math.ceil(total_samples / chunk_samples)

        all_segments: list[dict[str, Any]] = []
        all_speakers: set[str] = set()
        time_offset = 0.0

        for i in range(num_chunks):
            start = i * chunk_samples
            end = min(start + chunk_samples, total_samples)
            chunk = audio[start:end]
            chunk_duration = len(chunk) / max(audio_sample_rate, 1)

            logger.info(
                "VibeVoice-ASR chunk %d/%d (%.0fs - %.0fs)",
                i + 1,
                num_chunks,
                time_offset,
                time_offset + chunk_duration,
            )
            if progress_callback is not None:
                progress_callback(i + 1, num_chunks)

            segments = self._generate_segments(
                chunk,
                audio_sample_rate=audio_sample_rate,
                language=language,
                beam_size=beam_size,
            )

            for seg in segments:
                seg["start"] = float(seg.get("start", 0.0) or 0.0) + time_offset
                seg["end"] = float(seg.get("end", 0.0) or 0.0) + time_offset
                speaker = str(seg.get("speaker", "")).strip()
                if speaker:
                    all_speakers.add(speaker)

            all_segments.extend(segments)
            time_offset += chunk_duration
            if i < num_chunks - 1:
                clear_gpu_cache()

        return DiarizedTranscriptionResult(
            segments=all_segments,
            words=[],
            num_speakers=len(all_speakers),
            language=language,
            language_probability=0.0,
        )

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
            "num_beams": self._num_beams,
            "temperature": self._temperature,
        }
        # VibeVoice's structured JSON output is sensitive to generation settings.
        # Prefer backend-specific defaults instead of inheriting the global Whisper beam size.
        del beam_size
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

        logger.debug(
            "VibeVoice-ASR generation settings: num_beams=%s temperature=%s max_new_tokens=%s",
            generate_kwargs.get("num_beams"),
            generate_kwargs.get("temperature"),
            generate_kwargs.get("max_new_tokens", "<omitted>"),
        )
        with torch.inference_mode():
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

        # Free intermediate tensors to reclaim activation memory before next chunk
        del output, sequences, inputs
        clear_gpu_cache()

        decoded_text = _decode_generated_text(self._processor, generated_ids)
        normalized, parse_mode, parse_stats = _parse_vibevoice_structured_output_detailed(
            decoded_text
        )
        if not normalized:
            # Upstream parser emits a noisy warning when the JSON is clearly malformed.
            if not parse_stats.get("unbalanced", False):
                structured = self._processor.post_process_transcription(decoded_text)
                normalized = _normalize_vibevoice_segments(structured)
                if normalized:
                    parse_mode = "upstream_parser"
        if not normalized and decoded_text.strip():
            text_fallback = _extract_plaintext_from_jsonish_output(decoded_text)
            if text_fallback:
                parse_mode = "text_fallback"
                normalized = [{"text": text_fallback, "start": 0.0, "end": 0.0, "speaker": None}]
            else:
                # Last-resort fallback if upstream output formatting changes.
                parse_mode = "raw_fallback"
                fallback_text = (
                    _strip_chat_role_prefix(decoded_text).strip() or decoded_text.strip()
                )
                normalized = [{"text": fallback_text, "start": 0.0, "end": 0.0, "speaker": None}]

        log_fn = logger.debug if parse_mode in {"direct_json", "embedded_json"} else logger.info
        log_fn(
            "VibeVoice-ASR parse mode=%s decoded_chars=%d segments=%d json_start=%s unbalanced=%s in_string=%s "
            "bracket_depth=%s brace_depth=%s",
            parse_mode,
            len(decoded_text),
            len(normalized),
            parse_stats.get("has_json_start"),
            parse_stats.get("unbalanced"),
            parse_stats.get("in_string"),
            parse_stats.get("bracket_depth"),
            parse_stats.get("brace_depth"),
        )
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
    if hasattr(processor, "batch_decode"):
        batched = token_ids.unsqueeze(0) if hasattr(token_ids, "unsqueeze") else [token_ids]
        try:
            decoded = processor.batch_decode(batched, skip_special_tokens=True)
        except TypeError:
            decoded = processor.batch_decode(batched)
        if isinstance(decoded, list) and decoded:
            return str(decoded[0])
        if isinstance(decoded, tuple) and decoded:
            return str(decoded[0])
        if isinstance(decoded, str):
            return decoded
    if hasattr(processor, "decode"):
        try:
            return str(processor.decode(token_ids, skip_special_tokens=True))
        except TypeError:
            return str(processor.decode(token_ids))

    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is None or not hasattr(tokenizer, "decode"):
        raise RuntimeError("VibeVoice processor does not expose a decode method")
    return str(tokenizer.decode(token_ids, skip_special_tokens=True))


def _parse_vibevoice_structured_output(text: str) -> list[dict[str, Any]]:
    """Parse model-emitted structured transcription text without relying on upstream formatting."""
    normalized, _mode, _stats = _parse_vibevoice_structured_output_detailed(text)
    return normalized


def _parse_vibevoice_structured_output_detailed(
    text: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    cleaned = _sanitize_generated_structured_text(text)
    stats = _json_structure_stats(cleaned)

    payload, mode = _try_load_json_from_generated_text(cleaned)
    if payload is not None:
        normalized = _normalize_vibevoice_segments(payload)
        if normalized:
            return normalized, mode, stats

    repaired_payload = _repair_and_parse_json_payload(cleaned)
    if repaired_payload is not None:
        normalized = _normalize_vibevoice_segments(repaired_payload)
        if normalized:
            return normalized, "repaired_json", stats

    salvaged = _salvage_segments_from_jsonish_output(cleaned)
    if salvaged:
        return salvaged, "segment_salvage", stats

    return [], "none", stats


def _try_load_json_from_generated_text(text: str) -> tuple[Any | None, str]:
    """Extract and parse JSON payloads from model output.

    VibeVoice can emit JSON with a leading role prefix such as ``Assistant ``.
    ``json.JSONDecoder.raw_decode`` lets us scan for the first valid JSON object/array
    without requiring it to start at column 1.
    """
    if not text:
        return None, "none"

    decoder = json.JSONDecoder()

    # Fast path when the payload is already clean JSON.
    try:
        return json.loads(text), "direct_json"
    except json.JSONDecodeError:
        pass

    for idx, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text[idx:])
            return value, "embedded_json"
        except json.JSONDecodeError:
            continue
    return None, "none"


def _repair_and_parse_json_payload(text: str) -> Any | None:
    """Attempt to repair incomplete/truncated JSON-ish output."""
    if not text:
        return None
    start = _find_first_json_start(text)
    if start < 0:
        return None

    candidate = text[start:].strip()
    if not candidate:
        return None

    for _ in range(32):
        fixed = _close_unbalanced_json(candidate)
        payload, _mode = _try_load_json_from_generated_text(fixed)
        if payload is not None:
            return payload
        trimmed = _trim_jsonish_tail(candidate)
        if not trimmed or trimmed == candidate:
            break
        candidate = trimmed
    return None


def _close_unbalanced_json(text: str) -> str:
    stats = _scan_json_structure(text)
    fixed = text.rstrip()
    if stats["in_string"]:
        fixed += '"'
    fixed += "".join(reversed(stats["closers_needed"]))
    # Remove trailing commas before closers after we append synthetic delimiters.
    fixed = re.sub(r",(\s*[}\]])", r"\1", fixed)
    return fixed


def _trim_jsonish_tail(text: str) -> str:
    value = text.rstrip()
    if not value:
        return ""
    delimiter_positions = [value.rfind(ch) for ch in (",", "}", "]", '"')]
    cut = max(delimiter_positions)
    if cut < 0:
        return value[:-1].rstrip()
    if value[cut] == ",":
        return value[:cut].rstrip()
    return value[: cut + 1].rstrip()


def _salvage_segments_from_jsonish_output(text: str) -> list[dict[str, Any]]:
    """Salvage any fully-formed segment objects from truncated JSON output."""
    normalized: list[dict[str, Any]] = []
    for obj_text in _iter_balanced_json_objects(text):
        try:
            payload = json.loads(obj_text)
        except json.JSONDecodeError:
            continue
        normalized.extend(_normalize_vibevoice_segments(payload))
    return normalized


def _iter_balanced_json_objects(text: str) -> list[str]:
    results: list[str] = []
    in_string = False
    escape = False
    depth = 0
    start_idx: int | None = None
    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
            continue
        if ch == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start_idx is not None:
                results.append(text[start_idx : idx + 1])
                start_idx = None
    return results


def _sanitize_generated_structured_text(text: str) -> str:
    value = _strip_chat_role_prefix(text or "")
    value = _strip_code_fence_wrappers(value)
    return value.strip()


def _strip_code_fence_wrappers(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    # Drop opening fence (and optional language label) and trailing fence if present.
    first_newline = value.find("\n")
    if first_newline == -1:
        return value.strip("`").strip()
    body = value[first_newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()
        body = body[:-3]
    return body.strip()


def _strip_chat_role_prefix(text: str) -> str:
    """Strip common chat-style prefixes that can precede structured JSON."""
    value = text.lstrip()
    lowered = value.lower()
    prefixes = ("assistant:", "assistant", "response:", "output:")
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return value[len(prefix) :].lstrip()
    return value


def _extract_plaintext_from_jsonish_output(text: str) -> str | None:
    """Extract transcript text from malformed JSON-like output as a final fallback."""
    cleaned = _sanitize_generated_structured_text(text)
    if not cleaned:
        return None

    values: list[str] = []
    complete_pattern = re.compile(
        r'"(?:Content|content|Text|text)"\s*:\s*"((?:\\.|[^"\\])*)"',
        flags=re.DOTALL,
    )
    for match in complete_pattern.finditer(cleaned):
        values.append(_decode_json_string_fragment(match.group(1)))

    if values:
        return " ".join(v.strip() for v in values if v.strip()).strip() or None

    partial_match = re.search(
        r'"(?:Content|content|Text|text)"\s*:\s*"(?P<value>.*)$',
        cleaned,
        flags=re.DOTALL,
    )
    if partial_match:
        raw = partial_match.group("value").strip()
        raw = re.sub(r"[}\],`\s]+$", "", raw)
        raw = raw.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ")
        raw = raw.strip()
        return raw or None
    return None


def _decode_json_string_fragment(value: str) -> str:
    try:
        return str(json.loads(f'"{value}"'))
    except Exception:
        return value


def _find_first_json_start(text: str) -> int:
    for idx, ch in enumerate(text):
        if ch in "[{":
            return idx
    return -1


def _json_structure_stats(text: str) -> dict[str, Any]:
    stats = _scan_json_structure(text)
    stats["has_json_start"] = _find_first_json_start(text) >= 0
    stats["unbalanced"] = bool(stats["in_string"] or stats["bracket_depth"] or stats["brace_depth"])
    return stats


def _scan_json_structure(text: str) -> dict[str, Any]:
    in_string = False
    escape = False
    bracket_depth = 0
    brace_depth = 0
    closers_needed: list[str] = []

    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "[":
            bracket_depth += 1
            closers_needed.append("]")
            continue
        if ch == "{":
            brace_depth += 1
            closers_needed.append("}")
            continue
        if ch == "]":
            if closers_needed and closers_needed[-1] == "]":
                closers_needed.pop()
                bracket_depth = max(0, bracket_depth - 1)
            continue
        if ch == "}":
            if closers_needed and closers_needed[-1] == "}":
                closers_needed.pop()
                brace_depth = max(0, brace_depth - 1)
            continue

    return {
        "in_string": in_string,
        "bracket_depth": bracket_depth,
        "brace_depth": brace_depth,
        "closers_needed": closers_needed,
    }


def _normalize_vibevoice_segments(payload: Any) -> list[dict[str, Any]]:
    """Normalize VibeVoice structured output into API-compatible diarized segments."""
    if payload is None:
        return []

    # Upstream can return either a list of segments or an object wrapper.
    if isinstance(payload, dict):
        # Some VibeVoice outputs emit a top-level list wrapper, others emit a single
        # segment object. Accept both lowercase and title-case keys.
        if _looks_like_segment_item(payload):
            candidates = [payload]
        else:
            candidates = (
                payload.get("segments")
                or payload.get("Segments")
                or payload.get("transcription")
                or payload.get("Transcription")
                or payload.get("transcriptions")
                or payload.get("Transcriptions")
                or payload.get("items")
                or payload.get("Items")
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

        text = str(
            item.get("text") or item.get("Text") or item.get("content") or item.get("Content") or ""
        ).strip()
        start = _to_float(
            item.get("start")
            or item.get("Start")
            or item.get("start_time")
            or item.get("startTime")
            or item.get("StartTime")
            or 0.0
        )
        end = _to_float(
            item.get("end")
            or item.get("End")
            or item.get("end_time")
            or item.get("endTime")
            or item.get("EndTime")
            or start
        )
        if end < start:
            end = start

        speaker = (
            item.get("speaker")
            if "speaker" in item
            else item.get("Speaker")
            if "Speaker" in item
            else item.get("speaker_id")
            if "speaker_id" in item
            else item.get("speakerId")
            if "speakerId" in item
            else item.get("SpeakerId")
            if "SpeakerId" in item
            else item.get("speakerID")
            if "speakerID" in item
            else item.get("SpeakerID")
        )
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


def _looks_like_segment_item(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "text",
            "Text",
            "content",
            "Content",
            "start",
            "Start",
            "start_time",
            "StartTime",
            "end",
            "End",
            "speaker",
            "Speaker",
        )
    )


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
