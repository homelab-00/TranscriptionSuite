"""Tests for ``ModelManager.ensure_transcription_loaded`` (Issue #76).

Covers the four I/O matrix scenarios in
``_bmad-output/implementation-artifacts/spec-gh-76-fix-stt-not-loaded.md``:

1. Healthy steady state — backend attached, no reload triggered.
2. Backend silently unloaded — reload is triggered, engine returned with
   backend re-attached.
3. Engine never created (preload failed) — reload triggers creation; on
   success the engine is returned.
4. Reload raises ``BackendDependencyError`` — propagates unchanged for the
   route layer to map to HTTP 503 with the remedy.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.usefixtures("torch_stub")


def _build_manager(tmp_path: Path):
    """Construct a ModelManager with GPU/heavy imports stubbed out."""
    from server.core.model_manager import ModelManager

    config = {"main_transcriber": {"model": "tiny"}}

    with (
        patch(
            "server.core.model_manager.resolve_main_transcriber_model",
            return_value="tiny",
        ),
        patch("server.core.audio_utils.check_cuda_available", return_value=False),
        patch("server.core.audio_utils.get_gpu_memory_info", return_value={}),
        patch.dict(
            "os.environ",
            {"BOOTSTRAP_STATUS_FILE": str(tmp_path / "nope.json")},
            clear=False,
        ),
    ):
        return ModelManager(config)


def _attach_fake_loaded_engine(mgr):
    """Inject a fake engine with a non-None backend, mimicking a healthy state."""
    fake_backend = MagicMock(name="fake_backend")
    engine = SimpleNamespace(
        _backend=fake_backend,
        _model_loaded=True,
        is_loaded=lambda: True,
        model_name="tiny",
    )
    mgr._transcription_engine = engine
    return engine


class TestEnsureTranscriptionLoaded:
    def test_returns_existing_engine_when_backend_attached(self, tmp_path: Path):
        """Scenario 1: healthy state — no reload should occur."""
        mgr = _build_manager(tmp_path)
        engine = _attach_fake_loaded_engine(mgr)

        with patch.object(mgr, "load_transcription_model") as load_spy:
            result = mgr.ensure_transcription_loaded()

        assert result is engine
        load_spy.assert_not_called()

    def test_reloads_when_backend_detached(self, tmp_path: Path):
        """Scenario 2: backend was unloaded — reload runs and engine returns healthy."""
        mgr = _build_manager(tmp_path)

        # Engine exists but backend was detached (mimics post-Live-Mode state)
        detached_engine = SimpleNamespace(
            _backend=None,
            _model_loaded=False,
            is_loaded=lambda: False,
            model_name="tiny",
        )
        mgr._transcription_engine = detached_engine

        # After load_transcription_model fires, swap in a "now-loaded" engine
        loaded_engine = SimpleNamespace(
            _backend=MagicMock(name="reattached_backend"),
            _model_loaded=True,
            is_loaded=lambda: True,
            model_name="tiny",
        )

        def fake_load(*_a, **_kw):
            mgr._transcription_engine = loaded_engine

        with patch.object(mgr, "load_transcription_model", side_effect=fake_load) as load_spy:
            result = mgr.ensure_transcription_loaded()

        assert result is loaded_engine
        load_spy.assert_called_once()

    def test_reloads_when_engine_never_created(self, tmp_path: Path):
        """Scenario 3: preload failed at startup; engine is None."""
        mgr = _build_manager(tmp_path)
        assert mgr._transcription_engine is None

        loaded_engine = _attach_fake_loaded_engine(mgr)
        # Detach immediately so we can prove the helper called load_transcription_model
        mgr._transcription_engine = None

        def fake_load(*_a, **_kw):
            mgr._transcription_engine = loaded_engine

        with patch.object(mgr, "load_transcription_model", side_effect=fake_load) as load_spy:
            result = mgr.ensure_transcription_loaded()

        assert result is loaded_engine
        load_spy.assert_called_once()

    def test_propagates_backend_dependency_error(self, tmp_path: Path):
        """Scenario 4: reload fails with BackendDependencyError — must propagate."""
        from server.core.stt.backends.base import BackendDependencyError

        mgr = _build_manager(tmp_path)

        dep_err = BackendDependencyError(
            "NeMo toolkit is required for NVIDIA Parakeet models but is not installed",
            backend_type="nemo",
            remedy="Set INSTALL_NEMO=true in your Docker environment and restart.",
        )

        with patch.object(mgr, "load_transcription_model", side_effect=dep_err):
            with pytest.raises(BackendDependencyError) as excinfo:
                mgr.ensure_transcription_loaded()

        assert excinfo.value.backend_type == "nemo"
        assert "INSTALL_NEMO=true" in excinfo.value.remedy

    def test_propagates_generic_load_failure(self, tmp_path: Path):
        """Generic reload failure (e.g., transient OOM) propagates unchanged."""
        mgr = _build_manager(tmp_path)

        with patch.object(
            mgr,
            "load_transcription_model",
            side_effect=RuntimeError("CUDA out of memory"),
        ):
            with pytest.raises(RuntimeError, match="CUDA out of memory"):
                mgr.ensure_transcription_loaded()

    def test_reload_triggered_when_backend_is_none_but_is_loaded_lies(self, tmp_path: Path):
        """Defense-in-depth: ``_backend is None`` overrides a stale ``is_loaded()``."""
        mgr = _build_manager(tmp_path)

        inconsistent = SimpleNamespace(
            _backend=None,
            _model_loaded=True,  # stale flag
            is_loaded=lambda: True,  # lies
            model_name="tiny",
        )
        mgr._transcription_engine = inconsistent

        loaded_engine = SimpleNamespace(
            _backend=MagicMock(),
            _model_loaded=True,
            is_loaded=lambda: True,
            model_name="tiny",
        )

        def fake_load(*_a, **_kw):
            mgr._transcription_engine = loaded_engine

        with patch.object(mgr, "load_transcription_model", side_effect=fake_load) as load_spy:
            result = mgr.ensure_transcription_loaded()

        assert result is loaded_engine
        load_spy.assert_called_once()

    def test_raises_when_reload_lies_and_backend_still_none(self, tmp_path: Path):
        """Post-reload guard: if ``_backend`` is still None after load, raise."""
        mgr = _build_manager(tmp_path)

        broken_engine = SimpleNamespace(
            _backend=None,
            _model_loaded=False,
            is_loaded=lambda: False,
            model_name="tiny",
        )
        mgr._transcription_engine = broken_engine

        # Simulate a load_transcription_model that returns without raising but
        # leaves the engine's _backend unchanged (state desync bug).
        with patch.object(mgr, "load_transcription_model", return_value=None):
            with pytest.raises(RuntimeError, match="still detached after reload"):
                mgr.ensure_transcription_loaded()

    def test_concurrent_callers_trigger_exactly_one_reload(self, tmp_path: Path):
        """Two threads hitting ensure_transcription_loaded should serialize on the lock.

        Only one ``load_transcription_model`` call should occur; the second
        caller sees the (now-loaded) engine and short-circuits.
        """
        import threading
        import time

        mgr = _build_manager(tmp_path)
        # Start with a detached engine.
        detached = SimpleNamespace(
            _backend=None,
            _model_loaded=False,
            is_loaded=lambda: False,
            model_name="tiny",
        )
        mgr._transcription_engine = detached

        loaded = SimpleNamespace(
            _backend=MagicMock(),
            _model_loaded=True,
            is_loaded=lambda: True,
            model_name="tiny",
        )

        load_call_count = 0

        def slow_load(*_a, **_kw):
            nonlocal load_call_count
            load_call_count += 1
            # Sleep just long enough to force the second caller to wait on the
            # lock rather than race into a duplicate load.
            time.sleep(0.05)
            mgr._transcription_engine = loaded

        results: list[object] = []
        errors: list[BaseException] = []

        def worker():
            try:
                results.append(mgr.ensure_transcription_loaded())
            except BaseException as err:
                errors.append(err)

        with patch.object(mgr, "load_transcription_model", side_effect=slow_load):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

        assert not errors, f"unexpected errors from concurrent callers: {errors}"
        assert load_call_count == 1, f"expected exactly one load call, got {load_call_count}"
        assert len(results) == 2
        assert results[0] is loaded
        assert results[1] is loaded
