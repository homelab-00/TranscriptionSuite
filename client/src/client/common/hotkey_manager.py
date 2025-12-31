"""
Global hotkey manager using XDG Desktop Portal.

Provides global keyboard shortcuts on Wayland via the org.freedesktop.portal.GlobalShortcuts
interface. Works on KDE Plasma 5.27+ and GNOME 48+.

The XDG Desktop Portal approach:
1. Application registers shortcuts with preferred key bindings
2. Desktop environment shows user a dialog to confirm/customize
3. Shortcuts persist in DE settings
4. Application receives signals when shortcuts are activated
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable

logger = logging.getLogger(__name__)


class HotkeyAction:
    """Represents a registerable hotkey action."""

    START_RECORDING = "start-recording"
    STOP_RECORDING = "stop-recording"
    CANCEL = "cancel"


class HotkeyManager(ABC):
    """Abstract base class for hotkey managers."""

    def __init__(self):
        self.callbacks: dict[str, Callable[[], None]] = {}
        self._running = False

    def register_callback(self, action: str, callback: Callable[[], None]) -> None:
        """Register a callback for a hotkey action."""
        self.callbacks[action] = callback

    def _trigger_callback(self, action: str) -> None:
        """Trigger a registered callback."""
        if action in self.callbacks:
            try:
                self.callbacks[action]()
            except Exception as e:
                logger.error(f"Hotkey callback error for {action}: {e}")

    @abstractmethod
    def start(self) -> bool:
        """
        Start listening for hotkeys.

        Returns:
            True if successfully started
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop listening for hotkeys."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this hotkey backend is available."""
        pass


