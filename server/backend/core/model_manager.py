"""
Model lifecycle management for TranscriptionSuite server.

Handles:
- Model loading and caching
- GPU memory management
- Model switching between modes
- Real-time and preview transcription engines
- Client-aware model loading (preview for standalone clients)
- Graceful cleanup

NOTE: All heavy imports (torch, faster_whisper, pyannote, etc.) are done lazily
inside methods to avoid loading them at module import time.
"""

import logging
import threading
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

# Type-only imports for hints (no runtime cost)
if TYPE_CHECKING:
    from server.core.stt.engine import AudioToTextRecorder
    from server.core.diarization_engine import DiarizationEngine
    from server.core.realtime_engine import RealtimeTranscriptionEngine
    from server.core.preview_engine import PreviewTranscriptionEngine
    from server.core.client_detector import ClientType

logger = logging.getLogger(__name__)


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
        self._active_job_id: Optional[str] = None
        self._active_user: Optional[str] = None
        self._cancelled: bool = False
        self._lock = threading.Lock()

    def try_start_job(self, user: str) -> Tuple[bool, Optional[str], Optional[str]]:
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
            logger.info(f"Started transcription job {job_id[:8]} for user '{user}'")
            return (True, job_id, None)

    def end_job(self, job_id: str) -> bool:
        """
        Mark a transcription job as complete.

        Args:
            job_id: The job ID returned from try_start_job

        Returns:
            True if the job was ended, False if job_id didn't match
        """
        with self._lock:
            if self._active_job_id == job_id:
                logger.info(f"Ended transcription job {job_id[:8]} for user '{self._active_user}'")
                self._active_job_id = None
                self._active_user = None
                self._cancelled = False
                return True
            return False

    def cancel_job(self) -> Tuple[bool, Optional[str]]:
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
                logger.info(f"Cancellation requested for job {self._active_job_id[:8]} (user: {user})")
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

    def is_busy(self) -> Tuple[bool, Optional[str]]:
        """
        Check if a transcription job is currently running.

        Returns:
            Tuple of (is_busy, active_user_if_busy)
        """
        with self._lock:
            if self._active_job_id is not None:
                return (True, self._active_user)
            return (False, None)

    def get_status(self) -> Dict[str, Any]:
        """Get the current job tracker status."""
        with self._lock:
            return {
                "is_busy": self._active_job_id is not None,
                "active_user": self._active_user,
                "active_job_id": self._active_job_id[:8] if self._active_job_id else None,
                "cancellation_requested": self._cancelled,
            }


