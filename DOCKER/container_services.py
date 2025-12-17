"""
Manages Audio Notebook and Remote Server within the container.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ServiceManager:
    """Manages multiple services in the container."""

    def __init__(self):
        self.audio_notebook_server: Optional[uvicorn.Server] = None
        self.remote_server_task: Optional[asyncio.Task] = None
        self.shutdown_event = asyncio.Event()

    async def run(self):
        """Run all services concurrently."""
        await asyncio.gather(
            self._run_audio_notebook(),
            self._run_remote_server(),
            self._wait_for_shutdown(),
        )

    async def _run_audio_notebook(self):
        """Run the Audio Notebook FastAPI server."""
        # Import client endpoints for native client communication
        from AUDIO_NOTEBOOK.backend.routers import llm, recordings, search, transcribe
        from MAIN.api.client_endpoints import router as client_router

        app = FastAPI(title="Audio Notebook", version="1.0.0")

        # Include routers
        app.include_router(recordings.router, prefix="/api")
        app.include_router(search.router, prefix="/api")
        app.include_router(transcribe.router, prefix="/api")
        app.include_router(llm.router, prefix="/api")
        app.include_router(client_router)  # Client API at /api/client

        # Health check endpoint
        @app.get("/health")
        async def health():
            import torch

            return {
                "status": "healthy",
                "service": "audio-notebook",
                "gpu_available": torch.cuda.is_available(),
            }

        # Serve frontend static files
        frontend_path = Path("AUDIO_NOTEBOOK/dist")
        if frontend_path.exists():
            # Serve assets directory
            assets_path = frontend_path / "assets"
            if assets_path.exists():
                app.mount(
                    "/assets", StaticFiles(directory=str(assets_path)), name="assets"
                )

            # Catch-all route for SPA
            @app.get("/{path:path}")
            async def serve_frontend(path: str):
                file_path = frontend_path / path
                if file_path.is_file():
                    return FileResponse(file_path)
                # Return index.html for SPA routing
                return FileResponse(frontend_path / "index.html")
        else:
            logger.warning(f"Frontend not found at {frontend_path}")

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=True,
        )
        self.audio_notebook_server = uvicorn.Server(config)

        logger.info("Starting Audio Notebook server on port 8000")
        await self.audio_notebook_server.serve()

    async def _run_remote_server(self):
        """Run the Remote Transcription Server."""
        try:
            from pathlib import Path

            from MAIN.config_manager import ConfigManager
            from REMOTE_SERVER.transcription_engine import (
                create_file_transcription_callback,
                create_transcription_callbacks,
            )
            from REMOTE_SERVER.web_server import WebTranscriptionServer

            # Load config from file
            config_path = Path(__file__).parent.parent / "config.yaml"
            config_manager = ConfigManager(str(config_path))
            config = config_manager.load_or_create_config()

            # Create transcription callbacks
            # Returns: (transcribe_callback, realtime_callback, engine)
            transcribe_cb, realtime_cb, engine = create_transcription_callbacks(config)
            file_cb = create_file_transcription_callback(config, engine)

            server = WebTranscriptionServer(
                config=config,
                transcribe_callback=transcribe_cb,
                transcribe_file_callback=file_cb,
                realtime_callback=realtime_cb,
            )

            logger.info("Starting Remote Server on port 8443")
            # Call the internal async method directly since we're already in an event loop
            await server._run_servers()

        except Exception as e:
            logger.error(f"Failed to start Remote Server: {e}")
            raise

    async def _wait_for_shutdown(self):
        """Wait for shutdown signal."""
        await self.shutdown_event.wait()

    async def shutdown(self):
        """Graceful shutdown of all services."""
        logger.info("Initiating graceful shutdown...")
        self.shutdown_event.set()

        if self.audio_notebook_server:
            self.audio_notebook_server.should_exit = True

        # Give services time to cleanup
        await asyncio.sleep(1)
        logger.info("Shutdown complete")
