"""Every model download the server performs must report to the download bar (GH-318).

Only the main transcription model was tracked. The Live Mode model, the
diarization pipelines, the WhisperX alignment models and the whisper.cpp GGML
file all downloaded with no progress at all - and the GGML fetch was reported
as "loaded from cache" because it streams with httpx, which the tqdm
interception cannot see.

Each test drives the real load site with a fake download inside it and checks
the events that come out.
"""

from __future__ import annotations

import contextlib
import importlib
import sys
import types
from typing import Any

import numpy as np
import pytest

pytestmark = pytest.mark.usefixtures("torch_stub")


@pytest.fixture()
def events(monkeypatch):
    """Capture every download event."""
    calls: list[dict[str, Any]] = []

    def fake_emit(id: str, category: str, label: str, status: str = "active", **extra):
        calls.append({"id": id, "category": category, "label": label, "status": status, **extra})

    monkeypatch.setattr("server.core.download_progress.emit_event", fake_emit)
    return calls


def _simulate_download(size: int = 4_000_000) -> None:
    """What huggingface_hub does while a file downloads: one byte bar, updated to the end."""
    from server.core.download_progress import _ProgressTqdm

    bar = _ProgressTqdm(total=size, unit="B")
    bar.update(size)


def _completed(events: list[dict[str, Any]]) -> dict[str, Any]:
    done = [e for e in events if e["status"] == "complete"]
    assert done, f"no completion event in {events}"
    return done[-1]


# The Live Mode / main engine load site is covered in test_stt_engine_helpers.py,
# which carries the stubs the engine module needs to import.


# ── PyAnnote diarization ───────────────────────────────────────────────


class _FakePipeline:
    @classmethod
    def from_pretrained(cls, _model: str, **_kwargs: Any) -> _FakePipeline:
        _simulate_download(30_000_000)
        return cls()

    def to(self, _device: Any) -> _FakePipeline:
        return self


def _bare_diarization_engine(module, model: str = "pyannote/speaker-diarization-community-1"):
    engine = object.__new__(module.DiarizationEngine)
    engine.model = model
    engine.hf_token = "hf_test"
    engine.device = "cpu"
    engine._pipeline = None
    engine._loaded = False
    return engine


def test_pyannote_load_reports_a_diarization_model_download(monkeypatch, events):
    module = importlib.import_module("server.core.diarization_engine")
    monkeypatch.setattr(module, "Pipeline", _FakePipeline)
    monkeypatch.setattr(module, "HAS_TORCH", False)

    engine = _bare_diarization_engine(module)
    engine.load()

    assert engine.is_loaded()
    done = _completed(events)
    assert done["id"] == "diarization-model-load-pyannote--speaker-diarization-community-1"
    assert done["kind"] == "diarization-model"
    assert done["name"] == "Diarization model (speaker-diarization-community-1)"
    assert done["totalBytes"] == 30_000_000


def test_pyannote_load_survives_a_broken_progress_channel(monkeypatch):
    """A diarization load runs in the middle of a job. It must not depend on tracking."""
    module = importlib.import_module("server.core.diarization_engine")
    monkeypatch.setattr(module, "Pipeline", _FakePipeline)
    monkeypatch.setattr(module, "HAS_TORCH", False)
    monkeypatch.setattr(
        "server.core.download_progress.emit_event",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("events file gone")),
    )

    engine = _bare_diarization_engine(module)
    engine.load()

    assert engine.is_loaded()


# ── Sortformer diarization (Metal) ─────────────────────────────────────


def test_sortformer_load_reports_a_diarization_model_download(monkeypatch, events):
    module = importlib.import_module("server.core.sortformer_engine")

    def fake_load(_model_name: str) -> object:
        _simulate_download(12_000_000)
        return object()

    monkeypatch.setattr(module, "HAS_MLX_AUDIO", True)
    monkeypatch.setattr(module, "_load_sortformer", fake_load)

    engine = module.SortformerEngine()
    try:
        engine.load()
        assert engine.is_loaded()
    finally:
        engine.shutdown_mlx_thread()

    done = _completed(events)
    assert done["kind"] == "diarization-model"
    assert done["id"] == "diarization-model-load-mlx-community--diar_sortformer_4spk-v1-fp32"
    assert done["totalBytes"] == 12_000_000


# ── WhisperX alignment (loads lazily, in the middle of a transcription) ─


def _import_whisperx_backend():
    if "soundfile" not in sys.modules:
        soundfile_stub = types.ModuleType("soundfile")
        soundfile_stub.read = lambda *args, **kwargs: (np.zeros(16000, dtype=np.float32), 16000)
        sys.modules["soundfile"] = soundfile_stub
    return importlib.import_module("server.core.stt.backends.whisperx_backend")


class _FakeWhisperX:
    def __init__(self) -> None:
        self.aligned_with: Any = None

    def load_align_model(self, *, language_code: str, device: str):
        _simulate_download(1_200_000_000)
        return object(), {"language": language_code}

    def align(self, segments, model, metadata, audio, device, **_kwargs):
        self.aligned_with = metadata
        return {"segments": segments, "aligned": True}


def _whisperx_backend(module):
    backend = object.__new__(module.WhisperXBackend)
    backend._device = "cpu"
    backend._align_model = None
    backend._align_metadata = None
    backend._align_language = None
    return backend