class ModelManager:
    """
    Manages AI model lifecycle for the transcription server.

    Keeps one model loaded at a time to manage GPU memory efficiently.
    Handles model caching and switching between different configurations.

    Supports:
    - File-based and streaming transcription (AudioToTextRecorder - unified engine)
    - Real-time transcription with VAD (RealtimeTranscriptionEngine)
    - Preview transcription for standalone clients (PreviewTranscriptionEngine)
    - Speaker diarization (DiarizationEngine)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the model manager.

        Args:
            config: Full application configuration dict
        """
        # Lazy imports
        from server.core.audio_utils import check_cuda_available, get_gpu_memory_info
        from server.core.preview_engine import PreviewConfig

        self.config = config
        self._transcription_engine: Optional["AudioToTextRecorder"] = None
        self._diarization_engine: Optional[Any] = None  # Will be DiarizationEngine
        self._preview_engine: Optional["PreviewTranscriptionEngine"] = None
        self._realtime_engines: Dict[str, "RealtimeTranscriptionEngine"] = {}

        # Track connected standalone clients
        self._standalone_client_count = 0

        # Job tracker for ensuring only one transcription runs at a time
        self.job_tracker = TranscriptionJobTracker()

        # Check GPU availability
        self.gpu_available = check_cuda_available()
        if self.gpu_available:
            gpu_info = get_gpu_memory_info()
            logger.info(f"GPU available with {gpu_info.get('total_gb', 'unknown')} GB memory")
        else:
            logger.warning("No GPU available, using CPU for transcription")

        # Check if preview is enabled in config
        self._preview_config = PreviewConfig.from_dict(config)
        if self._preview_config.enabled:
            logger.info(f"Preview transcriber configured with model: {self._preview_config.model}")

    @property
    def transcription_engine(self) -> "AudioToTextRecorder":
        """Get or create the unified transcription engine."""
        if self._transcription_engine is None:
            self._transcription_engine = self._create_transcription_engine()
        return self._transcription_engine

    def _create_transcription_engine(self) -> "AudioToTextRecorder":
        """Create the unified transcription engine from config."""
        from server.core.stt.engine import AudioToTextRecorder

        main_cfg = self.config.get("main_transcriber", {})
        trans_opts = self.config.get("transcription_options", {})

        return AudioToTextRecorder(
            instance_name="file_transcriber",
            model=main_cfg.get("model", "Systran/faster-whisper-large-v3"),
            device=main_cfg.get("device", "cuda"),
            compute_type=main_cfg.get("compute_type", "default"),
            beam_size=main_cfg.get("beam_size", 5),
            batch_size=main_cfg.get("batch_size", 16),
            language=trans_opts.get("language", ""),
            faster_whisper_vad_filter=main_cfg.get("faster_whisper_vad_filter", True),
            initial_prompt=main_cfg.get("initial_prompt"),
        )

    def load_transcription_model(self) -> None:
        """Explicitly load the transcription model."""
        engine = self.transcription_engine
        if not engine.is_loaded():
            logger.info("Loading transcription model...")
            engine.load_model()
            logger.info("Transcription model ready")

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
            engine.load()
            logger.info("Diarization model ready")

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
    # Real-time Transcription Engine
    # =========================================================================

    def get_realtime_engine(
        self,
        session_id: str,
        client_type: "ClientType | None" = None,
        language: Optional[str] = None,
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
        from server.core.client_detector import ClientType
        from server.core.realtime_engine import create_realtime_engine

        # Default to WEB client type
        if client_type is None:
            client_type = ClientType.WEB

        # Check if engine already exists for this session
        if session_id in self._realtime_engines:
            return self._realtime_engines[session_id]

        # Determine if preview should be enabled
        enable_preview = client_type == ClientType.STANDALONE and self._preview_config.enabled

        if enable_preview:
            logger.info(f"Creating realtime engine with preview for session {session_id}")
        else:
            logger.info(f"Creating realtime engine for session {session_id}")

        # Create the engine
        engine = create_realtime_engine(
            config=self.config,
            enable_preview=enable_preview,
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
    # Preview Engine
    # =========================================================================

    @property
    def preview_engine(self) -> Optional["PreviewTranscriptionEngine"]:
        """Get the preview engine if available."""
        return self._preview_engine

    def load_preview_engine(self, language: Optional[str] = None) -> bool:
        """
        Load the preview transcription engine.

        Only loads if preview is enabled in config.

        Args:
            language: Target language code

        Returns:
            True if loaded successfully
        """
        from server.core.preview_engine import PreviewTranscriptionEngine

        if not self._preview_config.enabled:
            logger.debug("Preview engine disabled in config")
            return False

        if self._preview_engine is None:
            self._preview_engine = PreviewTranscriptionEngine(self.config)

        return self._preview_engine.load(language)

    def unload_preview_engine(self) -> None:
        """Unload the preview engine to free memory."""
        if self._preview_engine is not None:
            self._preview_engine.unload()
            self._preview_engine = None
            logger.info("Preview engine unloaded")

    # =========================================================================
    # Client Connection Management
    # =========================================================================

    def on_standalone_client_connected(self) -> None:
        """
        Called when a standalone client connects.

        Loads preview transcriber if enabled and this is the first
        standalone client.
        """
        self._standalone_client_count += 1

        if self._standalone_client_count == 1 and self._preview_config.enabled:
            logger.info("First standalone client connected - loading preview engine")
            self.load_preview_engine()

    def on_standalone_client_disconnected(self) -> None:
        """
        Called when a standalone client disconnects.

        Unloads preview transcriber if no standalone clients remain.
        """
        self._standalone_client_count = max(0, self._standalone_client_count - 1)

        if self._standalone_client_count == 0 and self._preview_engine is not None:
            logger.info("No standalone clients remaining - unloading preview engine")
            self.unload_preview_engine()

    @property
    def has_standalone_clients(self) -> bool:
        """Check if any standalone clients are connected."""
        return self._standalone_client_count > 0

    # =========================================================================
    # General Management
    # =========================================================================

    def unload_all(self) -> None:
        """Unload all models and free GPU memory."""
        from server.core.audio_utils import clear_gpu_cache

        logger.info("Unloading all models...")
        self.unload_transcription_model()
        self.unload_diarization_model()
        self.unload_preview_engine()
        self.release_all_realtime_engines()
        clear_gpu_cache()
        logger.info("All models unloaded")

    def get_status(self) -> Dict[str, Any]:
        """Get status information about loaded models."""
        from server.core.audio_utils import get_gpu_memory_info

        status = {
            "gpu_available": self.gpu_available,
            "gpu_memory": get_gpu_memory_info() if self.gpu_available else None,
            "transcription": {
                "loaded": self._transcription_engine is not None
                and self._transcription_engine.is_loaded(),
                "config": self._transcription_engine.get_status()
                if self._transcription_engine
                else None,
            },
            "diarization": {
                "loaded": self._diarization_engine is not None,
            },
            "preview": {
                "enabled": self._preview_config.enabled,
                "loaded": self._preview_engine is not None and self._preview_engine.is_loaded,
                "model": self._preview_config.model if self._preview_config.enabled else None,
            },
            "realtime": {
                "active_sessions": len(self._realtime_engines),
                "session_ids": list(self._realtime_engines.keys()),
            },
            "standalone_clients": self._standalone_client_count,
            "job_tracker": self.job_tracker.get_status(),
        }
        return status

    def reload_config(self, new_config: Dict[str, Any]) -> None:
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
_manager: Optional[ModelManager] = None


def get_model_manager(config: Optional[Dict[str, Any]] = None) -> ModelManager:
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
