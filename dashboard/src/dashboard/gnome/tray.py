"""
GNOME system tray implementation using GTK + AppIndicator.

Provides system tray integration for GNOME desktop.
Requires the AppIndicator GNOME extension to be installed.
Based on the architecture from NATIVE_CLIENT/tray/gtk4_tray.py.

NOTE: The tray uses GTK3 + AppIndicator3 because AppIndicator doesn't have
a GTK4 version. The Dashboard window uses GTK4/Adwaita for modern look.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from dashboard.common.docker_manager import DockerManager, ServerStatus
from dashboard.common.models import TrayAction, TrayState
from dashboard.common.server_control_mixin import ServerControlMixin
from dashboard.common.tray_base import AbstractTray

if TYPE_CHECKING:
    from dashboard.common.config import ClientConfig

logger = logging.getLogger(__name__)


def _get_assets_path() -> Path:
    """Resolve the assets directory across dev, AppImage, and bundled builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundle_dir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        return bundle_dir / "build" / "assets"

    if "APPDIR" in os.environ:
        appdir = Path(os.environ["APPDIR"])
        candidate = appdir / "usr" / "share" / "transcriptionsuite" / "assets"
        if candidate.exists():
            return candidate

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "README.md").exists():
            return parent / "build" / "assets"
    return current.parent.parent.parent.parent.parent / "build" / "assets"


def _resolve_logo_icon() -> tuple[Optional[str], Optional[Path]]:
    try:
        assets_path = _get_assets_path()
        logo_path = assets_path / "logo.png"
        if logo_path.exists():
            return "logo", logo_path
        logger.warning(f"App logo not found at {logo_path}")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug(f"Failed to resolve tray logo: {exc}")
    return None, None


# Try to import GTK3 for tray (AppIndicator3 requires GTK3)
HAS_GTK = False
try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3, Gdk, GLib, Gtk

    HAS_GTK = True
except (ImportError, ValueError):
    # Provide stubs for type checking
    AppIndicator3 = None  # type: ignore
    Gdk = None  # type: ignore
    GLib = None  # type: ignore
    Gtk = None  # type: ignore

# NOTE: GTK4/Adwaita imports removed - GTK3 and GTK4 cannot coexist in the
# same Python process. The Dashboard (GTK4) runs as a separate subprocess.
# See dashboard_main.py and dbus_service.py for the IPC architecture.


