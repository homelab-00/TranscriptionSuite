# Timing instrumentation - must be at very top before any imports
import time as _time

_start_time = _time.perf_counter()


def _log_time(msg: str) -> None:
    print(f"[TIMING] {_time.perf_counter() - _start_time:.3f}s - {msg}", flush=True)


_log_time("main.py module load started")

"""
Unified FastAPI application for TranscriptionSuite server.

Provides a single API serving:
- Transcription endpoints (/api/transcribe/*)
- Audio Notebook endpoints (/api/notebook/*)
- Search endpoints (/api/search/*)
- Admin endpoints (/api/admin/*)
- Health and status endpoints
"""

# Imports are placed after timing instrumentation intentionally
import asyncio  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

_log_time("stdlib imports done")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

_log_time("fastapi imports done")

import server.core.token_store as _ts_mod  # noqa: E402

_log_time("token_store imported")

from server.api.routes import (  # noqa: E402
    admin,
    auth,
    health,
    live,
    llm,
    notebook,
    openai_audio,
    search,
    transcription,
    websocket,
)

_log_time("routes imported")

from server.config import get_config, resolve_main_transcriber_model  # noqa: E402

_log_time("config imported")

# NOTE: model_manager is imported lazily inside lifespan() to avoid
# loading heavy ML libraries (torch, faster_whisper) at module import time.
_log_time("model_manager import SKIPPED (lazy import in lifespan)")

from server.database.database import init_db  # noqa: E402

_log_time("database imported")

from server.logging import get_logger, setup_logging  # noqa: E402

_log_time("logging imported")

from server.core.startup_events import emit_event  # noqa: E402

_log_time("startup_events imported")

from server import __version__  # noqa: E402

logger = get_logger("api")


# Adapted from Scriberr (https://github.com/rishikanthc/Scriberr) — startup recovery pattern
async def recover_orphaned_jobs(timeout_minutes: int) -> None:
    """Mark orphaned 'processing' jobs as failed on server startup.

    Finds jobs that were still processing when the server last stopped (crash or
    docker stop) and marks them failed with an actionable message. Logs each
    recovery action. Wraps the entire body in try/except so startup always continues.
    """
    if timeout_minutes <= 0:
        return
    try:
        from server.database.job_repository import get_orphaned_jobs
        from server.database.job_repository import mark_failed as _mark_failed_repo

        orphaned = await asyncio.to_thread(get_orphaned_jobs, timeout_minutes)
        for job in orphaned:
            job_id = job.get("id", "")
            audio_path = job.get("audio_path")
            if audio_path and Path(audio_path).exists():
                reason = "Server restarted — use retry to re-transcribe"
            else:
                reason = "Server restarted — audio not preserved"
            await asyncio.to_thread(_mark_failed_repo, job_id, reason)
            logger.info("Recovered orphaned job %s (%s)", job_id, reason)
    except Exception:
        logger.error("Orphan job recovery failed — continuing startup", exc_info=True)


async def periodic_orphan_sweep(
    timeout_minutes: int,
    interval_minutes: int,
    job_tracker: object | None = None,
) -> None:
    """Periodically sweep for orphaned 'processing' jobs and mark them failed.

    Unlike ``recover_orphaned_jobs`` (which runs once at startup), this runs on
    a repeating schedule so that orphans are caught even when the server runs
    continuously without restarts.

    When *job_tracker* is provided, the sweep is skipped if a job is currently
    active — this prevents falsely reaping a legitimate long-running recording
    session.

    Does NOT run immediately — startup already calls ``recover_orphaned_jobs``.
    If *interval_minutes* <= 0, logs that the sweep is disabled and returns.

    Follows the same cancel-safe pattern as
    :func:`server.database.audio_cleanup.periodic_cleanup`.
    """
    if interval_minutes <= 0:
        logger.info("Periodic orphan sweep disabled (interval_minutes=%d)", interval_minutes)
        return

    interval_seconds = interval_minutes * 60
    logger.info(
        "Periodic orphan sweep armed (every %dm, timeout=%dm)", interval_minutes, timeout_minutes
    )

    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Periodic orphan sweep cancelled (shutdown)")
            return
        try:
            # Skip sweep if a job is actively running — prevents falsely reaping
            # a legitimate long-running recording session (item 39).
            if job_tracker is not None:
                is_busy, _ = job_tracker.is_busy()
                if is_busy:
                    logger.debug("Orphan sweep skipped — a job is currently active")
                    continue

            from server.database.job_repository import get_orphaned_jobs
            from server.database.job_repository import mark_failed as _mark_failed_repo

            orphaned = await asyncio.to_thread(get_orphaned_jobs, timeout_minutes)
            for job in orphaned:
                job_id = job.get("id", "")
                audio_path = job.get("audio_path")
                if audio_path and Path(audio_path).exists():
                    reason = "Orphan sweep — use retry to re-transcribe"
                else:
                    reason = "Orphan sweep — audio not preserved"
                await asyncio.to_thread(_mark_failed_repo, job_id, reason)
                logger.info("Orphan sweep: marked job %s failed (%s)", job_id, reason)
        except Exception:
            logger.exception("Periodic orphan sweep failed — will retry next interval")


