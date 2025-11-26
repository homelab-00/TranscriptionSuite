"""
Transcription Viewer Backend API
FastAPI server providing endpoints for managing and searching transcriptions
"""

import os
import sys
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup"""
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
