"""Download progress tracking for model loads.

Provides a context manager that intercepts the progress bars huggingface_hub
(and torch.hub) create while downloading, and reports byte progress through
startup_events so the dashboard's download bar can show it.

Usage::

    from server.core.download_progress import track_model_download

    with track_model_download("nvidia/parakeet-tdt-0.6b-v2"):
        engine.load_model()

Downloads that do not go through a tqdm bar report bytes explicitly::

    with track_external_download("ggml-large-v3.bin", total_bytes, kind="ggml-model") as advance:
        for chunk in response.iter_bytes():
            advance(len(chunk))

Two rules shape this module:

* Tracking is cosmetic. Nothing here may fail a model load or a
  transcription: every tracker callback, event write and patch step is
  guarded, and only the tracked body's own exception propagates.
* A download does not stay on the thread that started it. snapshot_download
  creates each file's bar inside a ``thread_map`` worker, and the xet backend
  reports bytes from its own callback thread. A bar is therefore bound to its
  tracker when it is constructed, and worker threads inherit the tracker of
  the thread that submitted them.
"""

from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from collections.abc import Callable, Generator
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

# Process-wide state: how many contexts hold the module-level patches.
# Guarded by _state_lock.
_state_lock = threading.RLock()
_patch_refcount = 0
_patch_originals: list[tuple[ModuleType, str, Any]] = []

# Minimum file size (bytes) to track — skip tiny config/tokenizer files.
_MIN_TRACKABLE_BYTES = 1024

# How long the byte total must stay unchanged, with every registered byte
# downloaded, before the load is reported as having moved on to "loading into
# memory". In a multi-file download the bars registered so far can all be
# finished while more files are still about to start.
_LOAD_PHASE_SETTLE_S = 2.0

# Minimum gap between two progress events of one download.
_EMIT_INTERVAL_S = 1.0


def _format_bytes(num: float) -> str:
    """Human-readable byte size for dashboard display (GH-207)."""
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{int(num)} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def _safe_emit(*args: Any, **kwargs: Any) -> None:
    """emit_event that can never raise into a model load."""
    try:
        emit_event(*args, **kwargs)
    except Exception:
        logger.debug("Download progress event could not be written", exc_info=True)


def _get_tracker() -> _DownloadTracker | None:
    return getattr(_thread_local, "tracker", None)


def _set_tracker(tracker: _DownloadTracker | None) -> None:
    _thread_local.tracker = tracker


