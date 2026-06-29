"""SenseVoice (FunAudioLLM) STT backend.

Adapted from FunAudioLLM/SenseVoice (https://github.com/FunAudioLLM/SenseVoice)
and modelscope/FunASR (https://github.com/modelscope/FunASR) — wraps the
``funasr.AutoModel`` pipeline (SenseVoiceSmall + fsmn-vad) behind the project's
STTBackend interface.

Phase 1 scope: transcriber-only, CUDA/Linux. SenseVoice is non-autoregressive
and produces NO word-level timestamps; segments carry empty ``words`` lists and,
when funasr returns no per-sentence info, a single segment spanning the clip.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.core.audio_utils import clear_gpu_cache
from server.core.stt.backends.base import (
    BackendDependencyError,
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)

SAMPLE_RATE = 16000

# SenseVoiceSmall's first-class language codes (the only values its API accepts).
_SENSEVOICE_LANGUAGES = frozenset({"zh", "en", "yue", "ja", "ko"})
_LANG_TOKEN_RE = re.compile(r"<\|(zh|en|yue|ja|ko)\|>", re.IGNORECASE)

# FunASR's ``model=`` argument is a *hub repo id*, and the hub determines the
# namespace. The canonical id ``iic/SenseVoiceSmall`` lives on ModelScope; on
# HuggingFace (``hub="hf"``) the same weights are published under the FunAudioLLM
# org, and the bare ``iic/…`` id 404s (FunASR then silently retries it as an
# architecture key and dies with a misleading "not registered"). Map the
# well-known ModelScope ids to their HF equivalents so users can keep configuring
# the recognisable ``iic/SenseVoiceSmall``; unknown ids pass through unchanged.
_MODELSCOPE_TO_HF_REPO = {
    "iic/SenseVoiceSmall": "FunAudioLLM/SenseVoiceSmall",
}

logger = logging.getLogger(__name__)


def _compose_device(device: str, gpu_device_index: int) -> str:
    """Map the engine's ("cuda", index) convention to funasr's "cuda:N" string."""
    if device == "cuda":
        return f"cuda:{int(gpu_device_index)}"
    return device


def _resolve_hf_repo_id(model_name: str) -> str:
    """Translate a ModelScope model id to its HuggingFace repo id for ``hub="hf"``."""
    return _MODELSCOPE_TO_HF_REPO.get(model_name, model_name)


def _extract_language(raw_text: str | None) -> str | None:
    """Return the SenseVoice language code embedded in *raw_text*, if any."""
    match = _LANG_TOKEN_RE.search(raw_text or "")
    return match.group(1).lower() if match else None


def _format_spk(spk: Any) -> str:
    """Map a funasr integer ``spk`` index to the project's ``SPEAKER_NN`` label."""
    if spk is None:
        return "UNKNOWN"
    try:
        return f"SPEAKER_{int(spk):02d}"
    except (TypeError, ValueError):
        raw = str(spk).strip()
        return raw or "UNKNOWN"


_WORD_START_MARKER = "▁"  # U+2581; visually similar to "_" — named constant avoids confusion


def _tokens_to_words(
    tokens: list[list[Any]] | None, segment_offset_s: float
) -> list[dict[str, Any]]:
    """Merge CTC sub-word tokens ([piece, start_s, end_s]) into words.

    A new word starts on a piece beginning with the SentencePiece "▁" marker.
    Times are in seconds; ``segment_offset_s`` is added to make VAD-segment-relative
    timestamps absolute. Malformed input yields an empty list (caller falls back
    to segment-level).
    """
    if not tokens:
        return []
    words: list[dict[str, Any]] = []
    cur_text = ""
    cur_start: float | None = None
    cur_end: float | None = None
    try:
        for piece, start, end in tokens:
            piece_s = str(piece)
            s = float(start) + segment_offset_s
            e = float(end) + segment_offset_s
            if piece_s == _WORD_START_MARKER:
                if cur_text:
                    words.append({"word": cur_text, "start": cur_start, "end": cur_end})
                    cur_text, cur_start, cur_end = "", None, None
                continue
            starts_word = piece_s.startswith(_WORD_START_MARKER)
            clean = piece_s[1:] if starts_word else piece_s
            if starts_word or cur_start is None:
                if cur_text:
                    words.append({"word": cur_text, "start": cur_start, "end": cur_end})
                cur_text, cur_start, cur_end = clean, s, e
            else:
                cur_text += clean
                cur_end = e
    except (TypeError, ValueError):
        return []
    if cur_text:
        words.append({"word": cur_text, "start": cur_start, "end": cur_end})
    return words


def _segment_words(
    timestamp: list[list[Any]] | None, seg_start_s: float, seg_end_s: float
) -> list[dict[str, Any]]:
    """Best-effort: return words whose midpoint falls within [seg_start, seg_end).

    The top-level CTC ``timestamp`` is whole-clip; slice it per sentence. Any
    parse problem yields [] (segment-level fallback — never a hard dependency).
    """
    words = _tokens_to_words(timestamp, segment_offset_s=0.0)
    out: list[dict[str, Any]] = []
    for w in words:
        try:
            mid = (float(w["start"]) + float(w["end"])) / 2.0
        except (TypeError, ValueError, KeyError):
            continue
        if seg_start_s <= mid < seg_end_s:
            out.append(w)
    return out


