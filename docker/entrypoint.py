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
import time
import warnings
from pathlib import Path

# Timing instrumentation for startup diagnostics
_start_time = time.perf_counter()


def _log_time(msg: str) -> None:
    print(f"[TIMING] {time.perf_counter() - _start_time:.3f}s - {msg}", flush=True)

# Suppress pkg_resources deprecation warning from webrtcvad (global filter)
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated",
    category=UserWarning,
)

# Add app root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn


def get_user_config_dir() -> Path | None:
    """
    Get the user config directory if it's mounted and writable.

    Returns:
        Path to /user-config if mounted, None otherwise.
    """
    user_config = Path("/user-config")
    if user_config.exists() and user_config.is_dir():
        # Check if it's actually mounted (not just an empty directory)
        # by verifying it's writable
        try:
            test_file = user_config / ".write_test"
            test_file.touch()
            test_file.unlink()
            return user_config
        except (OSError, PermissionError):
            pass
    return None


def setup_directories() -> tuple[Path, Path]:
    """
    Initialize required data directories.

    Returns:
        Tuple of (data_dir, log_dir)
    """
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))

    # Create required subdirectories
    subdirs = ["database", "audio", "logs", "tokens"]
    for subdir in subdirs:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Determine log directory
    # Prefer user config directory if mounted, otherwise use /data/logs
    user_config = get_user_config_dir()
    if user_config:
        log_dir = user_config
        print(f"User config directory mounted at: {user_config}")
    else:
        log_dir = data_dir / "logs"

    return data_dir, log_dir


def print_banner(
    data_dir: Path, log_dir: Path, port: int, tls_enabled: bool = False
) -> None:
    """Print startup banner."""
    scheme = "https" if tls_enabled else "http"
    actual_port = 8443 if tls_enabled else port

    print("=" * 60)
    print("TranscriptionSuite Unified Server")
    print("=" * 60)
    print(f"Data directory: {data_dir}")
    print(f"Log directory:  {log_dir}")
    print(f"Server URL:     {scheme}://0.0.0.0:{actual_port}")
    print(f"TLS:            {'Enabled' if tls_enabled else 'Disabled'}")
    print("")
    print("Endpoints:")
    print("  - Health:      /health")
    print("  - API Docs:    /docs")
    print("  - Auth:        /auth")
    print("  - Record UI:   /record")
    print("  - Admin Panel: /admin")
    print("  - Notebook UI: /notebook")
    print("  - Transcribe:  /api/transcribe/*")
    print("  - Notebook:    /api/notebook/*")
    print("  - Search:      /api/search/*")
    print("  - Admin:       /api/admin/*")
    if tls_enabled:
        print("")
        print("NOTE: TLS mode enabled - authentication required for all routes")
    print("=" * 60)


def main() -> None:
    """Main entrypoint."""
    _log_time("entrypoint main() started")

    # Setup directories
    data_dir, log_dir = setup_directories()
    _log_time("directories setup complete")

    # Set working directory to app root
    app_root = Path(__file__).parent.parent
    os.chdir(app_root)

    # Set environment variables for the server
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["LOG_DIR"] = str(log_dir)

    # Configuration
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "8000"))
    log_level = os.environ.get("LOG_LEVEL", "info").lower()

    # TLS configuration
    tls_enabled = os.environ.get("TLS_ENABLED", "false").lower() == "true"
    tls_cert = os.environ.get("TLS_CERT_FILE")
    tls_key = os.environ.get("TLS_KEY_FILE")

    # Print banner
    print_banner(data_dir, log_dir, port, tls_enabled)

    # Initialize database
    _log_time("importing database module...")
    from server.database.database import init_db, set_data_directory
    _log_time("database module imported")

    set_data_directory(data_dir)
    _log_time("data directory set")
    init_db()
    _log_time("database initialized")

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
    _log_time("starting uvicorn (will load main.py module)...")
    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()
