"""NVIDIA Parakeet (NeMo) STT backend.

Wraps NeMo's ASRModel behind the STTBackend interface. NeMo is a large
optional dependency — imports are lazy so the module can be imported even
when ``nemo_toolkit`` is not installed.
"""

from __future__ import annotations

import gc
import logging
import math
from typing import Any

import numpy as np
import torch
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

# Target sample rate for Parakeet (same as Whisper)
SAMPLE_RATE = 16000

# Maximum audio duration (seconds) NeMo handles well in one pass.
# Longer files are chunked at this boundary to avoid OOM / quality issues.
MAX_CHUNK_DURATION = 20 * 60  # 20 minutes

logger = logging.getLogger(__name__)


def _patch_sampler_for_python313() -> None:
    """Fix lhotse compatibility with Python 3.13+.

    Python 3.13 made ``object.__init__()`` strict about rejecting keyword
    arguments.  lhotse's ``CutSampler`` calls
    ``super().__init__(data_source=None)`` which reaches ``object.__init__``
    when PyTorch's ``Sampler`` does not override ``__init__``, causing a
    ``TypeError``.  This patch adds a thin ``__init__`` that accepts and
    ignores the deprecated ``data_source`` parameter.
    """
    try:
        from torch.utils.data import Sampler

        if Sampler.__init__ is object.__init__:

            def _sampler_init(self, data_source=None):  # noqa: ARG001
                pass

            Sampler.__init__ = _sampler_init  # type: ignore[assignment]
    except (ImportError, AttributeError):
        pass


def _import_nemo_asr() -> Any:
    """Lazy-import ``nemo.collections.asr`` with a clear error message."""
    try:
        import nemo.collections.asr as nemo_asr  # type: ignore[import-untyped]

        _patch_sampler_for_python313()
        return nemo_asr
    except ImportError as exc:
        raise ImportError(
            "NeMo toolkit is required for NVIDIA Parakeet models but is not installed. "
            "Set INSTALL_NEMO=true in your Docker environment to enable it."
        ) from exc


