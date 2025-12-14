#!/usr/bin/env python3
"""
Standalone entry point for the Remote Transcription Server.

This script starts the WebSocket-based remote transcription server
that allows clients to send audio for transcription over the network.

Usage:
    # Start the server:
    uv run python REMOTE_SERVER/run_server.py

    # Generate a token for clients:
    uv run python REMOTE_SERVER/run_server.py --generate-token

    # Start with custom ports:
    uv run python REMOTE_SERVER/run_server.py --control-port 8011 --data-port 8012
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
import logging
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Add SCRIPT to path for imports
_script_path = _project_root / "SCRIPT"
if str(_script_path) not in sys.path:
    sys.path.insert(0, str(_script_path))

# Add REMOTE_SERVER to path for imports
_remote_server_path = Path(__file__).parent
if str(_remote_server_path) not in sys.path:
    sys.path.insert(0, str(_remote_server_path))

from config_manager import ConfigManager
from logging_setup import setup_logging

# Import from REMOTE_SERVER using absolute imports (since we added to sys.path)
from REMOTE_SERVER.server import RemoteTranscriptionServer
from REMOTE_SERVER.transcription_engine import create_transcription_callbacks


def main():
    parser = argparse.ArgumentParser(
        description="Remote Transcription Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start the server
    python run_server.py

    # Generate authentication token
    python run_server.py --generate-token

    # Generate token for specific client
    python run_server.py --generate-token --client-id my-phone

    # Start with custom ports
    python run_server.py --control-port 9011 --data-port 9012
        """,
    )

    parser.add_argument(
        "--generate-token",
        action="store_true",
        help="Generate an authentication token and exit",
    )
    parser.add_argument(
        "--client-id",
        default="default",
        help="Client identifier for token generation (default: 'default')",
    )
    parser.add_argument(
        "--token-expiry",
        type=int,
        default=3600,
        help="Token expiry time in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--control-port",
        type=int,
        help="Override control channel port from config",
    )
    parser.add_argument(
        "--data-port",
        type=int,
        help="Override data channel port from config",
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

    args = parser.parse_args()

    # Load configuration
    config_manager = ConfigManager(args.config)
    config = config_manager.load_or_create_config()

    # Initialize logging
    setup_logging(config)
    logger = logging.getLogger(__name__)

    # Apply command-line overrides
    remote_config = config.setdefault("remote_server", {})
    if args.control_port:
        remote_config["control_port"] = args.control_port
    if args.data_port:
        remote_config["data_port"] = args.data_port
    if args.host:
        remote_config["host"] = args.host

    # Create server instance
    transcribe_cb, realtime_cb, engine = create_transcription_callbacks(config)

    server = RemoteTranscriptionServer(
        config=config,
        transcribe_callback=transcribe_cb,
        realtime_callback=realtime_cb,
    )

    # Handle token generation mode
    if args.generate_token:
        expiry = args.token_expiry
        token = server.generate_token(client_id=args.client_id, expiry_seconds=expiry)

        print("\n" + "=" * 60)
        print("AUTHENTICATION TOKEN GENERATED")
        print("=" * 60)
        print(f"\nClient ID: {args.client_id}")
        print(f"Expiry: {expiry} seconds ({expiry // 3600}h {(expiry % 3600) // 60}m)")
        print(f"\nToken:\n{token}")
        print("\n" + "=" * 60)
        print("\nUse this token in your client to authenticate.")
        print("Keep it secret - anyone with this token can use your server!")
        print("=" * 60 + "\n")
        return

    # Start the server
    print("\n" + "=" * 60)
    print("REMOTE TRANSCRIPTION SERVER")
    print("=" * 60)

    host = remote_config.get("host", "0.0.0.0")
    control_port = remote_config.get("control_port", 8011)
    data_port = remote_config.get("data_port", 8012)

    # Check TLS status
    tls_config = remote_config.get("tls", {})
    tls_enabled = (
        tls_config.get("enabled", False)
        and tls_config.get("cert_file")
        and tls_config.get("key_file")
    )
    ws_scheme = "wss" if tls_enabled else "ws"

    print(f"\nListening on:")
    print(f"  Control: {ws_scheme}://{host}:{control_port}")
    print(f"  Data:    {ws_scheme}://{host}:{data_port}")
    if tls_enabled:
        print(f"\n  TLS: ENABLED")
        print(f"  Cert: {tls_config.get('cert_file')}")
    else:
        print(f"\n  TLS: disabled (configure in config.yaml for secure connections)")
    print(f"\nGenerate client tokens with: --generate-token")
    print("\nPress Ctrl+C to stop")
    print("=" * 60 + "\n")

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
