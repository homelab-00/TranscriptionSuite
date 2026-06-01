"""Thread-affinity tests for the MLX backend pinning helper (GH #134).

MLX binds each GPU stream to the thread that created it; the server otherwise
dispatches model load and inference on different threads. These tests prove that
``MLXThreadAffinityMixin`` + ``@mlx_pinned`` funnel every decorated call onto one
dedicated owning thread, distinct from the caller — WITHOUT importing MLX or
needing Apple-Silicon hardware (a fake backend records ``threading.get_ident()``).
"""

from __future__ import annotations

import threading

import pytest
from server.core.stt.backends.mlx_thread_pin import MLXThreadAffinityMixin, mlx_pinned


class _FakeMLXBackend(MLXThreadAffinityMixin):
    """Minimal backend-shaped object exercising only the pinning machinery."""

    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    @property
    def backend_name(self) -> str:
        return "fake"

    @mlx_pinned
    def load(self) -> None:
        self.events.append(("load", threading.get_ident()))

    @mlx_pinned
    def transcribe(self) -> str:
        self.events.append(("transcribe", threading.get_ident()))
        return "ok"

    @mlx_pinned
    def outer(self) -> tuple[str, int, tuple[str, int]]:
        # Reentrant: invokes another pinned method while already on the owning thread.
        return ("outer", threading.get_ident(), self.inner())

    @mlx_pinned
    def inner(self) -> tuple[str, int]:
        return ("inner", threading.get_ident())

    @mlx_pinned
    def boom(self) -> None:
        raise ValueError("kaboom")


def _run_in_new_thread(fn: object) -> dict:
    """Run ``fn`` in a fresh thread, returning its thread id and result."""
    box: dict = {}

    def run() -> None:
        box["tid"] = threading.get_ident()
        box["ret"] = fn()

    t = threading.Thread(target=run)
    t.start()
    t.join()
    return box


def test_load_and_transcribe_share_one_owning_thread_distinct_from_callers() -> None:
    backend = _FakeMLXBackend()

    load_caller = _run_in_new_thread(backend.load)
    transcribe_caller = _run_in_new_thread(backend.transcribe)

    owning_ids = {tid for (_, tid) in backend.events}
    assert len(owning_ids) == 1, "load and transcribe must run on a single owning thread"
    owning_id = owning_ids.pop()
    # The owning thread is still alive (executor not shut down), so its id cannot
    # collide with the (now-exited) caller threads.
    assert owning_id != load_caller["tid"]
    assert owning_id != transcribe_caller["tid"]
    assert transcribe_caller["ret"] == "ok"


def test_reentrant_pinned_call_runs_inline_without_deadlock() -> None:
    backend = _FakeMLXBackend()

    done = threading.Event()
    box: dict = {}

    def run() -> None:
        box["ret"] = backend.outer()
        done.set()

    t = threading.Thread(target=run)
    t.start()
    assert done.wait(timeout=5), "reentrant pinned call deadlocked the single worker"
    t.join()

    _, outer_tid, (inner_label, inner_tid) = box["ret"]
    assert inner_label == "inner"
    # Inner ran inline on the owning thread (no re-submit) → same thread id.
    assert outer_tid == inner_tid


def test_pinned_exception_propagates_original_type_and_message() -> None:
    backend = _FakeMLXBackend()
    with pytest.raises(ValueError, match="kaboom"):
        backend.boom()


def test_many_calls_across_threads_use_one_owning_thread() -> None:
    backend = _FakeMLXBackend()

    threads = [threading.Thread(target=backend.transcribe) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    owning_ids = {tid for (label, tid) in backend.events if label == "transcribe"}
    assert owning_ids != set()
    assert len(owning_ids) == 1, "all calls must marshal onto the same owning thread"


def test_distinct_instances_get_distinct_owning_threads() -> None:
    a = _FakeMLXBackend()
    b = _FakeMLXBackend()
    a.transcribe()
    b.transcribe()
    a_tid = a.events[0][1]
    b_tid = b.events[0][1]
    assert a_tid != b_tid, "each backend instance must own its own thread"


def test_shutdown_mlx_thread_is_safe_and_idempotent() -> None:
    backend = _FakeMLXBackend()
    backend.transcribe()
    backend.shutdown_mlx_thread()
    backend.shutdown_mlx_thread()  # second call must not raise
    # A fresh call after shutdown transparently re-creates the owning thread.
    backend.transcribe()
    assert len([e for e in backend.events if e[0] == "transcribe"]) == 2
