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

from dashboard.common.docker_manager import ServerStatus

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
            self._client_status_label.setStyleSheet("color: #4caf50;")  # success

            # Show connection info
            host = self.config.server_host
            port = self.config.server_port
            https = "HTTPS" if self.config.use_https else "HTTP"
            self._connection_info_label.setText(f"{https}://{host}:{port}")
        else:
            self._client_status_label.setText("Stopped")
            self._client_status_label.setStyleSheet("color: #ff9800;")  # warning
            self._connection_info_label.setText("Not connected")

        # Update button states
        self._start_client_local_btn.setEnabled(not self._client_running)
        self._start_client_remote_btn.setEnabled(not self._client_running)
        self._stop_client_btn.setEnabled(self._client_running)

        # Notebook toggle only allowed when both server and client are stopped
        # (setting takes effect on next client start)
        server_status = self._docker_manager.get_server_status()
        server_stopped = server_status != ServerStatus.RUNNING
        self._notebook_toggle_btn.setEnabled(
            not self._client_running and server_stopped
        )
        self._update_notebook_toggle_style()

        # Update models button based on server health
        self._update_models_button_state()

    def _update_models_button_state(self) -> None:
        """Update the models button state based on server health and connection type."""
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
                # Light blue (models loaded, ready to unload) - color 2
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #90caf9; border: none; border-radius: 6px; color: #121212; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #42a5f5; }"
                )
            else:
                # Red (models unloaded, ready to reload) - color 3
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
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
                # Light blue background (models loaded) - color 2
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #90caf9; border: none; border-radius: 6px; color: #121212; padding: 10px 20px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #42a5f5; }"
                )
            else:
                self._unload_models_btn.setText("Reload Models")
                self._unload_models_btn.setToolTip(
                    "Reload transcription models for use"
                )
                # Red background (models unloaded) - color 3
                self._unload_models_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
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
        tls_verify = self.config.get("server", "tls_verify", default=True)

        if not host:
            self._show_notification("Error", "No server host configured")
            return

        # Create temporary API client for this operation
        api_client = APIClient(
            host=host,
            port=port,
            use_https=use_https,
            token=token if token else None,
            tls_verify=tls_verify,
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
                    # Light blue background (models loaded) - color 2
                    self._unload_models_btn.setStyleSheet(
                        "QPushButton { background-color: #90caf9; border: none; border-radius: 6px; color: #121212; padding: 10px 20px; font-weight: 500; }"
                        "QPushButton:hover { background-color: #42a5f5; }"
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
                        "QPushButton { background-color: #f44336; border: none; border-radius: 6px; color: white; padding: 10px 20px; font-weight: 500; }"
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
        """Handle live transcriber toggle button click."""
        is_enabled = self._preview_toggle_btn.isChecked()
        self._preview_toggle_btn.setText("Enabled" if is_enabled else "Disabled")
        self._update_live_transcriber_toggle_style()

        # Save to server config - requires server restart to take effect
        self.config.set_server_config(
            "transcription_options", "enable_live_transcriber", value=is_enabled
        )

        logger.info(f"Live transcriber: {'enabled' if is_enabled else 'disabled'}")

    def _update_live_transcriber_toggle_style(self) -> None:
        """Update live transcriber toggle button style based on state and editability."""
        is_checked = self._preview_toggle_btn.isChecked()
        is_editable = self._preview_toggle_btn.isEnabled()

        if is_checked:
            # Enabled state - green (or desaturated green if not editable)
            if is_editable:
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #4caf50; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #43a047; }"
                )
            else:
                # Desaturated green when not editable
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #3d5d3d; border: none; border-radius: 4px; "
                    "color: #7a9a7a; padding: 6px 12px; min-width: 70px; }"
                )
        else:
            # Disabled state - red (or desaturated red if not editable)
            if is_editable:
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; border: none; border-radius: 4px; "
                    "color: white; padding: 6px 12px; font-weight: 500; min-width: 70px; }"
                    "QPushButton:hover { background-color: #e53935; }"
                )
            else:
                # Desaturated red when not editable
                self._preview_toggle_btn.setStyleSheet(
                    "QPushButton { background-color: #5d3d3d; border: none; border-radius: 4px; "
                    "color: #9a7a7a; padding: 6px 12px; min-width: 70px; }"
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
