"""
Model lifecycle management for TranscriptionSuite server.

Handles:
- Model loading and caching
- GPU memory management
- Model switching between modes
- Real-time transcription engines
- Graceful cleanup

NOTE: All heavy imports (torch, faster_whisper, pyannote, etc.) are done lazily
inside methods to avoid loading them at module import time.
"""

import logging
import os
import threading
import uuid
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from server.config import resolve_main_transcriber_model

# Type-only imports for hints (no runtime cost)
if TYPE_CHECKING:
    from server.core.client_detector import ClientType
    from server.core.diarization_engine import DiarizationEngine
    from server.core.realtime_engine import RealtimeTranscriptionEngine
    from server.core.stt.engine import AudioToTextRecorder

logger = logging.getLogger(__name__)

# Process-global filter: PyAnnote 4.x emits a noisy warning when TorchCodec is
# present but incompatible with the current Torch/FFmpeg runtime. We pass
# in-memory audio arrays everywhere, so the decoder warning is non-fatal.
# Install early at model_manager level to catch the warning during model init.
_PYANNOTE_TORCHCODEC_WARNING_RE = (
    r"torchcodec is not installed correctly so built-in audio decoding will fail\..*"
)
warnings.filterwarnings(
    "ignore",
    message=_PYANNOTE_TORCHCODEC_WARNING_RE,
    category=UserWarning,
)


class TranscriptionCancelledError(Exception):
    """Raised when a transcription job is cancelled."""

    pass


class TranscriptionJobTracker:
    """
    Tracks active transcription jobs across all methods (WebSocket, HTTP uploads).

    Ensures only one transcription job runs at a time across the entire server.
    Thread-safe for concurrent access from multiple request handlers.
    Supports cancellation of running jobs.
    """

    def __init__(self):
        self._active_job_id: str | None = None
        self._active_user: str | None = None
        self._cancelled: bool = False
        self._progress: dict[str, Any] | None = None
        self._result: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def try_start_job(self, user: str) -> tuple[bool, str | None, str | None]:
        """
        Attempt to start a new transcription job.

        Args:
            user: Client name/identifier for the user starting the job

        Returns:
            Tuple of (success, job_id_if_success, active_user_if_busy)
            - If success: (True, job_id, None)
            - If busy: (False, None, active_user)
        """
        with self._lock:
            if self._active_job_id is not None:
                return (False, None, self._active_user)

            job_id = str(uuid.uuid4())
            self._active_job_id = job_id
            self._active_user = user
            self._cancelled = False
            self._result = None  # Clear previous job result
            logger.info(f"Started transcription job {job_id[:8]} for user '{user}'")
            return (True, job_id, None)

    def end_job(self, job_id: str, result: dict[str, Any] | None = None) -> bool:
        """
        Mark a transcription job as complete.

        Args:
            job_id: The job ID returned from try_start_job
            result: Optional result dict to store for client polling.
                    On success: {"job_id": ..., "recording_id": ..., ...}
                    On failure: {"job_id": ..., "error": "..."}

        Returns:
            True if the job was ended, False if job_id didn't match
        """
        with self._lock:
            if self._active_job_id == job_id:
                logger.info(f"Ended transcription job {job_id[:8]} for user '{self._active_user}'")
                self._active_job_id = None
                self._active_user = None
                self._cancelled = False
                self._progress = None
                self._result = result
                return True
            return False

    def cancel_job(self) -> tuple[bool, str | None]:
        """
        Request cancellation of the currently running job.

        Returns:
            Tuple of (success, cancelled_user)
            - If job was running: (True, user_who_was_cancelled)
            - If no job running: (False, None)
        """
        with self._lock:
            if self._active_job_id is not None:
                self._cancelled = True
                user = self._active_user
                logger.info(
                    f"Cancellation requested for job {self._active_job_id[:8]} (user: {user})"
                )
                return (True, user)
            return (False, None)

    def is_cancelled(self) -> bool:
        """
        Check if cancellation has been requested for the current job.

        This should be called periodically during transcription to allow
        early termination.

        Returns:
            True if cancellation was requested
        """
        with self._lock:
            return self._cancelled

    def is_busy(self) -> tuple[bool, str | None]:
        """
        Check if a transcription job is currently running.

        Returns:
            Tuple of (is_busy, active_user_if_busy)
        """
        with self._lock:
            if self._active_job_id is not None:
                return (True, self._active_user)
            return (False, None)

    def update_progress(self, current: int, total: int, message: str = "") -> None:
        """Update the progress of the current transcription job."""
        with self._lock:
            self._progress = {"current": current, "total": total, "message": message}

    def clear_progress(self) -> None:
        """Clear the current progress information."""
        with self._lock:
            self._progress = None

    def get_status(self) -> dict[str, Any]:
        """Get the current job tracker status."""
        with self._lock:
            return {
                "is_busy": self._active_job_id is not None,
                "active_user": self._active_user,
                "active_job_id": self._active_job_id[:8] if self._active_job_id else None,
                "cancellation_requested": self._cancelled,
                "progress": self._progress,
                "result": self._result,
            }


