"""
Version utility for TranscriptionSuite Dashboard.

Provides a single source of truth for version information,
reading from pyproject.toml or installed package metadata.
"""

from pathlib import Path


def get_version() -> str:
    """
    Get the dashboard version.

    Priority:
    1. importlib.metadata.version() - when installed as a package
    2. pyproject.toml - when running from source or PyInstaller bundle

    Returns:
        Version string (e.g., "0.3.2") or "dev" if unavailable
    """
    # First try importlib.metadata (works when package is installed)
    try:
        from importlib.metadata import version

        return version("transcriptionsuite-dashboard")
    except Exception:
        pass

    # Fallback: read from pyproject.toml
    try:
        import sys
        import tomllib

        # Check if running as PyInstaller bundle
        if getattr(sys, "frozen", False):
            # Running as bundled app - pyproject.toml should be in the dashboard directory
            bundle_dir = Path(sys._MEIPASS)  # type: ignore
            pyproject_path = bundle_dir / "dashboard" / "pyproject.toml"
        else:
            # Running from source - find pyproject.toml relative to this file
            current = Path(__file__).resolve()
            pyproject_path = None
            for parent in current.parents:
                potential_path = parent / "pyproject.toml"
                if potential_path.exists():
                    pyproject_path = potential_path
                    break

        if pyproject_path and pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            return data.get("project", {}).get("version", "dev")
    except Exception:
        pass

    return "dev"


# Module-level constant for easy import
__version__ = get_version()