class GtkTray(ServerControlMixin, AbstractTray):
    """GTK + AppIndicator3 tray implementation for GNOME."""

    # Icon names for different states (using system theme icons)
    ICON_NAMES: dict[TrayState, str] = {
        TrayState.DISCONNECTED: "network-offline-symbolic",
        TrayState.CONNECTING: "network-transmit-symbolic",
        TrayState.STANDBY: "audio-input-microphone-symbolic",
        TrayState.RECORDING: "media-record-symbolic",
        TrayState.UPLOADING: "network-transmit-symbolic",
        TrayState.TRANSCRIBING: "preferences-system-time-symbolic",
        TrayState.ERROR: "dialog-error-symbolic",
        # Live Mode states
        TrayState.LIVE_LISTENING: "microphone-sensitivity-high-symbolic",  # Active listening
        TrayState.LIVE_MUTED: "microphone-sensitivity-muted-symbolic",  # Muted
    }

    def __init__(
        self, config: "ClientConfig | None" = None, app_name: str = "TranscriptionSuite"
    ):
        if not HAS_GTK:
            raise ImportError(
                "GTK3 and AppIndicator3 are required. "
                "Install with: sudo pacman -S gtk3 libappindicator-gtk3"
            )

        super().__init__(app_name)
        self.config = config

        self._logo_icon_name: Optional[str]
        self._logo_icon_path: Optional[Path]
        self._logo_icon_name, self._logo_icon_path = _resolve_logo_icon()

        indicator_icon = self._logo_icon_name or self.ICON_NAMES[TrayState.DISCONNECTED]

        # Create AppIndicator
        self.indicator = AppIndicator3.Indicator.new(
            "transcription-suite",
            indicator_icon,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        if self._logo_icon_path and self._logo_icon_name:
            self.indicator.set_icon_theme_path(str(self._logo_icon_path.parent))
            self.indicator.set_icon(self._logo_icon_name)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title(app_name)

        # Menu items (stored for state updates)
        self.start_item: Optional[Any] = None
        self.stop_item: Optional[Any] = None
        self.cancel_item: Optional[Any] = None
        self.transcribe_item: Optional[Any] = None
        self.toggle_models_item: Optional[Any] = None
        self.start_live_item: Optional[Any] = None
        self.stop_live_item: Optional[Any] = None

        # Model state tracking (assume loaded initially)
        self._models_loaded = True

        # Connection type tracking (assume local initially)
        self._is_local_connection = True

        # Live Mode tracking
        self._live_mode_active = False

        # Docker manager for server control
        self._docker_manager = DockerManager()

        # Dashboard process tracking (runs as separate GTK4 process)
        self._dashboard_process: Optional[subprocess.Popen] = None

        # D-Bus service for IPC with Dashboard
        self._dbus_service: Optional[Any] = None
        self._init_dbus_service()

        # Create menu
        self._setup_menu()

        self.state = TrayState.DISCONNECTED

    def _setup_menu(self) -> None:
        """Create the indicator menu."""
        menu = Gtk.Menu()

        # Recording actions
        self.start_item = Gtk.MenuItem(label="Start Recording")
        self.start_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.START_RECORDING)
        )
        menu.append(self.start_item)

        self.stop_item = Gtk.MenuItem(label="Stop Recording")
        self.stop_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.STOP_RECORDING)
        )
        self.stop_item.set_sensitive(False)
        menu.append(self.stop_item)

        self.cancel_item = Gtk.MenuItem(label="Cancel")
        self.cancel_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.CANCEL_RECORDING)
        )
        self.cancel_item.set_sensitive(False)
        menu.append(self.cancel_item)

        menu.append(Gtk.SeparatorMenuItem())

        # File transcription
        self.transcribe_item = Gtk.MenuItem(label="Transcribe File...")
        self.transcribe_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.TRANSCRIBE_FILE)
        )
        self.transcribe_item.set_sensitive(False)
        menu.append(self.transcribe_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Live Mode (RealtimeSTT)
        self.start_live_item = Gtk.MenuItem(label="Start Live Mode")
        self.start_live_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.START_LIVE_MODE)
        )
        self.start_live_item.set_sensitive(False)
        menu.append(self.start_live_item)

        self.stop_live_item = Gtk.MenuItem(label="Stop Live Mode")
        self.stop_live_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.STOP_LIVE_MODE)
        )
        self.stop_live_item.set_sensitive(False)
        menu.append(self.stop_live_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Model management (unload/reload)
        self.toggle_models_item = Gtk.MenuItem(label="Unload All Models")
        self.toggle_models_item.connect(
            "activate", lambda _: self._trigger_callback(TrayAction.TOGGLE_MODELS)
        )
        self.toggle_models_item.set_sensitive(False)
        menu.append(self.toggle_models_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Show App (opens Dashboard window)
        show_app_item = Gtk.MenuItem(label="Show App")
        show_app_item.connect("activate", lambda _: self._show_dashboard())
        menu.append(show_app_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Quit
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: self.quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def set_state(self, state: TrayState) -> None:
        """Update indicator icon based on state."""
        # Use GLib.idle_add for thread-safety
        GLib.idle_add(self._do_set_state, state)

    def _do_set_state(self, state: TrayState) -> bool:
        """Actually update the state (called on main thread)."""
        self.state = state
        if self._logo_icon_name:
            self.indicator.set_icon(self._logo_icon_name)
        else:
            # If models are unloaded, use DISCONNECTED icon (greyed out)
            if not self._models_loaded:
                icon_name = "network-offline-symbolic"  # Same as DISCONNECTED
            else:
                icon_name = self.ICON_NAMES.get(state, "dialog-question-symbolic")
            self.indicator.set_icon(icon_name)

        # Update menu sensitivity
        if self.start_item and self.stop_item:
            if state == TrayState.RECORDING:
                self.start_item.set_sensitive(False)
                self.stop_item.set_sensitive(True)
            else:
                self.start_item.set_sensitive(state == TrayState.STANDBY)
                self.stop_item.set_sensitive(False)

        # Cancel is enabled during recording, uploading, or transcribing
        if self.cancel_item:
            cancellable_states = {
                TrayState.RECORDING,
                TrayState.UPLOADING,
                TrayState.TRANSCRIBING,
            }
            self.cancel_item.set_sensitive(state in cancellable_states)

        # Transcribe File is only enabled when server is connected and ready (STANDBY)
        if self.transcribe_item:
            self.transcribe_item.set_sensitive(state == TrayState.STANDBY)

        # Toggle Models is only enabled when server is connected and ready (STANDBY)
        # AND the connection is to localhost (model management unavailable for remote)
        if self.toggle_models_item:
            self.toggle_models_item.set_sensitive(
                state == TrayState.STANDBY and self._is_local_connection
            )

        # Live Mode actions
        # Check if we're in a Live Mode state
        is_live_state = state in (TrayState.LIVE_LISTENING, TrayState.LIVE_MUTED)
        if is_live_state:
            self._live_mode_active = True
        elif state == TrayState.STANDBY:
            # Only reset when returning to STANDBY
            self._live_mode_active = False

        if self.start_live_item:
            self.start_live_item.set_sensitive(
                state == TrayState.STANDBY and not self._live_mode_active
            )
        if self.stop_live_item:
            self.stop_live_item.set_sensitive(is_live_state)
        # Emit D-Bus signal for Dashboard to track state
        if self._dbus_service:
            try:
                self._dbus_service.emit_state_changed(state.name)
            except Exception as e:
                logger.debug(f"Failed to emit D-Bus state signal: {e}")

        return False  # Don't repeat

    def show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification via notify-send."""
        # Check if notifications are enabled
        if self.config and not self.config.get("ui", "notifications", default=True):
            return
        GLib.idle_add(self._do_show_notification, title, message)

    def _do_show_notification(self, title: str, message: str) -> bool:
        """Actually show the notification (called on main thread)."""
        try:
            subprocess.run(
                ["notify-send", "-a", self.app_name, title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass  # notify-send not available
        return False

    def update_models_menu_state(self, models_loaded: bool) -> None:
        """
        Update the toggle models menu item text based on current state.

        Args:
            models_loaded: True if models are loaded, False if unloaded
        """
        self._models_loaded = models_loaded
        if self.toggle_models_item:
            if models_loaded:
                self.toggle_models_item.set_label("Unload All Models")
            else:
                self.toggle_models_item.set_label("Reload Models")

        # Update icon to grey if models unloaded
        GLib.idle_add(self._do_set_state, self.state)

        # Sync orchestrator state
        if self.orchestrator and hasattr(self.orchestrator, "sync_models_state"):
            self.orchestrator.sync_models_state(models_loaded)

    def update_connection_type(self, is_local: bool) -> None:
        """
        Update the connection type (local vs remote).

        This affects which menu items are enabled - model management is only
        available for local connections.

        Args:
            is_local: True if connected to localhost, False if remote
        """
        self._is_local_connection = is_local
        # Re-trigger state update to refresh menu item states
        GLib.idle_add(self._do_set_state, self.state)

    def set_live_mode_active(self, active: bool) -> None:
        """Set Live Mode active state and update menu."""
        self._live_mode_active = active
        # Update menu state on main thread
        GLib.idle_add(self._update_live_mode_menu, active)

    def _update_live_mode_menu(self, active: bool) -> bool:
        """Update Live Mode menu items (called on main thread)."""
        # Check if we're in a Live Mode state
        is_live_state = self.state in (TrayState.LIVE_LISTENING, TrayState.LIVE_MUTED)
        if self.start_live_item:
            self.start_live_item.set_sensitive(
                self.state == TrayState.STANDBY and not active
            )
        if self.stop_live_item:
            self.stop_live_item.set_sensitive(active or is_live_state)
        return False

    def run(self) -> None:
        """Start the GTK main loop."""
        # Show Dashboard window on startup (matches KDE behavior)
        GLib.idle_add(self._show_dashboard)
        Gtk.main()

    def quit(self) -> None:
        """Exit the application."""
        # Clean up Dashboard subprocess if running
        if self._dashboard_process:
            try:
                self._dashboard_process.terminate()
                self._dashboard_process.wait(timeout=2)
            except Exception as e:
                logger.debug(f"Error terminating Dashboard process: {e}")
            self._dashboard_process = None

        # Stop D-Bus service
        if self._dbus_service:
            try:
                self._dbus_service.stop()
            except Exception as e:
                logger.debug(f"Error stopping D-Bus service: {e}")
            self._dbus_service = None

        self._trigger_callback(TrayAction.QUIT)
        Gtk.main_quit()

    def _init_dbus_service(self) -> None:
        """Initialize the D-Bus service for IPC with Dashboard."""
        try:
            from dashboard.gnome.dbus_service import TranscriptionSuiteDBusService

            self._dbus_service = TranscriptionSuiteDBusService(
                on_start_client=self._dbus_start_client,
                on_stop_client=self._dbus_stop_client,
                on_get_status=self._dbus_get_status,
                on_reconnect=self._dbus_reconnect,
                on_show_settings=self._dbus_show_settings,
            )
            logger.info("D-Bus service initialized for Dashboard IPC")
        except Exception as e:
            logger.warning(f"Failed to initialize D-Bus service: {e}")
            self._dbus_service = None

    def _dbus_start_client(self, use_remote: bool) -> tuple[bool, str]:
        """D-Bus callback: Start the transcription client."""
        try:
            # Reload config from disk to get latest values saved by Dashboard
            # This prevents overwriting remote_host/token with stale values
            self.config._load()

            if use_remote:
                self.config.set("server", "use_remote", value=True)
                self.config.set("server", "use_https", value=True)
                self.config.set("server", "port", value=8443)
            else:
                self.config.set("server", "use_remote", value=False)
                self.config.set("server", "use_https", value=False)
                self.config.set("server", "port", value=8000)
            self.config.save()
            self._trigger_callback(TrayAction.RECONNECT)
            return True, "Client starting..."
        except Exception as e:
            logger.error(f"Failed to start client via D-Bus: {e}")
            return False, str(e)

    def _dbus_stop_client(self) -> tuple[bool, str]:
        """D-Bus callback: Stop the transcription client."""
        # Note: There's no direct "stop client" action, but we can trigger disconnect
        # For now, return a message indicating manual stop is needed
        return True, "Use tray menu to stop recording"

    def _dbus_get_status(self) -> tuple[str, str, bool]:
        """D-Bus callback: Get client status."""
        state = self.state.name if self.state else "UNKNOWN"
        host = ""
        connected = False

        if self.config:
            use_remote = self.config.get("server", "use_remote", default=False)
            if use_remote:
                host = self.config.get("server", "remote_host", default="")
            else:
                host = "localhost"
            connected = self.state in (
                TrayState.STANDBY,
                TrayState.RECORDING,
                TrayState.UPLOADING,
                TrayState.TRANSCRIBING,
                TrayState.LIVE_LISTENING,
                TrayState.LIVE_MUTED,
            )

        return state, host, connected

    def _dbus_reconnect(self) -> tuple[bool, str]:
        """D-Bus callback: Reconnect to server."""
        try:
            self._trigger_callback(TrayAction.RECONNECT)
            return True, "Reconnecting..."
        except Exception as e:
            return False, str(e)

    def _dbus_show_settings(self) -> bool:
        """D-Bus callback: Show settings dialog."""
        try:
            GLib.idle_add(self.show_settings_dialog)
            return True
        except Exception as e:
            logger.error(f"Failed to show settings via D-Bus: {e}")
            return False

    def _show_dashboard(self) -> None:
        """Show the Dashboard command center window (spawns separate GTK4 process)."""
        import sys

        # Check if Dashboard process is already running
        if self._dashboard_process:
            poll = self._dashboard_process.poll()
            if poll is None:
                # Process still running - try to present existing window
                if self._present_dashboard_window():
                    logger.debug("Existing Dashboard window presented")
                    return

                logger.debug(
                    "Dashboard process running but present attempt failed; "
                    "showing fallback notification"
                )
                self.show_notification(
                    "TranscriptionSuite",
                    "Dashboard is running; click its icon if the window stays hidden.",
                )
                return

        # Spawn Dashboard as separate process (GTK4 cannot coexist with GTK3)
        try:
            # Use the same Python interpreter to run dashboard_main
            cmd = [sys.executable, "-m", "dashboard.gnome.dashboard_main"]

            # Add config path if available
            if self.config and hasattr(self.config, "_config_path"):
                config_path = self.config._config_path
                if config_path:
                    cmd.extend(["--config", str(config_path)])

            logger.info(f"Spawning Dashboard process: {' '.join(cmd)}")

            # Inherit PYTHONPATH from current process so the module can be imported
            env = os.environ.copy()

            # Dashboard now uses unified logging (dashboard.log)
            # No need for separate log file - just inherit stdout/stderr
            self._dashboard_process = subprocess.Popen(
                cmd,
                start_new_session=True,  # Detach from parent process group
                stdout=subprocess.DEVNULL,  # Output goes to shared log file
                stderr=subprocess.DEVNULL,
                env=env,
            )
            logger.info(
                f"Dashboard process started (PID: {self._dashboard_process.pid})"
            )

        except FileNotFoundError as e:
            logger.error(f"Failed to launch Dashboard - Python not found: {e}")
            self.show_notification(
                "Show App",
                "Error: Could not find Python interpreter",
            )
        except Exception as e:
            logger.error(f"Failed to launch Dashboard: {e}")
            self.show_notification("Show App", f"Error: {e}")

    def _present_dashboard_window(self) -> bool:
        """Attempt to focus an already-running Dashboard window."""

        commands = [
            ["gapplication", "launch", "com.transcriptionsuite.dashboard"],
            ["gio", "launch", "com.transcriptionsuite.dashboard"],
        ]

        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, timeout=5)
                return True
            except FileNotFoundError:
                logger.debug(f"Focus helper not available: {' '.join(cmd)}")
            except subprocess.CalledProcessError as exc:
                logger.warning(
                    "Focus helper %s exited with %s", " ".join(cmd), exc.returncode
                )
            except subprocess.TimeoutExpired:
                logger.warning("Focus helper %s timed out", " ".join(cmd))

        return False

    def _on_dashboard_start_client(self, use_remote: bool) -> None:
        """Callback when Dashboard requests to start client (legacy, kept for compatibility)."""
        self._trigger_callback(TrayAction.RECONNECT)

    def _on_dashboard_stop_client(self) -> None:
        """Callback when Dashboard requests to stop client."""
        logger.info("Dashboard requested client stop")
        # Disconnect from server to properly clean up resources
        self._trigger_callback(TrayAction.DISCONNECT)
        # Set tray state to IDLE (client not running)
        self.set_state(TrayState.IDLE)

    def update_live_transcription_text(self, text: str, append: bool = False) -> None:
        """
        Forward live transcription text to dashboard for display.

        Called by the orchestrator during WebSocket streaming recording
        when live transcription updates are received.

        Args:
            text: The live transcription text to display
            append: If True, append to history. If False, replace current line.
        """
        if self._dbus_service and hasattr(self._dbus_service, "_dashboard"):
            dashboard = self._dbus_service._dashboard
            if dashboard and hasattr(dashboard, "update_live_transcription_text"):
                GLib.idle_add(dashboard.update_live_transcription_text, text, append)

    def open_file_dialog(
        self, title: str, filetypes: list[tuple[str, str]]
    ) -> str | None:
        """Open a file chooser dialog."""
        dialog = Gtk.FileChooserDialog(
            title=title,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Open", Gtk.ResponseType.ACCEPT)

        for name, pattern in filetypes:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(name)
            # Handle multiple patterns like "*.wav *.mp3"
            for p in pattern.split():
                file_filter.add_pattern(p)
            dialog.add_filter(file_filter)

        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        return path

    def show_settings_dialog(self) -> None:
        """Show the settings dialog."""
        if not self.config:
            logger.warning("No config available for settings dialog")
            return

        # Import here to avoid circular imports
        from dashboard.gnome.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.config)
        GLib.idle_add(dialog.show)

    def copy_to_clipboard(self, text: str) -> bool:
        """
        Copy text to the system clipboard (thread-safe).

        Args:
            text: Text to copy

        Returns:
            True if successful
        """
        GLib.idle_add(self._do_copy_to_clipboard, text)
        return True

    def _do_copy_to_clipboard(self, text: str) -> bool:
        """
        Actually copy to clipboard (called on main thread).

        On Wayland, we prefer wl-copy as it's more reliable than GTK3's clipboard.
        GTK3's Clipboard.store() doesn't persist well when using AppIndicator3.

        Args:
            text: Text to copy

        Returns:
            False to not repeat the idle callback
        """
        # Check if running on Wayland
        is_wayland = (
            os.environ.get("XDG_SESSION_TYPE") == "wayland"
            or os.environ.get("WAYLAND_DISPLAY") is not None
        )

        if is_wayland:
            # On Wayland, use wl-copy as PRIMARY method
            # Use Popen without waiting - wl-copy forks to background by default
            # to serve clipboard data requests. Waiting causes hangs when compositor
            # doesn't give focus to wl-copy's popup surface.
            try:
                proc = subprocess.Popen(
                    ["wl-copy"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.stdin.write(text.encode("utf-8"))
                proc.stdin.close()
                # Don't wait - wl-copy forks to background to serve clipboard requests
                logger.info(f"Copied to clipboard via wl-copy: {len(text)} characters")
                return False
            except FileNotFoundError:
                logger.warning(
                    "wl-copy not found, clipboard may not work. Install wl-clipboard package."
                )
            except Exception as e:
                logger.warning(f"wl-copy failed: {e}")

        # Try GTK clipboard (works on X11, less reliable on Wayland)
        # Note: On Wayland with AppIndicator, this often fails to persist
        try:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text, -1)
            # Force clipboard to persist - critical for AppIndicator
            clipboard.store()
            # Also trigger clipboard owner change to help persistence
            Gtk.main_iteration_do(False)
            logger.info(f"Copied to clipboard via GTK: {len(text)} characters")
            return False
        except Exception as e:
            logger.warning(f"GTK clipboard copy failed: {e}")

        # Last resort: try xclip for X11
        if not is_wayland:
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=2,
                )
                logger.info(f"Copied to clipboard via xclip: {len(text)} characters")
                return False
            except FileNotFoundError:
                logger.error(
                    "xclip not found. Install xclip package for clipboard support."
                )
            except (
                subprocess.TimeoutExpired,
                subprocess.CalledProcessError,
            ) as xclip_err:
                logger.error(f"xclip failed: {xclip_err}")

        logger.error("All clipboard methods failed. No text copied.")
        return False

    # Server control methods are provided by ServerControlMixin
    # (_on_server_start_local, _on_server_start_remote, _on_server_stop,
    #  _on_server_status)

    def _run_server_operation(self, operation, progress_msg: str) -> None:
        """Run a Docker server operation with notification feedback."""
        try:
            self.show_notification("Docker Server", progress_msg)
            result = operation()
            self.show_notification("Docker Server", result.message)

            # Trigger reconnect if server started successfully
            if result.success and result.status == ServerStatus.RUNNING:
                # Give server time to start, then reconnect
                GLib.timeout_add(
                    3000, lambda: self._trigger_callback(TrayAction.RECONNECT) or False
                )
        except Exception as e:
            logger.error(f"Server operation failed: {e}")
            self.show_notification("Docker Server", f"Error: {e}")


def run_tray(config) -> int:
    """
    Run the GNOME tray application.

    Args:
        config: Client configuration

    Returns:
        Exit code
    """
    from dashboard.common.orchestrator import ClientOrchestrator

    try:
        tray = GtkTray(config=config)
        # Check if user wants to auto-start client when app launches
        auto_start = config.get("behavior", "auto_start_client", default=False)
        orchestrator = ClientOrchestrator(
            config=config,
            auto_connect=auto_start,
            auto_copy_clipboard=config.get("clipboard", "auto_copy", default=True),
        )
        orchestrator.start(tray)
        return 0

    except ImportError as e:
        logger.error(f"GTK/AppIndicator not available: {e}")
        print("Error: GTK3 and AppIndicator are required for GNOME tray.")
        print("Install with: sudo pacman -S gtk3 libappindicator-gtk3")
        print("Also ensure the AppIndicator GNOME extension is installed.")
        return 1

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1
