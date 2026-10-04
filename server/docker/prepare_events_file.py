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
# Where docker-compose mounts the dashboard's events directory. This step only
# ever acts on a file directly inside it: the env var is operator-settable, and
# pointed anywhere else (the mounted config directory, say) it would have root
# re-own and re-mode something that is none of its business.
EVENTS_MOUNT_DIR = Path("/startup-events")


def log(message: str) -> None:
    print(f"[prepare-events-file] {message}", flush=True)


def prepare_events_file(
    path: Path,
    uid: int,
    gid: int,
    allowed_dir: Path = EVENTS_MOUNT_DIR,
) -> bool:
    """Give *path* to (*uid*, *gid*) and make its directory traversable.

    Returns False when there is nothing to prepare.

    This runs as root on a host-controlled mount, so every change is made
    through an open descriptor that was first checked: the file is opened
    without following a symlink and must be a regular file, and nothing can be
    swapped in between that check and the ownership or mode change.
    """
    if path.parent != allowed_dir:
        log(f"skipping {path}: not inside {allowed_dir}")
        return False

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False  # missing, or a symlink
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            log(f"skipping {path}: not a regular file")
            return False
        try:
            os.fchown(fd, uid, gid)
        except OSError as exc:
            # Docker Desktop file sharing rejects chown; the mount is writable anyway.
            log(f"could not change ownership of {path}: {exc}")
        try:
            os.fchmod(fd, 0o644)
        except OSError as exc:
            log(f"could not set mode 644 on {path}: {exc}")
    finally:
        os.close(fd)

    try:
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        log(f"could not open {path.parent}: {exc}")
        return True
    try:
        os.fchmod(dir_fd, 0o711)
    except OSError as exc:
        log(f"could not set mode 711 on {path.parent}: {exc}")
    finally:
        os.close(dir_fd)
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
