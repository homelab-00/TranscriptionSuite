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

import uvicorn  # noqa: E402


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
    subdirs = ["database", "audio", "logs", "tokens", "certs"]
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


def prepare_tls_certs(data_dir: Path) -> tuple[str | None, str | None]:
    """
    Get TLS certificate paths from environment.

    The docker-entrypoint.sh script handles copying certificates with proper
    permissions before this Python script runs. This function just validates
    that the certificates exist and are readable.

    Returns:
        Tuple of (cert_path, key_path) that uvicorn should use, or (None, None)
        if TLS is not enabled.
    """
    tls_enabled = os.environ.get("TLS_ENABLED", "false").lower() == "true"
    if not tls_enabled:
        return None, None

    cert_path = os.environ.get("TLS_CERT_FILE")
    key_path = os.environ.get("TLS_KEY_FILE")

    if not cert_path or not key_path:
        print("ERROR: TLS_CERT_FILE or TLS_KEY_FILE not set")
        return None, None

    cert_file = Path(cert_path)
    key_file = Path(key_path)

    if not cert_file.exists():
        print(f"ERROR: TLS cert not found at {cert_path}")
        return None, None
    if not key_file.exists():
        print(f"ERROR: TLS key not found at {key_path}")
        return None, None

    # Verify we can read the files
    try:
        cert_file.read_bytes()
        key_file.read_bytes()
    except PermissionError as e:
        print(f"ERROR: Cannot read TLS files: {e}")
        return None, None

    print(f"Using TLS certificates:")
    print(f"  Cert: {cert_path}")
    print(f"  Key:  {key_path}")

    return str(cert_path), str(key_path)


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

    # TLS configuration - prepare certs before printing banner
    tls_enabled = os.environ.get("TLS_ENABLED", "false").lower() == "true"
    tls_cert: str | None = None
    tls_key: str | None = None

    if tls_enabled:
        # Copy certs to readable location (handles permission issues with bind mounts)
        tls_cert, tls_key = prepare_tls_certs(data_dir)
        if not tls_cert or not tls_key:
            # Cert preparation failed - exit with helpful error
            print("ERROR: TLS_ENABLED=true but certificates could not be prepared")
            print("Check that the certificate files exist and are readable.")
            sys.exit(1)

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
    if tls_enabled and tls_cert and tls_key:
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