# Check if TLS mode is enabled (requires authentication for all routes)
TLS_MODE = os.environ.get("TLS_ENABLED", "false").lower() == "true"

# Routes that don't require authentication
PUBLIC_ROUTES = {
    "/health",
    "/api/status",
    "/api/auth/login",
    "/auth",
    "/auth/",
    "/favicon.ico",
}

# Route prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/auth/",
    "/docs",
    "/openapi.json",
    "/redoc",
)

NOTEBOOK_QUERY_TOKEN_ROUTES = re.compile(r"^/api/notebook/recordings/\d+/(audio|export)$")

_VIBEVOICE_RECOVERABLE_PRELOAD_ERROR_TEXTS = (
    "VibeVoice-ASR backend selected but VibeVoice is not installed.",
    "VibeVoice-ASR backend selected but compatible VibeVoice-ASR modules could not be imported",
)


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    stack = [exc]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        obj_id = id(current)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        chain.append(current)
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        if cause is not None:
            stack.append(cause)
        if context is not None:
            stack.append(context)
    return chain


def _is_recoverable_vibevoice_preload_error(model_name: str, exc: BaseException) -> bool:
    """Return True only for the known optional VibeVoice missing-package preload failure."""
    try:
        from server.core.stt.backends.factory import detect_backend_type
    except Exception:
        return False

    if detect_backend_type(model_name) != "vibevoice_asr":
        return False

    for current in _iter_exception_chain(exc):
        if isinstance(current, ImportError) and any(
            text in str(current) for text in _VIBEVOICE_RECOVERABLE_PRELOAD_ERROR_TEXTS
        ):
            return True
    return False


def _build_vibevoice_preload_skip_warning(
    model_name: str,
    feature_status: dict[str, object] | None,
) -> tuple[str, str]:
    """Return (message, timing_label) for recoverable VibeVoice preload failures."""
    feature_status = feature_status or {}
    reason = str(feature_status.get("reason", "unknown") or "unknown")
    error = str(feature_status.get("error", "") or "").strip()

    if reason == "import_failed":
        return (
            (
                "Transcription preload skipped for optional VibeVoice-ASR backend "
                f"(model={model_name}). INSTALL_VIBEVOICE_ASR was enabled, but the bootstrap "
                f"VibeVoice import probe failed (reason={reason}, error={error or 'n/a'}). "
                "Continuing startup without a loaded transcription model. The installed "
                "VibeVoice package may be incompatible with this integration; set "
                "VIBEVOICE_ASR_PACKAGE_SPEC to a known-good revision/commit if needed."
            ),
            "model preload skipped (VibeVoice-ASR import probe failed)",
        )

    if reason.startswith("install_failed"):
        return (
            (
                "Transcription preload skipped for optional VibeVoice-ASR backend "
                f"(model={model_name}). VibeVoice optional dependency installation failed during "
                f"bootstrap (reason={reason}, error={error or 'n/a'}). Continuing startup "
                "without a loaded transcription model."
            ),
            "model preload skipped (VibeVoice-ASR optional dependency install failed)",
        )

    return (
        (
            "Transcription preload skipped for optional VibeVoice-ASR backend "
            f"(model={model_name}). Enable INSTALL_VIBEVOICE_ASR=true and restart to load "
            "the model. Continuing startup without a loaded transcription model."
        ),
        "model preload skipped (VibeVoice-ASR optional dependency missing)",
    )


class OriginValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate CORS origins based on deployment mode.

    In TLS mode: Allow same-origin, Electron app (null / file:// origin),
                 and localhost origins (dev mode).
    In local mode: Only allow localhost origins and Electron app origins.

    Electron's Chromium renderer sends ``Origin: null`` for fetch() from
    file:// pages (production builds) and ``Origin: http://localhost:3000``
    in dev mode.  Both must be accepted for the desktop client to reach a
    remote server.  Auth tokens (checked by AuthenticationMiddleware)
    protect sensitive endpoints; the origin check guards against CSRF from
    arbitrary web pages, which does not apply to native Electron apps.
    """

    # Localhost addresses accepted in both local and TLS modes so the
    # Electron dev server (http://localhost:3000) works against a remote
    # server running on the same machine.
    _LOCALHOST = {"localhost", "127.0.0.1", "::1", "[::1]"}

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")

        # If no origin header, allow (same-origin requests don't send Origin)
        if not origin:
            return await call_next(request)

        # Electron production builds send the literal string "null" as the
        # origin (opaque origin from file:// pages).  Always allow it — the
        # request is coming from our own native app, not a web page.
        if origin == "null":
            return await call_next(request)

        # Parse the origin
        from urllib.parse import urlparse

        parsed_origin = urlparse(origin)
        origin_host = parsed_origin.netloc.split(":")[0]

        # Empty netloc means an opaque/unrecognised origin (e.g. file://).
        # Allow it — same rationale as the "null" check above.
        if not origin_host:
            return await call_next(request)

        # Localhost origins are always safe (Electron dev, local testing)
        if origin_host in self._LOCALHOST:
            return await call_next(request)

        if TLS_MODE:
            # In TLS mode, additionally allow same-origin requests
            request_host = request.headers.get("host", "").split(":")[0]

            if origin_host != request_host:
                logger.warning(
                    f"CORS: Blocked cross-origin request from {origin} to {request_host}"
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin requests not allowed"},
                )
        else:
            # In local mode, only localhost origins are allowed (already
            # handled above) — block everything else.
            logger.warning(f"CORS: Blocked non-localhost origin {origin}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Only localhost origins allowed"},
            )

        return await call_next(request)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce authentication for all routes in TLS mode.

    In TLS mode, all requests must include a valid Bearer token,
    except for public routes like /health, /auth, and /api/auth/login.
    Unauthenticated browser requests are redirected to /auth.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public routes without authentication
        if path in PUBLIC_ROUTES or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Check for valid authentication
        auth_header = request.headers.get("Authorization")

        # Check cookie-based auth for browser requests
        auth_cookie = request.cookies.get("auth_token")

        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif auth_cookie:
            token = auth_cookie
        elif NOTEBOOK_QUERY_TOKEN_ROUTES.match(path):
            query_token = request.query_params.get("token", "").strip()
            if query_token:
                token = query_token

        if token:
            token_store = _ts_mod.get_token_store()
            if token_store.validate_token(token):
                return await call_next(request)

        # For API requests, return 401
        if path.startswith("/api/") or path.startswith("/v1/") or path == "/ws":
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        # For browser requests to web pages, redirect to /auth
        # Preserve the original destination for redirect after auth
        original_url = str(request.url.path)
        if request.url.query:
            original_url += f"?{request.url.query}"

        return RedirectResponse(
            url=f"/auth?redirect={original_url}",
            status_code=302,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan handler for startup/shutdown."""
    # Lazy import to avoid loading torch/faster_whisper at module load time
    from server.core.model_manager import cleanup_models, get_model_manager

    # Startup
    lifespan_start = _time.perf_counter()
    _log_time("lifespan() started")
    logger.info("TranscriptionSuite server starting...")
    emit_event("lifespan-start", "server", "Starting server...", phase="lifespan")

    _cleanup_task = None
    _orphan_sweep_task = None

    config = get_config()
    _log_time("config loaded")

    # Initialize logging
    setup_logging(config.logging)
    _log_time("logging setup complete")

    # Initialize database
    init_db()
    _log_time("database init_db() complete")
    logger.info("Database initialized")

    # Read durability config early so orphan recovery can use it
    _durability_config_early = config.config.get("durability", {})
    _orphan_timeout = _durability_config_early.get("orphan_job_timeout_minutes", 10)

    # Recover orphaned jobs from a previous crash/restart (Wave 3)
    await recover_orphaned_jobs(_orphan_timeout)
    _log_time("orphan job recovery complete")

    # Schedule backup check in background (non-blocking)
    backup_config = config.config.get("backup", {})
    backup_enabled = backup_config.get("enabled", True)

    if backup_enabled:
        from server.database.backup import run_backup_if_needed
        from server.database.database import get_data_dir, get_db_path

        backup_dir = get_data_dir() / "database" / "backups"
        max_age_hours = backup_config.get("max_age_hours", 1)
        max_backups = backup_config.get("max_backups", 3)

        # Run backup check as background task (does not block startup)
        asyncio.create_task(
            run_backup_if_needed(
                db_path=get_db_path(),
                backup_dir=backup_dir,
                max_age_hours=max_age_hours,
                max_backups=max_backups,
            )
        )
        _log_time("backup check scheduled (async)")
        logger.info(f"Backup check scheduled (max_age={max_age_hours}h, max_backups={max_backups})")

    # Schedule periodic audio cleanup in background (non-blocking, Wave 2)
    durability_config = config.config.get("durability", {})
    _cleanup_enabled = durability_config.get("cleanup_enabled", True)

    if _cleanup_enabled:
        _recordings_dir = (
            durability_config.get("recordings_dir", "/data/recordings") or "/data/recordings"
        )
        _max_age_days = durability_config.get("audio_retention_days", 7)
        _cleanup_interval_hours = durability_config.get("cleanup_interval_hours", 24)

        from server.database.audio_cleanup import periodic_cleanup

        _cleanup_task = asyncio.create_task(
            periodic_cleanup(_recordings_dir, _max_age_days, _cleanup_interval_hours)
        )
        _log_time("audio cleanup scheduled (async, periodic)")
        logger.info(
            "Audio cleanup scheduled (recordings_dir=%s, retention=%d days, interval=%dh)",
            _recordings_dir,
            _max_age_days,
            _cleanup_interval_hours,
        )
    else:
        logger.info("Audio cleanup disabled (cleanup_enabled=false)")

    # Orphan sweep scheduling deferred until after model manager creation (needs job tracker)
    _orphan_sweep_interval = durability_config.get("orphan_sweep_interval_minutes", 30)

    # Initialize token store (generates admin token on first run)
    _ts_mod.get_token_store()
    _log_time("token store initialized")
    logger.info("Token store initialized")

    # CUDA health probe — detect unrecoverable GPU state before ModelManager
    from server.core.audio_utils import cuda_health_check

    _gpu_device_index = config.get("transcription", "gpu_device_index", default=0)
    gpu_start = _time.perf_counter()
    emit_event("lifespan-gpu", "server", "Checking GPU...", phase="lifespan")
    gpu_health = cuda_health_check(device_index=_gpu_device_index)
    gpu_elapsed_ms = round((_time.perf_counter() - gpu_start) * 1000)
    _log_time(f"CUDA health check: {gpu_health['status']}")
    gpu_unrecoverable = gpu_health["status"] == "unrecoverable"
    emit_event(
        "lifespan-gpu",
        "server",
        "GPU check complete",
        status="error" if gpu_unrecoverable else "complete",
        durationMs=gpu_elapsed_ms,
        phase="lifespan",
    )
    if gpu_health["status"] == "healthy":
        device_name = gpu_health.get("device_name", "Unknown")
        vram_gb = gpu_health.get("total_memory_gb", "?")
        emit_event(
            "info-gpu",
            "info",
            f"GPU: {device_name} ({vram_gb}GB)",
            status="complete",
            durationMs=gpu_elapsed_ms,
        )
    elif gpu_unrecoverable:
        emit_event(
            "warn-gpu-fatal",
            "warning",
            "GPU in unrecoverable state \u2014 restart container",
            persistent=True,
            severity="error",
        )
    elif gpu_health["status"] in ("no_cuda", "no_torch"):
        emit_event(
            "warn-gpu",
            "warning",
            "No GPU detected \u2014 CPU mode",
            persistent=True,
        )

    if gpu_unrecoverable:
        logger.error(
            "CUDA health check failed — GPU transcription disabled for this session",
            extra={
                "error": gpu_health["error"],
                "nvidia_smi": gpu_health.get("nvidia_smi", "N/A"),
            },
        )
        app.state.gpu_error = gpu_health

    # Initialize model manager (accesses CUDA — must come after health check)
    manager = get_model_manager(config.config)
    _log_time("model manager created")
    logger.info(f"Model manager initialized (GPU: {manager.gpu_available})")

    selected_main_model = resolve_main_transcriber_model(config)
    if gpu_unrecoverable:
        logger.warning("Model preload skipped — GPU in unrecoverable state")
        _log_time("model preload skipped (GPU unrecoverable)")
    elif not selected_main_model.strip():
        logger.info("No main model selected; preload skipped (intentional disabled slot mode)")
        _log_time("model preload skipped (main model disabled)")
    else:
        logger.info("Loading transcription model from cache...")
        _log_time("starting model preload (GPU VRAM should spike now)...")
        try:
            manager.load_transcription_model()
        except Exception as e:
            if _is_recoverable_vibevoice_preload_error(selected_main_model, e):
                vibevoice_feature_status = None
                try:
                    vibevoice_feature_status = manager.get_vibevoice_asr_feature_status()
                except Exception:
                    vibevoice_feature_status = None

                warning_message, timing_label = _build_vibevoice_preload_skip_warning(
                    selected_main_model,
                    vibevoice_feature_status,
                )
                logger.warning(
                    warning_message,
                    exc_info=True,
                )
                _log_time(timing_label)
            else:
                logger.error("Model preload failed")
                raise
        else:
            _log_time("model preload complete")

    # Store config in app state
    app.state.config = config
    app.state.model_manager = manager

    # Schedule periodic orphan sweep (deferred until after model manager creation
    # so the sweep can check the in-memory job tracker before reaping)
    _orphan_sweep_task = asyncio.create_task(
        periodic_orphan_sweep(_orphan_timeout, _orphan_sweep_interval, manager.job_tracker)
    )
    _log_time("orphan sweep scheduled (async, periodic)")
    logger.info(
        "Orphan sweep scheduled (timeout=%dm, interval=%dm)",
        _orphan_timeout,
        _orphan_sweep_interval,
    )

    logger.info("Server startup complete")
    _log_time("lifespan startup complete")
    emit_event(
        "server-ready",
        "server",
        "Server ready",
        status="complete",
        phase="ready",
        durationMs=round((_time.perf_counter() - lifespan_start) * 1000),
    )

    yield

    # Shutdown
    logger.info("Server shutting down...")

    # Cancel periodic audio cleanup task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            logger.debug("Audio cleanup task cancelled")

    # Cancel periodic orphan sweep task
    if _orphan_sweep_task and not _orphan_sweep_task.done():
        _orphan_sweep_task.cancel()
        try:
            await _orphan_sweep_task
        except asyncio.CancelledError:
            logger.debug("Orphan sweep task cancelled")

    # Graceful drain: stop any active recording sessions before killing the model.
    # Wave 1 already persisted results to DB, so a timeout just means the result
    # is in DB and can be fetched later — no data loss.
    from server.api.routes.websocket import _connected_sessions, _sessions_lock

    async with _sessions_lock:
        recording_sessions = [s for s in _connected_sessions.values() if s.is_recording]
    if recording_sessions:
        logger.info("Draining %d active recording session(s)...", len(recording_sessions))
    for session in recording_sessions:
        try:
            await asyncio.wait_for(session.stop_recording(), timeout=120.0)
            logger.info("Session %s drained successfully", session.session_id)
        except TimeoutError:
            logger.warning(
                "Timed out waiting for session %s to stop recording (120s) — "
                "result should be in DB if Wave 1 persisted it",
                session.session_id,
            )

    cleanup_models()
    logger.info("Shutdown complete")


def create_app(config_path: Path | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config_path: Optional path to configuration file

    Returns:
        Configured FastAPI application
    """
    # Initialize config early if path provided
    if config_path:
        get_config(config_path)

    app = FastAPI(
        title="TranscriptionSuite",
        description="Unified transcription server with Audio Notebook",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS middleware - configured permissively but validated by OriginValidationMiddleware
    # We need allow_origins=["*"] to enable CORS headers, but our custom middleware
    # will enforce strict origin validation based on deployment mode
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add origin validation middleware to enforce strict CORS policies
    app.add_middleware(OriginValidationMiddleware)

    # Add authentication middleware in TLS mode
    if TLS_MODE:
        app.add_middleware(AuthenticationMiddleware)
        logger.info("TLS mode enabled - authentication required for all routes")

    # Include API routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(transcription.router, prefix="/api/transcribe", tags=["Transcription"])
    app.include_router(notebook.router, prefix="/api/notebook", tags=["Audio Notebook"])
    app.include_router(search.router, prefix="/api/search", tags=["Search"])
    app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
    app.include_router(openai_audio.router, prefix="/v1/audio", tags=["OpenAI Compatible"])
    app.include_router(websocket.router, tags=["WebSocket"])
    app.include_router(live.router, tags=["Live Mode"])

    # Exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


# Create default app instance
_log_time("creating FastAPI app...")
app = create_app()
_log_time("FastAPI app created (lifespan will run when uvicorn starts)")

# Auth page HTML template
AUTH_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TranscriptionSuite - Authentication</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }
        .container {
            width: 100%;
            max-width: 400px;
        }
        .card {
            background: #1e293b;
            border-radius: 1rem;
            padding: 2rem;
            border: 1px solid #334155;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .icon {
            width: 4rem;
            height: 4rem;
            background: #6366f1;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1rem;
        }
        .icon svg {
            width: 2rem;
            height: 2rem;
            color: white;
        }
        h1 {
            color: white;
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
        }
        .subtitle {
            color: #94a3b8;
            font-size: 0.875rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            color: #cbd5e1;
            font-size: 0.875rem;
            margin-bottom: 0.5rem;
        }
        input[type="password"] {
            width: 100%;
            padding: 0.75rem 1rem;
            background: #334155;
            border: 1px solid #475569;
            border-radius: 0.5rem;
            color: white;
            font-size: 1rem;
            transition: border-color 0.2s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #6366f1;
        }
        input[type="password"]::placeholder {
            color: #64748b;
        }
        .error {
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid #ef4444;
            border-radius: 0.5rem;
            padding: 0.75rem;
            margin-bottom: 1rem;
            color: #fca5a5;
            font-size: 0.875rem;
            display: none;
        }
        .error.show {
            display: block;
        }
        button {
            width: 100%;
            padding: 0.75rem 1rem;
            background: #6366f1;
            border: none;
            border-radius: 0.5rem;
            color: white;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover {
            background: #4f46e5;
        }
        button:disabled {
            background: #475569;
            cursor: not-allowed;
        }
        .footer {
            text-align: center;
            margin-top: 1.5rem;
            color: #64748b;
            font-size: 0.75rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="icon">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                </div>
                <h1>TranscriptionSuite</h1>
                <p class="subtitle">Enter your authentication token to continue</p>
            </div>
            <form id="authForm">
                <div id="error" class="error"></div>
                <div class="form-group">
                    <label for="token">Authentication Token</label>
                    <input type="password" id="token" name="token" placeholder="Enter your token..." required autofocus>
                </div>
                <button type="submit" id="submitBtn">Authenticate</button>
            </form>
        </div>
        <p class="footer">Contact your administrator if you don't have a token</p>
    </div>
    <script>
        const form = document.getElementById('authForm');
        const tokenInput = document.getElementById('token');
        const errorDiv = document.getElementById('error');
        const submitBtn = document.getElementById('submitBtn');

        // Get redirect URL from query params
        const urlParams = new URLSearchParams(window.location.search);
        const redirectUrl = urlParams.get('redirect') || '/notebook/calendar';

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const token = tokenInput.value.trim();
            if (!token) return;

            submitBtn.disabled = true;
            submitBtn.textContent = 'Authenticating...';
            errorDiv.classList.remove('show');

            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token })
                });

                const data = await response.json();

                if (data.success) {
                    // Set auth cookie
                    document.cookie = `auth_token=${token}; path=/; max-age=${30*24*60*60}; SameSite=Strict; Secure`;
                    // Redirect to original destination
                    window.location.href = redirectUrl;
                } else {
                    errorDiv.textContent = data.message || 'Invalid token';
                    errorDiv.classList.add('show');
                }
            } catch (err) {
                errorDiv.textContent = 'Authentication failed. Please try again.';
                errorDiv.classList.add('show');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Authenticate';
            }
        });
    </script>
</body>
</html>
"""


# Auth page route (served for all modes, but only required in TLS mode)
@app.get("/auth", include_in_schema=False)
@app.get("/auth/{path:path}", include_in_schema=False)
async def serve_auth_page(path: str = "") -> HTMLResponse:
    """Serve the authentication page."""
    return HTMLResponse(content=AUTH_PAGE_HTML)


# Root redirect - send to API docs
@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    """Redirect root to API documentation."""
    return RedirectResponse(url="/docs", status_code=302)


_log_time("main.py module load complete")
