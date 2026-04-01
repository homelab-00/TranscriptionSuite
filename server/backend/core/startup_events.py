"""Append-only JSON Lines writer for startup lifecycle events.

Stdlib-only so it can be safely imported from bootstrap_runtime.py
(which runs before dependencies are installed).

Each call to emit_event() appends one JSON line to EVENTS_FILE.
The Electron host watches this file via fs.watch() and parses new
lines into the activityStore.

Protocol: repeated ``id`` values mean "update the existing item".
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

EVENTS_FILE = Path(os.environ.get("STARTUP_EVENTS_FILE", "/runtime/startup-events.jsonl"))


def truncate_events_file() -> None:
    """Clear the events file at the start of a new container session."""
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        EVENTS_FILE.write_text("", encoding="utf-8")
    except OSError:
        pass  # Non-fatal: file may not be writable outside container


def emit_event(
    id: str,
    category: str,
    label: str,
    status: str = "active",
    **extra: object,
) -> None:
    """Append one JSON line to the startup events file.

    Parameters
    ----------
    id:
        Stable identifier.  Repeated id = update existing item.
    category:
        One of ``download``, ``server``, ``warning``, ``info``.
    label:
        Human-readable description shown in the UI.
    status:
        One of ``active``, ``complete``, ``error``.
    **extra:
        Additional fields (progress, totalSize, durationMs, etc.).
    """
    event = {
        "id": id,
        "category": category,
        "label": label,
        "status": status,
        "ts": time.time(),
        **extra,
    }
    try:
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
            f.flush()
    except OSError:
        pass  # Non-fatal: don't crash server if file write fails
