#!/usr/bin/env python3
"""
Standalone entry point for GNOME Dashboard (GTK4/Adwaita).

This module exists because GTK3 (used by AppIndicator3 for the tray icon) and
GTK4 (used by the Dashboard window) cannot coexist in the same Python process.
GObject Introspection raises a ValueError when trying to load two different
versions of the Gtk namespace.

The solution is to run the Dashboard as a separate process from the tray.
Communication between tray and Dashboard happens via D-Bus.

Usage:
    python -m client.gnome.dashboard_main [--config PATH]

Or invoked by the tray process via subprocess when user clicks "Show App".
"""

import argparse
import logging
import sys
from pathlib import Path

from client.common.logging_config import setup_logging

# Set up logging using unified config
logger = setup_logging(verbose=False, component="dashboard", wipe_on_startup=False)


def main() -> int:
    """Run the Dashboard as a standalone GTK4 application."""
    parser = argparse.ArgumentParser(
        description="TranscriptionSuite Dashboard (GNOME GTK4)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to client config file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    try:
        from client.gnome.dashboard import run_dashboard

        return run_dashboard(config_path=args.config)
    except ImportError as e:
        logger.error(f"Failed to import Dashboard: {e}")
        print(
            "Error: GTK4 and libadwaita are required.\n"
            "Install with:\n"
            "  Arch Linux: sudo pacman -S gtk4 libadwaita\n"
            "  Ubuntu/Debian: sudo apt install gir1.2-adw-1 gir1.2-gtk-4.0",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
