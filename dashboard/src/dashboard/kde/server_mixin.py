"""
Server control mixin for the Dashboard.

This module contains server-related methods for the DashboardWindow class,
extracted to keep the main dashboard.py file smaller and more maintainable.
"""

import logging
import re
import threading
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QCheckBox, QMessageBox

from dashboard.common.docker_manager import DockerResult, ServerMode, ServerStatus

if TYPE_CHECKING:
    from dashboard.common.docker_manager import DockerPullWorker, DockerServerWorker

logger = logging.getLogger(__name__)


class ServerControlMixin:
    """
    Mixin class providing server control functionality for DashboardWindow.

    This mixin provides all server-related methods including:
    - Server status refresh and display
    - Server start/stop operations
    - Container and image management
    - Volume management
    - Docker pull operations
    - Server log display
    """

    MODEL_CHOICES: list[tuple[str, str]] = [
        ("Systran Faster Whisper Large v3", "Systran/faster-whisper-large-v3"),
        ("Systran Faster Whisper Medium", "Systran/faster-whisper-medium"),
    ]
    MODEL_CUSTOM_VALUE = "__custom__"
    MODEL_SAME_AS_MAIN_VALUE = "__same_as_main__"

    # =========================================================================
    # Server Status
    # =========================================================================

    def _refresh_server_status(self) -> None:
        """Refresh the server status display."""
        # Check image (using Web UI colors)
        if self._docker_manager.image_exists_locally():
            self._image_status_label.setText("✓ Available")
            self._image_status_label.setStyleSheet("color: #4caf50;")  # success

            # Get image date (inline, smaller)
            image_date = self._docker_manager.get_image_created_date()
            if image_date:
                self._image_date_label.setText(f"({image_date})")
            else:
                self._image_date_label.setText("")

            # Get image size (inline, smaller)
            image_size = self._docker_manager.get_image_size()
            if image_size:
                self._image_size_label.setText(f"{image_size}")
            else:
                self._image_size_label.setText("")
        else:
            self._image_status_label.setText("✗ Not found")
            self._image_status_label.setStyleSheet("color: #f44336;")  # error
            self._image_date_label.setText("")
            self._image_size_label.setText("")

        # Check server status
        status = self._docker_manager.get_server_status()
        mode = self._docker_manager.get_current_mode()

        health: str | None = None
        mode_str = f" ({mode.value})" if mode else ""

        if status == ServerStatus.RUNNING:
            health = self._docker_manager.get_container_health()
            if health and health != "healthy":
                if health == "unhealthy":
                    status_text = f"Unhealthy{mode_str}"
                    self._server_status_label.setStyleSheet("color: #f44336;")
                else:
                    status_text = f"Starting...{mode_str}"
                    self._server_status_label.setStyleSheet("color: #2196f3;")
            else:
                status_text = f"Running{mode_str}"
                self._server_status_label.setStyleSheet("color: #4caf50;")
        elif status == ServerStatus.STOPPED:
            status_text = "Stopped"
            self._server_status_label.setStyleSheet("color: #ff9800;")
        elif status == ServerStatus.NOT_FOUND:
            status_text = "Not set up"
            self._server_status_label.setStyleSheet("color: #6c757d;")
        elif status == ServerStatus.ERROR:
            status_text = "Error"
            self._server_status_label.setStyleSheet("color: #f44336;")
        else:
            status_text = "Unknown"
            self._server_status_label.setStyleSheet("color: #f44336;")

        self._server_status_label.setText(status_text)

        # Update auth token display - always check logs when running to catch new tokens
        if status == ServerStatus.RUNNING:
            # Force check logs for latest token (clears cache first)
            logs = self._docker_manager.get_logs(lines=1000)
            new_token = None
            for line in logs.split("\n"):
                if "Admin Token:" in line:
                    match = re.search(r"Admin Token:\s*(\S+)", line)
                    if match:
                        new_token = match.group(1)
                        # Update cache if token changed
                        if new_token != self._docker_manager._cached_auth_token:
                            self._docker_manager._cached_auth_token = new_token
                            self._docker_manager.save_server_auth_token(new_token)
                            logger.info("Detected new admin token from logs")

            # Display the token (either new or cached)
            token = new_token or self._docker_manager.get_admin_token(check_logs=False)
        else:
            # When not running, just use cached token
            token = self._docker_manager.get_admin_token(check_logs=False)

        if token:
            self._server_token_field.setText(token)
            self._server_token_field.setStyleSheet(
                "background: transparent; border: none; color: #4caf50;"
            )  # success
        else:
            self._server_token_field.setText("Not saved yet")
            self._server_token_field.setStyleSheet(
                "background: transparent; border: none; color: #6c757d;"
            )

        # Update button states
        is_running = status == ServerStatus.RUNNING
        container_exists = status in (ServerStatus.RUNNING, ServerStatus.STOPPED)
        image_exists = self._docker_manager.image_exists_locally()

        self._start_local_btn.setEnabled(not is_running)
        self._start_remote_btn.setEnabled(not is_running)
        self._stop_server_btn.setEnabled(is_running)
        self._remove_container_btn.setEnabled(container_exists and not is_running)

        # Docker management buttons with tooltips
        self._remove_image_btn.setEnabled(not container_exists and image_exists)
        if container_exists:
            self._remove_image_btn.setToolTip(
                "Remove container first before removing image"
            )
        else:
            self._remove_image_btn.setToolTip("Remove the Docker image")

        if is_running:
            self._remove_container_btn.setToolTip(
                "Stop container first before removing"
            )
        else:
            self._remove_container_btn.setToolTip("Remove the Docker container")

        self._pull_image_btn.setEnabled(True)  # Can always pull
        self._remove_data_volume_btn.setEnabled(not is_running)
        self._remove_models_volume_btn.setEnabled(not is_running)

        if self._server_health_timer:
            if status != ServerStatus.RUNNING or health in (None, "healthy"):
                self._server_health_timer.stop()
                self._server_health_timer = None

        # Update models button state when server status changes
        self._update_models_button_state()

        # Update volumes status
        data_volume_exists = self._docker_manager.volume_exists(
            "transcriptionsuite-data"
        )
        models_volume_exists = self._docker_manager.volume_exists(
            "transcriptionsuite-models"
        )

        if data_volume_exists:
            self._data_volume_status.setText("✓ Exists")
            self._data_volume_status.setStyleSheet("color: #4caf50;")  # success
            # Get volume size
            size = self._docker_manager.get_volume_size("transcriptionsuite-data")
            if size:
                self._data_volume_size.setText(f"({size})")
            else:
                self._data_volume_size.setText("")
        else:
            self._data_volume_status.setText("✗ Not found")
            self._data_volume_status.setStyleSheet("color: #6c757d;")
            self._data_volume_size.setText("")

        if models_volume_exists:
            self._models_volume_status.setText("✓ Exists")
            self._models_volume_status.setStyleSheet("color: #4caf50;")  # success
            # Get volume size
            size = self._docker_manager.get_volume_size("transcriptionsuite-models")
            if size:
                self._models_volume_size.setText(f"({size})")
            else:
                self._models_volume_size.setText("")

            # Update models list (only when container is running)
            if is_running:
                models = self._docker_manager.list_downloaded_models()
                if models:
                    models_lines = [f"  • {m['name']} ({m['size']})" for m in models]
                    models_text = "Downloaded:\n" + "\n".join(models_lines)
                    self._models_list_label.setText(models_text)
                    self._models_list_label.setVisible(True)
                else:
                    self._models_list_label.setText("No models downloaded yet")
                    self._models_list_label.setVisible(True)
            else:
                self._models_list_label.setText("Start container to view models")
                self._models_list_label.setVisible(True)
        else:
            self._models_volume_status.setText("✗ Not found")
            self._models_volume_status.setStyleSheet("color: #6c757d;")
            self._models_volume_size.setText("")
            self._models_list_label.setVisible(False)

    # =========================================================================
    # Model Selection
    # =========================================================================

    def _init_model_selectors(self) -> None:
        """Populate model selectors and apply current config."""
        if not hasattr(self, "_main_model_combo") or not hasattr(
            self, "_live_model_combo"
        ):
            return

        self._main_model_combo.blockSignals(True)
        self._main_model_combo.clear()
        for label, value in self.MODEL_CHOICES:
            self._main_model_combo.addItem(label, value)
        self._main_model_combo.addItem("Custom...", self.MODEL_CUSTOM_VALUE)
        self._main_model_combo.blockSignals(False)

        self._live_model_combo.blockSignals(True)
        self._live_model_combo.clear()
        self._live_model_combo.addItem(
            "Same as Main Transcriber", self.MODEL_SAME_AS_MAIN_VALUE
        )
        for label, value in self.MODEL_CHOICES:
            self._live_model_combo.addItem(label, value)
        self._live_model_combo.addItem("Custom...", self.MODEL_CUSTOM_VALUE)
        self._live_model_combo.blockSignals(False)

        self._apply_model_selector_state()

    def _apply_model_selector_state(self) -> None:
        """Sync model selectors with current config."""
        if not hasattr(self, "_main_model_combo") or not hasattr(
            self, "_live_model_combo"
        ):
            return

        main_model = self.config.get_server_config(
            "main_transcriber",
            "model",
            default="Systran/faster-whisper-large-v3",
        )
        self._set_model_combo(
            self._main_model_combo,
            self._main_model_custom,
            main_model,
            allow_same_as_main=False,
        )

        live_model = self.config.get_server_config(
            "live_transcriber", "model", default=None
        )
        if live_model in (None, ""):
            self._set_model_combo(
                self._live_model_combo,
                self._live_model_custom,
                self.MODEL_SAME_AS_MAIN_VALUE,
                allow_same_as_main=True,
            )
        else:
            self._set_model_combo(
                self._live_model_combo,
                self._live_model_custom,
                live_model,
                allow_same_as_main=True,
            )

        if hasattr(self, "_refresh_translation_capabilities"):
            self._refresh_translation_capabilities()

    def _set_model_combo(
        self,
        combo,
        custom_input,
        model_value: str | None,
        *,
        allow_same_as_main: bool,
    ) -> None:
        """Select the appropriate combo item and toggle custom input."""
        combo.blockSignals(True)
        custom_input.blockSignals(True)

        target = model_value or ""
        matched_index = -1
        for i in range(combo.count()):
            if combo.itemData(i) == target:
                matched_index = i
                break

        if matched_index != -1:
            combo.setCurrentIndex(matched_index)
            custom_input.setVisible(False)
        else:
            if allow_same_as_main and target == self.MODEL_SAME_AS_MAIN_VALUE:
                combo.setCurrentIndex(combo.findData(self.MODEL_SAME_AS_MAIN_VALUE))
                custom_input.setVisible(False)
            else:
                combo.setCurrentIndex(combo.findData(self.MODEL_CUSTOM_VALUE))
                custom_input.setText(target)
                custom_input.setVisible(True)

        combo.blockSignals(False)
        custom_input.blockSignals(False)

    def _on_main_model_selection_changed(self, index: int) -> None:
        """Handle main transcriber model selection."""
        if not hasattr(self, "_main_model_combo"):
            return
        selected = self._main_model_combo.currentData()
        if selected == self.MODEL_CUSTOM_VALUE:
            self._main_model_custom.setVisible(True)
            custom_value = self._main_model_custom.text().strip()
            if custom_value:
                self.config.set_server_config(
                    "main_transcriber", "model", value=custom_value
                )
        else:
            self._main_model_custom.setVisible(False)
            self.config.set_server_config("main_transcriber", "model", value=selected)
        if hasattr(self, "_refresh_translation_capabilities"):
            self._refresh_translation_capabilities()

    def _on_live_model_selection_changed(self, index: int) -> None:
        """Handle Live Mode model selection."""
        if not hasattr(self, "_live_model_combo"):
            return
        selected = self._live_model_combo.currentData()
        if selected == self.MODEL_SAME_AS_MAIN_VALUE:
            self._live_model_custom.setVisible(False)
            self.config.set_server_config("live_transcriber", "model", value=None)
        elif selected == self.MODEL_CUSTOM_VALUE:
            self._live_model_custom.setVisible(True)
            custom_value = self._live_model_custom.text().strip()
            if custom_value:
                self.config.set_server_config(
                    "live_transcriber", "model", value=custom_value
                )
        else:
            self._live_model_custom.setVisible(False)
            self.config.set_server_config("live_transcriber", "model", value=selected)
        if hasattr(self, "_refresh_translation_capabilities"):
            self._refresh_translation_capabilities()

    def _on_main_model_custom_changed(self) -> None:
        """Handle custom main transcriber model input."""
        if not hasattr(self, "_main_model_combo"):
            return
        if self._main_model_combo.currentData() != self.MODEL_CUSTOM_VALUE:
            return
        custom_value = self._main_model_custom.text().strip()
        if custom_value:
            self.config.set_server_config(
                "main_transcriber", "model", value=custom_value
            )
        if hasattr(self, "_refresh_translation_capabilities"):
            self._refresh_translation_capabilities()

    def _on_live_model_custom_changed(self) -> None:
        """Handle custom Live Mode model input."""
        if not hasattr(self, "_live_model_combo"):
            return
        if self._live_model_combo.currentData() != self.MODEL_CUSTOM_VALUE:
            return
        custom_value = self._live_model_custom.text().strip()
        if custom_value:
            self.config.set_server_config(
                "live_transcriber", "model", value=custom_value
            )
        if hasattr(self, "_refresh_translation_capabilities"):
            self._refresh_translation_capabilities()

    def _populate_image_selector(self) -> None:
        """Populate the image selector dropdown with available local images."""
        self._image_selector.blockSignals(True)
        self._image_selector.clear()

        # Add "Most Recent (auto)" as first option
        self._image_selector.addItem("Most Recent (auto)", "auto")

        # Get list of local images
        images = self._docker_manager.list_local_images()

        for img in images:
            display_text = img.display_name()
            self._image_selector.addItem(display_text, img.tag)

        self._image_selector.blockSignals(False)

        # If no images found, show a placeholder message
        if not images:
            self._image_selector.setToolTip(
                "No local images found.\n"
                "Use 'Fetch Fresh' to pull the latest image from the registry."
            )

    def _on_image_selection_changed(self, index: int) -> None:
        """Handle image selection change."""
        tag = self._image_selector.currentData()
        if tag == "auto":
            logger.debug("Image selection: auto (most recent)")
        else:
            logger.debug(f"Image selection: {tag}")

    def _get_selected_image_tag(self) -> str:
        """Get the currently selected image tag."""
        tag = self._image_selector.currentData()
        return tag if tag else "auto"

    # =========================================================================
    # Server Start/Stop
    # =========================================================================

    def _on_start_server_local(self) -> None:
        """Start server in local mode."""
        self._start_server(ServerMode.LOCAL)

    def _on_start_server_remote(self) -> None:
        """Start server in remote mode."""
        self._start_server(ServerMode.REMOTE)

    def _start_server(self, mode: ServerMode) -> None:
        """Start the Docker server asynchronously."""
        # Check if a server start is already in progress
        if self._server_worker is not None and self._server_worker.is_alive():
            logger.warning("Server start already in progress")
            return

        if self._server_health_timer:
            self._server_health_timer.stop()
            self._server_health_timer = None

        self._server_status_label.setText("Starting...")
        self._start_local_btn.setEnabled(False)
        self._start_remote_btn.setEnabled(False)

        # Get selected image from dropdown
        image_selection = self._get_selected_image_tag()

        # Define callbacks that emit signals for thread-safe UI updates
        def on_progress(msg: str) -> None:
            """Called from worker thread - emit signal for thread-safe UI update."""
            self._server_start_progress_signal.emit(msg)

        def on_complete(result: DockerResult) -> None:
            """Called from worker thread - emit signal for thread-safe UI update."""
            self._server_start_complete_signal.emit(result)

        # Start the server asynchronously
        result = self._docker_manager.start_server_async(
            mode=mode,
            progress_callback=on_progress,
            complete_callback=on_complete,
            image_selection=image_selection,
        )

        # Check if pre-flight validation failed (returns DockerResult instead of worker)
        if isinstance(result, DockerResult):
            # Validation failed - handle synchronously
            self._server_start_progress_signal.emit(f"Error: {result.message}")
            self._on_server_start_complete(result)
        else:
            # Got a worker - store reference
            self._server_worker = result

    def _update_server_start_progress(self, msg: str) -> None:
        """Update UI with server start progress (called on main thread via signal)."""
        logger.info(msg)
        if self._show_server_logs_btn.isChecked():
            self._server_log_view.appendPlainText(msg)

    def _on_server_start_complete(self, result: DockerResult) -> None:
        """Handle server start completion (called on main thread via signal)."""
        self._server_worker = None

        if result.success:
            self._update_server_start_progress(result.message)
            # Force refresh token from logs for new/restarted container
            QTimer.singleShot(2000, self._docker_manager.refresh_admin_token)
            self._refresh_server_status()

            self._server_health_timer = QTimer(self)
            self._server_health_timer.timeout.connect(self._refresh_server_status)
            self._server_health_timer.start(1500)

            # Update notebook API client when server starts
            # (user may use notebook without explicitly starting client)
            QTimer.singleShot(2000, self._update_notebook_api_client)
        else:
            self._update_server_start_progress(f"Error: {result.message}")
            QTimer.singleShot(1000, self._refresh_server_status)

        # Re-enable buttons
        self._start_local_btn.setEnabled(True)
        self._start_remote_btn.setEnabled(True)

    def _on_stop_server(self) -> None:
        """Stop the Docker server."""
        if self._server_health_timer:
            self._server_health_timer.stop()
            self._server_health_timer = None

        self._server_status_label.setText("Stopping...")
        self._stop_server_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.stop_server(progress_callback=progress)

        if result.success:
            progress(result.message)
            # Clear server logs window when server is stopped
            if self._server_log_window is not None:
                self._server_log_window.clear_logs()
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    # =========================================================================
    # Container Management
    # =========================================================================

    def _on_remove_container(self) -> None:
        """Remove the Docker container (for recreating from fresh image)."""
        if self._server_health_timer:
            self._server_health_timer.stop()
            self._server_health_timer = None

        # Confirm with user
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Container")
        msg_box.setText("Are you sure you want to remove the container?")
        msg_box.setInformativeText(
            "This will delete the container and its data. "
            "The Docker image will be kept. You can recreate the container by starting the server again."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._server_status_label.setText("Removing...")
        self._remove_container_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_container(progress_callback=progress)

        if result.success:
            progress(result.message)
            # Clear server logs window when container is removed
            if self._server_log_window is not None:
                self._server_log_window.clear_logs()
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    # =========================================================================
    # Image Management
    # =========================================================================

    def _on_remove_image(self) -> None:
        """Remove the Docker server image."""
        # Confirm with user
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Docker Image")
        msg_box.setText("Are you sure you want to remove the Docker image?")
        msg_box.setInformativeText(
            "This will delete the server Docker image from your system. "
            "The container must be removed first. "
            "You can re-download the image using 'Fetch Fresh Image'."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._image_status_label.setText("Removing...")
        self._remove_image_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_image(progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_pull_fresh_image(self) -> None:
        """Pull a fresh copy of the Docker server image (async, non-blocking)."""
        # Prevent starting another pull if one is already in progress
        if self._pull_worker is not None and self._pull_worker.is_alive():
            logger.warning("Docker pull already in progress")
            return

        # Inform user this may take time
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Fetch Fresh Image")
        msg_box.setText("Pull a fresh copy of the Docker image?")
        msg_box.setInformativeText(
            "This will download the latest server image (~17GB). "
            "This may take several minutes to hours depending on your connection speed.\n\n"
            "The download runs in the background - you can continue using the app."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        msg_box.setIcon(QMessageBox.Icon.Information)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        # Update UI for pull in progress
        self._image_status_label.setText("Pulling...")
        self._pull_image_btn.setEnabled(False)
        self._pull_cancel_btn.setVisible(True)

        def on_progress(msg: str) -> None:
            """Called from worker thread - emit signal for thread-safe UI update."""
            self._pull_progress_signal.emit(msg)

        def on_complete(result: DockerResult) -> None:
            """Called from worker thread - emit signal for thread-safe UI update."""
            logger.debug(f"Emitting pull complete signal: {result.message}")
            self._pull_complete_signal.emit(result)

        # Start async pull
        self._pull_worker = self._docker_manager.start_pull_worker(
            progress_callback=on_progress,
            complete_callback=on_complete,
        )
        logger.info("Started async Docker image pull")

    def _update_pull_progress(self, msg: str) -> None:
        """Update UI with pull progress (called on main thread)."""
        logger.info(msg)
        # Update status label with latest message
        self._image_status_label.setText(f"Pulling: {msg[:50]}...")

    def _on_pull_complete(self, result: DockerResult) -> None:
        """Handle pull completion (called on main thread)."""
        logger.info(
            f"Pull complete callback: success={result.success}, message={result.message}"
        )
        self._pull_worker = None

        # Reset UI state - ALWAYS do this regardless of result
        self._pull_image_btn.setEnabled(True)
        self._pull_cancel_btn.setVisible(False)
        self._pull_cancel_btn.setEnabled(True)  # Re-enable for next time

        if result.success:
            self._image_status_label.setText("Pull complete!")
            logger.info("Docker image pull completed successfully")
        else:
            # Show more specific message for cancellation
            if "cancelled" in result.message.lower():
                self._image_status_label.setText("Pull cancelled")
                logger.info(f"Docker image pull cancelled: {result.message}")
            else:
                self._image_status_label.setText("Pull failed")
                logger.error(f"Docker image pull failed: {result.message}")

        # Refresh status to update image info
        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_cancel_pull(self) -> None:
        """Cancel the in-progress Docker pull."""
        if self._pull_worker is not None:
            logger.info("User requested to cancel Docker pull")
            self._image_status_label.setText("Cancelling...")
            self._pull_cancel_btn.setEnabled(False)

            # Cancel in a separate thread to avoid blocking UI if it takes time
            def cancel_worker():
                try:
                    if self._pull_worker:
                        self._pull_worker.cancel()
                        # Wait for worker thread to finish (with timeout)
                        self._pull_worker.join(timeout=10)
                        if self._pull_worker.is_alive():
                            logger.warning(
                                "Docker pull worker still alive after cancel"
                            )
                        else:
                            logger.info("Docker pull worker terminated successfully")
                except Exception as e:
                    logger.error(f"Error during cancel: {e}")

            cancel_thread = threading.Thread(target=cancel_worker, daemon=True)
            cancel_thread.start()

    # =========================================================================
    # Volume Management
    # =========================================================================

    def _on_remove_data_volume(self) -> None:
        """Remove the data volume."""
        # Check if container exists first
        status = self._docker_manager.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Cannot Remove Volume")
            msg_box.setText("Container must be removed first")
            msg_box.setInformativeText(
                "Docker volumes cannot be removed while the container exists.\n\n"
                "Please remove the container first, then try removing the volume again."
            )
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()
            return

        # Confirm with user - this is destructive!
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Data Volume")
        msg_box.setText("WARNING: This will DELETE ALL SERVER DATA!")
        msg_box.setInformativeText(
            "This will permanently delete:\n"
            "• The SQLite database\n"
            "• All user data and transcription history\n"
            "• Server authentication token\n\n"
            "This action cannot be undone!"
        )

        # Add checkbox for also removing config directory
        config_checkbox = QCheckBox("Also remove config directory")
        config_checkbox.setToolTip(
            f"Remove {self._docker_manager.config_dir}\n"
            "(contains dashboard.yaml, docker-compose.yml, etc.)"
        )
        msg_box.setCheckBox(config_checkbox)

        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Critical)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        also_remove_config = config_checkbox.isChecked()
        self._remove_data_volume_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_data_volume(
            progress_callback=progress,
            also_remove_config=also_remove_config,
        )

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    def _on_remove_models_volume(self) -> None:
        """Remove the models volume."""
        # Check if container exists first
        status = self._docker_manager.get_server_status()
        if status != ServerStatus.NOT_FOUND:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Cannot Remove Volume")
            msg_box.setText("Container must be removed first")
            msg_box.setInformativeText(
                "Docker volumes cannot be removed while the container exists.\n\n"
                "Please remove the container first, then try removing the volume again."
            )
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()
            return

        # Confirm with user
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Models Volume")
        msg_box.setText("WARNING: This will DELETE ALL DOWNLOADED MODELS!")
        msg_box.setInformativeText(
            "This will permanently delete all downloaded Whisper models. "
            "Models will need to be re-downloaded when needed (may take time)."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._remove_models_volume_btn.setEnabled(False)

        def progress(msg: str) -> None:
            logger.info(msg)
            if self._show_server_logs_btn.isChecked():
                self._server_log_view.appendPlainText(msg)

        result = self._docker_manager.remove_models_volume(progress_callback=progress)

        if result.success:
            progress(result.message)
        else:
            progress(f"Error: {result.message}")

        QTimer.singleShot(1000, self._refresh_server_status)

    # =========================================================================
    # Server Logs
    # =========================================================================

    def _toggle_server_logs(self) -> None:
        """Open server logs in a separate window."""
        from dashboard.kde.log_window import LogWindow

        if self._server_log_window is None:
            self._server_log_window = LogWindow("Server Logs", self)

        # Start log polling if not already running
        if self._server_log_timer is None:
            self._refresh_server_logs()
            self._server_log_timer = QTimer()
            self._server_log_timer.timeout.connect(self._refresh_server_logs)
            self._server_log_timer.start(3000)  # Poll every 3 seconds

        self._server_log_window.show()
        self._server_log_window.raise_()
        self._server_log_window.activateWindow()

    def _refresh_server_logs(self) -> None:
        """Refresh server logs."""
        if self._server_log_window is None:
            return
        logs = self._docker_manager.get_logs(lines=300)
        self._server_log_window.set_logs(logs)
