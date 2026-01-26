"""
Utility functions and constants for the Dashboard.

This module contains helper functions for path resolution and constants
used across the dashboard components.
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Constants for embedded resources
GITHUB_PROFILE_URL = "https://github.com/homelab-00"
GITHUB_REPO_URL = "https://github.com/homelab-00/TranscriptionSuite"


def get_assets_path() -> Path:
    """Get the path to the assets directory, handling both dev and bundled modes."""
    # Check if running as PyInstaller bundle
    if getattr(sys, "frozen", False):
        # Running as bundled app
        bundle_dir = Path(sys._MEIPASS)  # type: ignore
        return bundle_dir / "build" / "assets"
    else:
        # Running from source - find repo root
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "README.md").exists():
                return parent / "build" / "assets"
        # Fallback
        return Path(__file__).parent.parent.parent.parent.parent / "build" / "assets"


def get_readme_path(dev: bool = False) -> Path | None:
    """Get the path to README.md or README_DEV.md.

    Handles multiple scenarios:
    - AppImage (looks in AppDir - checked even when not frozen)
    - PyInstaller bundle (looks in _MEIPASS)
    - Running from source (searches parent directories)
    - Current working directory (fallback)

    Args:
        dev: If True, look for README_DEV.md instead of README.md

    Returns:
        Path to the README file, or None if not found
    """
    filename = "README_DEV.md" if dev else "README.md"

    # List of potential paths to check (in order of priority)
    paths_to_check: list[Path] = []

    # 1. AppImage root directory (APPDIR is set by AppImage runtime)
    if "APPDIR" in os.environ:
        appdir = Path(os.environ["APPDIR"])
        logger.debug(f"Checking AppImage APPDIR: {appdir}")
        paths_to_check.extend(
            [
                appdir / filename,
                appdir / "usr" / "share" / "transcriptionsuite" / filename,
            ]
        )

    # 2. PyInstaller bundle (_MEIPASS)
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)  # type: ignore
        logger.debug(f"Checking PyInstaller bundle: {bundle_dir}")
        paths_to_check.extend(
            [
                bundle_dir / filename,
                bundle_dir / "docs" / filename,
                bundle_dir / "src" / "dashboard" / filename,
            ]
        )

    # 3. Running from source - find repo root
    current = Path(__file__).resolve()
    logger.debug(f"Searching from module path: {current}")
    for parent in current.parents:
        if (parent / "README.md").exists():
            # Found project root
            paths_to_check.insert(0, parent / filename)
            logger.debug(f"Found project root at: {parent}")
            break
        paths_to_check.append(parent / filename)

    # 4. Current working directory (fallback)
    paths_to_check.append(Path.cwd() / filename)

    # Check all paths and return first existing one
    logger.debug(
        f"Searching for {filename} in paths: {[str(p) for p in paths_to_check[:5]]}..."
    )
    for path in paths_to_check:
        if path.exists():
            logger.info(f"Found {filename} at: {path}")
            return path

    logger.error(
        f"Could not find {filename} in any expected location. Searched {len(paths_to_check)} paths."
    )
    return None
