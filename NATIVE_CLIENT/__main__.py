"""
Entry point for the native client.

Usage:
    python -m native_client
    python -m native_client --host 192.168.1.100
    python -m native_client --config /path/to/config.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

from .client_orchestrator import ClientOrchestrator
from .config import DEFAULT_CONFIG_PATH, load_config


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="TranscriptionSuite Native Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Connect to localhost
    python -m native_client
    
    # Connect to remote server
    python -m native_client --host 192.168.1.100
    
    # Use custom config file
    python -m native_client --config ~/my-config.yaml
    
    # Use HTTPS
    python -m native_client --host myserver.local --https
""",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
    )

    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default=None,
        help="Server hostname or IP (overrides config)",
    )

    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="Audio Notebook port (default: 8000)",
    )

    parser.add_argument(
        "--https",
        action="store_true",
        help="Use HTTPS for connections",
    )

    parser.add_argument(
        "--no-auto-connect",
        action="store_true",
        help="Don't automatically connect on startup",
    )

    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Disable automatic clipboard copy",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio input devices and exit",
    )

    return parser.parse_args()


def list_audio_devices() -> None:
    """List available audio input devices."""
    from .audio_recorder import AudioRecorder

    devices = AudioRecorder.list_devices()

    if not devices:
        print("No audio input devices found")
        return

    print("Available audio input devices:")
    print("-" * 60)
    for device in devices:
        print(f"  Index: {device['index']}")
        print(f"  Name:  {device['name']}")
        print(f"  Channels: {device['channels']}")
        print(f"  Sample Rate: {device['sample_rate']} Hz")
        print("-" * 60)


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Handle --list-devices
    if args.list_devices:
        list_audio_devices()
        return 0

    # Load config
    config = load_config(args.config)

    # Apply command-line overrides
    if args.host:
        config.server.host = args.host
    if args.port:
        config.server.audio_notebook_port = args.port
    if args.https:
        config.server.use_https = True

    # Create and start orchestrator
    orchestrator = ClientOrchestrator(
        server_config=config.server,
        auto_connect=not args.no_auto_connect,
        auto_copy_clipboard=not args.no_clipboard,
    )

    try:
        orchestrator.start()
        return 0
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        return 0
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
