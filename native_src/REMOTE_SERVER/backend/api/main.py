"""
Unified FastAPI application for TranscriptionSuite server.

Provides a single API serving:
- Transcription endpoints (/api/transcribe/*)
- Audio Notebook endpoints (/api/notebook/*)
- Search endpoints (/api/search/*)
- Admin endpoints (/api/admin/*)
- Health and status endpoints
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.api.routes import admin, health, notebook, search, transcription
from server.config import get_config
from server.core.model_manager import cleanup_models, get_model_manager
from server.database.database import init_db
from server.logging import get_logger, setup_logging

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("TranscriptionSuite server starting...")

    config = get_config()

    # Initialize logging
    setup_logging(config.logging)

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Initialize model manager
    manager = get_model_manager(config.config)
    logger.info(f"Model manager initialized (GPU: {manager.gpu_available})")

    # Preload transcription model at startup
    logger.info("Preloading transcription model...")
    manager.load_transcription_model()

    # Store config in app state
    app.state.config = config
    app.state.model_manager = manager

    logger.info("Server startup complete")

    yield

    # Shutdown
    logger.info("Server shutting down...")
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
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(
        transcription.router, prefix="/api/transcribe", tags=["Transcription"]
    )
    app.include_router(notebook.router, prefix="/api/notebook", tags=["Audio Notebook"])
    app.include_router(search.router, prefix="/api/search", tags=["Search"])
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])

    # Exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


def mount_frontend(app: FastAPI, frontend_path: Path, mount_path: str = "/") -> None:
    """
    Mount a frontend SPA to the application.

    Args:
        app: FastAPI application
        frontend_path: Path to the built frontend (dist directory)
        mount_path: URL path to mount at
    """
    if not frontend_path.exists():
        logger.warning(f"Frontend path not found: {frontend_path}")
        return

    # Mount assets directory
    assets_path = frontend_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    # Catch-all route for SPA
    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str) -> FileResponse:
        file_path = frontend_path / path
        if file_path.is_file():
            return FileResponse(file_path)
        # Return index.html for SPA routing
        return FileResponse(frontend_path / "index.html")

    logger.info(f"Frontend mounted from {frontend_path}")


# Create default app instance
app = create_app()

# Mount frontend in Docker environment
# Frontend is built and copied to /app/static/ during Docker build
_static_dir = Path("/app/static")
if _static_dir.exists():
    _audio_notebook_dir = _static_dir / "audio_notebook"
    if _audio_notebook_dir.exists():
        mount_frontend(app, _audio_notebook_dir, "/")
        logger.info(f"Audio Notebook frontend mounted from {_audio_notebook_dir}")