def _write_temp_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Write float32 mono audio to a temp 16-bit WAV and return its path."""
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="sensevoice_")
    try:
        os.close(fd)
        sf.write(path, audio, sample_rate, subtype="PCM_16")
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(path)
        raise
    return path


def _import_funasr_automodel() -> Any:
    """Lazy-import ``funasr.AutoModel`` with a clear, actionable error message."""
    try:
        from funasr import AutoModel

        return AutoModel
    except ImportError as exc:
        raise BackendDependencyError(
            "FunASR is required for SenseVoice models but is not installed. "
            "Set INSTALL_FUNASR=true in your Docker environment to enable it.",
            backend_type="funasr",
            remedy="Set INSTALL_FUNASR=true in your Docker environment and restart.",
        ) from exc


class SenseVoiceBackend(STTBackend):
    """FunASR-backed SenseVoice transcription backend (Phase 1, CUDA/Linux)."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._device: str | None = None
        self._diarization_loaded: bool = False

    # -- lifecycle ----------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        AutoModel = _import_funasr_automodel()

        gpu_device_index = kwargs.get("gpu_device_index", 0)
        funasr_device = _compose_device(device, gpu_device_index)
        hf_repo_id = _resolve_hf_repo_id(model_name)

        logger.info(f"Loading SenseVoice model: {model_name} (hf:{hf_repo_id}) on {funasr_device}")
        # CAM++ single-pass diarization is the default for SenseVoice. cam++ is
        # ~28 MB, so we build it into the model unconditionally (when requested)
        # rather than reloading on a per-job toggle. Disable via
        # sensevoice_diarization=False (e.g. cam++ unavailable offline).
        want_diarization = bool(kwargs.get("sensevoice_diarization", True))
        model_kwargs: dict[str, Any] = {
            "model": hf_repo_id,
            "vad_model": "fsmn-vad",
            "vad_kwargs": {"max_single_segment_time": 30000},
            "device": funasr_device,
            "hub": "hf",
            "disable_update": True,
        }
        if want_diarization:
            # spk_mode="vad_segment" matches SenseVoice (no token timestamps) and
            # skips funasr's punc_segment warning + forced fallback.
            model_kwargs["spk_model"] = "cam++"
            model_kwargs["spk_mode"] = "vad_segment"
        try:
            self._model = AutoModel(**model_kwargs)
        except Exception:
            if want_diarization:
                logger.warning(
                    "SenseVoice: building with cam++ failed; retrying transcriber-only "
                    "(diarization will fall back to pyannote).",
                    exc_info=True,
                )
                model_kwargs.pop("spk_model", None)
                model_kwargs.pop("spk_mode", None)
                self._model = AutoModel(**model_kwargs)
                self._diarization_loaded = False
            else:
                raise
        else:
            self._diarization_loaded = want_diarization
        self._model_name = model_name
        self._device = funasr_device
        logger.info("SenseVoice model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        self._device = None
        self._diarization_loaded = False
        clear_gpu_cache()

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        try:
            warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"
            if warmup_path.exists():
                self._model.generate(input=str(warmup_path), cache={}, language="en", use_itn=True)
                logger.debug("SenseVoice warmup complete")
            else:
                logger.debug("SenseVoice warmup skipped (no warmup_audio.wav)")
        except Exception as e:  # noqa: BLE001 — warmup is best-effort
            logger.warning(f"SenseVoice warmup failed (non-critical): {e}")

    # -- transcription ------------------------------------------------------

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = SAMPLE_RATE,
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
        # SenseVoice has no translate task and no word timestamps — ignore the
        # Whisper-shaped knobs the engine passes through.
        del task, beam_size, initial_prompt, suppress_tokens
        del vad_filter, word_timestamps, translation_target_language, progress_callback

        if self._model is None:
            raise RuntimeError("SenseVoice model is not loaded")

        lang = self._resolve_language(language)
        wav_path = _write_temp_wav(audio, audio_sample_rate)
        try:
            result = self._model.generate(
                input=wav_path,
                cache={},
                language=lang,
                use_itn=True,
                batch_size_s=300,
                merge_vad=True,
                merge_length_s=15,
                output_timestamp=True,
            )
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        duration_s = float(len(audio)) / float(audio_sample_rate) if audio_sample_rate else 0.0
        return self._parse_result(result, duration_s, forced_language=lang)

    def transcribe_with_diarization(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        num_speakers: int | None = None,
        hf_token: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DiarizedTranscriptionResult | None:
        # CAM++ single-pass: speakers come from funasr's own generate() call.
        # Whisper-shaped knobs do not apply.
        del task, beam_size, initial_prompt, suppress_tokens, vad_filter
        del num_speakers, hf_token, progress_callback

        if self._model is None:
            raise RuntimeError("SenseVoice model is not loaded")

        lang = self._resolve_language(language)
        wav_path = _write_temp_wav(audio, audio_sample_rate)
        duration_s = float(len(audio)) / float(audio_sample_rate) if audio_sample_rate else 0.0
        try:
            try:
                result = self._model.generate(
                    input=wav_path,
                    cache={},
                    language=lang,
                    use_itn=True,
                    batch_size_s=300,
                    merge_vad=True,
                    merge_length_s=15,
                )
            except Exception:
                # Known upstream failure modes (distribute_spk TypeError, etc.).
                # NEVER drop the result — degrade to a plain transcript.
                logger.warning(
                    "SenseVoice CAM++ diarization failed; returning plain transcript "
                    "without speaker labels.",
                    exc_info=True,
                )
                return self._plain_diarized_fallback(audio, audio_sample_rate, lang)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        return self._parse_diarized_result(result, duration_s, forced_language=lang)

    def supports_translation(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "sensevoice"

    # -- helpers ------------------------------------------------------------

    def _resolve_language(self, language: str | None) -> str:
        if not language:
            return "auto"
        code = language.strip().lower()
        if code in _SENSEVOICE_LANGUAGES:
            return code
        logger.warning(
            f"SenseVoice does not support language '{language}'; falling back to auto-detect"
        )
        return "auto"

    def _parse_result(
        self,
        result: list[dict[str, Any]],
        duration_s: float,
        *,
        forced_language: str,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        if not result:
            return [], BackendTranscriptionInfo(language=None, language_probability=0.0)

        first = result[0]
        raw_text = str(first.get("text", ""))
        detected = _extract_language(raw_text)
        if detected is None and forced_language != "auto":
            detected = forced_language
        info = BackendTranscriptionInfo(language=detected, language_probability=0.0)

        # Preferred shape: per-sentence segments (VAD-chunk boundaries in ms).
        sentence_info = first.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            segments: list[BackendSegment] = []
            for sentence in sentence_info:
                text = rich_transcription_postprocess(
                    str(sentence.get("sentence") or sentence.get("text") or "")
                )
                start = float(sentence.get("start") or 0) / 1000.0
                end = float(sentence.get("end") or 0) / 1000.0
                seg_words = _segment_words(first.get("timestamp"), start, end)
                segments.append(BackendSegment(text=text, start=start, end=end, words=seg_words))
            return segments, info

        # Fallback: one segment spanning the whole clip (no timestamps available).
        text = rich_transcription_postprocess(raw_text)
        return [BackendSegment(text=text, start=0.0, end=duration_s, words=[])], info

    def _parse_diarized_result(
        self,
        result: list[dict[str, Any]],
        duration_s: float,
        *,
        forced_language: str,
    ) -> DiarizedTranscriptionResult:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        if not result:
            return DiarizedTranscriptionResult(
                segments=[], words=[], num_speakers=0, language=None, language_probability=0.0
            )

        first = result[0]
        raw_text = str(first.get("text", ""))
        detected = _extract_language(raw_text)
        if detected is None and forced_language != "auto":
            detected = forced_language

        sentence_info = first.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            segments: list[dict[str, Any]] = []
            speakers: set[str] = set()
            for sentence in sentence_info:
                text = rich_transcription_postprocess(
                    str(sentence.get("sentence") or sentence.get("text") or "")
                )
                speaker = _format_spk(sentence.get("spk"))
                if speaker != "UNKNOWN":
                    speakers.add(speaker)
                segments.append(
                    {
                        "text": text,
                        "start": float(sentence.get("start") or 0) / 1000.0,
                        "end": float(sentence.get("end") or 0) / 1000.0,
                        "speaker": speaker,
                        "words": [],
                    }
                )
            return DiarizedTranscriptionResult(
                segments=segments,
                words=[],
                num_speakers=len(speakers),
                language=detected,
                language_probability=0.0,
            )

        # No per-segment speaker info — degrade to one UNKNOWN-speaker segment.
        return DiarizedTranscriptionResult(
            segments=[
                {
                    "text": rich_transcription_postprocess(raw_text),
                    "start": 0.0,
                    "end": duration_s,
                    "speaker": "UNKNOWN",
                    "words": [],
                }
            ],
            words=[],
            num_speakers=0,
            language=detected,
            language_probability=0.0,
        )

    def _plain_diarized_fallback(
        self, audio: np.ndarray, audio_sample_rate: int, lang: str
    ) -> DiarizedTranscriptionResult:
        """Re-transcribe without speaker labels and wrap as UNKNOWN-speaker segments.

        Deliberately does NOT swallow a transcribe() failure: if the model is
        genuinely broken, the exception propagates so the route can fall through
        to standard (non-diarized) transcription / surface a real error — rather
        than silently delivering an empty transcript.
        """
        segments, info = self.transcribe(audio, audio_sample_rate=audio_sample_rate, language=lang)
        return DiarizedTranscriptionResult(
            segments=[
                {"text": s.text, "start": s.start, "end": s.end, "speaker": "UNKNOWN", "words": []}
                for s in segments
            ],
            words=[],
            num_speakers=0,
            language=info.language,
            language_probability=info.language_probability,
        )
