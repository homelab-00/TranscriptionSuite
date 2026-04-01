"""Download progress tracking via huggingface_hub tqdm interception.

Provides a context manager that monkey-patches huggingface_hub's tqdm
to intercept download progress and emit events via startup_events.

Usage::

    from server.core.download_progress import track_model_download

    with track_model_download("nvidia/parakeet-tdt-0.6b-v2"):
        engine.load_model()
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from server.core.startup_events import emit_event

if TYPE_CHECKING:
    from types import ModuleType

logger = logging.getLogger(__name__)

# Thread-local storage for the active tracker.  Model loads can happen on
# different threads (asyncio.to_thread in live mode, run_in_executor in
# admin reload), so each thread tracks its own download independently.
_thread_local = threading.local()

# Minimum file size (bytes) to track — skip tiny config/tokenizer files.
_MIN_TRACKABLE_BYTES = 1024


def _get_tracker() -> _DownloadTracker | None:
    return getattr(_thread_local, "tracker", None)


def _set_tracker(tracker: _DownloadTracker | None) -> None:
    _thread_local.tracker = tracker


class _DownloadTracker:
    """Aggregates download progress across multiple tqdm instances for one model."""

    def __init__(self, event_id: str, label: str) -> None:
        self.event_id = event_id
        self.label = label
        self.download_started = False
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self._last_emit_time = 0.0

    def on_tqdm_created(self, total: int | float | None) -> None:
        """Register a new download file's total size."""
        if total is not None and total > _MIN_TRACKABLE_BYTES:
            self.download_started = True
            self.total_bytes += int(total)
            self._emit_progress()

    def on_tqdm_update(self, n: int | float) -> None:
        """Accumulate downloaded bytes; emit throttled progress event."""
        self.downloaded_bytes += int(n)
        now = time.monotonic()
        if now - self._last_emit_time >= 1.0:
            self._emit_progress()
            self._last_emit_time = now

    def _emit_progress(self) -> None:
        progress = (
            min(100, int(self.downloaded_bytes / self.total_bytes * 100))
            if self.total_bytes > 0
            else 0
        )
        emit_event(
            self.event_id,
            "download",
            f"Downloading {self.label}...",
            status="active",
            progress=progress,
            downloadedSize=self.downloaded_bytes,
            totalSize=self.total_bytes,
        )


class _ProgressTqdm:
    """tqdm-compatible class that routes progress updates to the active tracker.

    Implements the subset of the tqdm API that huggingface_hub actually uses
    during file downloads: constructor, update, close, context manager,
    and the get_lock/set_lock class methods required by ``thread_map``.
    """

    # Class-level lock used by tqdm.contrib.concurrent.thread_map.
    _lock: threading.RLock | None = None

    def __init__(
        self,
        iterable: Any = None,
        desc: str | None = None,
        total: int | float | None = None,
        *,
        disable: bool = False,
        initial: int | float = 0,
        name: str | None = None,  # huggingface_hub custom kwarg
        **kwargs: Any,
    ) -> None:
        self._iterable = iterable
        self.total = total  # plain attribute — snapshot_download mutates via +=
        self.n: int | float = initial
        self._disable = disable

        tracker = _get_tracker()
        if tracker and not disable:
            tracker.on_tqdm_created(total)

    def update(self, n: int | float = 1) -> None:
        self.n += n
        tracker = _get_tracker()
        if tracker and not self._disable:
            tracker.on_tqdm_update(n)

    def close(self) -> None:
        pass

    def __enter__(self) -> _ProgressTqdm:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __iter__(self) -> Generator[Any]:
        if self._iterable is None:
            return
        for item in self._iterable:
            yield item
            self.update(1)

    # ── tqdm compatibility stubs ──────────────────────────────────────

    @classmethod
    def get_lock(cls) -> threading.RLock:
        """Return class-level lock (used by ``tqdm.contrib.concurrent.thread_map``)."""
        if cls._lock is None:
            cls._lock = threading.RLock()
        return cls._lock

    @classmethod
    def set_lock(cls, lock: threading.RLock) -> None:
        """Set class-level lock (used by ``tqdm.contrib.concurrent.thread_map``)."""
        cls._lock = lock

    def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
        pass

    def set_postfix(self, *args: Any, **kwargs: Any) -> None:
        pass

    def refresh(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def reset(self, total: int | float | None = None) -> None:
        self.n = 0
        if total is not None:
            self.total = total

    def __del__(self) -> None:
        pass

    def __delattr__(self, attr: str) -> None:
        """Match huggingface_hub's tqdm __delattr__ safety for _lock."""
        try:
            super().__delattr__(attr)
        except AttributeError:
            if attr != "_lock":
                raise


# ── Patch targets ─────────────────────────────────────────────────────
# huggingface_hub 0.36 imports tqdm in three modules.  We patch all three
# so that both file_download and snapshot_download use our class.

_PATCH_TARGETS: list[tuple[str, str]] = [
    ("huggingface_hub.utils.tqdm", "tqdm"),
    ("huggingface_hub.file_download", "tqdm"),
    ("huggingface_hub._snapshot_download", "hf_tqdm"),
]


def _patch_hf_tqdm(
    tqdm_cls: type,
) -> list[tuple[ModuleType, str, Any]]:
    """Replace huggingface_hub's tqdm references with *tqdm_cls*.

    Returns a list of (module, attr_name, original_value) for restoration.
    """
    originals: list[tuple[ModuleType, str, Any]] = []
    for module_path, attr in _PATCH_TARGETS:
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, attr):
                originals.append((mod, attr, getattr(mod, attr)))
                setattr(mod, attr, tqdm_cls)
        except (ImportError, AttributeError):
            logger.debug("Could not patch %s.%s — skipping", module_path, attr)
    return originals


def _restore_hf_tqdm(originals: list[tuple[ModuleType, str, Any]]) -> None:
    """Restore original tqdm references saved by :func:`_patch_hf_tqdm`."""
    for mod, attr, original_value in originals:
        setattr(mod, attr, original_value)


@contextmanager
def track_model_download(model_name: str) -> Generator[None]:
    """Patch huggingface_hub tqdm to emit download progress events.

    On exit emits either a *"Loaded from cache"* completion (no tqdm was
    instantiated) or a *download-complete* event with byte totals.

    Parameters
    ----------
    model_name:
        Full model identifier (e.g. ``nvidia/parakeet-tdt-0.6b-v2``).
        Used to derive the event ID and human-readable label.
    """
    event_id = f"model-load-{model_name.replace('/', '--')}"
    label = model_name.split("/")[-1] if "/" in model_name else model_name

    tracker = _DownloadTracker(event_id, label)
    prev_tracker = _get_tracker()
    _set_tracker(tracker)

    start = time.perf_counter()

    emit_event(event_id, "download", f"Loading {label}...", status="active")

    originals: list[tuple[ModuleType, str, Any]] = []
    try:
        originals = _patch_hf_tqdm(_ProgressTqdm)
        yield
    except Exception:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        emit_event(
            event_id,
            "download",
            f"Failed to load {label}",
            status="error",
            durationMs=elapsed_ms,
        )
        raise
    else:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        if tracker.download_started:
            emit_event(
                event_id,
                "download",
                f"{label} ready",
                status="complete",
                durationMs=elapsed_ms,
                downloadedSize=tracker.downloaded_bytes,
                totalSize=tracker.total_bytes,
            )
        else:
            emit_event(
                event_id,
                "download",
                f"{label} loaded from cache",
                status="complete",
                durationMs=elapsed_ms,
            )
    finally:
        _restore_hf_tqdm(originals)
        _set_tracker(prev_tracker)
