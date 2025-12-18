#!/usr/bin/env python3
"""
TranscriptionSuite Native Client entry point.

Usage:
    python -m client [options]

Options:
    --host HOST          Server hostname (default: localhost)
    --port PORT          Server port (default: 8000)
    --https              Use HTTPS
    --list-devices       List available audio devices and exit
    --help               Show this help message
"""

import argparse
import logging
import sys

from client.common.audio_recorder import AudioRecorder
from client.common.config import ClientConfig, get_config_dir


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="TranscriptionSuite Native Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--host",
        type=str,
        help="Server hostname",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Server port",
    )
    parser.add_argument(
        "--https",
        action="store_true",
        help="Use HTTPS connection",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def list_audio_devices() -> None:
    """List available audio input devices."""
    print("\nAvailable Audio Input Devices:")
    print("-" * 50)

    devices = AudioRecorder.list_devices()
    if not devices:
        print("No audio input devices found.")
        print("Make sure PyAudio is installed: pip install pyaudio")
        return

    for device in devices:
        print(f"  [{device['index']}] {device['name']}")
        print(
            f"      Channels: {device['channels']}, Sample Rate: {device['sample_rate']}"
        )

    print()


def setup_logging(debug: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Handle --list-devices
    if args.list_devices:
        list_audio_devices()
        return 0

    # Set up logging
    setup_logging(args.debug)

    # Load configuration
    config = ClientConfig()

    # Apply command line overrides
    if args.host:
        config.set("server", "host", value=args.host)
    if args.port:
        config.set("server", "port", value=args.port)
    if args.https:
        config.set("server", "use_https", value=True)

    # Print startup info
    print("\nTranscriptionSuite Native Client v2.0.0")
    print(f"Config directory: {get_config_dir()}")
    print(f"Server: {config.server_host}:{config.server_port}")
    print(f"HTTPS: {config.use_https}")
    print()

    # Detect platform and start appropriate tray
    try:
        import platform

        system = platform.system()

        if system == "Linux":
            # Try to detect desktop environment
            desktop = None
            try:
                import os

                desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            except Exception:
                pass

            if "kde" in (desktop or ""):
                print("Detected KDE Plasma - using PyQt6 tray")
                from client.kde.tray import run_tray
            elif "gnome" in (desktop or ""):
                print("Detected GNOME - using GTK tray")
                from client.gnome.tray import run_tray
            else:
                # Default to Qt
                print(f"Desktop: {desktop or 'unknown'} - using PyQt6 tray")
                from client.kde.tray import run_tray

        elif system == "Windows":
            print("Detected Windows - using PyQt6 tray")
            from client.windows.tray import run_tray

        else:
            print(f"Unsupported platform: {system}")
            return 1

        # Run the tray application
        return run_tray(config)

    except ImportError as e:
        print(f"\nError: Missing dependency - {e}")
        print("\nInstall dependencies for your platform:")
        print("  KDE/Windows: pip install PyQt6 pyaudio")
        print("  GNOME: pip install pyaudio (GTK from system packages)")
        return 1
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
