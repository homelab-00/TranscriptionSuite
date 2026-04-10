"""MLX Parakeet STT backend (Apple Silicon / Metal acceleration).

Uses the ``parakeet-mlx`` package which runs NVIDIA Parakeet-TDT models via
Apple's MLX framework, giving Metal GPU acceleration on Apple Silicon Macs.

Recommended model ID (mlx-community namespace on HuggingFace):
    mlx-community/parakeet-tdt-0.6b-v3

key characteristics:
- 25 European languages with native punctuation and capitalisation
- No translation task support
- Token-level timestamps exposed as word timestamps for diarization
- Sentence segmentation via silence-gap and duration heuristics

Note: mlx-community/parakeet-tdt-1.1b is the older (pre-2025) model trained
on 64K hours of English-only data without native punctuation or capitalisation.
``parakeet-tdt-0.6b-v3`` supersedes it: 660K hours, 25 languages, P&C native.

The model is downloaded and cached by ``parakeet-mlx`` on first load.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.config import get_config
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

# Default local-attention context window (frames).  Mirrors the parakeet-mlx
# streaming default and the NeMo backend's local_attention_window setting.
DEFAULT_LOCAL_ATTENTION_WINDOW: tuple[int, int] = (256, 256)

# Audio longer than this (seconds) automatically gets local (sliding-window)
# attention to prevent the O(N²) Metal allocation crash.  Files at or below
# this threshold keep the default global attention for best quality.
# Mirrors the NeMo backend's max_chunk_duration_s setting.
DEFAULT_MAX_CHUNK_DURATION_S: int = 30

# Audio longer than this (seconds) falls back from local attention to chunked
# inference.  Local attention dispatches a Metal kernel with (B*H*S_q) *
# (2*window+1) threads; for ~10 min of audio that is ~92 M threads, which
# reliably causes a Metal GPU fault or hang on Apple Silicon.  Chunked
# inference processes the audio in shorter pieces and avoids the crash.
DEFAULT_CHUNK_INFERENCE_THRESHOLD_S: int = 600  # 10 minutes

# Chunk parameters used when falling back to chunked inference.
DEFAULT_CHUNK_DURATION_S: float = 60.0
DEFAULT_CHUNK_OVERLAP_S: float = 15.0

logger = logging.getLogger(__name__)


def _tokens_to_words(tokens: list[Any]) -> list[dict[str, Any]]:
    """Group Parakeet AlignedToken objects into word-level dicts.

    parakeet-mlx replaces the SentencePiece word-boundary character `▁`
    (U+2581) with a plain space in each token's ``.text`` field.  A token
    whose ``.text`` starts with a space marks the beginning of a new word;
    continuation pieces have no leading space.  Pure-whitespace tokens are
    treated as separators and discarded.

    Returns a list of dicts compatible with the engine's word format:
    ``{"word", "start", "end", "probability"}``.
    """
    words: list[dict[str, Any]] = []
    buf_pieces: list[str] = []
    buf_start: float = 0.0
    buf_end: float = 0.0
    buf_conf: list[float] = []

    def flush() -> None:
        text = "".join(buf_pieces).strip()
        if text:
            words.append(
                {
                    "word": text,
                    "start": round(buf_start, 3),
                    "end": round(buf_end, 3),
                    # Use minimum confidence across pieces (conservative).
                    "probability": round(min(buf_conf, default=1.0), 3),
                }
            )
        buf_pieces.clear()
        buf_conf.clear()

    for tok in tokens:
        text: str = tok.text
        if not text or not text.strip():
            # Pure whitespace / blank token — word separator.
            flush()
            continue

        starts_word = text.startswith(" ")
        stripped = text.lstrip(" ")

        if starts_word and buf_pieces:
            flush()

        if not buf_pieces:
            # First piece of a new word — record its start time.
            buf_start = float(tok.start)  # type: ignore[attr-defined]

        buf_pieces.append(stripped)
        buf_end = float(tok.end)  # type: ignore[attr-defined]
        buf_conf.append(float(tok.confidence))  # type: ignore[attr-defined]

    flush()
    return words


class MLXParakeetBackend(STTBackend):
    """Apple MLX / Metal-accelerated Parakeet-TDT backend.

    Wraps ``parakeet-mlx`` for NVIDIA Parakeet-TDT inference on Apple Silicon.
    25 EU languages (auto-detected from audio); sentence-level timestamps; no translation.
    Only available on macOS with Apple Silicon.
    """

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._model: Any | None = None
        self._loaded: bool = False
        self._use_local_attention: bool = True
        self._local_attention_window: tuple[int, int] = DEFAULT_LOCAL_ATTENTION_WINDOW
        self._max_chunk_duration_s: int = DEFAULT_MAX_CHUNK_DURATION_S
        self._chunk_inference_threshold_s: int = DEFAULT_CHUNK_INFERENCE_THRESHOLD_S
        self._chunk_duration_s: float = DEFAULT_CHUNK_DURATION_S
        self._chunk_overlap_s: float = DEFAULT_CHUNK_OVERLAP_S
        # Tracks the encoder's current attention mode so we only call
        # set_attention_model() when a switch is actually needed.
        self._attention_mode: str = "global"

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        """Load the Parakeet model via ``parakeet_mlx.from_pretrained``."""
        del device, kwargs
        try:
            from parakeet_mlx import from_pretrained  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "parakeet-mlx is not installed. "
                "Run: uv sync --extra mlx  (requires macOS + Apple Silicon)"
            ) from exc

        logger.info(f"Loading MLX Parakeet model: {model_name}")
        try:
            from parakeet_mlx import from_pretrained

            self._model = from_pretrained(model_name)
            self._model_name = model_name
            self._loaded = True

            # Read config from mlx_parakeet section.
            cfg = get_config()
            mlx_cfg = cfg.get("mlx_parakeet", default={}) or {}

            self._use_local_attention = bool(mlx_cfg.get("use_local_attention", True))

            raw_window = mlx_cfg.get("local_attention_window", list(DEFAULT_LOCAL_ATTENTION_WINDOW))
            try:
                left, right = int(raw_window[0]), int(raw_window[1])
                self._local_attention_window = (left, right)
            except (TypeError, ValueError, IndexError):
                self._local_attention_window = DEFAULT_LOCAL_ATTENTION_WINDOW

            try:
                self._max_chunk_duration_s = max(
                    1,
                    int(mlx_cfg.get("max_chunk_duration_s", DEFAULT_MAX_CHUNK_DURATION_S) or DEFAULT_MAX_CHUNK_DURATION_S),
                )
            except (TypeError, ValueError):
                self._max_chunk_duration_s = DEFAULT_MAX_CHUNK_DURATION_S

            try:
                self._chunk_inference_threshold_s = max(
                    1,
                    int(mlx_cfg.get("chunk_inference_threshold_s", DEFAULT_CHUNK_INFERENCE_THRESHOLD_S) or DEFAULT_CHUNK_INFERENCE_THRESHOLD_S),
                )
            except (TypeError, ValueError):
                self._chunk_inference_threshold_s = DEFAULT_CHUNK_INFERENCE_THRESHOLD_S

            try:
                self._chunk_duration_s = max(
                    5.0,
                    float(mlx_cfg.get("chunk_duration_s", DEFAULT_CHUNK_DURATION_S) or DEFAULT_CHUNK_DURATION_S),
                )
            except (TypeError, ValueError):
                self._chunk_duration_s = DEFAULT_CHUNK_DURATION_S

            try:
                self._chunk_overlap_s = max(
                    0.0,
                    float(mlx_cfg.get("chunk_overlap_s", DEFAULT_CHUNK_OVERLAP_S) or DEFAULT_CHUNK_OVERLAP_S),
                )
            except (TypeError, ValueError):
                self._chunk_overlap_s = DEFAULT_CHUNK_OVERLAP_S

            # Attention mode starts as "global" (the model's built-in default);
            # transcribe() switches per-call based on audio duration.
            self._attention_mode = "global"

            logger.info(
                "MLX Parakeet model loaded: %s (use_local_attention=%s, local_attention_window=%s, "
                "max_chunk_duration_s=%d, chunk_inference_threshold_s=%d)",
                model_name,
                self._use_local_attention,
                self._local_attention_window,
                self._max_chunk_duration_s,
                self._chunk_inference_threshold_s,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load MLX Parakeet model '{model_name}': {exc}"
            ) from exc

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def warmup(self) -> None:
        if not self._loaded or self._model is None:
            return
        try:
            warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, warmup_audio, SAMPLE_RATE)
                tmp_path = tmp.name
            try:
                self._model.transcribe(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
            logger.debug("MLX Parakeet warmup complete")
        except Exception as e:
            logger.warning(f"MLX Parakeet warmup failed (non-critical): {e}")

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
        # parakeet-mlx exposes no language-hint API; language/task parameters are
        # accepted for interface compatibility but have no effect. The model
        # auto-detects the language from the audio content.
        del (
            language,
            task,
            beam_size,
            initial_prompt,
            suppress_tokens,
            vad_filter,
            word_timestamps,
            translation_target_language,
            progress_callback,
        )

        if not self._loaded or self._model is None:
            raise RuntimeError("MLX Parakeet model is not loaded")

        # Resample if needed.
        if audio_sample_rate != SAMPLE_RATE:
            from scipy.signal import resample as sp_resample

            target_length = int(len(audio) * SAMPLE_RATE / audio_sample_rate)
            audio = sp_resample(audio, target_length).astype(np.float32)

        if audio.dtype != np.float32:
            if np.issubdtype(audio.dtype, np.integer):
                audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
            else:
                audio = audio.astype(np.float32)

        # parakeet-mlx expects a file path, write audio to a temp WAV.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            from parakeet_mlx import DecodingConfig, SentenceConfig

            decoding_config = DecodingConfig(
                sentence=SentenceConfig(
                    # Split on silence gaps ≥ 0.5 s and cap each sentence at
                    # 30 s.  This ensures the 1.1b model (which rarely emits
                    # sentence-ending punctuation) still produces meaningful
                    # segments rather than one monolithic utterance.
                    silence_gap=0.5,
                    max_duration=30.0,
                )
            )

            # 3-way strategy based on audio duration:
            #
            # ① Short (≤ max_chunk_duration_s): global attention — best quality,
            #    the full-sequence attention matrix fits easily in Metal.
            #
            # ② Medium (max_chunk_duration_s < dur ≤ chunk_inference_threshold_s):
            #    local (sliding-window) attention — O(N) memory, single pass,
            #    no boundary stitching artefacts.
            #
            # ③ Very long (> chunk_inference_threshold_s): chunked inference with
            #    global attention per chunk.  Local attention's custom Metal kernel
            #    dispatches B*H*S_q * (2*W+1) threads — for a 61-minute file that
            #    is ~380 M threads, which causes a Metal GPU fault / hang on Apple
            #    Silicon regardless of available memory.  The parakeet-mlx
            #    chunk_duration API processes overlapping segments so boundary
            #    artefacts are minimised.
            audio_duration_s = len(audio) / SAMPLE_RATE

            if self._use_local_attention and audio_duration_s > self._chunk_inference_threshold_s:
                # Regime ③ — chunked inference.  Switch encoder back to global
                # attention so each chunk gets the highest-quality decode.
                if self._attention_mode != "global":
                    self._model.encoder.set_attention_model(
                        "rel_pos", self._local_attention_window
                    )
                    self._attention_mode = "global"
                logger.info(
                    "MLX Parakeet: using chunked inference (%.0fs chunks, %.0fs overlap) for %.0fs audio",
                    self._chunk_duration_s,
                    self._chunk_overlap_s,
                    audio_duration_s,
                )
                result = self._model.transcribe(
                    tmp_path,
                    decoding_config=decoding_config,
                    chunk_duration=self._chunk_duration_s,
                    overlap_duration=self._chunk_overlap_s,
                )

            elif self._use_local_attention and audio_duration_s > self._max_chunk_duration_s:
                # Regime ② — local sliding-window attention.
                if self._attention_mode != "local":
                    self._model.encoder.set_attention_model(
                        "rel_pos_local_attn", self._local_attention_window
                    )
                    self._attention_mode = "local"
                    logger.info(
                        "MLX Parakeet: switched to local attention for %.0fs audio",
                        audio_duration_s,
                    )
                result = self._model.transcribe(tmp_path, decoding_config=decoding_config)

            else:
                # Regime ① — global attention.
                if self._attention_mode != "global":
                    self._model.encoder.set_attention_model(
                        "rel_pos", self._local_attention_window
                    )
                    self._attention_mode = "global"
                    logger.info(
                        "MLX Parakeet: switched to global attention for %.0fs audio",
                        audio_duration_s,
                    )
                result = self._model.transcribe(tmp_path, decoding_config=decoding_config)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Convert AlignedResult.sentences → BackendSegment list.
        #
        # sentence.text is the library's authoritative decode: it joins all
        # token texts as "".join(t.text for t in tokens), where each token's
        # text is vocabulary[id].replace("▁", " ").  This correctly places
        # spaces only at word boundaries (word-initial SentencePiece pieces
        # carry "▁" → space; continuation pieces do not) and preserves all
        # punctuation tokens exactly as the model produced them.
        #
        # _tokens_to_words() is retained solely to generate word-level
        # timestamps for the diarization pipeline.  We no longer use it to
        # reconstruct segment text, which avoids two problems that occurred
        # when joining stripped word groups with " ".join():
        #   1. Punctuation tokens that start with a space in the vocabulary
        #      (e.g. " ," or " .") became isolated words, producing
        #      "boundary . Okay" instead of "boundary. Okay".
        #   2. Any punctuation at a word-group boundary could be dropped or
        #      misattributed when the join added an extra space before it.
        #
        # parakeet-tdt-0.6b-v3 produces punctuation and capitalisation natively
        # (those are part of its token vocabulary from training).
        segments: list[BackendSegment] = []
        if hasattr(result, "sentences") and result.sentences:
            for sentence in result.sentences:
                words = _tokens_to_words(sentence.tokens)
                segments.append(
                    BackendSegment(
                        text=str(sentence.text).strip(),
                        start=float(sentence.start),
                        end=float(sentence.end),
                        words=words,
                    )
                )
        elif hasattr(result, "text") and str(result.text).strip():
            # Fallback: no sentence segmentation — create one segment.
            segments.append(
                BackendSegment(
                    text=str(result.text).strip(),
                    start=0.0,
                    end=float(len(audio)) / SAMPLE_RATE,
                    words=[],
                )
            )

        info = BackendTranscriptionInfo(
            language="en",
            language_probability=1.0,
        )
        return segments, info

    def supports_translation(self) -> bool:
        return False

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_parakeet"
