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
        )
        return result, None

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