class _DownloadTracker:
    """Aggregates download progress across multiple tqdm instances for one model."""

    def __init__(
        self,
        event_id: str,
        label: str,
        *,
        kind: str = "model",
        name: str | None = None,
        settle_s: float = 0.0,
    ) -> None:
        self.event_id = event_id
        self.label = label
        self.kind = kind
        # Clean display name for the download bar; `label` only feeds the
        # status lines ("Downloading X...") older dashboards render as-is.
        self.name = name or label
        self.download_started = False
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self._last_emit_time = 0.0
        self._load_phase_emitted = False
        self._settle_s = settle_s
        self._settle_timer: threading.Timer | None = None
        self._closed = False
        # Bars are updated from library worker threads concurrently.
        self._lock = threading.RLock()

    def on_tqdm_created(self, total: int | float | None) -> None:
        """Register a new download file's total size."""
        if total is not None and total > _MIN_TRACKABLE_BYTES:
            self.on_total_delta(int(total))

    def on_total_delta(self, delta: int) -> None:
        """Grow (or correct) the byte total by *delta*."""
        if delta == 0:
            return
        with self._lock:
            # A bar can outlive its download (the xet backend may report once
            # more after the call returned). Anything emitted after the
            # terminal event would reopen the download in the dashboard.
            if self._closed:
                return
            self.total_bytes = max(0, self.total_bytes + delta)
            if delta > 0:
                self.download_started = True
                # More bytes to fetch: whatever was announced as "loading" is
                # downloading again (a pipeline fetching its next sub-model).
                self._load_phase_emitted = False
            self._emit_progress()
            # A total corrected downwards (xet deduplication) can be what
            # completes the download.
            self._maybe_enter_load_phase()

    def on_external_start(self, total: int) -> None:
        """A non-tqdm download begins; *total* may be 0 when the size is unknown."""
        with self._lock:
            if self._closed:
                return
            self.download_started = True
            self.total_bytes += max(0, total)
            self._load_phase_emitted = False
            self._emit_progress()

    def on_tqdm_update(self, n: int | float) -> None:
        """Accumulate downloaded bytes; emit throttled progress event."""
        with self._lock:
            if self._closed:
                return
            self.downloaded_bytes += int(n)
            now = time.monotonic()
            if now - self._last_emit_time >= _EMIT_INTERVAL_S:
                self._emit_progress()
                self._last_emit_time = now
            self._maybe_enter_load_phase()

    def close(self) -> None:
        """Stop the tracker: no load-phase event may fire after the context exits."""
        with self._lock:
            self._closed = True
            if self._settle_timer is not None:
                self._settle_timer.cancel()
                self._settle_timer = None

    @property
    def download_finished(self) -> bool:
        return self.total_bytes > 0 and self.downloaded_bytes >= self.total_bytes

    @property
    def download_settled(self) -> bool:
        """The download is confirmed over: every byte in, and no new file since."""
        return self._load_phase_emitted

    def _maybe_enter_load_phase(self) -> None:
        # Every registered byte is in. That is the point where the (possibly
        # long, CPU-bound) weight-instantiation phase begins (GH-207) - once
        # the total has stopped growing.
        if self._load_phase_emitted or self._closed or not self.download_finished:
            return
        if self._settle_s <= 0:
            self._emit_load_phase()
            return
        if self._settle_timer is not None:
            return
        expected_total = self.total_bytes
        timer = threading.Timer(self._settle_s, lambda: self._settle(expected_total))
        timer.daemon = True
        self._settle_timer = timer
        timer.start()

    def _settle(self, expected_total: int) -> None:
        try:
            with self._lock:
                self._settle_timer = None
                if self._closed or self._load_phase_emitted:
                    return
                if self.total_bytes == expected_total and self.download_finished:
                    self._emit_load_phase()
                else:
                    # Another file registered meanwhile. If that one has
                    # finished too, wait out a fresh settle window.
                    self._maybe_enter_load_phase()
        except Exception:
            logger.debug("Download load-phase settle failed", exc_info=True)

    def _emit_load_phase(self) -> None:
        self._load_phase_emitted = True
        _safe_emit(
            self.event_id,
            "download",
            f"Loading {self.label} into memory...",
            status="active",
            progress=100,
            phase="load",
            kind=self.kind,
            name=self.name,
            downloadedBytes=self.downloaded_bytes,
            totalBytes=self.total_bytes,
        )

    def _emit_progress(self) -> None:
        progress = (
            min(100, int(self.downloaded_bytes / self.total_bytes * 100))
            if self.total_bytes > 0
            else 0
        )
        _safe_emit(
            self.event_id,
            "download",
            f"Downloading {self.label}...",
            status="active",
            progress=progress,
            downloadedSize=_format_bytes(self.downloaded_bytes),
            totalSize=_format_bytes(self.total_bytes),
            # Raw numbers for the download bar (speed, ETA); the formatted
            # strings above stay for older dashboards.
            phase="download",
            kind=self.kind,
            name=self.name,
            downloadedBytes=self.downloaded_bytes,
            totalBytes=self.total_bytes,
        )