def test_alignment_model_load_reports_an_alignment_download(monkeypatch, events):
    module = _import_whisperx_backend()
    fake = _FakeWhisperX()
    monkeypatch.setattr(module, "_import_whisperx_modules", lambda: (fake, None))

    result = _whisperx_backend(module)._align(
        {"segments": []}, np.zeros(16000, dtype=np.float32), "el"
    )

    assert result["aligned"] is True
    done = _completed(events)
    assert done["id"] == "alignment-load-el"
    assert done["kind"] == "alignment-model"
    assert done["name"] == "Alignment model (el)"
    assert done["totalBytes"] == 1_200_000_000


def test_alignment_survives_every_way_tracking_can_break(monkeypatch):
    """The alignment model loads while a transcription is in flight. A broken
    progress channel, a failed patch or a misbehaving tracker must cost
    nothing: the transcription still gets its aligned result."""
    module = _import_whisperx_backend()
    fake = _FakeWhisperX()
    monkeypatch.setattr(module, "_import_whisperx_modules", lambda: (fake, None))

    import server.core.download_progress as dp

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("tracking is broken")

    monkeypatch.setattr(dp, "emit_event", boom)
    monkeypatch.setattr(dp, "_patch_hf_tqdm", boom)
    monkeypatch.setattr(dp._DownloadTracker, "on_tqdm_update", boom)
    monkeypatch.setattr(dp._DownloadTracker, "on_total_delta", boom)

    result = _whisperx_backend(module)._align(
        {"segments": [{"text": "γεια"}]}, np.zeros(16000, dtype=np.float32), "el"
    )

    assert result == {"segments": [{"text": "γεια"}], "aligned": True}
    assert fake.aligned_with == {"language": "el"}


def test_cached_alignment_model_reports_no_download(monkeypatch, events):
    module = _import_whisperx_backend()

    class _CachedWhisperX(_FakeWhisperX):
        def load_align_model(self, *, language_code: str, device: str):
            return object(), {"language": language_code}  # nothing downloaded

    monkeypatch.setattr(module, "_import_whisperx_modules", lambda: (_CachedWhisperX(), None))

    _whisperx_backend(module)._align({"segments": []}, np.zeros(16000, dtype=np.float32), "en")

    assert _completed(events)["downloaded"] is False
    assert not any(e.get("phase") == "download" for e in events)


# ── whisper.cpp GGML (streams with httpx, invisible to tqdm) ────────────


class _FakeGgmlResponse:
    def __init__(self, chunks: list[bytes], content_length: bool = True) -> None:
        self._chunks = chunks
        self.headers = (
            {"content-length": str(sum(len(c) for c in chunks))} if content_length else {}
        )

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int = 0):
        yield from self._chunks


def _patch_ggml_stream(monkeypatch, wb, response) -> None:
    @contextlib.contextmanager
    def _fake_stream(_method, _url, **_kwargs):
        yield response

    monkeypatch.setattr(wb.httpx, "stream", _fake_stream)


def test_ggml_download_reports_bytes(monkeypatch, tmp_path, events):
    wb = importlib.import_module("server.core.stt.backends.whispercpp_backend")
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))
    _patch_ggml_stream(monkeypatch, wb, _FakeGgmlResponse([b"a" * 2048, b"b" * 2048]))

    assert wb._ensure_ggml_model_present("ggml-small.en.bin") is True

    done = _completed(events)
    assert done["id"] == "ggml-model-load-ggml-small.en.bin"
    assert done["kind"] == "ggml-model"
    assert done["downloaded"] is True
    assert done["downloadedBytes"] == 4096
    assert done["totalBytes"] == 4096


def test_ggml_download_inside_a_model_load_is_no_longer_a_cache_hit(monkeypatch, tmp_path, events):
    """The enclosing model load used to end with 'loaded from cache' after a
    real multi-gigabyte download, because httpx never touches a tqdm bar."""
    wb = importlib.import_module("server.core.stt.backends.whispercpp_backend")
    from server.core.download_progress import track_model_download

    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))
    _patch_ggml_stream(monkeypatch, wb, _FakeGgmlResponse([b"a" * 4096]))

    with track_model_download("ggml-small.en.bin"):
        wb._ensure_ggml_model_present("ggml-small.en.bin")

    done = _completed(events)
    assert done["label"] == "ggml-small.en.bin ready"
    assert done["downloaded"] is True
    assert done["downloadedBytes"] == 4096


def test_ggml_download_without_content_length_still_counts_bytes(monkeypatch, tmp_path, events):
    wb = importlib.import_module("server.core.stt.backends.whispercpp_backend")
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))
    _patch_ggml_stream(monkeypatch, wb, _FakeGgmlResponse([b"a" * 4096], content_length=False))

    wb._ensure_ggml_model_present("ggml-small.en.bin")

    done = _completed(events)
    assert done["downloaded"] is True
    assert done["downloadedBytes"] == 4096
    assert (tmp_path / "ggml-small.en.bin").read_bytes() == b"a" * 4096


def test_ggml_already_present_reports_nothing(monkeypatch, tmp_path, events):
    wb = importlib.import_module("server.core.stt.backends.whispercpp_backend")
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))
    (tmp_path / "ggml-small.en.bin").write_bytes(b"x")

    assert wb._ensure_ggml_model_present("ggml-small.en.bin") is False
    assert events == []
