#!/usr/bin/env python3
"""Container entrypoint for TranscriptionSuite unified server.

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
    subdirs = ["database", "audio", "logs", "tokens"]
    for subdir in subdirs:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)

    return data_dir


def print_banner(data_dir: Path, port: int, tls_enabled: bool = False) -> None:
    """Print startup banner."""
    scheme = "https" if tls_enabled else "http"
    actual_port = 8443 if tls_enabled else port

    print("=" * 60)
    print("TranscriptionSuite Unified Server")
    print("=" * 60)
    print(f"Data directory: {data_dir}")
    print(f"Server URL:     {scheme}://0.0.0.0:{actual_port}")
    print(f"TLS:            {'Enabled' if tls_enabled else 'Disabled'}")
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

    # Set DATA_DIR env var
    os.environ["DATA_DIR"] = str(data_dir)

    # Configuration
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "8000"))
    log_level = os.environ.get("LOG_LEVEL", "info").lower()

    # TLS configuration
    tls_enabled = os.environ.get("TLS_ENABLED", "false").lower() == "true"
    tls_cert = os.environ.get("TLS_CERT_FILE")
    tls_key = os.environ.get("TLS_KEY_FILE")

    # Print banner
    print_banner(data_dir, port, tls_enabled)

    # Initialize database
    from server.database.database import init_db, set_data_directory

    set_data_directory(data_dir)
    init_db()

    # Prepare uvicorn config
    uvicorn_config = {
        "app": "server.api.main:app",
        "host": host,
        "log_level": log_level,
        "access_log": True,
        "reload": False,
    }

    # Enable TLS if configured
    if tls_enabled:
        if not tls_cert or not Path(tls_cert).exists():
            print(f"ERROR: TLS_ENABLED=true but cert not found: {tls_cert}")
            print("Set TLS_CERT_FILE environment variable to cert path")
            sys.exit(1)
        if not tls_key or not Path(tls_key).exists():
            print(f"ERROR: TLS_ENABLED=true but key not found: {tls_key}")
            print("Set TLS_KEY_FILE environment variable to key path")
            sys.exit(1)

        uvicorn_config["port"] = 8443
        uvicorn_config["ssl_certfile"] = tls_cert
        uvicorn_config["ssl_keyfile"] = tls_key
        print(f"TLS enabled - listening on https://{host}:8443")
    else:
        uvicorn_config["port"] = port
        print(f"TLS disabled - listening on http://{host}:{port}")

    # Run uvicorn
    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()
