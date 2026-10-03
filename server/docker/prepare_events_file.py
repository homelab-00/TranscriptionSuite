"""Make the startup-events file writable by the unprivileged server user (GH-318).

Runs as **root** from ``docker-entrypoint.sh``, before privileges are dropped to
``appuser`` and before ``bootstrap_runtime.py`` emits its first event.

Why this exists
---------------
The dashboard creates the events directory on the host as the desktop user
(``mkdtemp``: mode 0700) and the JSON Lines file inside it as 0600, then
bind-mounts the directory at ``/startup-events``. The server process runs as
``appuser`` - a different uid - which cannot even traverse that directory. Every
``emit_event()`` therefore failed with ``EACCES``, was swallowed (events are
deliberately non-fatal), and no startup stage, warning or download progress ever
reached the dashboard on a Linux host.

What it does
------------
* hands the **file** to ``appuser`` and makes it 0644, so the server writes it
  and the host user still reads it back through the "other" bits;
* opens the **directory** for traversal only (0711). It keeps its host owner, so
  the dashboard can still read and delete it.

Nothing becomes world-writable. Everything is best-effort: on bind-mount
backends that ignore ownership changes (Docker Desktop file sharing) the file is
already writable, and a failure here must never stop the container from starting.
"""

from __future__ import annotations

import os
import pwd
import stat
import sys
from pathlib import Path

SERVER_USER = "appuser"
EVENTS_FILE_ENV = "STARTUP_EVENTS_FILE"


def log(message: str) -> None:
    print(f"[prepare-events-file] {message}", flush=True)


def prepare_events_file(path: Path, uid: int, gid: int) -> bool:
    """Give *path* to (*uid*, *gid*) and make its directory traversable.

    Returns False when there is nothing to prepare.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return False
    # A regular file only: this runs as root on a host-controlled mount, and
    # must not be steered into re-owning whatever a symlink points at.
    if not stat.S_ISREG(info.st_mode):
        log(f"skipping {path}: not a regular file")
        return False

    try:
        os.chown(path, uid, gid, follow_symlinks=False)
    except OSError as exc:
        # Docker Desktop file sharing rejects chown; the mount is writable anyway.
        log(f"could not change ownership of {path}: {exc}")
    for target, mode in ((path, 0o644), (path.parent, 0o711)):
        try:
            os.chmod(target, mode)
        except OSError as exc:
            log(f"could not set mode {mode:o} on {target}: {exc}")
    return True


def main() -> int:
    raw = os.environ.get(EVENTS_FILE_ENV, "").strip()
    if not raw:
        return 0
    try:
        user = pwd.getpwnam(SERVER_USER)
    except KeyError:
        log(f"user {SERVER_USER!r} not found; leaving {raw} untouched")
        return 0
    try:
        prepare_events_file(Path(raw), user.pw_uid, user.pw_gid)
    except Exception as exc:  # never fail the entrypoint over a progress channel
        log(f"unexpected error: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
