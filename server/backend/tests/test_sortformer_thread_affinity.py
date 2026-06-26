"""SortformerEngine MLX thread-affinity tests (GH #124 — extends GH #134).

Sortformer is a second Metal-native MLX consumer: the #134 pin covered only the
four MLX STT backends, but the diarization path dispatches across interchangeable
``asyncio.to_thread`` workers while the engine is materialized elsewhere, so the
same cross-thread "no stream (gpu,0)" hazard applies. These tests prove that
``SortformerEngine`` funnels ``load`` + ``diarize_audio`` onto one dedicated
owning thread distinct from the callers — WITHOUT mlx-audio or Apple-Silicon
hardware (fakes record ``threading.get_ident()``).
"""

from __future__ import annotations

import sys
import threading
import types

import numpy as np


def _run_in_new_thread(fn: object) -> dict:
    box: dict = {}

    def run() -> None:
        box["tid"] = threading.get_ident()
        box["ret"] = fn()

    t = threading.Thread(target=run)
    t.start()
    t.join()
    return box


class _FakeSeg:
    def __init__(self, start: float, end: float, speaker: str) -> None:
        self.start, self.end, self.speaker = start, end, speaker


class _FakeResult:
    def __init__(self, segs: list) -> None:
        self.segments = segs


def _make_engine(monkeypatch, events: list):
    """Build a SortformerEngine with mlx-audio / soundfile / mlx.core faked out."""
    import server.core.sortformer_engine as se

    monkeypatch.setattr(se, "HAS_MLX_AUDIO", True)

    class _FakeModel:
        def generate_stream(self, path, chunk_duration, threshold):  # noqa: ANN001
            events.append(("generate", threading.get_ident()))
            yield _FakeResult([_FakeSeg(0.0, 1.0, "0"), _FakeSeg(1.0, 2.0, "1")])

    def _fake_load(name):  # noqa: ANN001
        events.append(("load", threading.get_ident()))
        return _FakeModel()

    monkeypatch.setattr(se, "_load_sortformer", _fake_load)

    class _FakeCfg:
        def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return {}

    monkeypatch.setattr(se, "get_config", lambda: _FakeCfg())

    # diarize_audio / unload do function-level `import soundfile` / `import mlx.core`.
    fake_sf = types.ModuleType("soundfile")
    fake_sf.write = lambda *a, **k: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "soundfile", fake_sf)
    fake_mlx = types.ModuleType("mlx")
    fake_core = types.ModuleType("mlx.core")
    fake_core.clear_cache = lambda: None  # type: ignore[attr-defined]
    fake_mlx.core = fake_core  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", fake_mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", fake_core)

    return se.SortformerEngine()


def test_sortformer_inherits_affinity_mixin() -> None:
    from server.core.sortformer_engine import SortformerEngine
    from server.core.stt.backends.mlx_thread_pin import MLXThreadAffinityMixin

    assert issubclass(SortformerEngine, MLXThreadAffinityMixin)


def test_sortformer_load_and_diarize_share_one_owning_thread(monkeypatch) -> None:
    events: list[tuple[str, int]] = []
    engine = _make_engine(monkeypatch, events)

    load_caller = _run_in_new_thread(engine.load)
    audio = np.zeros(16000, dtype=np.float32)
    diar_caller = _run_in_new_thread(lambda: engine.diarize_audio(audio, 16000, num_speakers=2))

    owning_ids = {tid for (_, tid) in events}
    assert len(owning_ids) == 1, "load + generate_stream must run on one owning thread"
    owning = owning_ids.pop()
    # The owning thread is still alive (executor not shut down), so it cannot
    # collide with the now-exited caller threads.
    assert owning != load_caller["tid"]
    assert owning != diar_caller["tid"]
    assert diar_caller["ret"].num_speakers == 2


def test_sortformer_shutdown_mlx_thread_is_idempotent(monkeypatch) -> None:
    events: list[tuple[str, int]] = []
    engine = _make_engine(monkeypatch, events)
    engine.load()
    engine.shutdown_mlx_thread()
    engine.shutdown_mlx_thread()  # second call must not raise
