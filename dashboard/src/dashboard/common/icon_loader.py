"""
Platform-aware icon loader for PyQt6 applications.

Provides a unified interface for loading icons that works across platforms:
- Linux (KDE/GNOME): Uses QIcon.fromTheme with FreeDesktop icon theme
- Windows: Falls back to QStyle.standardIcon or bundled assets
- macOS: Falls back to QStyle.standardIcon or bundled assets

Usage:
    from dashboard.common.icon_loader import IconLoader

    # Initialize once (usually in main window __init__)
    icon_loader = IconLoader(widget)

    # Get icons with automatic fallbacks
    server_icon = icon_loader.get_icon("server")
    settings_icon = icon_loader.get_icon("settings")
"""

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QStyle, QWidget

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class IconLoader:
    """
    Platform-aware icon loader with automatic fallbacks.

    On Linux, attempts to load from the system icon theme first.
    On Windows/macOS, uses Qt's built-in standard icons or bundled assets.
    """

    # Mapping of semantic icon names to:
    # - theme_names: List of FreeDesktop icon theme names to try (Linux)
    # - standard_pixmap: QStyle.StandardPixmap fallback (all platforms)
    # - bundled_name: Optional bundled asset filename (if no standard pixmap fits)
    #
    # NOTE: Some icons have no good StandardPixmap equivalent on Windows.
    # For these, we set standard_pixmap to None and the UI should handle
    # missing icons gracefully (e.g., by showing text labels).
    ICON_MAP: dict[str, dict] = {
        # Navigation icons - these have no good Windows equivalents
        # UI should show text labels when icons are null
        "home": {
            "theme_names": ["go-home", "user-home"],
            "standard_pixmap": None,  # No good Windows equivalent
        },
        "server": {
            "theme_names": ["server-database", "network-server", "computer"],
            "standard_pixmap": None,  # Let theme icons work on Windows like home/client
        },
        "client": {
            "theme_names": ["audio-input-microphone", "microphone"],
            "standard_pixmap": None,  # No good Windows equivalent
        },
        "notebook": {
            "theme_names": [
                "accessories-text-editor",
                "text-editor",
                "x-office-document",
                "notebook",
            ],
            "standard_pixmap": QStyle.StandardPixmap.SP_FileIcon,
        },
        "menu": {
            "theme_names": ["application-menu", "open-menu-symbolic", "view-more"],
            "standard_pixmap": None,  # Use hamburger text ☰ instead
        },
        # Action icons
        "settings": {
            "theme_names": [
                "configure-symbolic",
                "settings-configure-symbolic",
                "preferences-system-symbolic",
                "preferences-system",
            ],
            "standard_pixmap": QStyle.StandardPixmap.SP_FileDialogDetailedView,
        },
        "help": {
            "theme_names": ["help-contents", "help-about", "help-browser"],
            "standard_pixmap": QStyle.StandardPixmap.SP_DialogHelpButton,
        },
        "about": {
            "theme_names": ["help-about", "dialog-information"],
            "standard_pixmap": QStyle.StandardPixmap.SP_MessageBoxInformation,
        },
        "logs": {
            "theme_names": ["text-x-log", "text-x-generic", "utilities-log-viewer"],
            "standard_pixmap": QStyle.StandardPixmap.SP_FileIcon,
        },
        "document": {
            "theme_names": [
                "x-office-document",
                "document-properties",
                "text-x-generic",
            ],
            "standard_pixmap": QStyle.StandardPixmap.SP_FileIcon,
        },
        "script": {
            "theme_names": ["text-x-script", "text-x-source", "text-x-generic"],
            "standard_pixmap": QStyle.StandardPixmap.SP_FileIcon,
        },
        # Status icons
        "info": {
            "theme_names": ["dialog-information"],
            "standard_pixmap": QStyle.StandardPixmap.SP_MessageBoxInformation,
        },
        "warning": {
            "theme_names": ["dialog-warning"],
            "standard_pixmap": QStyle.StandardPixmap.SP_MessageBoxWarning,
        },
        "error": {
            "theme_names": ["dialog-error"],
            "standard_pixmap": QStyle.StandardPixmap.SP_MessageBoxCritical,
        },
        # Media icons
        "play": {
            "theme_names": ["media-playback-start"],
            "standard_pixmap": QStyle.StandardPixmap.SP_MediaPlay,
        },
        "stop": {
            "theme_names": ["media-playback-stop"],
            "standard_pixmap": QStyle.StandardPixmap.SP_MediaStop,
        },
        "refresh": {
            "theme_names": ["view-refresh", "reload"],
            "standard_pixmap": QStyle.StandardPixmap.SP_BrowserReload,
        },
        # File/folder icons
        "folder": {
            "theme_names": ["folder", "folder-open"],
            "standard_pixmap": QStyle.StandardPixmap.SP_DirIcon,
        },
        "folder-open": {
            "theme_names": ["folder-open", "document-open-folder"],
            "standard_pixmap": QStyle.StandardPixmap.SP_DirOpenIcon,
        },
        "file": {
            "theme_names": ["text-x-generic", "document-new"],
            "standard_pixmap": QStyle.StandardPixmap.SP_FileIcon,
        },
    }

    def __init__(self, widget: QWidget, assets_path: Path | None = None):
        """
        Initialize icon loader.

        Args:
            widget: A QWidget to get the style from (for standard icons).
            assets_path: Optional path to bundled assets directory.
        """
        self._widget = widget
        self._style = widget.style()
        self._assets_path = assets_path
        self._is_linux = sys.platform.startswith("linux")
        self._cache: dict[str, QIcon] = {}

        if self._assets_path:
            logger.debug(f"IconLoader initialized with assets path: {assets_path}")

    def get_icon(self, name: str) -> QIcon:
        """
        Get an icon by semantic name with automatic platform fallbacks.

        Args:
            name: Semantic icon name (e.g., "server", "settings", "home")

        Returns:
            QIcon instance (may be null if no icon found)
        """
        # Check cache first
        if name in self._cache:
            return self._cache[name]

        icon = QIcon()
        icon_config = self.ICON_MAP.get(name)

        if not icon_config:
            logger.warning(f"Unknown icon name: {name}")
            return icon

        # On Linux, try theme icons first
        if self._is_linux:
            for theme_name in icon_config.get("theme_names", []):
                icon = QIcon.fromTheme(theme_name)
                if not icon.isNull():
                    logger.debug(f"Loaded icon '{name}' from theme: {theme_name}")
                    self._cache[name] = icon
                    return icon

        # Try bundled asset if available
        if self._assets_path:
            bundled_name = icon_config.get("bundled_name")
            if bundled_name:
                asset_path = self._assets_path / bundled_name
                if asset_path.exists():
                    icon = QIcon(str(asset_path))
                    if not icon.isNull():
                        logger.debug(
                            f"Loaded icon '{name}' from bundled asset: {asset_path}"
                        )
                        self._cache[name] = icon
                        return icon

        # Fall back to standard pixmap
        standard_pixmap = icon_config.get("standard_pixmap")
        if standard_pixmap and self._style:
            icon = self._style.standardIcon(standard_pixmap)
            if not icon.isNull():
                logger.debug(f"Loaded icon '{name}' from standard pixmap")
                self._cache[name] = icon
                return icon

        # Last resort: try theme icons on non-Linux too (some may work)
        if not self._is_linux:
            for theme_name in icon_config.get("theme_names", []):
                icon = QIcon.fromTheme(theme_name)
                if not icon.isNull():
                    logger.debug(
                        f"Loaded icon '{name}' from theme (non-Linux): {theme_name}"
                    )
                    self._cache[name] = icon
                    return icon

        logger.debug(f"No icon found for '{name}'")
        self._cache[name] = icon  # Cache null icon to avoid repeated lookups
        return icon

    def get_icon_from_theme(
        self,
        *theme_names: str,
        fallback_pixmap: QStyle.StandardPixmap | None = None,
    ) -> QIcon:
        """
        Get an icon by trying multiple theme names with optional fallback.

        This is useful for one-off icons not in ICON_MAP.

        Args:
            *theme_names: FreeDesktop theme icon names to try in order
            fallback_pixmap: QStyle.StandardPixmap to use if theme icons fail

        Returns:
            QIcon instance (may be null if no icon found)
        """
        # Try theme icons on Linux
        if self._is_linux:
            for theme_name in theme_names:
                icon = QIcon.fromTheme(theme_name)
                if not icon.isNull():
                    return icon

        # Try standard pixmap
        if fallback_pixmap is not None and self._style:
            icon = self._style.standardIcon(fallback_pixmap)
            if not icon.isNull():
                return icon

        # Try theme icons on non-Linux as last resort
        if not self._is_linux:
            for theme_name in theme_names:
                icon = QIcon.fromTheme(theme_name)
                if not icon.isNull():
                    return icon

        return QIcon()

    def clear_cache(self) -> None:
        """Clear the icon cache."""
        self._cache.clear()
