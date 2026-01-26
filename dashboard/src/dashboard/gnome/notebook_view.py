"""
Audio Notebook view for GNOME Dashboard.

Provides a tabbed interface with Calendar, Search, and Import sub-tabs
for managing audio recordings and transcriptions.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    HAS_GTK4 = True
except (ImportError, ValueError):
    HAS_GTK4 = False
    Gtk = None
    Adw = None
    GLib = None

if TYPE_CHECKING:
    from dashboard.common.api_client import APIClient

logger = logging.getLogger(__name__)


class NotebookView:
    """
    Main Audio Notebook view with tabbed interface for GNOME.

    Contains three sub-tabs:
    - Calendar: Browse recordings by date
    - Search: Full-text search across transcriptions
    - Import: Upload and transcribe audio files
    """

    def __init__(self, api_client: "APIClient | None"):
        if not HAS_GTK4:
            raise ImportError("GTK4 is required for NotebookView")

        self._api_client = api_client

        # Callbacks for recording requests
        self._recording_requested_callback: Any = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the notebook view UI."""
        # Main container
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header section
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.add_css_class("notebook-header")
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(15)
        header.set_margin_bottom(15)

        title = Gtk.Label(label="Audio Notebook")
        title.add_css_class("view-title")
        header.append(title)

        self.widget.append(header)

        # Tab widget (Gtk.Notebook)
        self._notebook = Gtk.Notebook()
        self._notebook.set_vexpand(True)
        self._notebook.add_css_class("notebook-tabs")

        # Create sub-tab widgets
        from dashboard.gnome.calendar_widget import CalendarWidget
        from dashboard.gnome.import_widget import ImportWidget
        from dashboard.gnome.search_widget import SearchWidget

        self._calendar_widget = CalendarWidget(self._api_client)
        self._search_widget = SearchWidget(self._api_client)
        self._import_widget = ImportWidget(self._api_client)

        # Add tabs
        calendar_label = Gtk.Label(label="Calendar")
        self._notebook.append_page(self._calendar_widget.widget, calendar_label)

        search_label = Gtk.Label(label="Search")
        self._notebook.append_page(self._search_widget.widget, search_label)

        import_label = Gtk.Label(label="Import")
        self._notebook.append_page(self._import_widget.widget, import_label)

        # Connect signals
        self._calendar_widget.set_recording_callback(self._on_recording_requested)
        self._calendar_widget.set_delete_callback(self._on_delete_requested)
        self._calendar_widget.set_change_date_callback(self._on_change_date_requested)
        self._calendar_widget.set_export_callback(self._on_export_requested)
        self._search_widget.set_recording_callback(self._on_recording_requested)
        self._import_widget.set_recording_created_callback(self._on_import_complete)

        self.widget.append(self._notebook)

        # Apply styling
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .notebook-header {
                background-color: #1e1e1e;
                border-bottom: 1px solid #2d2d2d;
            }

            .view-title {
                color: #ffffff;
                font-size: 22px;
                font-weight: bold;
            }

            .notebook-tabs tab {
                background-color: #1e1e1e;
                color: #a0a0a0;
                padding: 10px 20px;
                border: none;
                border-bottom: 2px solid transparent;
            }

            .notebook-tabs tab:checked {
                color: #90caf9;
                border-bottom: 2px solid #90caf9;
            }

            .notebook-tabs tab:hover:not(:checked) {
                color: #ffffff;
                background-color: #2d2d2d;
            }
        """)

        Gtk.StyleContext.add_provider_for_display(
            self.widget.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_recording_requested(self, recording_id: int) -> None:
        """Handle request to open a recording."""
        logger.debug(f"Recording requested: {recording_id}")
        if self._recording_requested_callback:
            self._recording_requested_callback(recording_id)

    def _on_import_complete(self, recording_id: int) -> None:
        """Handle import completion - refresh calendar (don't auto-open)."""
        logger.info(f"Import complete, recording ID: {recording_id}")
        # Refresh calendar to show new recording
        self._calendar_widget.refresh()
        # Don't auto-open the recording - let user review queue first

    def _on_delete_requested(self, recording_id: int) -> None:
        """Handle delete request from calendar."""
        dialog = Adw.MessageDialog(
            heading="Delete Recording",
            body="Are you sure you want to delete this recording?\n\nThis action cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(dialog, response):
            if response == "delete":
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self._delete_recording(recording_id))
                    else:
                        asyncio.run(self._delete_recording(recording_id))
                except RuntimeError:
                    pass
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    async def _delete_recording(self, recording_id: int) -> None:
        """Delete a recording and refresh the view."""
        try:
            await self._api_client.delete_recording(recording_id)
            logger.info(f"Deleted recording {recording_id}")
            GLib.idle_add(self._calendar_widget.refresh)
        except Exception as e:
            logger.error(f"Failed to delete recording: {e}")
            GLib.idle_add(
                lambda: self._show_error_dialog(f"Failed to delete recording: {e}")
            )

    def _on_change_date_requested(self, recording_id: int) -> None:
        """Handle change date request from calendar."""
        dialog = Gtk.Window(title="Change Date & Time")
        dialog.set_default_size(350, 200)
        dialog.set_modal(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)

        label = Gtk.Label(label="Select new date and time:")
        label.set_xalign(0)
        main_box.append(label)

        # Date and time entry (simplified - using entry fields)
        datetime_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        date_entry = Gtk.Entry()
        date_entry.set_placeholder_text("YYYY-MM-DD")
        date_entry.set_text(datetime.now().strftime("%Y-%m-%d"))
        date_entry.set_hexpand(True)
        datetime_box.append(date_entry)

        time_entry = Gtk.Entry()
        time_entry.set_placeholder_text("HH:MM")
        time_entry.set_text(datetime.now().strftime("%H:%M"))
        time_entry.set_max_width_chars(6)
        datetime_box.append(time_entry)

        main_box.append(datetime_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        main_box.append(spacer)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("secondary-button")
        cancel_btn.connect("clicked", lambda _: dialog.close())
        button_box.append(cancel_btn)

        spacer2 = Gtk.Box()
        spacer2.set_hexpand(True)
        button_box.append(spacer2)

        ok_btn = Gtk.Button(label="OK")
        ok_btn.add_css_class("primary-button")

        def on_ok_clicked(_):
            date_str = date_entry.get_text().strip()
            time_str = time_entry.get_text().strip()
            try:
                new_datetime = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                )
                new_datetime_iso = new_datetime.isoformat()
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(
                            self._update_recording_date(recording_id, new_datetime_iso)
                        )
                    else:
                        asyncio.run(
                            self._update_recording_date(recording_id, new_datetime_iso)
                        )
                except RuntimeError:
                    pass
                dialog.close()
            except ValueError as e:
                logger.error(f"Invalid date/time format: {e}")

        ok_btn.connect("clicked", on_ok_clicked)
        button_box.append(ok_btn)

        main_box.append(button_box)
        dialog.set_child(main_box)

        # Apply styles
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .primary-button {
                background-color: #1e3a5f;
                border: 1px solid #2d4a6d;
                border-radius: 4px;
                color: white;
                padding: 8px 16px;
            }
            .secondary-button {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: white;
                padding: 8px 16px;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            dialog.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        dialog.present()

    async def _update_recording_date(self, recording_id: int, new_date: str) -> None:
        """Update a recording's date and refresh the view."""
        try:
            await self._api_client.update_recording_date(recording_id, new_date)
            logger.info(f"Updated recording {recording_id} date to {new_date}")
            GLib.idle_add(self._calendar_widget.refresh)
        except Exception as e:
            logger.error(f"Failed to update recording date: {e}")
            GLib.idle_add(
                lambda: self._show_error_dialog(f"Failed to update recording date: {e}")
            )

    def _show_error_dialog(self, message: str) -> None:
        """Show an error dialog."""
        dialog = Adw.MessageDialog(
            heading="Error",
            body=message,
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    def _on_export_requested(self, recording_id: int) -> None:
        """Handle export request from calendar."""
        dialog = Adw.MessageDialog(
            heading="Export Format",
            body="Choose export format:",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("txt", "Text (.txt)")
        dialog.add_response("json", "JSON (.json)")
        dialog.set_default_response("txt")
        dialog.set_close_response("cancel")

        def on_format_response(dialog, response):
            dialog.destroy()
            if response == "cancel":
                return

            export_format = response
            file_filter = "Text Files (*.txt)" if export_format == "txt" else "JSON Files (*.json)"
            default_ext = ".txt" if export_format == "txt" else ".json"

            # Create file chooser
            file_dialog = Gtk.FileDialog()
            file_dialog.set_title("Export Transcription")
            file_dialog.set_initial_name(f"transcription_export{default_ext}")

            def on_save_response(file_dialog, result):
                try:
                    file = file_dialog.save_finish(result)
                    if file:
                        file_path = file.get_path()
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(
                                    self._export_recording(recording_id, export_format, file_path)
                                )
                            else:
                                asyncio.run(
                                    self._export_recording(recording_id, export_format, file_path)
                                )
                        except RuntimeError:
                            pass
                except GLib.Error:
                    pass  # User cancelled

            file_dialog.save(None, None, on_save_response)

        dialog.connect("response", on_format_response)
        dialog.present()

    async def _export_recording(self, recording_id: int, format: str, file_path: str) -> None:
        """Export a recording to a file."""
        try:
            content, _ = await self._api_client.export_recording(recording_id, format)

            # Write to file
            from pathlib import Path
            Path(file_path).write_bytes(content)

            logger.info(f"Exported recording {recording_id} to {file_path}")
            GLib.idle_add(
                lambda: self._show_info_dialog(
                    "Export Complete",
                    f"Transcription exported successfully to:\n{file_path}"
                )
            )
        except Exception as e:
            logger.error(f"Failed to export recording: {e}")
            GLib.idle_add(
                lambda: self._show_error_dialog(f"Failed to export recording: {e}")
            )

    def _show_info_dialog(self, heading: str, body: str) -> None:
        """Show an info dialog."""
        dialog = Adw.MessageDialog(
            heading=heading,
            body=body,
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    def set_recording_callback(self, callback) -> None:
        """Set callback for recording requests."""
        self._recording_requested_callback = callback

    def refresh(self) -> None:
        """Refresh all notebook data."""
        current_page = self._notebook.get_current_page()
        if current_page == 0:
            self._calendar_widget.refresh()

    def set_api_client(self, api_client: "APIClient") -> None:
        """Update the API client reference."""
        self._api_client = api_client
        self._calendar_widget.set_api_client(api_client)
        self._search_widget.set_api_client(api_client)
        self._import_widget.set_api_client(api_client)