class XDGPortalHotkeyManager(HotkeyManager):
    """
    XDG Desktop Portal GlobalShortcuts implementation.

    Uses D-Bus to communicate with org.freedesktop.portal.GlobalShortcuts.
    Works on KDE Plasma 5.27+ and GNOME 48+.
    """

    PORTAL_BUS = "org.freedesktop.portal.Desktop"
    PORTAL_PATH = "/org/freedesktop/portal/desktop"
    SHORTCUTS_IFACE = "org.freedesktop.portal.GlobalShortcuts"

    # Default key bindings (compositor may override)
    DEFAULT_SHORTCUTS = {
        HotkeyAction.START_RECORDING: {
            "description": "Start recording audio",
            "preferred_trigger": "CTRL+SHIFT+R",
        },
        HotkeyAction.STOP_RECORDING: {
            "description": "Stop recording and transcribe",
            "preferred_trigger": "CTRL+SHIFT+S",
        },
        HotkeyAction.CANCEL: {
            "description": "Cancel recording or transcription",
            "preferred_trigger": "CTRL+SHIFT+Escape",
        },
    }

    def __init__(self):
        super().__init__()
        self._session_path: str | None = None
        self._bus = None
        self._signal_match = None
        self._thread: threading.Thread | None = None
        self._loop = None

    def is_available(self) -> bool:
        """Check if XDG Portal GlobalShortcuts is available."""
        try:
            import dbus

            bus = dbus.SessionBus()
            proxy = bus.get_object(self.PORTAL_BUS, self.PORTAL_PATH)
            # Check if GlobalShortcuts interface exists
            iface = dbus.Interface(proxy, "org.freedesktop.DBus.Properties")
            try:
                iface.Get(self.SHORTCUTS_IFACE, "version")
                return True
            except dbus.exceptions.DBusException:
                return False
        except Exception as e:
            logger.debug(f"XDG Portal not available: {e}")
            return False

    def start(self) -> bool:
        """Start the hotkey listener."""
        if self._running:
            return True

        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib

            # Set up D-Bus main loop
            DBusGMainLoop(set_as_default=True)

            self._bus = dbus.SessionBus()

            # Create session
            if not self._create_session():
                return False

            # Bind shortcuts
            if not self._bind_shortcuts():
                return False

            # Start the GLib main loop in a thread
            self._loop = GLib.MainLoop()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

            self._running = True
            logger.info("XDG Portal hotkeys started")
            return True

        except ImportError as e:
            logger.error(f"Missing dependency for XDG Portal hotkeys: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start XDG Portal hotkeys: {e}")
            return False

    def _run_loop(self) -> None:
        """Run the GLib main loop."""
        try:
            self._loop.run()
        except Exception as e:
            logger.error(f"GLib main loop error: {e}")

    def _create_session(self) -> bool:
        """Create a GlobalShortcuts session."""
        import dbus

        try:
            proxy = self._bus.get_object(self.PORTAL_BUS, self.PORTAL_PATH)
            shortcuts = dbus.Interface(proxy, self.SHORTCUTS_IFACE)

            # Generate unique token
            import uuid

            token = f"transcriptionsuite_{uuid.uuid4().hex[:8]}"
            session_token = f"session_{uuid.uuid4().hex[:8]}"

            options = dbus.Dictionary(
                {
                    "handle_token": token,
                    "session_handle_token": session_token,
                },
                signature="sv",
            )

            # CreateSession returns a request path
            request_path = shortcuts.CreateSession("", options)
            logger.debug(f"CreateSession request: {request_path}")

            # Wait for response
            response = self._wait_for_response(request_path)
            if response is None or response.get("response", 1) != 0:
                logger.error(f"CreateSession failed: {response}")
                return False

            self._session_path = response.get("session_handle")
            logger.info(f"Session created: {self._session_path}")

            # Connect to Activated signal
            self._connect_activated_signal()

            return True

        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return False

    def _wait_for_response(self, request_path: str, timeout: float = 30.0) -> dict | None:
        """Wait for a portal request response."""
        from gi.repository import GLib

        result = {"response": None}
        loop = GLib.MainLoop()

        def on_response(response_code, results):
            result["response"] = response_code
            result.update(results)
            loop.quit()

        try:
            request = self._bus.get_object(self.PORTAL_BUS, request_path)
            request.connect_to_signal(
                "Response",
                on_response,
                dbus_interface="org.freedesktop.portal.Request",
            )

            # Run loop with timeout
            GLib.timeout_add(int(timeout * 1000), loop.quit)
            loop.run()

            return result if result["response"] is not None else None

        except Exception as e:
            logger.error(f"Error waiting for response: {e}")
            return None

    def _bind_shortcuts(self) -> bool:
        """Bind the application shortcuts."""
        import dbus

        if not self._session_path:
            return False

        try:
            proxy = self._bus.get_object(self.PORTAL_BUS, self.PORTAL_PATH)
            shortcuts = dbus.Interface(proxy, self.SHORTCUTS_IFACE)

            # Build shortcuts list
            shortcuts_list = dbus.Array([], signature="(sa{sv})")
            for action_id, config in self.DEFAULT_SHORTCUTS.items():
                shortcut = dbus.Struct(
                    (
                        action_id,
                        dbus.Dictionary(
                            {
                                "description": config["description"],
                                "preferred_trigger": config["preferred_trigger"],
                            },
                            signature="sv",
                        ),
                    ),
                    signature="(sa{sv})",
                )
                shortcuts_list.append(shortcut)

            import uuid

            token = f"bind_{uuid.uuid4().hex[:8]}"
            options = dbus.Dictionary({"handle_token": token}, signature="sv")

            # BindShortcuts - this triggers the DE's shortcut configuration dialog
            request_path = shortcuts.BindShortcuts(
                self._session_path,
                shortcuts_list,
                "",  # parent_window
                options,
            )
            logger.debug(f"BindShortcuts request: {request_path}")

            # Wait for user to confirm shortcuts
            response = self._wait_for_response(request_path, timeout=120.0)
            if response is None:
                logger.warning("BindShortcuts timed out (user may not have responded)")
                return True  # Continue anyway, shortcuts may be pre-configured

            if response.get("response", 1) != 0:
                logger.warning(f"BindShortcuts declined: {response}")
                return False

            logger.info("Shortcuts bound successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to bind shortcuts: {e}")
            return False

    def _connect_activated_signal(self) -> None:
        """Connect to the Activated signal to receive hotkey events."""
        if not self._session_path:
            return

        try:
            session = self._bus.get_object(self.PORTAL_BUS, self._session_path)
            session.connect_to_signal(
                "Activated",
                self._on_shortcut_activated,
                dbus_interface=self.SHORTCUTS_IFACE,
            )
            logger.debug("Connected to Activated signal")
        except Exception as e:
            logger.error(f"Failed to connect Activated signal: {e}")

    def _on_shortcut_activated(self, shortcut_id: str, timestamp: int, options: dict) -> None:
        """Handle shortcut activation."""
        logger.info(f"Shortcut activated: {shortcut_id}")
        self._trigger_callback(shortcut_id)

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if not self._running:
            return

        self._running = False

        if self._loop:
            self._loop.quit()

        if self._session_path and self._bus:
            try:
                session = self._bus.get_object(self.PORTAL_BUS, self._session_path)
                session_iface = self._bus.dbus.Interface(
                    session, "org.freedesktop.portal.Session"
                )
                session_iface.Close()
            except Exception:
                pass

        self._session_path = None
        self._bus = None
        logger.info("XDG Portal hotkeys stopped")


