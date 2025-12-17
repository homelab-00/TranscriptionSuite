#!/usr/bin/env python3
"""
Entry point for the Remote Transcription Web Server.

This script starts a combined HTTPS + WebSocket server that allows clients
to transcribe audio via a web browser interface or WebSocket streaming.

Usage:
    # Start the server:
    uv run python REMOTE_SERVER/run_server.py

    # The server will print the admin token on first run.
    # Access the web UI at https://<your-ip>:8443

    # Custom ports:
    uv run python REMOTE_SERVER/run_server.py --https-port 8443 --wss-port 8444
"""

# =============================================================================
# CUDA 12.6 Configuration (same as orchestrator.py)
# =============================================================================
import os
import sys

_CUDA_12_PATH = "/opt/cuda-12.6"
_ENV_MARKER = "_TRANSCRIPTION_SUITE_CONFIGURED"

if os.environ.get(_ENV_MARKER) != "1":
    os.environ[_ENV_MARKER] = "1"
    if os.path.exists(_CUDA_12_PATH):
        os.environ["CUDA_HOME"] = _CUDA_12_PATH
        os.environ["CUDA_PATH"] = _CUDA_12_PATH
        os.environ["PATH"] = f"{_CUDA_12_PATH}/bin:{os.environ.get('PATH', '')}"
        os.environ["LD_LIBRARY_PATH"] = (
            f"{_CUDA_12_PATH}/lib64:{os.environ.get('LD_LIBRARY_PATH', '')}"
        )
    os.execv(sys.executable, [sys.executable] + sys.argv)
# =============================================================================

# ruff: noqa: E402

import argparse
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Add MAIN to path for imports
_script_path = _project_root / "MAIN"
if str(_script_path) not in sys.path:
    sys.path.insert(0, str(_script_path))

from MAIN.config_manager import ConfigManager

# Import from REMOTE_SERVER package
from REMOTE_SERVER.web_server import WebTranscriptionServer
from REMOTE_SERVER.transcription_engine import (
    create_transcription_callbacks,
    create_file_transcription_callback,
)
from REMOTE_SERVER.server_logging import get_server_logger


def main():
    parser = argparse.ArgumentParser(
        description="Remote Transcription Web Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start the server
    python run_server.py

    # Access the web UI at https://localhost:8443
    # (Accept self-signed certificate warning on first visit)

    # Start with custom ports
    python run_server.py --https-port 9443 --wss-port 9444
        """,
    )

    parser.add_argument(
        "--https-port",
        type=int,
        help="Override HTTPS port from config (default: 8443)",
    )
    parser.add_argument(
        "--wss-port",
        type=int,
        help="Override WebSocket port from config (default: 8444)",
    )
    parser.add_argument(
        "--host",
        help="Override host binding from config",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="Disable TLS (use HTTP/WS instead of HTTPS/WSS)",
    )

    args = parser.parse_args()

    # Load configuration
    config_manager = ConfigManager(args.config)
    config = config_manager.load_or_create_config()

    # Initialize logging (uses server_mode.log)
    logger = get_server_logger()

    # Log file location
    log_file = _project_root / "server_mode.log"
    print(f"\nLog file: {log_file}")

    # Apply command-line overrides
    remote_config = config.setdefault("remote_server", {})
    if args.https_port:
        remote_config["https_port"] = args.https_port
    if args.wss_port:
        remote_config["wss_port"] = args.wss_port
    if args.host:
        remote_config["host"] = args.host
    if args.no_tls:
        remote_config.setdefault("tls", {})["enabled"] = False

    # Create transcription callbacks
    transcribe_cb, realtime_cb, engine = create_transcription_callbacks(config)
    file_transcribe_cb = create_file_transcription_callback(config, engine)

    # Create server instance
    server = WebTranscriptionServer(
        config=config,
        transcribe_callback=transcribe_cb,
        transcribe_file_callback=file_transcribe_cb,
        realtime_callback=realtime_cb,
    )

    # Get configuration for display
    host = remote_config.get("host", "0.0.0.0")
    https_port = remote_config.get("https_port", 8443)
    wss_port = remote_config.get("wss_port", 8444)

    # Check TLS status
    tls_config = remote_config.get("tls", {})
    tls_enabled = tls_config.get("enabled", True)
    http_scheme = "https" if tls_enabled else "http"
    ws_scheme = "wss" if tls_enabled else "ws"

    # Start the server
    print("\n" + "=" * 70)
    print("REMOTE TRANSCRIPTION WEB SERVER")
    print("=" * 70)

    print("\nServer URLs:")
    print(f"  Web UI:    {http_scheme}://{host}:{https_port}")
    print(f"  WebSocket: {ws_scheme}://{host}:{wss_port}")

    if tls_enabled:
        print("\n  TLS: ENABLED (self-signed certificate)")
        print("  Note: Accept the browser security warning on first visit")
    else:
        print("\n  TLS: disabled")

    print("\nTokens are stored in: REMOTE_SERVER/data/tokens.json")
    print("Admin token is printed on first run. Use web UI to manage tokens.")
    print(f"\nLogs are written to: {log_file}")
    print("  Use 'tail -f' to watch logs in real-time")
    print("\nPress Ctrl+C to stop")
    print("=" * 70 + "\n")

    try:
        # Load model before starting (so it's ready for first connection)
        logger.info("Pre-loading transcription model...")
        engine.load_model()
        logger.info("Model loaded, starting server...")

        # Start server (blocking)
        server.start(blocking=True)

    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()
        engine.unload_model()
        print("Server stopped.")

    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
