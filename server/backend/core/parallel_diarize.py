"""
Parallel transcription + diarization orchestrator.

Runs STT transcription and PyAnnote speaker diarization concurrently using a
ThreadPoolExecutor.  Both operations are fully independent — transcription
produces word timestamps from audio, diarization produces speaker segments from
audio — and only the final merge step needs both outputs.

Thread safety: the two jobs use completely separate objects
(AudioToTextRecorder vs DiarizationEngine) with no shared mutable state.
Both release the GIL during CUDA operations, enabling real GPU parallelism.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

from server.core.model_manager import TranscriptionCancelledError

if TYPE_CHECKING:
    from server.core.diarization_engine import DiarizationResult
    from server.core.model_manager import ModelManager
    from server.core.stt.engine import AudioToTextRecorder, TranscriptionResult

logger = logging.getLogger(__name__)


def transcribe_then_diarize(
    *,
    engine: AudioToTextRecorder,
    model_manager: ModelManager,
    file_path: str,
    language: str | None = None,
    task: str | None = None,
    translation_target_language: str | None = None,
    word_timestamps: bool = True,
    expected_speakers: int | None = None,
    cancellation_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[TranscriptionResult, DiarizationResult | None]:
    """Run transcription and diarization **sequentially**.

    Identical contract to :func:`transcribe_and_diarize` but never runs both
    models on GPU at the same time.  Useful on GPUs with <16 GB VRAM where the
    combined memory pressure of concurrent STT + diarization causes OOM.

    Phase 1 — Transcribe (GPU).
    Phase 2 — Load diarization model + audio, then diarize (GPU).

    Returns ``(transcription_result, diarization_result | None)``.
    *diarization_result* is ``None`` when diarization fails at any stage.
    """

    # ------------------------------------------------------------------
    # Phase 1 — Transcribe
    # ------------------------------------------------------------------
    logger.info("Starting sequential transcription (transcribe-then-diarize)")
    result = engine.transcribe_file(
        file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        word_timestamps=word_timestamps,
        cancellation_check=cancellation_check,
        progress_callback=progress_callback,
    )
    logger.info("Transcription complete — unloading STT model before diarization")
    model_manager.unload_transcription_model()  # Frees ~1-10GB VRAM depending on backend

    # ------------------------------------------------------------------
    # Phase 2 — Diarize
    # ------------------------------------------------------------------
    try:
        model_manager.load_diarization_model()
        diar_engine = model_manager.diarization_engine

        from server.core.audio_utils import load_audio

        audio_data, audio_sample_rate = load_audio(file_path, target_sample_rate=16000)

        diar_result = diar_engine.diarize_audio(
            audio_data, audio_sample_rate, num_speakers=expected_speakers
        )
        logger.info(
            "Sequential diarization complete: %s speakers found",
            diar_result.num_speakers,
        )
        return result, diar_result
    except Exception:
        logger.warning(
            "Diarization failed during sequential run — returning transcript without speakers",
            exc_info=True,
        )
        return result, None
    finally:
        # Restore the pre-job model state:
        #   • Unload the diarization model — it's only needed during this phase.
        #   • Reload the STT model — it was unloaded above to free VRAM.
        # Both are no-ops when models are already in the target state.
        # Running here (before any return) guarantees the STT model is available
        # for subsequent jobs regardless of how this function exits.
        model_manager.unload_diarization_model()
        try:
            model_manager.load_transcription_model()
        except Exception:
            logger.warning(
                "Failed to reload STT model after sequential diarization",
                exc_info=True,
            )


def transcribe_and_diarize(
    *,
    engine: AudioToTextRecorder,
    model_manager: ModelManager,
    file_path: str,
    language: str | None = None,
    task: str | None = None,
    translation_target_language: str | None = None,
    word_timestamps: bool = True,
    expected_speakers: int | None = None,
    cancellation_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[TranscriptionResult, DiarizationResult | None]:
    """Run transcription and diarization in parallel.

    Phase 1 — Pre-load: load the diarization model and audio (for diarization).
    Phase 2 — Parallel: submit transcription and diarization to a 2-thread pool.
    Phase 3 — Collect: wait for both, handle errors gracefully.

    Returns ``(transcription_result, diarization_result | None)``.
    *diarization_result* is ``None`` when diarization fails at any stage.
    """

    # ------------------------------------------------------------------
    # Phase 1 — Pre-load diarization model + audio
    # ------------------------------------------------------------------
    diar_engine = None
    audio_data = None
    audio_sample_rate: int = 16000

    try:
        model_manager.load_diarization_model()
        diar_engine = model_manager.diarization_engine

        from server.core.audio_utils import load_audio

        audio_data, audio_sample_rate = load_audio(file_path, target_sample_rate=16000)
    except Exception:
        logger.warning(
            "Diarization pre-load failed — falling back to transcription only",
            exc_info=True,
        )

    # If pre-load failed, just transcribe normally
    if diar_engine is None or audio_data is None:
        result = engine.transcribe_file(
            file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
        )
        return result, None

    # Sortformer uses MLX/Metal — running it in parallel with MLX Whisper
    # (also Metal) deadlocks the GPU.  Fall back to sequential mode.
    from server.core.sortformer_engine import SortformerEngine

    if isinstance(diar_engine, SortformerEngine):
        logger.info(
            "Sortformer + MLX detected — switching to sequential mode to avoid Metal deadlock"
        )
        return transcribe_then_diarize(
            engine=engine,
            model_manager=model_manager,
            file_path=file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            expected_speakers=expected_speakers,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
        )

    # ------------------------------------------------------------------
    # Phase 2 — Parallel execution
    # ------------------------------------------------------------------
    logger.info("Starting parallel transcription + diarization")

    # Capture audio_data/sample_rate in closures for the diarization worker
    _audio_data = audio_data
    _audio_sr = audio_sample_rate
    _expected = expected_speakers

    def _do_transcribe() -> TranscriptionResult:
        threading.current_thread().name = "parallel_diarize:transcribe"
        return engine.transcribe_file(
            file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
        )

    def _do_diarize() -> DiarizationResult:
        threading.current_thread().name = "parallel_diarize:diarize"
        return diar_engine.diarize_audio(_audio_data, _audio_sr, num_speakers=_expected)

    transcribe_future: Future[TranscriptionResult]
    diarize_future: Future[DiarizationResult]

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="parallel_diarize") as pool:
        transcribe_future = pool.submit(_do_transcribe)
        diarize_future = pool.submit(_do_diarize)

        # ------------------------------------------------------------------
        # Phase 3 — Collect results
        # ------------------------------------------------------------------

        # Wait for transcription first — it's the critical path.
        try:
            result = transcribe_future.result()
        except TranscriptionCancelledError:
            diarize_future.cancel()
            raise
        except Exception:
            diarize_future.cancel()
            raise

        # Collect diarization (non-critical — failures degrade gracefully).
        try:
            diar_result = diarize_future.result()
            logger.info(
                "Parallel diarization complete: %s speakers found",
                diar_result.num_speakers,
            )
            return result, diar_result
        except Exception:
            logger.warning(
                "Diarization failed during parallel run — returning transcript without speakers",
                exc_info=True,
            )
            return result, None