class _ProgressTqdm:
    """tqdm-compatible class that routes progress updates to a download tracker.

    Implements the subset of the tqdm API that huggingface_hub and torch.hub
    actually use during file downloads: constructor, update, close, context
    manager, a mutable ``total``, and the get_lock/set_lock class methods
    required by ``thread_map``.

    The tracker is bound at construction, not looked up per update: updates
    routinely arrive on a different thread than the one that created the bar.
    """

    # Class-level lock used by tqdm.contrib.concurrent.thread_map.
    _lock: threading.RLock | None = None

    # False on the subclass used for bars that count things other than bytes.
    _counts_bytes = True

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
        self.n: int | float = initial
        self.disable = bool(disable)
        self._disable = self.disable
        self._tracker: _DownloadTracker | None = None
        self._registered_total = 0

        # Byte bars are created with unit="B" (or no unit at all); a bar with
        # any other unit counts files or items and must never reach the total.
        # huggingface_hub 1.x keeps two byte bars per download: the bytes
        # written to disk, and `<name>.transfer` for the bytes off the network.
        # Both grow by the file size, so only the first one is counted.
        is_transfer_bar = isinstance(name, str) and name.endswith(".transfer")
        unit = kwargs.get("unit")
        if not self.disable and self._counts_bytes and not is_transfer_bar and unit in (None, "B"):
            # Only a bar created on a thread that belongs to the load is bound.
            # An owner is never guessed for a bar from some other thread: that
            # put unrelated bytes under the wrong name.
            self._tracker = _get_tracker()

        self.total = total  # registers with the tracker through the setter
        # A resumed file is announced with its full size and `initial` set to
        # what is already on disk; those bytes are done.
        if self._tracker is not None and self._registered_total > 0 and initial:
            try:
                self._tracker.on_tqdm_update(initial)
            except Exception:
                logger.debug("Download tracker rejected a resume offset", exc_info=True)

    @property
    def total(self) -> int | float | None:
        return self._total

    @total.setter
    def total(self, value: int | float | None) -> None:
        # A property rather than a plain attribute: newer huggingface_hub
        # grows one shared bar with `bar.total += file_size`, and those bytes
        # have to reach the tracker too.
        self._total = value
        tracker = self.__dict__.get("_tracker")
        if tracker is None:
            return
        try:
            trackable = (
                int(value)
                if isinstance(value, (int, float)) and value > _MIN_TRACKABLE_BYTES
                else 0
            )
            delta = trackable - self._registered_total
            if delta:
                self._registered_total = trackable
                tracker.on_total_delta(delta)
        except Exception:
            logger.debug("Download tracker rejected a total update", exc_info=True)

    def update(self, n: int | float = 1) -> None:
        self.n += n
        tracker = self._tracker
        if tracker is None or self._registered_total <= 0:
            return
        try:
            tracker.on_tqdm_update(n)
        except Exception:
            logger.debug("Download tracker rejected a progress update", exc_info=True)

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
        # Read defensively with getattr, NOT ``cls._lock``: tqdm's
        # ``ensure_lock`` (tqdm.contrib.concurrent, used by thread_map inside
        # huggingface_hub.snapshot_download) ends with ``del tqdm_class._lock``
        # when it created the lock — removing the class attribute entirely, not
        # setting it to None. A bare ``cls._lock`` read then raises
        # ``AttributeError: ... has no attribute '_lock'``. This mirrors real
        # tqdm's own ``if not hasattr(cls, '_lock')`` guard. The crash surfaced
        # as intermittent HTTP 500s on the parallel-diarization path, which
        # interleaves a model-load tqdm-patch window with concurrent HF
        # snapshot_download calls.
        if getattr(cls, "_lock", None) is None:
            cls._lock = threading.RLock()
        return cls._lock

    @classmethod
    def set_lock(cls, lock: threading.RLock) -> None:
        """Set class-level lock (used by ``tqdm.contrib.concurrent.thread_map``)."""
        cls._lock = lock

    def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
        pass

    def set_description_str(self, desc: str | None = None, refresh: bool = True) -> None:
        pass

    def set_postfix(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_postfix_str(self, s: str = "", refresh: bool = True) -> None:
        pass

    def refresh(self, *args: Any, **kwargs: Any) -> None:
        pass

    def display(self, *args: Any, **kwargs: Any) -> None:
        pass

    def unpause(self) -> None:
        pass

    def moveto(self, n: int) -> None:
        pass

    def clear(self, *args: Any, **kwargs: Any) -> None:
        pass

    @property
    def format_dict(self) -> dict[str, Any]:
        return {"n": self.n, "total": self.total}

    # Static formatters the xet progress reporter of huggingface_hub 1.x calls
    # on the tqdm class itself (`tqdm.format_sizeof(speed)`).

    @staticmethod
    def format_sizeof(num: float, suffix: str = "", divisor: float = 1000) -> str:
        for unit in ("", "k", "M", "G", "T", "P", "E", "Z"):
            if abs(num) < 999.5:
                if abs(num) < 99.95:
                    if abs(num) < 9.995:
                        return f"{num:1.2f}{unit}{suffix}"
                    return f"{num:2.1f}{unit}{suffix}"
                return f"{num:3.0f}{unit}{suffix}"
            num /= divisor
        return f"{num:3.1f}Y{suffix}"

    @staticmethod
    def format_interval(t: float) -> str:
        minutes, seconds = divmod(int(t), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def format_num(n: float) -> str:
        return f"{n:.3g}".replace("e+0", "e+").replace("e-0", "e-")

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


class _UntrackedTqdm(_ProgressTqdm):
    """Same no-op surface, never counted: for bars that count files, not bytes."""

    _counts_bytes = False


def _make_tracking_thread_map(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``tqdm.contrib.concurrent.thread_map`` so workers inherit the tracker.

    snapshot_download fans its files out through thread_map and each file's
    progress bar is created inside the worker. Without this the bars see no
    thread-local tracker and a real download is reported as a cache hit.
    """

    def tracking_thread_map(fn: Callable[..., Any], *iterables: Any, **kwargs: Any) -> Any:
        tracker = _get_tracker()
        if tracker is None:
            return original(fn, *iterables, **kwargs)

        def run_with_tracker(*args: Any, **kw: Any) -> Any:
            previous = _get_tracker()
            _set_tracker(tracker)
            try:
                return fn(*args, **kw)
            finally:
                _set_tracker(previous)

        # thread_map builds its own "Fetching N files" bar from tqdm_class.
        # That one counts files; keep it out of the byte total.
        if kwargs.get("tqdm_class") is _ProgressTqdm:
            kwargs["tqdm_class"] = _UntrackedTqdm
        return original(run_with_tracker, *iterables, **kwargs)

    return tracking_thread_map


# ── Patch targets ─────────────────────────────────────────────────────
# huggingface_hub 0.36 imports tqdm in three modules.  We patch all three
# so that both file_download and snapshot_download use our class. torch.hub
# is how torchaudio fetches its bundled alignment models.

_PATCH_TARGETS: list[tuple[str, str]] = [
    ("huggingface_hub.utils.tqdm", "tqdm"),
    ("huggingface_hub.file_download", "tqdm"),
    ("huggingface_hub._snapshot_download", "hf_tqdm"),
    # huggingface_hub 1.x: the xet reporter builds its bars from its own copy.
    ("huggingface_hub.utils._xet_progress_reporting", "tqdm"),
    ("torch.hub", "tqdm"),
]

# Patched only when something else already imported them: tracking a download
# must not be the reason torch gets loaded.
_PATCH_ONLY_IF_LOADED = frozenset({"torch.hub"})

_THREAD_MAP_TARGET: tuple[str, str] = ("huggingface_hub._snapshot_download", "thread_map")


def _patch_hf_tqdm(
    tqdm_cls: type,
) -> list[tuple[ModuleType, str, Any]]:
    """Replace huggingface_hub's tqdm references with *tqdm_cls*.

    Returns a list of (module, attr_name, original_value) for restoration.
    """
    # Two passes: resolve every original first, replace afterwards. Importing
    # one target can copy a name out of another at import time
    # (`from .utils.tqdm import tqdm as hf_tqdm`); if that other target were
    # already patched, the copy would be our class and "restoring" it would
    # leave huggingface_hub patched for the rest of the process.
    originals: list[tuple[ModuleType, str, Any]] = []
    for module_path, attr in _PATCH_TARGETS:
        if module_path in _PATCH_ONLY_IF_LOADED and module_path not in sys.modules:
            continue
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, attr):
                originals.append((mod, attr, getattr(mod, attr)))
        except Exception:
            # Any failure of one target (not just ImportError) only costs that
            # target: the others are still patched, and nothing is left half done.
            logger.debug("Could not patch %s.%s - skipping", module_path, attr, exc_info=True)
    for mod, attr, _original in originals:
        setattr(mod, attr, tqdm_cls)
    return originals


def _patch_thread_map() -> list[tuple[ModuleType, str, Any]]:
    """Wrap snapshot_download's thread_map so its workers inherit the tracker."""
    module_path, attr = _THREAD_MAP_TARGET
    try:
        mod = importlib.import_module(module_path)
        original = getattr(mod, attr, None)
        if original is None:
            return []
        setattr(mod, attr, _make_tracking_thread_map(original))
        return [(mod, attr, original)]
    except Exception:
        logger.debug("Could not patch %s.%s - skipping", module_path, attr, exc_info=True)
        return []


def _restore_hf_tqdm(originals: list[tuple[ModuleType, str, Any]]) -> None:
    """Restore original tqdm references saved by :func:`_patch_hf_tqdm`."""
    for mod, attr, original_value in originals:
        setattr(mod, attr, original_value)


def _acquire_patches() -> None:
    """Install the module-level patches on the first holder; count the rest.

    Reference-counted because the patches are process-wide while loads are
    per-thread: saving "the previous value" per context let a later context
    restore an earlier context's patch as if it were the original, leaving
    huggingface_hub patched for good.
    """
    global _patch_refcount, _patch_originals
    with _state_lock:
        if _patch_refcount == 0:
            # Counted only once the patches are in: a failed setup must not
            # leave a count behind, or they would never be installed again.
            _patch_originals = _patch_hf_tqdm(_ProgressTqdm) + _patch_thread_map()
        _patch_refcount += 1


def _release_patches() -> None:
    global _patch_refcount, _patch_originals
    with _state_lock:
        _patch_refcount = max(0, _patch_refcount - 1)
        if _patch_refcount == 0:
            originals, _patch_originals = _patch_originals, []
            _restore_hf_tqdm(originals)


def _failure_text(exc: BaseException) -> str:
    """One short line describing *exc* for the dashboard."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    summary = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return summary[:300]


@contextmanager
def track_model_download(
    model_name: str,
    *,
    kind: str = "model",
    name: str | None = None,
    event_id: str | None = None,
) -> Generator[None]:
    """Report download progress for whatever the body fetches.

    On exit emits either a *"Loaded from cache"* completion (nothing was
    downloaded) or a *download-complete* event with byte totals.

    Nested use on one thread is a no-op: the inner body reports into the
    enclosing download, so wrapping both a caller and its callee is safe.

    Parameters
    ----------
    model_name:
        Full model identifier (e.g. ``nvidia/parakeet-tdt-0.6b-v2``).
        Used to derive the event ID and the status-line label.
    kind:
        What is being downloaded, as the dashboard's download bar names it:
        ``model``, ``live-model``, ``diarization-model``, ``alignment-model``,
        ``ggml-model``.
    name:
        Display name for the download bar. Defaults to the short model name.
    event_id:
        Explicit event ID; derived from *kind* and *model_name* otherwise.
    """
    if _get_tracker() is not None:
        yield
        return

    start = time.perf_counter()
    tracker: _DownloadTracker | None = None
    patched = False
    try:
        label = model_name.split("/")[-1] if "/" in model_name else model_name
        resolved_id = event_id or f"{kind}-load-{model_name.replace('/', '--')}"
        tracker = _DownloadTracker(
            resolved_id,
            label,
            kind=kind,
            name=name or label,
            settle_s=_LOAD_PHASE_SETTLE_S,
        )
        _set_tracker(tracker)
        # No phase on this one: until bytes actually flow, the load is not
        # known to be a download and must not look like one.
        _safe_emit(
            resolved_id,
            "download",
            f"Loading {label}...",
            status="active",
            kind=kind,
            name=tracker.name,
        )
        _acquire_patches()
        patched = True
    except Exception:
        logger.debug("Download tracking could not be set up", exc_info=True)

    failure: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            _finish_tracking(tracker, start, failure)
        except Exception:
            logger.debug("Download tracking could not be finalised", exc_info=True)
        try:
            if patched:
                _release_patches()
        except Exception:
            logger.debug("Download tracking patches could not be released", exc_info=True)
        _set_tracker(None)


def _finish_tracking(
    tracker: _DownloadTracker | None,
    start: float,
    failure: BaseException | None,
) -> None:
    if tracker is None:
        return
    tracker.close()
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    common = {"kind": tracker.kind, "name": tracker.name, "durationMs": elapsed_ms}

    if failure is not None:
        # A failure only counts as a failed *download* while bytes were still
        # outstanding; anything else (CUDA OOM, bad weights) is a load failure.
        # "Every registered byte is in" is not enough: in a multi-file download
        # the next file may have failed at its first request. Only a download
        # that had settled is treated as finished.
        mid_download = tracker.download_started and not tracker.download_settled
        _safe_emit(
            tracker.event_id,
            "download",
            f"Failed to load {tracker.label}",
            status="error",
            phase="download" if mid_download else "load",
            error=_failure_text(failure),
            **common,
        )
    elif tracker.download_started:
        _safe_emit(
            tracker.event_id,
            "download",
            f"{tracker.label} ready",
            status="complete",
            downloaded=True,
            downloadedSize=_format_bytes(tracker.downloaded_bytes),
            totalSize=_format_bytes(tracker.total_bytes),
            downloadedBytes=tracker.downloaded_bytes,
            totalBytes=tracker.total_bytes,
            **common,
        )
    else:
        _safe_emit(
            tracker.event_id,
            "download",
            f"{tracker.label} loaded from cache",
            status="complete",
            downloaded=False,
            **common,
        )


@contextmanager
def track_external_download(
    name: str,
    total_bytes: int,
    *,
    kind: str = "model",
) -> Generator[Callable[[int], None]]:
    """Report a download that does not go through a tqdm bar.

    Yields ``advance(n)``, to be called with each chunk's size. Feeds the
    enclosing :func:`track_model_download` when there is one, so the bytes
    show up under the model being loaded; stands alone otherwise.

    *total_bytes* may be 0 when the server sent no Content-Length: bytes are
    still counted and the dashboard shows an indeterminate bar.
    """
    with track_model_download(name, kind=kind):
        tracker = _get_tracker()
        if tracker is not None:
            try:
                tracker.on_external_start(int(total_bytes or 0))
            except Exception:
                logger.debug("Download tracker rejected an external start", exc_info=True)

        def advance(n: int) -> None:
            if tracker is None:
                return
            try:
                tracker.on_tqdm_update(n)
            except Exception:
                logger.debug("Download tracker rejected an external update", exc_info=True)

        yield advance
