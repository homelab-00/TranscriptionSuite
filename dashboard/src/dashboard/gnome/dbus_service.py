"""
D-Bus service for IPC between GNOME tray (GTK3) and Dashboard (Qt/GTK).

The GNOME tray runs with GTK3 + AppIndicator. The Dashboard runs in a
separate process (Qt/PyQt6 by default), and communicates via D-Bus.

- The tray exposes a D-Bus service for controlling the transcription client
- The Dashboard acts as a D-Bus client to invoke tray methods

D-Bus Interface: com.transcriptionsuite.Dashboard
Object Path: /com/transcriptionsuite/Client

Methods exposed by tray:
    StartClient(use_remote: bool) -> (success: bool, message: str)
    StopClient() -> (success: bool, message: str)
    GetClientStatus() -> (state: str, server_host: str, is_connected: bool)
    Reconnect() -> (success: bool, message: str)
    SetModelsLoaded(loaded: bool) -> (success: bool)

Signals emitted by tray:
    ClientStateChanged(state: str)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

logger = logging.getLogger(__name__)

# D-Bus constants
DBUS_SERVICE_NAME = "com.transcriptionsuite.Dashboard"
DBUS_OBJECT_PATH = "/com/transcriptionsuite/Client"
DBUS_INTERFACE_NAME = "com.transcriptionsuite.Dashboard"

# D-Bus interface XML for introspection
INTERFACE_XML = """
<node>
  <interface name="com.transcriptionsuite.Dashboard">
    <method name="StartClient">
      <arg direction="in" name="use_remote" type="b"/>
      <arg direction="out" name="success" type="b"/>
      <arg direction="out" name="message" type="s"/>
    </method>
    <method name="StopClient">
      <arg direction="out" name="success" type="b"/>
      <arg direction="out" name="message" type="s"/>
    </method>
    <method name="GetClientStatus">
      <arg direction="out" name="state" type="s"/>
      <arg direction="out" name="server_host" type="s"/>
      <arg direction="out" name="is_connected" type="b"/>
    </method>
    <method name="Reconnect">
      <arg direction="out" name="success" type="b"/>
      <arg direction="out" name="message" type="s"/>
    </method>
    <method name="SetModelsLoaded">
      <arg direction="in" name="loaded" type="b"/>
      <arg direction="out" name="success" type="b"/>
    </method>
    <signal name="ClientStateChanged">
      <arg name="state" type="s"/>
    </signal>
    <signal name="LiveTranscriptionText">
      <arg name="text" type="s"/>
      <arg name="append" type="b"/>
    </signal>
  </interface>