class WindowsHotkeyManager(HotkeyManager):
    """
    Windows global hotkey implementation using keyboard library.
    
    Uses the keyboard module which provides global hotkey registration on Windows.
    """

    DEFAULT_SHORTCUTS = {
        HotkeyAction.START_RECORDING: "ctrl+shift+r",
        HotkeyAction.STOP_RECORDING: "ctrl+shift+s",
        HotkeyAction.CANCEL: "ctrl+shift+esc",
    }

    def __init__(self):
        super().__init__()
        self._registered_hotkeys: list[str] = []

    def is_available(self) -> bool:
        """Check if Windows keyboard library is available."""
        import platform
        if platform.system() != "Windows":
            return False
        
        try:
            from importlib.util import find_spec
            return find_spec("keyboard") is not None
        except (ImportError, ValueError):
            return False

    def start(self) -> bool:
        """Start the hotkey listener."""
        if self._running:
            return True

        try:
            import keyboard

            # Register hotkeys
            for action, hotkey in self.DEFAULT_SHORTCUTS.items():
                try:
                    keyboard.add_hotkey(
                        hotkey,
                        lambda a=action: self._trigger_callback(a),
                        suppress=True,
                    )
                    self._registered_hotkeys.append(hotkey)
                    logger.info(f"Registered Windows hotkey: {hotkey} -> {action}")
                except Exception as e:
                    logger.warning(f"Failed to register hotkey {hotkey}: {e}")

            if not self._registered_hotkeys:
                return False

            self._running = True
            logger.info("Windows hotkeys started")
            return True

        except ImportError:
            logger.error("keyboard library not available for Windows hotkeys")
            return False
        except Exception as e:
            logger.error(f"Failed to start Windows hotkeys: {e}")
            return False

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if not self._running:
            return

        try:
            import keyboard

            for hotkey in self._registered_hotkeys:
                try:
                    keyboard.remove_hotkey(hotkey)
                except Exception:
                    pass

            self._registered_hotkeys.clear()
            self._running = False
            logger.info("Windows hotkeys stopped")

        except Exception as e:
            logger.error(f"Error stopping Windows hotkeys: {e}")


def create_hotkey_manager() -> HotkeyManager | None:
    """
    Create the appropriate hotkey manager for the current platform.

    Global hotkeys are supported on:
    - Windows: Using keyboard library
    - KDE Plasma: Using XDG Desktop Portal GlobalShortcuts

    GNOME is NOT supported because Mutter doesn't fully implement the
    GlobalShortcuts protocol.

    Returns:
        HotkeyManager instance or None if not available
    """
    import os
    import platform

    system = platform.system()

    # Windows: Use keyboard library
    if system == "Windows":
        manager = WindowsHotkeyManager()
        if manager.is_available():
            return manager

    # Linux: Only support KDE (GNOME's Mutter doesn't fully implement the protocol)
    elif system == "Linux":
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if "kde" in desktop:
            manager = XDGPortalHotkeyManager()
            if manager.is_available():
                return manager
        else:
            logger.info(f"Global hotkeys not supported on {desktop or 'unknown'} desktop")

    logger.info("No hotkey manager available for this platform")
    return None
