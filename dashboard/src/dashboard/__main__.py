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
    --skip-setup         Skip first-time setup wizard
    --help               Show this help message
"""

import argparse
import logging
import sys

from dashboard import __version__
from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.config import ClientConfig, get_config_dir
from dashboard.common.single_instance import (
    acquire_instance_lock,
    release_instance_lock,
)
from dashboard.common.setup_wizard import (
    SetupWizard,
    is_first_time_setup,
    ensure_config_yaml,
)
from dashboard.common.logging_config import setup_logging


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
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip first-time setup wizard",
    )
    parser.add_argument(
        "--no-tls-verify",
        action="store_true",
        help="Disable TLS certificate verification (for self-signed certs)",
    )
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="Allow HTTP to remote hosts (Tailscale WireGuard encrypts traffic)",
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

    # Enforce single instance - acquire lock before proceeding
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        print(
            "Another instance of TranscriptionSuite is already running.",
            file=sys.stderr,
        )
        print("Only one instance can run at a time.", file=sys.stderr)
        return 1

    # Set up logging (verbose mode or legacy debug flag)
    verbose = args.verbose or args.debug
    try:
        setup_logging(verbose=verbose, component="client", wipe_on_startup=True)
    except Exception as e:
        print(f"WARNING: Failed to set up logging: {e}", file=sys.stderr)
        # Continue anyway - we can still run without file logging

    # Ensure config.yaml exists (copy from bundled/dev source if missing)
    # This runs before setup wizard to handle case where config.yaml was deleted
    ensure_config_yaml()

    # Check for first-time setup (before loading config)
    if not args.skip_setup and is_first_time_setup():
        print("\n" + "=" * 60)
        print("  First-Time Setup")
        print("=" * 60)
        print("\nThis appears to be your first time running TranscriptionSuite.")
        print("Running initial setup to configure Docker server files...")
        print()

        wizard = SetupWizard()
        result = wizard.run_setup(
            pull_image=False,
            progress_callback=lambda msg: print(f"  {msg}"),
        )

        if result.success:
            print("\n" + result.message)
        else:
            print(f"\nSetup warning: {result.message}")
            print("You can continue, but server control may not work.")

        print()

    # Load configuration
    config = ClientConfig()

    # Apply command line overrides
    if args.host:
        config.set("server", "host", value=args.host)
    if args.port:
        config.set("server", "port", value=args.port)
    if args.https:
        config.set("server", "use_https", value=True)
    if args.no_tls_verify:
        config.set("server", "tls_verify", value=False)
    if args.allow_insecure_http:
        config.set("server", "allow_insecure_http", value=True)

    # Print startup info
    print(f"\nTranscriptionSuite Native Client v{__version__}")
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
                pass  # Unlikely to fail - proceed with None

            if "kde" in (desktop or ""):
                print("Detected KDE Plasma - using PyQt6 tray")
                from dashboard.kde.tray import run_tray
            elif "gnome" in (desktop or ""):
                print("Detected GNOME - using GTK tray")
                from dashboard.gnome.tray import run_tray
            else:
                # Default to Qt
                print(f"Desktop: {desktop or 'unknown'} - using PyQt6 tray")
                from dashboard.kde.tray import run_tray

        elif system == "Windows":
            print("Detected Windows - using PyQt6 tray")
            from dashboard.windows.tray import run_tray

        else:
            print(f"Unsupported platform: {system}")
            return 1

        # Run the tray application
        try:
            return run_tray(config)
        finally:
            # Release instance lock when exiting
            release_instance_lock(lock_fd)

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