</node>
"""

if TYPE_CHECKING:
    from gi.repository import Gio, GLib


# =============================================================================
# D-Bus Service (Tray-side)
# =============================================================================


class TranscriptionSuiteDBusService:
    """
    D-Bus service exposed by the tray process.

    Allows the Dashboard (running in a separate process) to
    control the transcription client via D-Bus method calls.
    """

    def __init__(
        self,
        on_start_client: Callable[[bool], tuple[bool, str]] | None = None,
        on_stop_client: Callable[[], tuple[bool, str]] | None = None,
        on_get_status: Callable[[], tuple[str, str, bool]] | None = None,
        on_reconnect: Callable[[], tuple[bool, str]] | None = None,
        on_set_models_loaded: Callable[[bool], bool] | None = None,
    ):
        """
        Initialize the D-Bus service.

        Args:
            on_start_client: Callback for StartClient(use_remote) -> (success, message)
            on_stop_client: Callback for StopClient() -> (success, message)
            on_get_status: Callback for GetClientStatus() -> (state, host, connected)
            on_reconnect: Callback for Reconnect() -> (success, message)
        """
        self._on_start_client = on_start_client
        self._on_stop_client = on_stop_client
        self._on_get_status = on_get_status
        self._on_reconnect = on_reconnect
        self._on_set_models_loaded = on_set_models_loaded

        self._connection: Any = None
        self._registration_id: int = 0
        self._owner_id: int = 0

        self._start()

    def _start(self) -> None:
        """Register the D-Bus service."""
        try:
            from gi.repository import Gio

            # Own the bus name
            self._owner_id = Gio.bus_own_name(
                Gio.BusType.SESSION,
                DBUS_SERVICE_NAME,
                Gio.BusNameOwnerFlags.NONE,
                self._on_bus_acquired,
                self._on_name_acquired,
                self._on_name_lost,
            )
            logger.info(f"Requesting D-Bus name: {DBUS_SERVICE_NAME}")
        except Exception as e:
            logger.error(f"Failed to start D-Bus service: {e}")

    def _on_bus_acquired(self, connection: "Gio.DBusConnection", name: str) -> None:
        """Called when bus connection is acquired."""
        from gi.repository import Gio

        self._connection = connection

        # Parse interface XML
        node_info = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        interface_info = node_info.interfaces[0]

        # Register the object
        try:
            self._registration_id = connection.register_object(
                DBUS_OBJECT_PATH,
                interface_info,
                self._handle_method_call,
                None,  # get_property
                None,  # set_property
            )
            logger.debug(f"D-Bus object registered at {DBUS_OBJECT_PATH}")
        except Exception as e:
            logger.error(f"Failed to register D-Bus object: {e}")

    def _on_name_acquired(self, connection: "Gio.DBusConnection", name: str) -> None:
        """Called when the bus name is acquired."""
        logger.info(f"D-Bus name acquired: {name}")

    def _on_name_lost(self, connection: "Gio.DBusConnection", name: str) -> None:
        """Called when the bus name is lost."""
        logger.warning(f"D-Bus name lost: {name}")

    def _handle_method_call(
        self,
        connection: "Gio.DBusConnection",
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: "GLib.Variant",
        invocation: "Gio.DBusMethodInvocation",
    ) -> None:
        """Handle incoming D-Bus method calls."""
        from gi.repository import GLib

        logger.debug(f"D-Bus method call: {method_name} from {sender}")

        try:
            if method_name == "StartClient":
                use_remote = parameters.unpack()[0]
                if self._on_start_client:
                    success, message = self._on_start_client(use_remote)
                else:
                    success, message = False, "Not implemented"
                invocation.return_value(GLib.Variant("(bs)", (success, message)))

            elif method_name == "StopClient":
                if self._on_stop_client:
                    success, message = self._on_stop_client()
                else:
                    success, message = False, "Not implemented"
                invocation.return_value(GLib.Variant("(bs)", (success, message)))

            elif method_name == "GetClientStatus":
                if self._on_get_status:
                    state, host, connected = self._on_get_status()
                else:
                    state, host, connected = "unknown", "", False
                invocation.return_value(GLib.Variant("(ssb)", (state, host, connected)))

            elif method_name == "Reconnect":
                if self._on_reconnect:
                    success, message = self._on_reconnect()
                else:
                    success, message = False, "Not implemented"
                invocation.return_value(GLib.Variant("(bs)", (success, message)))

            elif method_name == "SetModelsLoaded":
                loaded = parameters.unpack()[0]
                if self._on_set_models_loaded:
                    success = self._on_set_models_loaded(loaded)
                else:
                    success = False
                invocation.return_value(GLib.Variant("(b)", (success,)))

            else:
                invocation.return_error_literal(
                    GLib.quark_from_string("org.freedesktop.DBus.Error"),
                    0,
                    f"Unknown method: {method_name}",
                )
        except Exception as e:
            logger.exception(f"Error handling D-Bus method {method_name}: {e}")
            invocation.return_error_literal(
                GLib.quark_from_string("org.freedesktop.DBus.Error"),
                0,
                str(e),
            )

    def emit_state_changed(self, state: str) -> None:
        """Emit ClientStateChanged signal."""
        if not self._connection:
            return

        from gi.repository import GLib

        try:
            self._connection.emit_signal(
                None,  # Broadcast to all listeners
                DBUS_OBJECT_PATH,
                DBUS_INTERFACE_NAME,
                "ClientStateChanged",
                GLib.Variant("(s)", (state,)),
            )
            logger.debug(f"Emitted ClientStateChanged signal: {state}")
        except Exception as e:
            logger.error(f"Failed to emit D-Bus signal: {e}")

    def emit_live_transcription_text(self, text: str, append: bool) -> None:
        """Emit LiveTranscriptionText signal."""
        if not self._connection:
            return

        from gi.repository import GLib

        try:
            self._connection.emit_signal(
                None,  # Broadcast to all listeners
                DBUS_OBJECT_PATH,
                DBUS_INTERFACE_NAME,
                "LiveTranscriptionText",
                GLib.Variant("(sb)", (text, append)),
            )
            # Don't log essentially every character typed/spoken as it spams debug logs
        except Exception as e:
            logger.error(f"Failed to emit LiveTranscriptionText signal: {e}")

    def stop(self) -> None:
        """Unregister the D-Bus service."""
        from gi.repository import Gio

        if self._registration_id and self._connection:
            self._connection.unregister_object(self._registration_id)
            self._registration_id = 0

        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

        logger.info("D-Bus service stopped")


# =============================================================================
# D-Bus Client (Dashboard-side)
# =============================================================================


class DashboardDBusClient:
    """
    D-Bus client used by the Dashboard to communicate with the tray.

    Provides a simple synchronous API for calling tray methods.
    """

    def __init__(self):
        """Initialize the D-Bus client."""
        self._proxy: Any = None
        self._connected = False
        self._connect()

    def _connect(self) -> None:
        """Connect to the D-Bus service."""
        try:
            from gi.repository import Gio

            self._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,  # Interface info (use introspection)
                DBUS_SERVICE_NAME,
                DBUS_OBJECT_PATH,
                DBUS_INTERFACE_NAME,
                None,  # Cancellable
            )

            # Check if the service is actually running
            if self._proxy.get_name_owner() is not None:
                self._connected = True
                logger.info(f"Connected to D-Bus service: {DBUS_SERVICE_NAME}")
            else:
                self._connected = False
                logger.warning(f"D-Bus service not running: {DBUS_SERVICE_NAME}")
        except Exception as e:
            logger.warning(f"Failed to connect to D-Bus service: {e}")
            self._proxy = None
            self._connected = False

    def is_connected(self) -> bool:
        """Check if connected to the D-Bus service."""
        return self._connected and self._proxy is not None

    def start_client(self, use_remote: bool) -> tuple[bool, str]:
        """
        Start the transcription client.

        Args:
            use_remote: True for remote (HTTPS) mode, False for local

        Returns:
            Tuple of (success, message)
        """
        if not self._proxy:
            return False, "Not connected to tray"

        try:
            from gi.repository import GLib

            result = self._proxy.call_sync(
                "StartClient",
                GLib.Variant("(b)", (use_remote,)),
                0,  # Flags
                -1,  # Timeout (-1 = default)
                None,  # Cancellable
            )
            return result.unpack()
        except Exception as e:
            logger.error(f"D-Bus call StartClient failed: {e}")
            return False, str(e)

    def stop_client(self) -> tuple[bool, str]:
        """
        Stop the transcription client.

        Returns:
            Tuple of (success, message)
        """
        if not self._proxy:
            return False, "Not connected to tray"

        try:
            result = self._proxy.call_sync(
                "StopClient",
                None,  # No parameters
                0,
                -1,
                None,
            )
            return result.unpack()
        except Exception as e:
            logger.error(f"D-Bus call StopClient failed: {e}")
            return False, str(e)

    def get_client_status(self) -> tuple[str, str, bool]:
        """
        Get current client status.

        Returns:
            Tuple of (state, server_host, is_connected)
        """
        if not self._proxy:
            return "unknown", "", False

        try:
            result = self._proxy.call_sync(
                "GetClientStatus",
                None,
                0,
                -1,
                None,
            )
            return result.unpack()
        except Exception as e:
            logger.error(f"D-Bus call GetClientStatus failed: {e}")
            return "error", "", False

    def reconnect(self) -> tuple[bool, str]:
        """
        Trigger a reconnect to the server.

        Returns:
            Tuple of (success, message)
        """
        if not self._proxy:
            return False, "Not connected to tray"

        try:
            result = self._proxy.call_sync(
                "Reconnect",
                None,
                0,
                -1,
                None,
            )
            return result.unpack()
        except Exception as e:
            logger.error(f"D-Bus call Reconnect failed: {e}")
            return False, str(e)

    def set_models_loaded(self, loaded: bool) -> bool:
        """
        Sync models loaded state with tray.

        Args:
            loaded: True if models are loaded, False if unloaded

        Returns:
            True if successful
        """
        if not self._proxy:
            return False

        try:
            from gi.repository import GLib

            result = self._proxy.call_sync(
                "SetModelsLoaded",
                GLib.Variant("(b)", (loaded,)),
                0,
                -1,
                None,
            )
            return result.unpack()[0]
        except Exception as e:
            logger.error(f"D-Bus call SetModelsLoaded failed: {e}")
            return False

    def connect_state_changed(self, callback: Callable[[str], None]) -> None:
        """
        Connect to the ClientStateChanged signal.

        Args:
            callback: Function to call with new state string
        """
        if not self._proxy:
            return

        def on_signal(
            proxy: Any,
            sender_name: str,
            signal_name: str,
            parameters: "GLib.Variant",
        ) -> None:
            if signal_name == "ClientStateChanged":
                state = parameters.unpack()[0]
                callback(state)

        self._proxy.connect("g-signal", on_signal)
        logger.debug("Connected to ClientStateChanged signal")

    def connect_live_transcription_text(
        self, callback: Callable[[str, bool], None]
    ) -> None:
        """
        Connect to the LiveTranscriptionText signal.

        Args:
            callback: Function to call with (text, append)
        """
        if not self._proxy:
            return

        def on_signal(
            proxy: Any,
            sender_name: str,
            signal_name: str,
            parameters: "GLib.Variant",
        ) -> None:
            if signal_name == "LiveTranscriptionText":
                text, append = parameters.unpack()
                callback(text, append)

        self._proxy.connect("g-signal", on_signal)
        logger.debug("Connected to LiveTranscriptionText signal")
