#!/usr/bin/env python3
"""
Container entrypoint for TranscriptionSuite.
Runs Audio Notebook and Remote Server as managed subprocesses.
"""

import asyncio
import os
import signal
import sys
from pathlib import Path

# Add app root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    """Main entrypoint - runs both services."""

    # Initialize data directories
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    (data_dir / "audio").mkdir(parents=True, exist_ok=True)
    (data_dir / "certs").mkdir(parents=True, exist_ok=True)
    (data_dir / "tokens").mkdir(parents=True, exist_ok=True)

    # Set working directory to app root
    app_root = Path(__file__).parent.parent
    os.chdir(app_root)

    # Initialize database
    from AUDIO_NOTEBOOK.backend.database import init_db

    init_db()

    # Import and start services
    from DOCKER.container_services import ServiceManager

    manager = ServiceManager()

    # Handle signals for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(manager.shutdown()))

    print("=" * 60)
    print("TranscriptionSuite Container Starting")
    print("=" * 60)
    print(f"Data directory: {data_dir}")
    print("Services:")
    print("  - Audio Notebook:  http://0.0.0.0:8000")
    print("  - Remote Server:   https://0.0.0.0:8443")
    print("=" * 60)

    await manager.run()


if __name__ == "__main__":
    asyncio.run(main())
