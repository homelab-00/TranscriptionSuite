"""NVIDIA Canary (NeMo) multitask ASR + translation backend.

Extends the Parakeet backend with ``source_lang`` / ``target_lang``
support required by Canary encoder-decoder models.  Canary supports
ASR in 25 European languages and bidirectional translation between
English and the other 24 languages.

Like Parakeet, NeMo is a large optional dependency — imports are lazy.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
)
from server.core.stt.backends.parakeet_backend import (
    MAX_CHUNK_DURATION,
    SAMPLE_RATE,
    ParakeetBackend,
)

logger = logging.getLogger(__name__)


class CanaryBackend(ParakeetBackend):
    """NVIDIA Canary / NeMo multitask ASR + translation backend."""

    # NeMo loads Canary checkpoints via ``EncDecMultiTaskModel`` — the AED
    # (Attention Encoder-Decoder) class. Loading them with the inherited
    # Parakeet default (``EncDecRNNTBPEModel``) crashes in
    # ``rnnt_bpe_models.py`` with ``ConfigAttributeError: Key 'decoder' is
    # not in struct`` because the saved Canary config has ``encoder`` and
    # ``decoding`` only — there is no top-level ``decoder`` key for the
    # RNN-T transducer. Confirmed via NeMo's official Canary tutorial,
    # which loads ``nvidia/canary-1b-v2`` with ``EncDecMultiTaskModel``.
    _NEMO_MODEL_CLASS_NAME: str = "EncDecMultiTaskModel"
    # Canary's AED model rejects Parakeet's minimal ``decoding.greedy``
    # override at restore time (the AED loader insists the override config
    # supply a full ``tokenizer`` section). Skip the pre-load Hydra patch
    # entirely — the RNN-T-specific CUDA-graph workaround it carries does
    # not apply to AED decoding.
    _LOAD_OVERRIDE_CONFIG: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # STTBackend interface overrides
    # ------------------------------------------------------------------

    def _apply_post_load_setup(self, model: Any) -> None:
        """Canary AED post-load configuration.

        The Parakeet superclass applies the RNN-T CUDA-graph workaround and
        the optional ``parakeet:`` Conformer-encoder tweaks. Both target
        constructs that do not exist on the Canary AED model:

        * the CUDA-graph patch reads ``cfg.decoding.greedy.use_cuda_graph_decoder``,
          which Canary's beam-search-over-Transformer-decoder configuration
          does not define;
        * ``change_attention_model`` / ``change_subsampling_conv_chunking_factor``
          target the Conformer encoder helpers and are gated on the
          ``parakeet:`` config block — applying them implicitly to a
          Canary load would silently re-shape its encoder.

        Just record ``_max_chunk_duration_s`` so the inherited chunking
        path in ``_transcribe_long`` has a sane value.
        """
        self._max_chunk_duration_s = MAX_CHUNK_DURATION

    def _do_warmup(self) -> None:
        """Internal method to perform actual Canary warmup."""
        try:
            warmup_start = time.perf_counter()
            logger.info("Starting Canary warmup...")
            silent_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self._transcribe_array_canary(
                silent_audio, source_lang="en", target_lang="en", timestamps=False
            )
            warmup_time = time.perf_counter() - warmup_start
            logger.info(f"[TIMING] Canary warmup complete ({warmup_time:.2f}s)")
            self._warmup_complete = True
        except Exception as e:
            logger.warning(f"Canary model warmup failed (non-critical): {e}")
            self._warmup_complete = True

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
            raise RuntimeError("Canary model is not loaded")

        # Canary requires an explicit source language — the model has no
        # built-in auto-detection. Silently defaulting to "en" caused issue
        # #81 (non-English audio was force-translated to English).
        if not language:
            raise ValueError(
                "Canary requires an explicit source language; received None. "
                "Set 'language' in the transcription request."
            )
        source_lang = language

        if task == "translate":
            # Use caller-specified target, defaulting to English.
            target_lang = (translation_target_language or "en").strip().lower()
            if word_timestamps:
                logger.info(
                    "Canary translation (AST) only provides segment-level timestamps; "
                    "word-level timestamps may be unavailable. Diarization speaker "
                    "attribution will fall back to segment-level alignment."
                )
        else:
            # Same source and target = pure transcription.
            target_lang = source_lang

        total_duration = len(audio) / SAMPLE_RATE

        if total_duration > MAX_CHUNK_DURATION:
            canary_fn = functools.partial(
                self._transcribe_array_canary,
                source_lang=source_lang,
                target_lang=target_lang,
            )
            return self._transcribe_long(
                audio,
                word_timestamps=word_timestamps,
                transcribe_fn=canary_fn,
                language=source_lang,
                progress_callback=progress_callback,
            )

        return self._transcribe_short_canary(
            audio,
            source_lang=source_lang,
            target_lang=target_lang,
            word_timestamps=word_timestamps,
        )

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "canary"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transcribe_array_canary(
        self,
        audio: np.ndarray,
        *,
        source_lang: str = "en",
        target_lang: str = "en",
        timestamps: bool = True,
    ) -> Any:
        """Run NeMo transcribe with Canary-specific language parameters."""
        import tempfile

        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype="FLOAT")
            output = self._model.transcribe(
                [tmp.name],
                source_lang=source_lang,
                target_lang=target_lang,
                timestamps=timestamps,
            )
        return output

    def _transcribe_short_canary(
        self,
        audio: np.ndarray,
        *,
        source_lang: str = "en",
        target_lang: str = "en",
        word_timestamps: bool = True,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Transcribe a single chunk within MAX_CHUNK_DURATION."""
        output = self._transcribe_array_canary(
            audio,
            source_lang=source_lang,
            target_lang=target_lang,
            timestamps=word_timestamps,
        )

        segments = self._parse_output(output, word_timestamps=word_timestamps)

        info = BackendTranscriptionInfo(
            language=source_lang,
            language_probability=1.0,
        )
        return segments, info
