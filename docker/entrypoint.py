#!/usr/bin/env python3
"""
Container entrypoint for TranscriptionSuite unified server.

Runs the unified FastAPI server with all services:
- Audio Notebook
- Transcription API
- Search API
- Admin API
"""

import os
import sys
from pathlib import Path

# Add app root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn


def setup_directories() -> Path:
    """Initialize required data directories."""
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))

    # Create required subdirectories
    subdirs = ["database", "audio", "logs", "certs", "tokens"]
    for subdir in subdirs:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)

    return data_dir


def print_banner(data_dir: Path, port: int) -> None:
    """Print startup banner."""
    print("=" * 60)
    print("TranscriptionSuite Unified Server")
    print("=" * 60)
    print(f"Data directory: {data_dir}")
    print(f"Server URL:     http://0.0.0.0:{port}")
    print("")
    print("Endpoints:")
    print("  - Health:      /health")
    print("  - API Docs:    /docs")
    print("  - Transcribe:  /api/transcribe/*")
    print("  - Notebook:    /api/notebook/*")
    print("  - Search:      /api/search/*")
    print("  - Admin:       /api/admin/*")
    print("=" * 60)


def main() -> None:
    """Main entrypoint."""
    # Setup directories
    data_dir = setup_directories()

    # Set working directory to app root
    app_root = Path(__file__).parent.parent
    os.chdir(app_root)

    # Configuration
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "8000"))
    log_level = os.environ.get("LOG_LEVEL", "info").lower()

    # Print banner
    print_banner(data_dir, port)

    # Initialize database
    from server.database.database import init_db, set_data_directory

    set_data_directory(data_dir)
    init_db()

    # Run uvicorn
    uvicorn.run(
        "server.api.main:app",
        host=host,
        port=port,
        log_level=log_level,
        access_log=True,
        reload=False,
    )


if __name__ == "__main__":
    main()
