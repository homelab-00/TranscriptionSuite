#!/usr/bin/env python3
"""
Container entrypoint for TranscriptionSuite unified server.

Runs the unified FastAPI server with all services:
- Audio Notebook
- Transcription API
- Search API
- Admin API

On first run, prompts for configuration (HuggingFace token, admin token).
"""

import argparse
import os
import sys
from pathlib import Path

# Add app root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="TranscriptionSuite Server")
    parser.add_argument(
        "--setup", action="store_true", help="Run interactive setup wizard"
    )
    parser.add_argument(
        "--force-setup",
        action="store_true",
        help="Force re-run setup wizard even if already configured",
    )
    return parser.parse_args()


def setup_directories() -> Path:
    """Initialize required data directories."""
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))

    # Create required subdirectories
    subdirs = ["database", "audio", "logs", "certs", "tokens"]
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
    args = parse_args()

    # Setup directories
    data_dir = setup_directories()

    # Set working directory to app root
    app_root = Path(__file__).parent.parent
    os.chdir(app_root)

    # Set DATA_DIR env var for setup wizard
    os.environ["DATA_DIR"] = str(data_dir)

    # Run setup wizard if requested or on first run
    from server.setup_wizard import get_config, run_setup_wizard

    if args.setup or args.force_setup:
        run_setup_wizard(force=args.force_setup)
        if args.setup:
            # If only --setup was passed, exit after setup
            print("\nSetup complete. Run without --setup to start the server.")
            return

    # Get configuration (will run wizard interactively if first run)
    config = get_config()

    # Export config to environment for the app to use
    if config.get("huggingface_token"):
        os.environ["HF_TOKEN"] = config["huggingface_token"]
    if config.get("admin_token"):
        os.environ["ADMIN_TOKEN"] = config["admin_token"]
    if config.get("lm_studio_url"):
        os.environ["LM_STUDIO_URL"] = config["lm_studio_url"]

    # Configuration
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "8000"))
    log_level = os.environ.get("LOG_LEVEL", "info").lower()

    # TLS configuration
    tls_enabled = os.environ.get("TLS_ENABLED", "false").lower() == "true"
    tls_cert = os.environ.get("TLS_CERT_FILE", "/data/certs/my-machine.crt")
    tls_key = os.environ.get("TLS_KEY_FILE", "/data/certs/my-machine.key")

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
        if not Path(tls_cert).exists():
            print(f"ERROR: TLS_ENABLED=true but cert not found: {tls_cert}")
            print("Mount your certificate with TLS_CERT_PATH environment variable")
            sys.exit(1)
        if not Path(tls_key).exists():
            print(f"ERROR: TLS_ENABLED=true but key not found: {tls_key}")
            print("Mount your key with TLS_KEY_PATH environment variable")
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