class ModelManager:
    """
    Manages AI model lifecycle for the transcription server.

    Keeps one model loaded at a time to manage GPU memory efficiently.
    Handles model caching and switching between different configurations.

    Supports:
    - File-based and streaming transcription (AudioToTextRecorder - unified engine)
    - Real-time transcription with VAD (RealtimeTranscriptionEngine)
    - Speaker diarization (DiarizationEngine)
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize the model manager.

        Args:
            config: Full application configuration dict
        """
        # Lazy imports
        from server.core.audio_utils import check_cuda_available, get_gpu_memory_info

        self.config = config
        self._transcription_engine: AudioToTextRecorder | None = None
        self._diarization_engine: Any | None = None  # Will be DiarizationEngine
        self._realtime_engines: dict[str, RealtimeTranscriptionEngine] = {}
        self._diarization_feature_available: bool = False
        self._diarization_feature_reason: str = "token_missing"
        self._whisper_feature_available: bool = False
        self._whisper_feature_reason: str = "not_requested"
        self._nemo_feature_available: bool = False
        self._nemo_feature_reason: str = "not_requested"
        self._nemo_import_thread: threading.Thread | None = None
        self._vibevoice_asr_feature_available: bool = False
        self._vibevoice_asr_feature_reason: str = "not_requested"
        self._vibevoice_asr_feature_error: str | None = None

        # Job tracker for ensuring only one transcription runs at a time
        self.job_tracker = TranscriptionJobTracker()

        # Check GPU availability
        self.gpu_available = check_cuda_available()
        if self.gpu_available:
            gpu_info = get_gpu_memory_info()
            logger.info(f"GPU available with {gpu_info.get('total_gb', 'unknown')} GB memory")
        else:
            logger.warning("No GPU available, using CPU for transcription")

        # Initialize feature status from bootstrap output if available.
        self._initialize_diarization_feature_status()
        self._initialize_whisper_feature_status()
        self._initialize_nemo_feature_status()
        self._initialize_vibevoice_asr_feature_status()

        # Fix 3: Start background NeMo import if NeMo models will be used
        self._start_background_nemo_import()

    def _initialize_diarization_feature_status(self) -> None:
        """Initialize diarization feature availability from bootstrap state/env."""
        status_file = os.environ.get("BOOTSTRAP_STATUS_FILE", "/runtime/bootstrap-status.json")
        try:
            import json
            from pathlib import Path

            path = Path(status_file)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                diar = payload.get("features", {}).get("diarization", {})
                available = bool(diar.get("available", False))
                reason = str(diar.get("reason", "unavailable") or "unavailable")
                self._set_diarization_feature_status(available, reason)
                logger.info(
                    "Loaded diarization feature status from bootstrap: "
                    f"available={available}, reason={reason}"
                )
                return
        except Exception as e:
            logger.debug(f"Could not load bootstrap feature status: {e}")

        # Fallback to env/config signal only.
        diar_cfg = self.config.get("diarization", {})
        token = (
            os.environ.get("HF_TOKEN", "").strip() or str(diar_cfg.get("hf_token") or "").strip()
        )
        if token:
            self._set_diarization_feature_status(True, "ready")
        else:
            self._set_diarization_feature_status(False, "token_missing")

    def _initialize_nemo_feature_status(self) -> None:
        """Initialize NeMo feature availability from bootstrap state/env."""
        status_file = os.environ.get("BOOTSTRAP_STATUS_FILE", "/runtime/bootstrap-status.json")
        try:
            import json
            from pathlib import Path

            path = Path(status_file)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                nemo = payload.get("features", {}).get("nemo", {})
                available = bool(nemo.get("available", False))
                reason = str(nemo.get("reason", "not_requested") or "not_requested")
                self._nemo_feature_available = available
                self._nemo_feature_reason = reason
                logger.info(
                    "Loaded NeMo feature status from bootstrap: "
                    f"available={available}, reason={reason}"
                )
                return
        except Exception as e:
            logger.debug(f"Could not load NeMo feature status from bootstrap: {e}")

        self._nemo_feature_available = False
        self._nemo_feature_reason = "not_requested"

    def _initialize_whisper_feature_status(self) -> None:
        """Initialize faster-whisper feature availability from bootstrap state/env."""
        status_file = os.environ.get("BOOTSTRAP_STATUS_FILE", "/runtime/bootstrap-status.json")
        try:
            import json
            from pathlib import Path

            path = Path(status_file)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                whisper = payload.get("features", {}).get("whisper", {})
                available = bool(whisper.get("available", False))
                reason = str(whisper.get("reason", "not_requested") or "not_requested")
                self._whisper_feature_available = available
                self._whisper_feature_reason = reason
                logger.info(
                    "Loaded faster-whisper feature status from bootstrap: "
                    f"available={available}, reason={reason}"
                )
                return
        except Exception as e:
            logger.debug(f"Could not load faster-whisper feature status from bootstrap: {e}")

        install_requested = os.environ.get("INSTALL_WHISPER", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._whisper_feature_available = False
        self._whisper_feature_reason = "requested" if install_requested else "not_requested"

    def _initialize_vibevoice_asr_feature_status(self) -> None:
        """Initialize VibeVoice-ASR feature availability from bootstrap state/env."""
        status_file = os.environ.get("BOOTSTRAP_STATUS_FILE", "/runtime/bootstrap-status.json")
        try:
            import json
            from pathlib import Path

            path = Path(status_file)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                vibevoice = payload.get("features", {}).get("vibevoice_asr", {})
                available = bool(vibevoice.get("available", False))
                reason = str(vibevoice.get("reason", "not_requested") or "not_requested")
                error_value = vibevoice.get("error")
                error = str(error_value).strip() if error_value else None
                self._vibevoice_asr_feature_available = available
                self._vibevoice_asr_feature_reason = reason
                self._vibevoice_asr_feature_error = error or None
                logger.info(
                    "Loaded VibeVoice-ASR feature status from bootstrap: "
                    f"available={available}, reason={reason}"
                )
                return
        except Exception as e:
            logger.debug(f"Could not load VibeVoice-ASR feature status from bootstrap: {e}")

        install_requested = os.environ.get("INSTALL_VIBEVOICE_ASR", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._vibevoice_asr_feature_available = False
        self._vibevoice_asr_feature_reason = "requested" if install_requested else "not_requested"
        self._vibevoice_asr_feature_error = None

    def _start_background_nemo_import(self) -> None:
        """Fix 3: Start background NeMo import to reduce startup latency.

        If a NeMo model (Parakeet/Canary) is configured, start importing
        nemo.collections.asr in a background thread. By the time backend.load()
        runs, the import will be cached in sys.modules, eliminating B1.
        """
        if not self._nemo_feature_available:
            return

        # Check if main transcriber is a NeMo model
        model_name = self.main_model_name.lower()
        is_nemo_model = "parakeet" in model_name or "canary" in model_name

        if not is_nemo_model:
            return

        def _import_nemo_async():
            """Background thread to import NeMo."""
            try:
                logger.info("[BACKGROUND] Starting NeMo import...")
                import time as time_module

                start = time_module.perf_counter()

                import nemo.collections.asr  # noqa: F401

                elapsed = time_module.perf_counter() - start
                logger.info(f"[BACKGROUND] NeMo import complete ({elapsed:.2f}s)")
            except ImportError as e:
                logger.warning(f"[BACKGROUND] NeMo import failed: {e}")
            except Exception as e:
                logger.warning(f"[BACKGROUND] Unexpected error in NeMo import: {e}")

        self._nemo_import_thread = threading.Thread(target=_import_nemo_async, daemon=True)
        self._nemo_import_thread.start()
        logger.info("Started background NeMo import thread")

    def _set_diarization_feature_status(self, available: bool, reason: str) -> None:
        """Set diarization feature availability metadata."""
        self._diarization_feature_available = available
        self._diarization_feature_reason = reason

    def _classify_diarization_error(self, exc: Exception) -> str:
        """Map diarization exceptions to capability reasons."""
        message = str(exc).lower()
        status_code = getattr(getattr(exc, "response", None), "status_code", None)

        if "huggingface token required" in message or "set hf_token" in message:
            return "token_missing"
        if status_code == 401 or "invalid token" in message or "unauthorized" in message:
            return "token_invalid"
        if status_code == 403 and ("gated" in message or "terms" in message or "accept" in message):
            return "terms_not_accepted"
        if status_code == 403:
            return "token_invalid"
        if "gated" in message or "terms" in message or "accept" in message:
            return "terms_not_accepted"
        return "unavailable"

    def get_diarization_feature_status(self) -> dict[str, Any]:
        """Return diarization capability metadata for API clients."""
        return {
            "available": self._diarization_feature_available,
            "reason": self._diarization_feature_reason,
        }

    def get_vibevoice_asr_feature_status(self) -> dict[str, Any]:
        """Return VibeVoice-ASR capability metadata for API clients."""
        status: dict[str, Any] = {
            "available": self._vibevoice_asr_feature_available,
            "reason": self._vibevoice_asr_feature_reason,
        }
        if self._vibevoice_asr_feature_error:
            status["error"] = self._vibevoice_asr_feature_error
        return status

    def _get_mlx_feature_status(self) -> dict[str, Any]:
        """Check if MLX Whisper (Apple Silicon Metal) is available."""
        import platform as _platform
        import sys

        if sys.platform != "darwin":
            return {"available": False, "reason": "not_macos"}
        if _platform.machine() != "arm64":
            return {"available": False, "reason": "not_apple_silicon"}
        try:
            import mlx_whisper  # noqa: F401

            return {"available": True, "reason": "mlx_whisper_installed"}
        except ImportError:
            return {"available": False, "reason": "mlx_whisper_not_installed"}

    def get_whisper_feature_status(self) -> dict[str, Any]:
        """Return faster-whisper capability metadata for API clients."""
        return {
            "available": self._whisper_feature_available,
            "reason": self._whisper_feature_reason,
        }

    def is_main_model_disabled(self) -> bool:
        """Return True when main transcription slot is intentionally disabled."""
        return not self.main_model_name.strip()

    @property
    def main_model_name(self) -> str:
        """Get the configured main transcription model name."""
        return resolve_main_transcriber_model(self.config)

    def is_same_model(self, model_a: str, model_b: str) -> bool:
        """
        Check if two model names refer to the same underlying model files.

        This handles cases where the model names may differ slightly
        (e.g., with or without 'Systran/' prefix) but use the same weights.

        Args:
            model_a: First model name
            model_b: Second model name

        Returns:
            True if models are the same, False otherwise
        """

        # Normalize model names (remove common prefixes)
        def normalize(name: str) -> str:
            name = name.lower().strip()
            # Remove common prefixes
            for prefix in [
                "systran/",
                "faster-whisper-",
                "openai/whisper-",
                "nvidia/",
                "microsoft/",
            ]:
                if name.startswith(prefix):
                    name = name[len(prefix) :]
            return name

        return normalize(model_a) == normalize(model_b)

    def _scale_batch_size(self, configured_batch_size: int) -> int:
        """Scale batch_size down for GPUs with limited VRAM.

        WhisperX batched inference allocates ~0.2-0.3 GB per batch slot for
        encoder outputs, decoder KV caches, and attention matrices.  On GPUs
        with ≤12 GB total VRAM, the default batch_size=16 can push peak usage
        beyond the available budget when combined with the whisper model itself
        (~3 GB) and the PyAnnote VAD (~0.5 GB).

        The scaling is conservative — it only reduces, never increases, and
        logs when it does so.
        """
        if not self.gpu_available:
            return configured_batch_size

        from server.core.audio_utils import get_gpu_memory_info

        gpu_info = get_gpu_memory_info()
        total_gb = gpu_info.get("total_gb", 0)
        if total_gb <= 0:
            return configured_batch_size

        # Tiered caps based on total GPU VRAM
        if total_gb <= 8:
            cap = 4
        elif total_gb <= 12:
            cap = 8
        elif total_gb <= 16:
            cap = 12
        else:
            return configured_batch_size  # ≥24 GB — no cap needed

        if configured_batch_size > cap:
            logger.info(
                "Auto-scaling batch_size %d → %d for %.1f GB GPU to avoid OOM",
                configured_batch_size,
                cap,
                total_gb,
            )
            return cap
        return configured_batch_size

    @property
    def transcription_engine(self) -> "AudioToTextRecorder":
        """Get or create the unified transcription engine."""
        if self._transcription_engine is None:
            self._transcription_engine = self._create_transcription_engine()
        return self._transcription_engine

    def _create_transcription_engine(self) -> "AudioToTextRecorder":
        """Create the unified transcription engine from config."""
        # Wait for background NeMo import to complete if it's running
        if self._nemo_import_thread is not None and self._nemo_import_thread.is_alive():
            logger.info("Waiting for background NeMo import to complete...")
            self._nemo_import_thread.join(timeout=60.0)
            if self._nemo_import_thread.is_alive():
                logger.warning("Background NeMo import still running after 60s timeout")

        from server.core.stt.engine import AudioToTextRecorder

        main_cfg = self.config.get("main_transcriber", {})
        trans_opts = self.config.get("longform_recording", {})
        resolved_main_model = resolve_main_transcriber_model(self.config)
        if not resolved_main_model.strip():
            raise RuntimeError(
                "Main transcriber model is disabled; select a model before recording."
            )

        configured_batch_size = main_cfg.get("batch_size", 16)
        effective_batch_size = self._scale_batch_size(configured_batch_size)

        return AudioToTextRecorder(
            instance_name="file_transcriber",
            model=resolved_main_model,
            device=main_cfg.get("device", "cuda"),
            compute_type=main_cfg.get("compute_type", "default"),
            beam_size=main_cfg.get("beam_size", 5),
            batch_size=effective_batch_size,
            language=trans_opts.get("language", ""),
            task=("translate" if trans_opts.get("translation_enabled", False) else "transcribe"),
            translation_target_language=trans_opts.get("translation_target_language", "en"),
            faster_whisper_vad_filter=main_cfg.get("faster_whisper_vad_filter", True),
            initial_prompt=main_cfg.get("initial_prompt"),
        )

    def load_transcription_model(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        """
        Explicitly load the transcription model.

        Args:
            progress_callback: Optional callback for progress messages.
                              Called with status strings during loading.
        """

        def report(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        engine = self.transcription_engine
        if not engine.is_loaded():
            report("Loading transcription model...")
            report(f"Model: {engine.model_name}")
            report("This may take a few minutes for first-time downloads...")
            engine.load_model()
            report("Transcription model ready")

    def unload_transcription_model(self) -> None:
        """Unload the transcription model to free memory."""
        if self._transcription_engine is not None:
            self._transcription_engine.unload_model()

    @property
    def diarization_engine(self) -> "DiarizationEngine":
        """Get or create the diarization engine."""
        from server.core.diarization_engine import create_diarization_engine

        if self._diarization_engine is None:
            self._diarization_engine = create_diarization_engine(self.config)
        return self._diarization_engine

    def load_diarization_model(self) -> None:
        """Load the speaker diarization model."""
        engine = self.diarization_engine
        if not engine.is_loaded():
            logger.info("Loading diarization model...")
            try:
                engine.load()
            except Exception as e:
                reason = self._classify_diarization_error(e)
                self._set_diarization_feature_status(False, reason)
                logger.warning(f"Diarization model load failed: reason={reason}, error={e}")
                raise
            logger.info("Diarization model ready")
            self._set_diarization_feature_status(True, "ready")

    def unload_diarization_model(self) -> None:
        """Unload the diarization model."""
        from server.core.audio_utils import clear_gpu_cache

        if self._diarization_engine is not None:
            try:
                self._diarization_engine.unload()
            except AttributeError:
                logger.debug("Diarization engine has no unload method")
            self._diarization_engine = None
            clear_gpu_cache()
            logger.info("Diarization model unloaded")

    # =========================================================================
    # Backend Sharing (main ↔ live mode)
    # =========================================================================

    def detach_transcription_backend(self) -> Any:
        """Detach the backend from the main transcription engine without unloading it.

        The backend stays in GPU memory so the live engine can reuse it.
        The main engine's ``_backend`` is set to ``None`` so it cannot
        transcribe while the backend is borrowed.

        Returns:
            The backend object, or ``None`` if no backend is loaded.
        """
        engine = self._transcription_engine
        if engine is None or engine._backend is None:
            return None

        backend = engine._backend
        engine._backend = None
        engine._model_loaded = False
        logger.info("Detached transcription backend for sharing (model stays in GPU memory)")
        return backend

    def attach_transcription_backend(self, backend: Any) -> None:
        """Re-attach a previously detached backend to the main transcription engine.

        Args:
            backend: The backend object returned by :meth:`detach_transcription_backend`.
        """
        engine = self._transcription_engine
        if engine is None:
            logger.warning("Cannot attach backend: transcription engine does not exist")
            return

        engine._backend = backend
        engine._model_loaded = True
        logger.info("Re-attached transcription backend to main engine")

    def get_transcription_load_params(self) -> dict[str, Any]:
        """Return the model-level parameters the main engine was loaded with.

        These are the parameters baked into the backend at ``load()`` time.
        A live engine can only reuse the backend if its own load params match.
        """
        engine = self._transcription_engine
        if engine is None:
            return {}
        return {
            "device": engine.device,
            "compute_type": engine.compute_type,
            "gpu_device_index": engine.gpu_device_index,
            "batch_size": engine.batch_size,
        }

    # =========================================================================
    # Real-time Transcription Engine
    # =========================================================================

    def get_realtime_engine(
        self,
        session_id: str,
        client_type: "ClientType | None" = None,
        language: str | None = None,
        **callbacks: Callable,
    ) -> "RealtimeTranscriptionEngine":
        """
        Get or create a real-time transcription engine for a session.

        Args:
            session_id: Unique session identifier
            client_type: Type of client (standalone or web), defaults to WEB
            language: Target language code
            **callbacks: Optional callback functions

        Returns:
            RealtimeTranscriptionEngine for the session
        """
        from server.core.realtime_engine import create_realtime_engine

        # Check if engine already exists for this session
        if session_id in self._realtime_engines:
            return self._realtime_engines[session_id]

        logger.info(f"Creating realtime engine for session {session_id}")

        # Create the engine
        engine = create_realtime_engine(
            config=self.config,
            **callbacks,
        )

        # Initialize with language
        engine.initialize(language)

        # Store for cleanup
        self._realtime_engines[session_id] = engine

        return engine

    def release_realtime_engine(self, session_id: str) -> None:
        """
        Release a real-time transcription engine.

        Args:
            session_id: Session identifier to release
        """
        if session_id in self._realtime_engines:
            engine = self._realtime_engines.pop(session_id)
            try:
                engine.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down realtime engine: {e}")
            logger.info(f"Released realtime engine for session {session_id}")

    def release_all_realtime_engines(self) -> None:
        """Release all real-time transcription engines."""
        session_ids = list(self._realtime_engines.keys())
        for session_id in session_ids:
            self.release_realtime_engine(session_id)

    # =========================================================================
    # General Management
    # =========================================================================

    def unload_all(self) -> None:
        """Unload all models and free GPU memory."""
        from server.core.audio_utils import clear_gpu_cache

        logger.info("Unloading all models...")
        self.unload_transcription_model()
        self.unload_diarization_model()
        self.release_all_realtime_engines()
        clear_gpu_cache()
        logger.info("All models unloaded")

    def get_status(self) -> dict[str, Any]:
        """Get status information about loaded models."""
        from server.core.audio_utils import get_gpu_memory_info

        status = {
            "gpu_available": self.gpu_available,
            "gpu_memory": get_gpu_memory_info() if self.gpu_available else None,
            "transcription": {
                "selected_model": self.main_model_name,
                "disabled": self.is_main_model_disabled(),
                "loaded": self._transcription_engine is not None
                and self._transcription_engine.is_loaded(),
                "config": self._transcription_engine.get_status()
                if self._transcription_engine
                else None,
            },
            "diarization": {
                "loaded": self._diarization_engine is not None,
            },
            "realtime": {
                "active_sessions": len(self._realtime_engines),
                "session_ids": list(self._realtime_engines.keys()),
            },
            "job_tracker": self.job_tracker.get_status(),
            "features": {
                "diarization": self.get_diarization_feature_status(),
                "whisper": self.get_whisper_feature_status(),
                "nemo": {
                    "available": self._nemo_feature_available,
                    "reason": self._nemo_feature_reason,
                },
                "vibevoice_asr": self.get_vibevoice_asr_feature_status(),
                "mlx": self._get_mlx_feature_status(),
            },
        }
        return status

    def reload_config(self, new_config: dict[str, Any]) -> None:
        """
        Reload with new configuration.

        Unloads current models if configuration has changed.
        """
        old_trans_config = self.config.get("transcription", {})
        new_trans_config = new_config.get("transcription", {})

        # Check if transcription config changed
        if old_trans_config.get("model") != new_trans_config.get("model"):
            logger.info("Transcription model changed, reloading...")
            self.unload_transcription_model()
            self._transcription_engine = None

        self.config = new_config


# Global model manager instance
_manager: ModelManager | None = None


def get_model_manager(config: dict[str, Any] | None = None) -> ModelManager:
    """Get or create the global model manager instance."""
    global _manager
    if _manager is None:
        if config is None:
            raise RuntimeError("Model manager not initialized and no config provided")
        _manager = ModelManager(config)
    return _manager


def cleanup_models() -> None:
    """Clean up all loaded models."""
    global _manager
    if _manager is not None:
        _manager.unload_all()
        _manager = None
