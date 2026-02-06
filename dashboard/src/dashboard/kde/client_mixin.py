"""
Client control mixin for the Dashboard.

This module contains client-related methods for the DashboardWindow class,
extracted to keep the main dashboard.py file smaller and more maintainable.
"""

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.docker_manager import ServerStatus
from dashboard.common.models import TrayAction

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class ClientControlMixin:
    """
    Mixin class providing client control functionality for DashboardWindow.

    This mixin provides all client-related methods including:
    - Client status refresh and display
    - Client start/stop operations
    - Model management (load/unload)
    - Toggle button handlers
    - Client log display
    - Notification handling
    """

    # =========================================================================
    # Client Status
    # =========================================================================

    def _refresh_client_status(self) -> None:
        """Refresh the client status display."""
        if self._client_running:
            self._client_status_label.setText("Running")
            self._client_status_label.setStyleSheet("color: #4caf50;")  # match sidebar

            # Show connection info
            host = self.config.server_host
            port = self.config.server_port
            https = "HTTPS" if self.config.use_https else "HTTP"
            self._connection_info_label.setText(f"{https}://{host}:{port}")
        else:
            self._client_status_label.setText("Stopped")
            self._client_status_label.setStyleSheet("color: #ff9800;")  # match sidebar
            self._connection_info_label.setText("Not connected")

        # Update button states
        self._start_client_local_btn.setEnabled(not self._client_running)
        self._start_client_remote_btn.setEnabled(not self._client_running)
        self._stop_client_btn.setEnabled(self._client_running)

        # Update models button based on server health
        self._update_models_button_state()

        # Live Mode toggle is only usable when the client is running
        if hasattr(self, "_preview_toggle_btn"):
            self._preview_toggle_btn.setEnabled(self._client_running)
            self._update_live_transcriber_toggle_style()
        if hasattr(self, "_live_mode_mute_btn"):
            self._live_mode_mute_btn.setEnabled(False)

    def _update_models_button_state(self) -> None:
        """Update the models button state based on server health and connection type."""
        # If client isn't running yet, keep the button disabled
        if not self._client_running:
            self._unload_models_btn.setEnabled(False)
            self._unload_models_btn.setStyleSheet(
                "QPushButton { background-color: #2d2d2d; border: 1px solid #3d3d3d; border-radius: 6px; color: #606060; padding: 10px 20px; }"
                "QPushButton:disabled { background-color: #2d2d2d; border-color: #3d3d3d; color: #606060; }"
            )
            return

        # Check if server is running and healthy
        status = self._docker_manager.get_server_status()
        health = self._docker_manager.get_container_health()

        is_healthy = status == ServerStatus.RUNNING and (
            health is None or health == "healthy"
        )

        # Only enable if healthy AND connected locally (model management unavailable for remote)
        if is_healthy and self._is_local_connection:
            # Server is healthy and local, enable button with appropriate color
            self._unload_models_btn.setEnabled(True)
            if self._models_loaded:
                # Cyan (models loaded, ready to unload) - color 2
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #0AFCCF; border: none; border-radius: 6px; color: #141414; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #08d9b3; }"
                )
            else:
                # Red (models unloaded, ready to reload) - color 3
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #ff0000; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #d32f2f; }"
                )
        else:
            # Server not healthy, disable button with dark gray style
            self._unload_models_btn.setEnabled(False)
            self._unload_models_btn.setStyleSheet(
                "QPushButton { background-color: #2d2d2d; border: 1px solid #3d3d3d; border-radius: 6px; color: #606060; padding: 10px 20px; }"
                "QPushButton:disabled { background-color: #2d2d2d; border-color: #3d3d3d; color: #606060; }"
            )

    def _validate_remote_settings(self) -> tuple[bool, str]:
        """
        Validate settings for remote client connection.

        Returns:
            Tuple of (is_valid, error_message)
        """
        errors = []

        # Check remote host is set and contains .ts.net
        remote_host = self.config.get("server", "remote_host", default="")
        if not remote_host:
            errors.append("Remote host is not set")
        elif ".ts.net" not in remote_host:
            errors.append("Remote host should be a Tailscale hostname (*.ts.net)")

        # Check use_remote is enabled
        if not self.config.get("server", "use_remote", default=False):
            errors.append("'Use remote server' is not enabled")

        # Check HTTPS is enabled
        if not self.config.get("server", "use_https", default=False):
            errors.append("HTTPS is not enabled (required for remote)")

        # Check authentication token
        token = self.config.get("server", "token", default="")
        if not token or not token.strip():
            errors.append("Authentication token is not set")

        # Check port is appropriate for remote (should be 8443)
        port = self.config.get("server", "port", default=8000)
        # Note: We get the expected remote port from a constant or config
        # For now, we check for 8443 as the standard remote port
        expected_remote_port = 8443
        if port != expected_remote_port:
            errors.append(
                f"Port should be {expected_remote_port} for remote connection (currently {port})"
            )

        if errors:
            return False, "\n".join(errors)
        return True, ""

    # =========================================================================
    # Client Start/Stop
    # =========================================================================

    def _on_start_client_local(self) -> None:
        """Start client in local mode."""
        # Configure for local connection
        self.config.set("server", "use_remote", value=False)
        self.config.set("server", "use_https", value=False)
        self.config.set("server", "port", value=8000)
        self.config.save()

        self._client_running = True
        self._refresh_client_status()
        self.start_client_requested.emit(False)  # False = local

        # Schedule notebook API client update after connection establishes
        QTimer.singleShot(2000, self._update_notebook_api_client)

    def _on_start_client_remote(self) -> None:
        """Start client in remote mode."""
        # Validate settings first
        is_valid, error_msg = self._validate_remote_settings()

        if not is_valid:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Invalid Settings")
            msg_box.setText("Please edit your settings before starting remote client.")
            msg_box.setDetailedText(error_msg)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()
            return

        self._client_running = True
        self._refresh_client_status()
        self.start_client_requested.emit(True)  # True = remote

        # Schedule notebook API client update after connection establishes
        QTimer.singleShot(2000, self._update_notebook_api_client)

    def _on_stop_client(self) -> None:
        """Stop the client."""
        self._client_running = False
        self._refresh_client_status()
        self.stop_client_requested.emit()

    def _on_show_settings(self) -> None:
        """Show settings dialog."""
        self.show_settings_requested.emit()

    # =========================================================================
    # Client Logs
    # =========================================================================

    def _toggle_client_logs(self) -> None:
        """Open client logs in a separate window."""
        from dashboard.kde.log_window import LogWindow

        if self._client_log_window is None:
            self._client_log_window = LogWindow("Client Logs", self)

        # Read client logs from the unified log file
        try:
            from dashboard.common.logging_config import get_log_file

            log_file = get_log_file()
            if log_file.exists():
                # Read last 200 lines
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    last_lines = lines[-200:] if len(lines) > 200 else lines
                    logs = "".join(last_lines)
            else:
                logs = "No log file found"
        except Exception as e:
            logger.error(f"Failed to read client logs: {e}")
            logs = f"Error reading logs: {e}"

        self._client_log_window.set_logs(logs)
        self._client_log_window.show()
        self._client_log_window.raise_()
        self._client_log_window.activateWindow()

    def append_client_log(self, message: str) -> None:
        """Append a message to the client log view."""
        from dashboard.kde.log_window import LogWindow

        if self._client_log_window is None:
            self._client_log_window = LogWindow("Client Logs", self)
        self._client_log_window.append_log(message)

    # =========================================================================
    # Client State Management
    # =========================================================================

    def set_client_running(self, running: bool) -> None:
        """Update client running state (called from orchestrator)."""
        self._client_running = running
        if self._current_view == self._View.CLIENT:
            self._refresh_client_status()

        # Update notebook API client when client starts
        if running:
            QTimer.singleShot(2000, self._update_notebook_api_client)

    def set_models_loaded(self, loaded: bool) -> None:
        """
        Update models loaded state (called from tray when changed via menu).

        Args:
            loaded: True if models are loaded, False if unloaded
        """
        self._models_loaded = loaded
        if self._current_view == self._View.CLIENT and self._unload_models_btn:
            if loaded:
                self._unload_models_btn.setText("Unload All Models")
                self._unload_models_btn.setToolTip(
                    "Unload transcription models to free GPU memory"
                )
                # Cyan background (models loaded) - color 2
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #0AFCCF; border: none; border-radius: 6px; color: #141414; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #08d9b3; }"
                )
            else:
                self._unload_models_btn.setText("Reload Models")
                self._unload_models_btn.setToolTip(
                    "Reload transcription models for use"
                )
                # Red background (models unloaded) - color 3
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #ff0000; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #d32f2f; }"
                )

    def set_connection_local(self, is_local: bool) -> None:
        """
        Update connection type (called from tray when connection changes).

        Args:
            is_local: True if connected to localhost, False if remote
        """
        self._is_local_connection = is_local
        # Refresh button state with new connection type
        if self._current_view == self._View.CLIENT:
            self._update_models_button_state()

    # =========================================================================
    # Model Management
    # =========================================================================

    def _on_toggle_models(self) -> None:
        """Toggle model loading state - unload to free GPU memory or reload."""
        from dashboard.common.api_client import APIClient

        # Get server connection settings
        use_remote = self.config.get("server", "use_remote", default=False)
        use_https = self.config.get("server", "use_https", default=False)

        if use_remote:
            host = self.config.get("server", "remote_host", default="")
            port = self.config.get("server", "port", default=8443)
        else:
            host = "localhost"
            port = self.config.get("server", "port", default=8000)

        token = self.config.get("server", "token", default="")

        if not host:
            self._show_notification("Error", "No server host configured")
            return

        # Create temporary API client for this operation
        api_client = APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token if token else None,
        )

        async def do_toggle():
            try:
                if self._models_loaded:
                    result = await api_client.unload_models()
                else:
                    result = await api_client.reload_models()
                return result
            finally:
                await api_client.close()

        # Run async operation
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(do_toggle())
            loop.close()

            if result.get("success"):
                self._models_loaded = not self._models_loaded
                # Emit signal to notify tray of state change
                self.models_state_changed.emit(self._models_loaded)
                if self._models_loaded:
                    self._unload_models_btn.setText("Unload All Models")
                    self._unload_models_btn.setToolTip(
                        "Unload transcription models to free GPU memory"
                    )
                    # Cyan background (models loaded) - color 2
                    self._unload_models_btn.setStyleSheet(
                        "QPushButton { background-color: #0AFCCF; border: none; border-radius: 6px; color: #141414; padding: 10px 20px; font-weight: 500; }"
                        "QPushButton:hover { background-color: #08d9b3; }"
                    )
                    self._show_notification(
                        "Models Loaded", "Models ready for transcription"
                    )
                else:
                    self._unload_models_btn.setText("Reload Models")
                    self._unload_models_btn.setToolTip(
                        "Reload transcription models for use"
                    )
                    # Red background (models unloaded) - color 3
                    self._unload_models_btn.setStyleSheet(
                        "QPushButton { background-color: #ff0000; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
                        "QPushButton:hover { background-color: #d32f2f; }"
                    )
                    self._show_notification(
                        "Models Unloaded",
                        "GPU memory freed. Click 'Reload Models' to restore.",
                    )
            else:
                self._show_notification(
                    "Operation Failed", result.get("message", "Unknown error")
                )
        except Exception as e:
            logger.error(f"Model toggle failed: {e}")
            self._show_notification("Error", f"Failed to toggle models: {e}")

    def _show_notification(self, title: str, message: str) -> None:
        """Show a desktop notification."""
        # Check if notifications are enabled in settings
        if not self.config.get("ui", "notifications", default=True):
            logger.debug("Notifications disabled in settings")
            return

        try:
            subprocess.run(
                ["notify-send", "-a", "TranscriptionSuite", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            logger.debug("notify-send not found - cannot show desktop notifications")

    # =========================================================================
    # Toggle Button Handlers
    # =========================================================================

    def _on_main_language_changed(self, index: int) -> None:
        """Handle main transcription language selection change."""
        del index
        if not hasattr(self, "_main_language_combo"):
            return

        language_code = self._main_language_combo.currentData()
        language_value = language_code or None
        self.config.set_server_config(
            "longform_recording", "language", value=language_value
        )
        logger.info(
            "Main transcription language set to: %s (%s)",
            self._main_language_combo.currentText(),
            language_code or "auto",
        )

    def _refresh_source_devices(self) -> None:
        """Refresh microphone/system-audio source dropdowns."""
        if not hasattr(self, "_microphone_combo") or not hasattr(
            self, "_system_audio_combo"
        ):
            return

        selected_mic = self.config.get("recording", "device_index", default=None)
        selected_output = self.config.get("recording", "system_output_id", default=None)

        self._microphone_combo.blockSignals(True)
        self._system_audio_combo.blockSignals(True)

        self._microphone_combo.clear()
        self._microphone_combo.addItem("System Default", None)
        try:
            for device in AudioRecorder.list_input_devices():
                name = device.get("name", f"Input {device.get('index', '?')}")
                self._microphone_combo.addItem(name, device.get("index"))
        except Exception as e:
            logger.warning(f"Failed to list microphone devices: {e}")

        self._system_audio_combo.clear()
        self._system_audio_combo.addItem("System Default", None)
        try:
            for device in AudioRecorder.list_output_devices():
                name = device.get("name", "Output device")
                self._system_audio_combo.addItem(name, device.get("id"))
        except Exception as e:
            logger.warning(f"Failed to list system audio devices: {e}")

        self._microphone_combo.setCurrentIndex(0)
        if selected_mic is not None:
            for i in range(self._microphone_combo.count()):
                if self._microphone_combo.itemData(i) == selected_mic:
                    self._microphone_combo.setCurrentIndex(i)
                    break

        self._system_audio_combo.setCurrentIndex(0)
        if selected_output is not None:
            for i in range(self._system_audio_combo.count()):
                if self._system_audio_combo.itemData(i) == selected_output:
                    self._system_audio_combo.setCurrentIndex(i)
                    break

        self._microphone_combo.blockSignals(False)
        self._system_audio_combo.blockSignals(False)
        self._sync_audio_source_ui()

    def _on_audio_source_toggled(self, checked: bool) -> None:
        """Handle microphone/system-audio source toggle."""
        source_type = "system_audio" if checked else "microphone"
        self.config.set("recording", "source_type", value=source_type)
        self.config.save()
        self._sync_audio_source_ui()
        logger.info("Recording source set to: %s", source_type)

    def _on_microphone_device_changed(self, index: int) -> None:
        """Handle microphone dropdown selection change."""
        del index
        if not hasattr(self, "_microphone_combo"):
            return
        self.config.set(
            "recording", "device_index", value=self._microphone_combo.currentData()
        )
        self.config.save()

    def _on_system_audio_device_changed(self, index: int) -> None:
        """Handle system-audio output dropdown selection change."""
        del index
        if not hasattr(self, "_system_audio_combo"):
            return
        self.config.set(
            "recording",
            "system_output_id",
            value=self._system_audio_combo.currentData(),
        )
        self.config.save()

    def _sync_audio_source_ui(self) -> None:
        """Sync source labels and toggle state with stored source configuration."""
        if not hasattr(self, "_source_switch"):
            return

        source_type = self.config.get("recording", "source_type", default="microphone")
        is_system_audio = source_type == "system_audio"

        self._source_switch.blockSignals(True)
        self._source_switch.setChecked(is_system_audio)
        self._source_switch.blockSignals(False)

        if hasattr(self, "_source_mic_label"):
            if is_system_audio:
                self._source_mic_label.setStyleSheet(
                    "color: #7f7f7f; font-size: 12px; font-weight: 500;"
                )
            else:
                self._source_mic_label.setStyleSheet(
                    "color: #d0d0d0; font-size: 12px; font-weight: 600;"
                )

        if hasattr(self, "_source_system_label"):
            if is_system_audio:
                self._source_system_label.setStyleSheet(
                    "color: #d0d0d0; font-size: 12px; font-weight: 600;"
                )
            else:
                self._source_system_label.setStyleSheet(
                    "color: #7f7f7f; font-size: 12px; font-weight: 500;"
                )

    def set_recording_source(self, source_type: str) -> None:
        """Force-select the recording source and sync the Client tab UI."""
        if source_type not in {"microphone", "system_audio"}:
            return
        self.config.set("recording", "source_type", value=source_type)
        self.config.save()
        self._sync_audio_source_ui()

    def _on_notebook_toggle(self) -> None:
        """Handle notebook toggle button click."""
        is_enabled = self._notebook_toggle_btn.isChecked()
        self._notebook_toggle_btn.setText("Enabled" if is_enabled else "Disabled")
        self._update_notebook_toggle_style()

        # Save to server config - orchestrator will read this on next startup
        self.config.set_server_config(
            "longform_recording", "auto_add_to_audio_notebook", value=is_enabled
        )

        logger.info(f"Auto-add to notebook: {'enabled' if is_enabled else 'disabled'}")

    def _update_notebook_toggle_style(self) -> None:
        """Update notebook toggle button style based on state and editability."""
        is_checked = self._notebook_toggle_btn.isChecked()
        is_editable = self._notebook_toggle_btn.isEnabled()

        if is_checked:
            # Enabled state - green (or desaturated green if not editable)
            if is_editable:
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #4caf50; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #43a047; }"
                )
            else:
                # Desaturated green when not editable
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #3d5d3d; border: none; border-radius: 4px; "
                    "color: #7a9a7a; padding: 6px 12px; min-width: 70px; }"
                )
        else:
            # Disabled state - red (or desaturated red if not editable)
            if is_editable:
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #e53935; }"
                )
            else:
                # Desaturated red when not editable
                self._notebook_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #5d3d3d; border: none; border-radius: 4px; "
                    "color: #9a7a7a; padding: 6px 12px; min-width: 70px; }"
                )

    def _on_live_transcriber_toggle(self) -> None:
        """Handle Live Mode toggle button click."""
        is_enabled = self._preview_toggle_btn.isChecked()
        self._preview_toggle_btn.setText("Enabled" if is_enabled else "Disabled")
        self._update_live_transcriber_toggle_style()

        # Persist UI state to server config
        self.config.set_server_config("live_transcriber", "enabled", value=is_enabled)

        # Trigger Live Mode start/stop via tray orchestrator
        if not self.tray:
            logger.warning("Live Mode toggle ignored: tray not available")
            return

        if not self._client_running:
            self.set_live_mode_active(False)
            if hasattr(self.tray, "show_notification"):
                self.tray.show_notification(
                    "Live Mode",
                    "Start the client before enabling Live Mode.",
                )
            return

        action = TrayAction.START_LIVE_MODE if is_enabled else TrayAction.STOP_LIVE_MODE
        self.tray._trigger_callback(action)

        logger.info(f"Live Mode: {'enabled' if is_enabled else 'disabled'}")

    def _update_live_transcriber_toggle_style(self) -> None:
        """Update Live Mode toggle button style based on state and editability."""
        is_checked = self._preview_toggle_btn.isChecked()
        is_editable = self._preview_toggle_btn.isEnabled()

        if is_checked:
            # Enabled state - green (or desaturated green if not editable)
            if is_editable:
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #4caf50; border: none; border-radius: 6px; "
                    "color: white; padding: 6px 10px; font-weight: 500; min-width: 70px; "
                    "font-size: 12px; }"
                    "QPushButton:hover { background-color: #43a047; }"
                )
            else:
                # Keep the enabled state visibly green even when not editable
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #388e3c; border: none; border-radius: 6px; "
                    "color: #c8e6c9; padding: 6px 10px; min-width: 70px; font-size: 12px; }"
                )
        else:
            # Disabled state - red (or desaturated red if not editable)
            if is_editable:
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 6px; "
                    "color: white; padding: 6px 10px; font-weight: 500; min-width: 70px; "
                    "font-size: 12px; }"
                    "QPushButton:hover { background-color: #e53935; }"
                )
            else:
                # Desaturated red when not editable
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #5d3d3d; border: none; border-radius: 6px; "
                    "color: #9a7a7a; padding: 6px 10px; min-width: 70px; font-size: 12px; }"
                )

    def _on_live_language_changed(self, index: int) -> None:
        """Handle live mode language selection change."""
        language_code = self._live_language_combo.currentData()

        # Save to server config
        self.config.set_server_config(
            "live_transcriber", "live_language", value=language_code
        )

        language_name = self._live_language_combo.currentText()
        logger.info(f"Live mode language set to: {language_name} ({language_code})")

        # If Live Mode is active, restart to apply language change
        if self.tray and getattr(self.tray, "orchestrator", None):
            orchestrator = self.tray.orchestrator
            if getattr(orchestrator, "is_live_mode_active", False):
                orchestrator.request_live_mode_restart()

    def _on_live_mode_mute_click(self) -> None:
        """Handle Live Mode mute button click."""
        if not self.tray:
            logger.warning("Live Mode mute ignored: tray not available")
            return

        orchestrator = getattr(self.tray, "orchestrator", None)
        if not orchestrator or not getattr(orchestrator, "is_live_mode_active", False):
            if hasattr(self.tray, "show_notification"):
                self.tray.show_notification(
                    "Live Mode",
                    "Live Mode must be running to mute.",
                )
            return

        self.tray._trigger_callback(TrayAction.TOGGLE_LIVE_MUTE)

    def set_live_mode_active(self, active: bool) -> None:
        """Sync the Live Mode toggle UI with the actual runtime state."""
        if not hasattr(self, "_preview_toggle_btn"):
            return
        self._preview_toggle_btn.blockSignals(True)
        self._preview_toggle_btn.setChecked(active)
        self._preview_toggle_btn.setText("Enabled" if active else "Disabled")
        self._preview_toggle_btn.blockSignals(False)
        self._update_live_transcriber_toggle_style()
        self.config.set_server_config("live_transcriber", "enabled", value=active)
        if hasattr(self, "_live_mode_mute_btn"):
            self._live_mode_mute_btn.setEnabled(active)

    def _toggle_live_preview_collapse(self) -> None:
        """Toggle the live preview section collapse state."""
        is_visible = self._preview_content.isVisible()
        self._preview_content.setVisible(not is_visible)
        self._preview_collapse_btn.setText("\u25b6" if is_visible else "\u25bc")

    def _copy_and_clear_live_preview(self) -> None:
        """Copy live preview content to clipboard and clear it."""
        from PyQt6.QtWidgets import QApplication

        text = self._live_transcription_text_edit.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self._live_transcription_text_edit.clear()
            self._live_transcription_history.clear()
            logger.debug("Live preview copied to clipboard and cleared")

    def update_live_transcription_text(self, text: str, append: bool = False) -> None:
        """
        Update live transcription text display.

        Args:
            text: The text to display
            append: If True, append to history. If False, replace current line.
        """
        if not hasattr(self, "_live_transcription_text_edit"):
            return

        if not text:
            self._live_transcription_text_edit.setPlainText("")
            return

        if append:
            # Append text as a new line in history
            self._live_transcription_history.append(text)
            # Keep only last 1000 lines to prevent memory bloat
            if len(self._live_transcription_history) > 1000:
                self._live_transcription_history = self._live_transcription_history[
                    -1000:
                ]
            display_text = " ".join(self._live_transcription_history)
        else:
            # Real-time update: show history + current partial text
            if self._live_transcription_history:
                display_text = " ".join(self._live_transcription_history) + " " + text
            else:
                display_text = text

        self._live_transcription_text_edit.setPlainText(display_text)

        # Auto-scroll to bottom
        scrollbar = self._live_transcription_text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