class ParakeetBackend(STTBackend):
    """NVIDIA Parakeet / NeMo ASR backend."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None

    # ------------------------------------------------------------------
    # CUDA graph workaround
    # ------------------------------------------------------------------

    @staticmethod
    def _disable_cuda_graphs(model: Any) -> None:
        """Disable CUDA graphs in NeMo's RNNT/TDT decoding stack.

        NeMo 2.6's ``tdt_label_looping._full_graph_compile`` unpacks 6
        values from ``cu_call(cudaStreamGetCaptureInfo_v3, ...)``, but
        newer CUDA toolkit versions (≥ 12.8) return only 5 values,
        causing ``ValueError: not enough values to unpack``.

        Disabling CUDA graphs forces the fallback ``loop_labels_impl``
        path which avoids the incompatibility.

        The fix is applied at the **config level** so that any future
        decoding strategy recreation (e.g. ``transcribe(timestamps=True)``)
        also inherits the disabled setting.
        """
        from omegaconf import OmegaConf, open_dict

        # ---- Config-level fix (persistent across strategy rebuilds) ----
        cfg = getattr(model, "cfg", None)
        decoding_cfg = cfg.get("decoding", None) if cfg is not None else None

        if decoding_cfg is not None:
            greedy_cfg = decoding_cfg.get("greedy", None)
            if greedy_cfg is not None and greedy_cfg.get("use_cuda_graph_decoder", False):
                with open_dict(decoding_cfg):
                    greedy_cfg.use_cuda_graph_decoder = False
                logger.info("Patched model.cfg.decoding.greedy.use_cuda_graph_decoder = False")

                # Rebuild the current decoding stack from the patched config
                if hasattr(model, "change_decoding_strategy"):
                    try:
                        model.change_decoding_strategy(
                            decoding_cfg=OmegaConf.to_container(decoding_cfg, resolve=True),
                        )
                        logger.info("Rebuilt decoding strategy via change_decoding_strategy()")
                        return
                    except Exception:
                        logger.warning(
                            "change_decoding_strategy() failed; falling back to runtime patch",
                            exc_info=True,
                        )

        # ---- Fallback: runtime object patch ----
        decoding = getattr(model, "decoding", None)
        if decoding is None:
            return

        inner = getattr(decoding, "decoding", None)
        if inner is None:
            return

        computer = getattr(inner, "decoding_computer", None)
        if computer is not None and getattr(computer, "use_cuda_graphs", False):
            computer.use_cuda_graphs = False
            logger.info("Disabled CUDA graphs on decoding_computer (runtime fallback)")

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        nemo_asr = _import_nemo_asr()

        logger.info(f"Loading Parakeet model: {model_name}")

        model = nemo_asr.models.ASRModel.from_pretrained(model_name=model_name)
        model = model.to(device)
        model.eval()

        self._disable_cuda_graphs(model)

        self._model = model
        self._model_name = model_name
        logger.info("Parakeet model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None
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
            silent_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self._transcribe_array(silent_audio, timestamps=False)
            logger.debug("Parakeet model warmup complete")
        except Exception as e:
            logger.warning(f"Parakeet model warmup failed (non-critical): {e}")

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
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        if self._model is None:
            raise RuntimeError("Parakeet model is not loaded")

        if task == "translate":
            raise ValueError(
                "NVIDIA Parakeet models do not support translation. "
                "Use a multilingual Whisper model for the translate task."
            )

        # Whisper-specific params (beam_size, suppress_tokens, vad_filter,
        # initial_prompt) are silently ignored — they have no Parakeet equivalent.

        total_samples = len(audio)
        total_duration = total_samples / SAMPLE_RATE

        if total_duration > MAX_CHUNK_DURATION:
            return self._transcribe_long(audio, word_timestamps=word_timestamps)

        return self._transcribe_short(audio, word_timestamps=word_timestamps, language=language)

    def supports_translation(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "parakeet"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transcribe_array(
        self,
        audio: np.ndarray,
        *,
        timestamps: bool = True,
    ) -> Any:
        """Run NeMo transcribe on a single numpy array."""
        import tempfile

        import soundfile as sf

        # NeMo's transcribe() expects file paths or torch tensors.
        # We write a temporary WAV for simplicity and compatibility.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype="FLOAT")
            output = self._model.transcribe(
                [tmp.name],
                timestamps=timestamps,
            )
        return output

    def _transcribe_short(
        self,
        audio: np.ndarray,
        *,
        word_timestamps: bool = True,
        language: str | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Transcribe a single chunk that fits within MAX_CHUNK_DURATION."""
        output = self._transcribe_array(audio, timestamps=word_timestamps)

        segments = self._parse_output(output, word_timestamps=word_timestamps)

        # Language detection: Parakeet v3 auto-detects but NeMo doesn't
        # expose the detected language consistently. Default to user-specified
        # or "en".
        detected_language = language or "en"

        info = BackendTranscriptionInfo(
            language=detected_language,
            language_probability=1.0,
        )
        return segments, info

    def _transcribe_long(
        self,
        audio: np.ndarray,
        *,
        word_timestamps: bool = True,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Chunk long audio at ~20 min boundaries and concatenate results."""
        chunk_samples = int(MAX_CHUNK_DURATION * SAMPLE_RATE)
        total_samples = len(audio)
        num_chunks = math.ceil(total_samples / chunk_samples)

        all_segments: list[BackendSegment] = []
        time_offset = 0.0

        for i in range(num_chunks):
            start = i * chunk_samples
            end = min(start + chunk_samples, total_samples)
            chunk = audio[start:end]

            logger.info(
                f"Transcribing chunk {i + 1}/{num_chunks} "
                f"({time_offset:.0f}s - {time_offset + len(chunk) / SAMPLE_RATE:.0f}s)"
            )

            output = self._transcribe_array(chunk, timestamps=word_timestamps)
            chunk_segments = self._parse_output(output, word_timestamps=word_timestamps)

            # Offset timestamps
            for seg in chunk_segments:
                seg.start += time_offset
                seg.end += time_offset
                for w in seg.words:
                    w["start"] = w["start"] + time_offset
                    w["end"] = w["end"] + time_offset

            all_segments.extend(chunk_segments)
            time_offset += len(chunk) / SAMPLE_RATE

        info = BackendTranscriptionInfo(
            language="en",
            language_probability=1.0,
        )
        return all_segments, info

    # ------------------------------------------------------------------
    # Hypothesis helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_timestamp_dict(obj: Any) -> dict | None:
        """Extract the timestamp dict from a NeMo Hypothesis-like object.

        NeMo has used ``timestamp``, ``timestamps``, and ``timestep`` across
        versions.  Return the first truthy dict found, or *None*.
        """
        for attr in ("timestamp", "timestamps", "timestep"):
            ts = getattr(obj, attr, None)
            if ts and isinstance(ts, dict):
                return ts
        return None

    def _hypothesis_to_segments(
        self,
        hypothesis: Any,
        *,
        word_timestamps: bool = True,
    ) -> list[BackendSegment]:
        """Convert a single NeMo Hypothesis object into BackendSegments."""
        segments: list[BackendSegment] = []
        ts = self._get_timestamp_dict(hypothesis)

        if ts is not None:
            seg_timestamps = ts.get("segment", [])
            word_timestamps_data = ts.get("word", [])

            if seg_timestamps:
                for seg_ts in seg_timestamps:
                    text = seg_ts.get("text", seg_ts.get("label", "")).strip()
                    start = float(seg_ts.get("start", 0.0))
                    end = float(seg_ts.get("end", 0.0))

                    words: list[dict[str, Any]] = []
                    if word_timestamps and word_timestamps_data:
                        for w in word_timestamps_data:
                            w_start = float(w.get("start", 0.0))
                            w_end = float(w.get("end", 0.0))
                            if w_start >= start - 0.01 and w_end <= end + 0.01:
                                words.append(
                                    {
                                        "word": w.get("text", w.get("label", "")),
                                        "start": w_start,
                                        "end": w_end,
                                        "probability": float(w.get("confidence", 1.0)),
                                    }
                                )

                    if text:
                        segments.append(
                            BackendSegment(text=text, start=start, end=end, words=words)
                        )

                if segments:
                    return segments

            # Timestamps dict exists but no segment entries — build words-only
            if word_timestamps_data:
                all_words: list[dict[str, Any]] = []
                text_parts: list[str] = []
                for w in word_timestamps_data:
                    w_text = w.get("text", w.get("label", w.get("char", "")))
                    all_words.append(
                        {
                            "word": w_text,
                            "start": float(w.get("start", 0.0)),
                            "end": float(w.get("end", 0.0)),
                            "probability": float(w.get("confidence", 1.0)),
                        }
                    )
                    text_parts.append(w_text)
                joined = " ".join(text_parts).strip()
                if joined:
                    start = all_words[0]["start"]
                    end = all_words[-1]["end"]
                    segments.append(
                        BackendSegment(text=joined, start=start, end=end, words=all_words)
                    )
                    return segments

        # Fall back to text-only
        text = getattr(hypothesis, "text", None)
        if text is None:
            text = str(hypothesis)
        text = text.strip() if isinstance(text, str) else ""
        if text:
            segments.append(BackendSegment(text=text, start=0.0, end=0.0))
        return segments

    def _parse_output(
        self,
        output: Any,
        *,
        word_timestamps: bool = True,
    ) -> list[BackendSegment]:
        """Convert NeMo transcription output to BackendSegment list."""
        segments: list[BackendSegment] = []

        # NeMo output structure varies by model version. Known shapes:
        #   List[str]              — plain text (return_hypotheses=False)
        #   List[Hypothesis]       — with timestamps / return_hypotheses=True
        #   List[List[str]]        — batched plain text
        #   List[List[Hypothesis]] — batched hypotheses

        if not output:
            logger.info("_parse_output: output is falsy: %r", output)
            return segments

        logger.info(
            "_parse_output: type(output)=%s, len=%s, repr=%.500r",
            type(output).__name__,
            getattr(output, "__len__", lambda: "N/A")(),
            output,
        )

        # Iterate over all items in output (one per input file)
        for idx, item in enumerate(output):
            logger.info(
                "_parse_output: item[%d] type=%s, repr=%.500r",
                idx,
                type(item).__name__,
                item,
            )

            if isinstance(item, str):
                # Plain text result
                if item.strip():
                    segments.append(BackendSegment(text=item.strip(), start=0.0, end=0.0))
                continue

            if isinstance(item, list):
                # Nested list — iterate inner items
                for inner in item:
                    if isinstance(inner, str):
                        if inner.strip():
                            segments.append(BackendSegment(text=inner.strip(), start=0.0, end=0.0))
                    else:
                        segments.extend(
                            self._hypothesis_to_segments(inner, word_timestamps=word_timestamps)
                        )
                continue

            # Hypothesis-like object
            segments.extend(self._hypothesis_to_segments(item, word_timestamps=word_timestamps))

        logger.info("_parse_output: returning %d segments", len(segments))
        return segments
