"""Thread-affinity helper for MLX (Apple Silicon / Metal) STT backends.

MLX binds each GPU stream to the OS thread that *created* it; dispatching MLX GPU
work from a different thread raises ``RuntimeError: There is no stream (gpu,0) in
current thread`` (upstream ml-explore/mlx#2133). The server, however, dispatches
transcription across interchangeable threads — ``asyncio.to_thread`` pool workers
(``api/routes/transcription.py``), the parallel-diarization ``ThreadPoolExecutor``
(``core/parallel_diarize.py``), and the live-mode worker thread
(``core/live_engine.py``) — while the model is materialized on yet another thread
(the startup prewarm at ``api/main.py`` runs synchronously on the event-loop
thread). Load-thread != inference-thread, so every MLX call after start fails.

This module pins **all** MLX GPU operations for a backend instance onto a single
dedicated owning thread. Mix :class:`MLXThreadAffinityMixin` into an MLX backend
(before ``STTBackend`` in the MRO) and decorate every GPU-touching method with
:func:`mlx_pinned`. The fix is Metal-specific: CUDA/PyTorch contexts are
process-wide, so the identical dispatch is safe there.

Root cause + fix design: GH #134.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

# Classic typing.TypeVar — deliberately NOT a PEP 695 ``def f[T]`` type parameter:
# CodeQL's Python extractor does not yet understand PEP 695 type parameters and
# raises a false py/uninitialized-local-variable on the type variable when it is
# referenced inside a nested function (the ``wrapper`` below). A module-level
# TypeVar is unambiguously initialized, so CodeQL stays quiet. ``mlx_pinned`` thus
# carries a matching ``# noqa: UP047`` for ruff, which would otherwise push it back
# to the PEP 695 form that breaks CodeQL. See GH #134 / PR #138.
_T = TypeVar("_T")

# Serializes lazy executor creation across instances. Creation is rare (once per
# backend instance), so a single shared lock has no meaningful contention cost.
_MLX_EXECUTOR_INIT_LOCK = threading.Lock()


class MLXThreadAffinityMixin:
    """Marshal decorated MLX GPU methods onto one dedicated owning thread.

    The first :func:`mlx_pinned` call lazily creates a single-worker
    ``ThreadPoolExecutor`` and records its worker-thread id; every later pinned
    call runs on that same thread. A pinned method invoked while *already* on the
    owning thread runs inline (no re-submit), so nested pinned calls cannot
    deadlock the single worker.

    State is created lazily so backends need not call ``super().__init__()``.
    """

    def _ensure_mlx_executor(self) -> ThreadPoolExecutor:
        executor: ThreadPoolExecutor | None = getattr(self, "_mlx_executor", None)
        if executor is not None:
            return executor
        with _MLX_EXECUTOR_INIT_LOCK:
            # Re-check under the lock (another thread may have created it).
            executor = getattr(self, "_mlx_executor", None)
            if executor is not None:
                return executor
            name = getattr(self, "backend_name", "mlx")
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"mlx-{name}")
            # Capture the worker's thread id on the worker itself, so reentrant
            # pinned calls can detect that they are already on the owning thread.
            self._mlx_owning_thread_id: int = executor.submit(threading.get_ident).result()
            self._mlx_executor: ThreadPoolExecutor = executor
            return executor

    def _run_on_mlx_thread(self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
        """Run ``fn`` on this instance's owning MLX thread and return its result.

        Re-raises the callee's exception with its original type and traceback.
        """
        # Reentrancy guard: already on the owning thread → run inline, otherwise
        # the single worker would wait on itself and deadlock.
        if getattr(self, "_mlx_owning_thread_id", None) == threading.get_ident():
            return fn(*args, **kwargs)
        executor = self._ensure_mlx_executor()
        # Future.result() propagates the body's exception unchanged.
        return executor.submit(fn, *args, **kwargs).result()

    def shutdown_mlx_thread(self) -> None:
        """Tear down the owning thread. Idempotent; a later pinned call re-creates it."""
        executor: ThreadPoolExecutor | None = getattr(self, "_mlx_executor", None)
        if executor is not None:
            executor.shutdown(wait=True)
            self._mlx_executor = None
            self._mlx_owning_thread_id = None


def mlx_pinned(method: Callable[..., _T]) -> Callable[..., _T]:  # noqa: UP047
    """Decorator: run a backend method on its instance's owning MLX thread.

    The wrapped method's signature, return value, and exceptions are preserved.
    Apply only to GPU-touching methods (``load``/``unload``/``warmup``/
    ``transcribe``/``transcribe_with_diarization``); leave pure/metadata methods
    (``is_loaded``, ``backend_name``, ...) un-decorated so they stay non-blocking.
    """

    @functools.wraps(method)
    def wrapper(self: MLXThreadAffinityMixin, *args: Any, **kwargs: Any) -> _T:
        return self._run_on_mlx_thread(method, self, *args, **kwargs)

    return wrapper
