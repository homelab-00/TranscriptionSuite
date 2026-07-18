"""Tests for the whisper.cpp backend's GGML self-download + sidecar-ready path.

Covers the Option-B fix that gives the GGML/Vulkan path parity with the HF
backends: the model is fetched into the shared volume on load if missing, and a
not-yet-ready sidecar (RemoteProtocolError on /load) no longer crashes startup.
"""

from __future__ import annotations

import contextlib

import httpx
import pytest
from server.core.stt.backends import whispercpp_backend as wb


def test_ensure_rejects_unexpected_filename() -> None:
    """A non-GGML / path-traversal name must be refused before any network I/O."""
    with pytest.raises(RuntimeError, match="unexpected name"):
        wb._ensure_ggml_model_present("../../etc/passwd")
    with pytest.raises(RuntimeError, match="unexpected name"):
        wb._ensure_ggml_model_present("Systran/faster-whisper-large-v3")


def test_ensure_noop_when_models_dir_absent(monkeypatch, tmp_path) -> None:
    """Outside the container layout (no models dir), fetching is left to others."""
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path / "does-not-exist"))

    def _boom(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("httpx.stream should not be called when dir is absent")

    monkeypatch.setattr(wb.httpx, "stream", _boom)
    wb._ensure_ggml_model_present("ggml-small.en.bin")  # no raise, no download


def test_ensure_noop_when_file_present(monkeypatch, tmp_path) -> None:
    """An already-downloaded model must not be re-fetched."""
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))
    (tmp_path / "ggml-small.en.bin").write_bytes(b"already here")

    def _boom(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("httpx.stream should not be called when file exists")

    monkeypatch.setattr(wb.httpx, "stream", _boom)
    wb._ensure_ggml_model_present("ggml-small.en.bin")


def test_ensure_downloads_when_missing(monkeypatch, tmp_path) -> None:
    """A missing model is streamed to the volume and published atomically."""
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))
    captured: dict[str, object] = {}

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, chunk_size: int = 0):
            yield b"ggml-"
            yield b"weights"

    @contextlib.contextmanager
    def _fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["follow_redirects"] = kwargs.get("follow_redirects")
        yield _FakeResp()

    monkeypatch.setattr(wb.httpx, "stream", _fake_stream)
    wb._ensure_ggml_model_present("ggml-small.en.bin")

    target = tmp_path / "ggml-small.en.bin"
    assert target.read_bytes() == b"ggml-weights"
    assert not (tmp_path / "ggml-small.en.bin.tmp").exists()  # tmp cleaned up
    assert captured["url"] == f"{wb._GGML_HF_BASE_URL}/ggml-small.en.bin"
    assert captured["follow_redirects"] is True


def test_ensure_download_failure_cleans_tmp_and_raises(monkeypatch, tmp_path) -> None:
    """A failed download leaves no partial file and raises an actionable error."""
    monkeypatch.setattr(wb, "_GGML_MODELS_DIR", str(tmp_path))

    @contextlib.contextmanager
    def _fake_stream(method, url, **kwargs):
        raise httpx.ConnectError("network down")
        yield  # pragma: no cover

    monkeypatch.setattr(wb.httpx, "stream", _fake_stream)
    with pytest.raises(RuntimeError, match="Failed to download GGML model"):
        wb._ensure_ggml_model_present("ggml-small.en.bin")
    assert not (tmp_path / "ggml-small.en.bin.tmp").exists()
    assert not (tmp_path / "ggml-small.en.bin").exists()


def test_load_tolerates_remote_protocol_error(monkeypatch) -> None:
    """A not-ready sidecar (disconnect on /load) must not crash load()."""
    backend = wb.WhisperCppBackend()
    # Skip the real download and readiness wait — we only exercise /load handling.
    monkeypatch.setattr(wb, "_ensure_ggml_model_present", lambda *_a, **_k: None)
    monkeypatch.setattr(backend, "_wait_for_sidecar_ready", lambda *_a, **_k: None)

    class _FakeClient:
        def post(self, *_a, **_k):
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(backend, "_ensure_client", lambda: _FakeClient())

    backend.load(model_name="ggml-small.en.bin", device="cpu")
    assert backend.is_loaded() is True


def test_external_model_management_skips_download_and_load(monkeypatch) -> None:
    """vulkan-wsl2: load() must NOT download or POST /load — the host exe owns
    model loading. It should only wait for the sidecar and mark itself loaded."""
    backend = wb.WhisperCppBackend()
    monkeypatch.setenv("WHISPERCPP_EXTERNAL_MODEL_MGMT", "1")

    def _fail_download(*_a, **_k):
        raise AssertionError("must not download the GGML in external management mode")

    def _fail_client(*_a, **_k):
        raise AssertionError("must not POST /load in external management mode")

    monkeypatch.setattr(wb, "_ensure_ggml_model_present", _fail_download)
    monkeypatch.setattr(backend, "_ensure_client", _fail_client)

    waited: list[float] = []
    monkeypatch.setattr(
        backend, "_wait_for_sidecar_ready", lambda timeout_s: waited.append(timeout_s)
    )

    backend.load(model_name="ggml-small.en.bin", device="cpu")

    assert backend.is_loaded() is True
    # Waited exactly once, with the full cold-start budget (host relaunch).
    assert waited == [wb._SIDECAR_READY_TIMEOUT]


def test_external_model_management_disabled_by_default(monkeypatch) -> None:
    """Absent the env flag, the normal download + /load path runs."""
    monkeypatch.delenv("WHISPERCPP_EXTERNAL_MODEL_MGMT", raising=False)
    assert wb._external_model_management() is False
    monkeypatch.setenv("WHISPERCPP_EXTERNAL_MODEL_MGMT", "1")
    assert wb._external_model_management() is True
    monkeypatch.setenv("WHISPERCPP_EXTERNAL_MODEL_MGMT", "0")
    assert wb._external_model_management() is False
