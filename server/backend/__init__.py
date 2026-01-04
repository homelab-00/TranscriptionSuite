"""
TranscriptionSuite Server Package.

This is the unified server component that runs inside Docker,
providing transcription services via REST API and WebSocket.
"""

from pathlib import Path


def _get_version() -> str:
    """
    Get the server version from pyproject.toml or package metadata.

    Returns:
        Version string (e.g., "0.3.2") or "dev" if unavailable
    """
    # First try importlib.metadata (works when package is installed)
    try:
        from importlib.metadata import version

        return version("transcription-suite-server")
    except Exception:
        pass

    # Fallback: read from pyproject.toml
    try:
        import tomllib

        # Find pyproject.toml relative to this file
        current = Path(__file__).resolve()
        for parent in current.parents:
            potential_path = parent / "pyproject.toml"
            if potential_path.exists():
                with open(potential_path, "rb") as f:
                    data = tomllib.load(f)
                return data.get("project", {}).get("version", "dev")
    except Exception:
        pass

    return "dev"


__version__ = _get_version()
