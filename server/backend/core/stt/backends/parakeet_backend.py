"""NVIDIA Parakeet (NeMo) STT backend.

Wraps NeMo's ASRModel behind the STTBackend interface. NeMo is a large
optional dependency — imports are lazy so the module can be imported even
when ``nemo_toolkit`` is not installed.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np
from server.config import get_config
from server.core.audio_utils import clear_gpu_cache
from server.core.stt.backends.base import (
    BackendDependencyError,
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

# Target sample rate for Parakeet (same as Whisper)
SAMPLE_RATE = 16000

# Maximum audio duration (seconds) NeMo handles well in one pass.
# Longer files are chunked at this boundary to avoid OOM / quality issues.
MAX_CHUNK_DURATION = 10 * 60  # 10 minutes

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
        logger.debug("Skipping Python 3.13 Sampler compatibility patch", exc_info=True)


def _import_nemo_asr() -> Any:
    """Lazy-import ``nemo.collections.asr`` with a clear error message."""
    try:
        import nemo.collections.asr as nemo_asr  # type: ignore[import-untyped]

        _patch_sampler_for_python313()
        return nemo_asr
    except ImportError as exc:
        raise BackendDependencyError(
            "NeMo toolkit is required for NVIDIA Parakeet models but is not installed. "
            "Set INSTALL_NEMO=true in your Docker environment to enable it.",
            backend_type="nemo",
            remedy="Set INSTALL_NEMO=true in your Docker environment and restart.",
        ) from exc


class ParakeetBackend(STTBackend):
    """NVIDIA Parakeet / NeMo ASR backend."""

    # ------------------------------------------------------------------
    # Subclass override hooks
    # ------------------------------------------------------------------
    # Concrete NeMo model class used by ``load()``. Subclasses targeting
    # different NeMo model families (e.g. CanaryBackend's AED multitask
    # model) override this instead of duplicating the full ``load()`` body.
    _NEMO_MODEL_CLASS_NAME: str = "EncDecRNNTBPEModel"
    # Optional Hydra override config written to a temp YAML and passed as
    # ``override_config_path`` to ``from_pretrained()`` / ``restore_from()``.
    # Disables NeMo's CUDA graph decoder for CUDA ≥ 12.8 (RNN-T-specific).
    # Subclasses whose model class rejects this minimal override (e.g. the
    # Canary AED model, which insists the override include a tokenizer
    # section) set this to ``None`` to skip pre-load patching entirely.
    _LOAD_OVERRIDE_CONFIG: dict[str, Any] | None = {
        "decoding": {"greedy": {"use_cuda_graph_decoder": False}}
    }

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._warmup_complete: bool = False
        self._warmup_thread: threading.Thread | None = None
        self._max_chunk_duration_s: int = MAX_CHUNK_DURATION

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
        nemo_asr = _import_nemo_asr()
        logger.info(f"Loading {self.backend_name.capitalize()} model: {model_name}")

        # Fix 5: Check if model is cached locally and use restore_from()
        import tempfile
        from pathlib import Path

        import yaml

        local_nemo_path = self._find_cached_nemo_file(model_name)

        config_override_path = None

        try:
            # Optional Hydra override (RNN-T-specific CUDA-graph disable, Fix 2).
            # Subclasses set ``_LOAD_OVERRIDE_CONFIG = None`` to skip this when
            # their NeMo model class rejects the minimal override at restore
            # time (e.g. Canary's AED model demands a full tokenizer section).
            override_dict = self._LOAD_OVERRIDE_CONFIG

            if override_dict is not None:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
                    yaml.dump(override_dict, tmp)
                    config_override_path = tmp.name

            # Resolve the concrete NeMo model class from the subclass-overridable
            # ``_NEMO_MODEL_CLASS_NAME`` attribute. Using a concrete class
            # (rather than abstract ``ASRModel``) avoids "Can't instantiate
            # abstract class" errors when NeMo's saved-config target lookup
            # fails. CanaryBackend overrides this to ``"EncDecMultiTaskModel"``
            # so its AED checkpoint is loaded by the right class — using the
            # default RNN-T BPE class on a Canary model crashes inside
            # ``rnnt_bpe_models.py`` with ``cfg.decoder`` not in struct.
            model_cls = getattr(nemo_asr.models, self._NEMO_MODEL_CLASS_NAME)

            def _load_with_optional_override(
                load_fn: Any, load_name: str, **load_kwargs: Any
            ) -> Any:
                if not config_override_path:
                    return load_fn(**load_kwargs)

                try:
                    return load_fn(**load_kwargs, override_config_path=config_override_path)
                except TypeError:
                    # Older NeMo versions do not support override_config_path.
                    logger.warning(
                        "%s() does not support override_config_path; retrying without pre-patch",
                        load_name,
                    )
                    return load_fn(**load_kwargs)
                except ValueError as exc:
                    # Some newer NeMo builds appear to treat the override YAML as a full
                    # config during restore/from_pretrained, which drops required sections
                    # like tokenizer. Retry without the override and patch after load.
                    if "tokenizer" in str(exc) and "cfg" in str(exc):
                        logger.warning(
                            "%s() rejected minimal override config (%s); retrying without pre-patch",
                            load_name,
                            exc,
                        )
                        return load_fn(**load_kwargs)
                    raise

            if local_nemo_path:
                # Fix 5: Use restore_from() for cached models (faster, skips registry)
                logger.info(f"Found cached model at {local_nemo_path}, using restore_from()")
                try:
                    model = _load_with_optional_override(
                        model_cls.restore_from,
                        "restore_from",
                        restore_path=local_nemo_path,
                    )
                    logger.info("Loaded from local cache using restore_from()")
                except Exception as e:
                    logger.warning(f"restore_from() failed: {e}, falling back to from_pretrained()")
                    model = _load_with_optional_override(
                        model_cls.from_pretrained,
                        "from_pretrained",
                        model_name=model_name,
                    )
            else:
                # No local cache, use from_pretrained()
                logger.info("No cached model found, using from_pretrained()")
                model = _load_with_optional_override(
                    model_cls.from_pretrained,
                    "from_pretrained",
                    model_name=model_name,
                )
        finally:
            # Clean up temporary config file
            if config_override_path and Path(config_override_path).exists():
                try:
                    Path(config_override_path).unlink()
                except OSError:
                    logger.debug(
                        "Failed to delete temporary NeMo override config %s",
                        config_override_path,
                        exc_info=True,
                    )

        model = model.to(device)
        model.eval()
        self._apply_post_load_setup(model)

        self._model = model
        self._model_name = model_name
        logger.info(
            "%s model loaded (max_chunk_duration_s=%d)",
            self.backend_name.capitalize(),
            self._max_chunk_duration_s,
        )

    def _apply_post_load_setup(self, model: Any) -> None:
        """Apply RNN-T / Parakeet-specific post-load configuration.

        Disables NeMo's CUDA graph decoder (incompatible with CUDA ≥ 12.8),
        applies optional Conformer encoder optimisations from the
        ``parakeet:`` config block, and resolves ``_max_chunk_duration_s``.

        Subclasses targeting non-RNN-T NeMo models (e.g. Canary's AED
        multitask backend) override this — both the CUDA-graph patch and
        the encoder helpers are tied to the RNN-T decoding stack and the
        Conformer encoder respectively, neither of which apply to AED
        attention-encoder-decoder models.
        """
        self._disable_cuda_graphs(model)

        cfg = get_config()
        parakeet_cfg = cfg.get("parakeet", default={}) or {}

        if parakeet_cfg.get("use_local_attention", True):
            window = parakeet_cfg.get("local_attention_window", [128, 128])
            model.change_attention_model("rel_pos_local_attn", window)
            logger.info("Enabled local attention with window %s", window)

        if parakeet_cfg.get("subsampling_conv_chunking", True):
            model.change_subsampling_conv_chunking_factor(1)
            logger.info("Enabled subsampling conv chunking (factor=1)")

        try:
            self._max_chunk_duration_s = max(
                60,
                int(parakeet_cfg.get("max_chunk_duration_s", 300) or 300),
            )
        except (TypeError, ValueError):
            self._max_chunk_duration_s = 300

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        clear_gpu_cache()

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
        del audio_sample_rate
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

        if total_duration > self._max_chunk_duration_s:
            return self._transcribe_long(
                audio,
                word_timestamps=word_timestamps,
                progress_callback=progress_callback,
            )

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
        transcribe_fn: Callable[..., Any] | None = None,
        language: str = "en",
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Chunk long audio at ~20 min boundaries and concatenate results."""
        if transcribe_fn is None:
            transcribe_fn = self._transcribe_array

        chunk_samples = int(self._max_chunk_duration_s * SAMPLE_RATE)
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
            if progress_callback is not None:
                progress_callback(i + 1, num_chunks)

            output = transcribe_fn(chunk, timestamps=word_timestamps)
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
            if i < num_chunks - 1:
                clear_gpu_cache()

        info = BackendTranscriptionInfo(
            language=language,
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
