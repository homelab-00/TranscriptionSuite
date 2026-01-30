#!/usr/bin/env python3
"""
Standalone entry point for GNOME Dashboard (Qt / PyQt6).

This runs the Qt (KDE) dashboard in a separate process from the GNOME tray.
The tray uses GTK3 + AppIndicator, while the dashboard uses PyQt6.
IPC between them happens via D-Bus.

Usage:
    python -m dashboard.gnome.qt_dashboard_main [--config PATH]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dashboard.common.logging_config import setup_logging

logger = setup_logging(verbose=False, component="dashboard", wipe_on_startup=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TranscriptionSuite Dashboard (GNOME Qt)",
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
    return parser.parse_args()


def _map_state_to_running(state_name: str) -> bool:
    from dashboard.common.models import TrayState

    try:
        state = TrayState[state_name]
    except KeyError:
        return False

    running_states = {
        TrayState.STANDBY,
        TrayState.RECORDING,
        TrayState.UPLOADING,
        TrayState.TRANSCRIBING,
        TrayState.LIVE_LISTENING,
        TrayState.LIVE_MUTED,
    }
    return state in running_states


def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
    except ImportError as e:
        logger.error(f"Failed to import PyQt6: {e}")
        print(
            "Error: PyQt6 is required for the GNOME Qt dashboard.\n"
            "Install with:\n"
            "  Arch Linux: sudo pacman -S python-pyqt6\n"
            "  Ubuntu/Debian: sudo apt install python3-pyqt6\n"
            "  Fedora: sudo dnf install python3-qt6",
            file=sys.stderr,
        )
        return 1

    try:
        from dashboard.common.config import ClientConfig
        from dashboard.gnome.dbus_service import DashboardDBusClient
        from dashboard.kde.dashboard import DashboardWindow
        from dashboard.kde.settings_dialog import SettingsDialog
    except Exception as e:
        logger.error(f"Failed to import dashboard modules: {e}")
        return 1

    config = ClientConfig(args.config) if args.config else ClientConfig()

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = DashboardWindow(config)

    # Initial connection type from config
    use_remote = config.get("server", "use_remote", default=False)
    window.set_connection_local(not use_remote)

    # Settings dialog handler (Qt)
    settings_dialog: SettingsDialog | None = None

    def show_settings_dialog() -> None:
        nonlocal settings_dialog
        if settings_dialog is None:
            settings_dialog = SettingsDialog(config)
        settings_dialog._load_values()
        settings_dialog.exec()

    window.show_settings_requested.connect(show_settings_dialog)

    # D-Bus client for tray IPC
    dbus_client = DashboardDBusClient()
    tray_connected = dbus_client.is_connected()

    if tray_connected:

        def on_start_client(use_remote_mode: bool) -> None:
            success, message = dbus_client.start_client(use_remote_mode)
            if not success:
                logger.error(f"Failed to start client: {message}")
                return
            window.set_connection_local(not use_remote_mode)
            window.set_client_running(True)

        def on_stop_client() -> None:
            success, message = dbus_client.stop_client()
            if not success:
                logger.error(f"Failed to stop client: {message}")
                return
            window.set_client_running(False)

        def on_models_state_changed(loaded: bool) -> None:
            success = dbus_client.set_models_loaded(loaded)
            if not success:
                logger.debug("Failed to sync models state to tray")

        def on_state_changed(state_name: str) -> None:
            window.set_client_running(_map_state_to_running(state_name))

        window.start_client_requested.connect(on_start_client)
        window.stop_client_requested.connect(on_stop_client)
        window.models_state_changed.connect(on_models_state_changed)

        dbus_client.connect_live_transcription_text(
            lambda text, append: window.update_live_transcription_text(text, append)
        )
        dbus_client.connect_state_changed(on_state_changed)

        # Prime initial status
        state, _host, connected = dbus_client.get_client_status()
        window.set_client_running(connected or _map_state_to_running(state))
    else:
        logger.warning(
            "D-Bus connection to tray not available. "
            "Client control will be disabled. Start the tray first."
        )
        try:
            window._show_notification(
                "Limited Mode",
                "Client control unavailable. Start the tray first for full functionality.",
            )
        except Exception:
            pass

    # Pump GLib main loop so D-Bus signals are delivered
    try:
        from gi.repository import GLib

        context = GLib.MainContext.default()

        def pump_glib() -> None:
            while context.pending():
                context.iteration(False)

        glib_timer = QTimer()
        glib_timer.timeout.connect(pump_glib)
        glib_timer.start(50)
    except Exception:
        pass

    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
