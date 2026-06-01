"""Regression test for GH #122: STT backend ``transcribe_with_diarization``
overrides must remain a superset of the base contract.

The bug: ``WhisperXBackend.transcribe_with_diarization()`` had dropped the
``progress_callback`` parameter that ``STTBackend`` declares and that the
file-import route always passes. Python only catches this at call time, so it
shipped — every WhisperX diarization run raised ``TypeError`` and silently fell
back to the slower, more failure-prone two-model path. This test would have
caught it at CI time instead.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import types

import numpy as np
import pytest

# WhisperX import touches torch + soundfile; reuse the conftest torch stub.
pytestmark = pytest.mark.usefixtures("torch_stub")


def _install_soundfile_stub() -> None:
    if "soundfile" not in sys.modules:
        sf = types.ModuleType("soundfile")
        sf.read = lambda *a, **k: (np.zeros(16000, dtype=np.float32), 16000)
        sys.modules["soundfile"] = sf


# Every concrete backend that overrides transcribe_with_diarization. mlx_*
# backends require the `mlx` runtime (Apple Silicon only) and are imported
# best-effort — skipped where unavailable rather than failing the suite.
_BACKENDS = [
    ("server.core.stt.backends.whisperx_backend", "WhisperXBackend"),
    ("server.core.stt.backends.vibevoice_asr_backend", "VibeVoiceASRBackend"),
    ("server.core.stt.backends.mlx_vibevoice_backend", "MLXVibeVoiceBackend"),
]


def _base_param_names() -> set[str]:
    from server.core.stt.backends.base import STTBackend

    sig = inspect.signature(STTBackend.transcribe_with_diarization)
    return {name for name in sig.parameters if name != "self"}


@pytest.mark.parametrize(("module_path", "class_name"), _BACKENDS)
def test_override_signature_is_superset_of_base(module_path: str, class_name: str) -> None:
    _install_soundfile_stub()
    # importorskip returns the module, or skips cleanly if its deps are absent
    # (e.g. the `mlx` runtime off Apple Silicon). Using it instead of a
    # try/except + pytest.skip keeps `module` unconditionally bound, avoiding a
    # CodeQL py/uninitialized-local-variable false positive.
    module = pytest.importorskip(module_path, reason=f"{module_path} not importable in this env")

    from server.core.stt.backends.base import STTBackend

    backend_cls = getattr(module, class_name)
    if backend_cls.transcribe_with_diarization is STTBackend.transcribe_with_diarization:
        pytest.skip(f"{class_name} does not override transcribe_with_diarization")

    override_params = set(inspect.signature(backend_cls.transcribe_with_diarization).parameters)
    # An override accepting **kwargs implicitly satisfies the contract.
    accepts_var_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in inspect.signature(backend_cls.transcribe_with_diarization).parameters.values()
    )
    if accepts_var_kwargs:
        return

    missing = _base_param_names() - override_params
    assert not missing, (
        f"{class_name}.transcribe_with_diarization is missing base params {sorted(missing)} — "
        "callers passing them will raise TypeError at runtime (see GH #122)."
    )


def test_whisperx_accepts_progress_callback_explicitly() -> None:
    """Direct guard for the exact GH #122 regression."""
    _install_soundfile_stub()
    module = importlib.import_module("server.core.stt.backends.whisperx_backend")
    params = inspect.signature(module.WhisperXBackend.transcribe_with_diarization).parameters
    assert "progress_callback" in params, (
        "WhisperXBackend.transcribe_with_diarization must accept progress_callback "
        "(the file-import route passes it)."
    )
