"""NVIDIA Parakeet (NeMo) STT backend.

Wraps NeMo's ASRModel behind the STTBackend interface. NeMo is a large
optional dependency — imports are lazy so the module can be imported even
when ``nemo_toolkit`` is not installed.
"""

from __future__ import annotations

import gc
import logging
import math
import threading
import time
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
        self._warmup_complete: bool = False
        self._warmup_thread: threading.Thread | None = None

    @staticmethod
    def _find_cached_nemo_file(model_name: str) -> str | None:
        """Fix 5: Find cached .nemo file for the model to use restore_from().

        Searches common cache locations for NeMo models downloaded by from_pretrained().
        Returns path to .nemo file if found, None otherwise.
        """
        import os
        from pathlib import Path

        # Common cache locations
        cache_dirs = []

        # HuggingFace cache (most common for NeMo models)
        hf_cache = os.environ.get("HF_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface"
        )
        cache_dirs.append(Path(hf_cache) / "hub")

        # NeMo cache
        nemo_cache = os.environ.get("NEMO_CACHE_DIR") or os.path.join(
            os.path.expanduser("~"), ".cache", "nemo"
        )
        cache_dirs.append(Path(nemo_cache))

        # Torch hub cache
        torch_cache = os.environ.get("TORCH_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache", "torch"
        )
        cache_dirs.append(Path(torch_cache) / "hub")

        # Normalize model name for searching (e.g., nvidia/parakeet-tdt-0.6b-v3)
        search_patterns = [
            model_name.lower().replace("/", "--").replace("_", "-"),
            model_name.lower().replace("/", "_"),
            model_name.split("/")[-1] if "/" in model_name else model_name,
        ]

        for cache_dir in cache_dirs:
            if not cache_dir.exists():
                continue

            # Search for matching directories
            for pattern in search_patterns:
                # HuggingFace format: models--nvidia--parakeet-tdt-0.6b-v3
                for subdir in cache_dir.glob(f"*{pattern}*"):
                    if subdir.is_dir():
                        # Look for .nemo files recursively
                        for nemo_file in subdir.rglob("*.nemo"):
                            logger.info(f"Found cached .nemo file: {nemo_file}")
                            return str(nemo_file)

        return None

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

        config_patched = False
        if decoding_cfg is not None:
            greedy_cfg = decoding_cfg.get("greedy", None)

            # NeMo defaults use_cuda_graph_decoder=None to True when CUDA
            # is available, so we must patch unless it is explicitly False.
            if greedy_cfg is not None:
                current = greedy_cfg.get("use_cuda_graph_decoder", None)
                if current is not False:
                    with open_dict(decoding_cfg):
                        greedy_cfg.use_cuda_graph_decoder = False
                    config_patched = True
                    logger.info(
                        "Patched model.cfg.decoding.greedy.use_cuda_graph_decoder = False (was %r)",
                        current,
                    )
            else:
                # greedy section missing — create it so rebuilds pick it up
                with open_dict(decoding_cfg):
                    decoding_cfg.greedy = {"use_cuda_graph_decoder": False}
                config_patched = True
                logger.info("Created model.cfg.decoding.greedy with use_cuda_graph_decoder = False")

            if config_patched and hasattr(model, "change_decoding_strategy"):
                try:
                    model.change_decoding_strategy(
                        decoding_cfg=OmegaConf.to_container(decoding_cfg, resolve=True),
                    )
                    logger.info("Rebuilt decoding strategy via change_decoding_strategy()")
                except Exception:
                    logger.warning(
                        "change_decoding_strategy() failed; will try runtime patch",
                        exc_info=True,
                    )

        # ---- Belt-and-suspenders: runtime object patch ----
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
        progress_callback = kwargs.get("progress_callback")
        load_start = time.perf_counter()

        def report(msg: str, elapsed: float | None = None) -> None:
            if elapsed is not None:
                logger.info(f"[TIMING] {msg} ({elapsed:.2f}s)")
            else:
                logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        # B1: NeMo Import
        step_start = time.perf_counter()
        report("Importing NeMo toolkit...")
        nemo_asr = _import_nemo_asr()
        import_time = time.perf_counter() - step_start
        report("NeMo import complete", import_time)

        # B2: Load model - use restore_from() for cached models (Fix 5)
        step_start = time.perf_counter()
        report(f"Loading Parakeet model: {model_name}")

        # Fix 5: Check if model is cached locally and use restore_from()
        import tempfile
        from pathlib import Path

        import yaml

        local_nemo_path = self._find_cached_nemo_file(model_name)

        config_override_path = None

        try:
            # Create a minimal config override to disable CUDA graphs (Fix 2)
            override_dict = {"decoding": {"greedy": {"use_cuda_graph_decoder": False}}}

            # Write to a temporary YAML file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
                yaml.dump(override_dict, tmp)
                config_override_path = tmp.name

            # Use concrete EncDecRNNTBPEModel instead of abstract ASRModel
            # to avoid "Can't instantiate abstract class ASRModel" errors
            # when NeMo fails to resolve the target class from config.
            model_cls = nemo_asr.models.EncDecRNNTBPEModel

            if local_nemo_path:
                # Fix 5: Use restore_from() for cached models (faster, skips registry)
                logger.info(f"Found cached model at {local_nemo_path}, using restore_from()")
                try:
                    model = model_cls.restore_from(
                        restore_path=local_nemo_path, override_config_path=config_override_path
                    )
                    logger.info("Loaded from local cache using restore_from()")
                except Exception as e:
                    logger.warning(f"restore_from() failed: {e}, falling back to from_pretrained()")
                    model = model_cls.from_pretrained(
                        model_name=model_name, override_config_path=config_override_path
                    )
            else:
                # No local cache, use from_pretrained()
                logger.info("No cached model found, using from_pretrained()")
                try:
                    model = model_cls.from_pretrained(
                        model_name=model_name, override_config_path=config_override_path
                    )
                except TypeError:
                    # Fallback: override_config_path not supported in this NeMo version
                    logger.warning("override_config_path not supported, loading without pre-patch")
                    model = model_cls.from_pretrained(model_name=model_name)
        finally:
            # Clean up temporary config file
            if config_override_path and Path(config_override_path).exists():
                try:
                    Path(config_override_path).unlink()
                except Exception:
                    pass

        pretrained_time = time.perf_counter() - step_start
        report("Model loading complete", pretrained_time)

        # B3: model.to(device)
        step_start = time.perf_counter()
        report("Transferring model to GPU...")
        model = model.to(device)
        model.eval()
        to_device_time = time.perf_counter() - step_start
        report("GPU transfer complete", to_device_time)

        # B4: CUDA graph verification (should be pre-patched by Fix 2)
        step_start = time.perf_counter()
        report("Verifying CUDA graph config...")
        # Verify the config was applied, apply runtime patch if needed
        self._disable_cuda_graphs(model)
        cuda_graph_time = time.perf_counter() - step_start
        report("CUDA graph config verified", cuda_graph_time)

        self._model = model
        self._model_name = model_name
        total_time = time.perf_counter() - load_start
        report(f"Parakeet model loaded (total: {total_time:.2f}s)")

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

    def warmup(self, background: bool = False) -> None:
        """Run warmup inference.

        Args:
            background: If True, run warmup in a background thread (Fix 4)
        """
        if self._model is None:
            return

        if background:
            # Start warmup in background thread
            def _warmup_worker():
                self._do_warmup()

            self._warmup_thread = threading.Thread(target=_warmup_worker, daemon=True)
            self._warmup_thread.start()
            logger.info("Started background warmup thread")
        else:
            # Blocking warmup
            self._do_warmup()

    def _do_warmup(self) -> None:
        """Internal method to perform actual warmup."""
        try:
            # B5: First inference (warmup)
            warmup_start = time.perf_counter()
            logger.info("Starting Parakeet warmup...")
            silent_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self._transcribe_array(silent_audio, timestamps=False)
            warmup_time = time.perf_counter() - warmup_start
            logger.info(f"[TIMING] Parakeet warmup complete ({warmup_time:.2f}s)")
            self._warmup_complete = True
        except Exception as e:
            logger.warning(f"Parakeet model warmup failed (non-critical): {e}")
            self._warmup_complete = True  # Mark complete even on failure

    def wait_for_warmup(self, timeout: float = 60.0) -> bool:
        """Wait for background warmup to complete.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if warmup completed, False if timeout
        """
        if self._warmup_complete:
            return True

        if self._warmup_thread is not None and self._warmup_thread.is_alive():
            logger.info("Waiting for warmup to complete...")
            self._warmup_thread.join(timeout=timeout)
            if self._warmup_thread.is_alive():
                logger.warning(f"Warmup still running after {timeout}s timeout")
                return False

        return self._warmup_complete

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
            raise RuntimeError("Parakeet model is not loaded")

        # Wait for warmup to complete if it's still running
        if not self._warmup_complete:
            self.wait_for_warmup()

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
                    # NeMo Parakeet uses "segment" key; other models may use "text"/"label"
                    text = seg_ts.get(
                        "text", seg_ts.get("label", seg_ts.get("segment", ""))
                    ).strip()
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
                                        # NeMo Parakeet uses "word" key; others use "text"/"label"
                                        "word": w.get("word", w.get("text", w.get("label", ""))),
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
                    # NeMo Parakeet uses "word" key; other models use "text"/"label"/"char"
                    w_text = w.get("word", w.get("text", w.get("label", w.get("char", ""))))
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
