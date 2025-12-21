#!/usr/bin/env python3
"""
TranscriptionSuite Native Client entry point.

Usage:
    python -m client [options]

Options:
    --host HOST          Server hostname (default: localhost)
    --port PORT          Server port (default: 8000)
    --https              Use HTTPS
    --verbose, -v        Enable verbose debug logging
    --list-devices       List available audio devices and exit
    --help               Show this help message
"""

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging with detailed connection info",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Alias for --verbose (deprecated, use --verbose instead)",
    )

    return parser.parse_args()


def list_audio_devices() -> None:
    """List available audio input devices."""
    print("\nAvailable Audio Input Devices:")
    print("-" * 50)

    devices = AudioRecorder.list_devices()
    if not devices:
        print("No audio input devices found.")
        print("Install PyAudio:")
        print("  Arch: sudo pacman -S python-pyaudio")
        print("  Ubuntu/Debian: sudo apt install python3-pyaudio")
        print("  Fedora: sudo dnf install python3-pyaudio")
        return

    for device in devices:
        print(f"  [{device['index']}] {device['name']}")
        print(
            f"      Channels: {device['channels']}, Sample Rate: {device['sample_rate']}"
        )

    print()


def get_log_dir() -> Path:
    """Get platform-specific log directory."""
    log_dir = get_config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(verbose: bool = False) -> None:
    """
    Set up logging configuration with file and console handlers.

    Args:
        verbose: Enable verbose debug logging
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Create formatters
    verbose_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (always present)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (persistent logs)
    try:
        log_dir = get_log_dir()
        log_file = log_dir / "client.log"

        # Rotating file handler: 5MB per file, keep 3 backups
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
        file_handler.setFormatter(verbose_formatter)
        root_logger.addHandler(file_handler)

        print(f"Logs written to: {log_file}")

    except Exception as e:
        print(f"Warning: Could not set up file logging: {e}")

    # Set up verbose logging for key modules
    if verbose:
        # Enable detailed aiohttp logging for connection debugging
        logging.getLogger("aiohttp").setLevel(logging.DEBUG)
        logging.getLogger("aiohttp.client").setLevel(logging.DEBUG)

        # Log initial verbose mode notification
        logger = logging.getLogger(__name__)
        logger.info("=" * 60)
        logger.info("VERBOSE MODE ENABLED - Detailed connection diagnostics active")
        logger.info("=" * 60)


def main() -> int:
    """Main entry point."""
    try:
        args = parse_args()
    except Exception as e:
        print(f"FATAL: Failed to parse arguments: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    # Handle --list-devices
    if args.list_devices:
        list_audio_devices()
        return 0

    # Set up logging (verbose mode or legacy debug flag)
    verbose = args.verbose or args.debug
    try:
        setup_logging(verbose)
    except Exception as e:
        print(f"WARNING: Failed to set up logging: {e}", file=sys.stderr)
        # Continue anyway - we can still run without file logging

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
        print("\n  Arch Linux:")
        print("    sudo pacman -S python-pyaudio python-pyqt6")
        print("\n  Ubuntu/Debian:")
        print("    sudo apt install python3-pyaudio python3-pyqt6")
        print("\n  Fedora:")
        print("    sudo dnf install python3-pyaudio python3-pyqt6")
        print("\n  GNOME AppImage (requires system packages):")
        print("    sudo apt install python3-pyaudio python3-numpy python3-aiohttp")
        return 1
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
