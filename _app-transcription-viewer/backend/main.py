"""
Transcription Viewer Backend API
FastAPI server providing endpoints for managing and searching transcriptions
"""

import os
import sys
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers import recordings, search, transcribe

# Add parent directory to path for transcription imports
CORE_PATH = Path(__file__).parent.parent.parent / "_core" / "SCRIPT"
if CORE_PATH.exists():
    sys.path.insert(0, str(CORE_PATH))


def check_for_orchestrator_instance() -> bool:
    """
    Check if orchestrator.py is already running.

    Returns:
        True if another instance is detected, False otherwise
    """
    try:
        # Use pgrep to find python processes running orchestrator.py
        result = subprocess.run(
            ["pgrep", "-f", "orchestrator.py"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 and result.stdout.strip():
            # Found matching processes
            pids = result.stdout.strip().split("\n")
            # Filter out our own process if we happen to match
            current_pid = str(os.getpid())
            other_pids = [pid for pid in pids if pid != current_pid and pid.strip()]
            return len(other_pids) > 0

        return False
    except Exception:
        # If pgrep fails, we can't detect - assume no conflict
        return False


def print_startup_warnings():
    """Print warnings about potential conflicts at startup."""

    if check_for_orchestrator_instance():
        print("\n" + "=" * 70)
        print("⚠️  WARNING: Orchestrator Instance Detected!")
        print("=" * 70)
        print("Another instance of TranscriptionSuite (orchestrator.py) is running.")
        print("")
        print("If you perform transcription tasks from BOTH the webapp AND the")
        print("orchestrator simultaneously, you may experience:")
        print("")
        print("  • CUDA Out of Memory errors (each loads its own model)")
        print("  • Slow performance due to GPU memory contention")
        print("  • System instability on memory-limited GPUs")
        print("")
        print("RECOMMENDATION: Use either the webapp OR the orchestrator for")
        print("transcription tasks, but not both at the same time.")
        print("=" * 70 + "\n")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup and check for conflicts"""
    print_startup_warnings()
    init_db()
    yield


app = FastAPI(
    title="Transcription Viewer API",
    description="API for managing and searching audio transcriptions with word-level timestamps",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(recordings.router, prefix="/api/recordings", tags=["recordings"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(transcribe.router, prefix="/api/transcribe", tags=["transcribe"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
