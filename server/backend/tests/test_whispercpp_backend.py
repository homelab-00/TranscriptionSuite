"""Tests for WhisperCppBackend — HTTP client to whisper-server sidecar."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest
from server.core.stt.backends.base import BackendTranscriptionInfo
from server.core.stt.backends.whispercpp_backend import (
    WhisperCppBackend,
    _audio_to_wav_bytes,
    _resolve_server_url,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend() -> WhisperCppBackend:
    return WhisperCppBackend()


@pytest.fixture()
def mock_httpx():
    """Patch httpx.Client so no real HTTP calls are made."""
    mock_client = MagicMock()
    with patch("server.core.stt.backends.whispercpp_backend.httpx") as httpx_mod:
        httpx_mod.Client.return_value = mock_client
        yield mock_client


@pytest.fixture()
def loaded_backend(backend: WhisperCppBackend, mock_httpx: MagicMock) -> WhisperCppBackend:
    """Return a backend that has already been loaded."""
    mock_httpx.post.return_value = MagicMock(status_code=200)
    with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
        backend.load("ggml-large-v3.bin", "cpu")
    return backend


# ---------------------------------------------------------------------------
# _resolve_server_url
# ---------------------------------------------------------------------------


class TestResolveServerUrl:
    def test_env_var_takes_precedence(self):
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://my-server:9999"}):
            assert _resolve_server_url() == "http://my-server:9999"

    def test_strips_trailing_slash(self):
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://s:8080/"}):
            assert _resolve_server_url() == "http://s:8080"

    def test_falls_back_to_default(self):
        with patch.dict("os.environ", {}, clear=True):
            url = _resolve_server_url()
            assert "whisper-server" in url


# ---------------------------------------------------------------------------
# _audio_to_wav_bytes
# ---------------------------------------------------------------------------


class TestAudioToWavBytes:
    def test_produces_valid_wav_header(self):
        audio = np.zeros(16000, dtype=np.float32)
        wav = _audio_to_wav_bytes(audio, 16000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"

    def test_correct_data_size(self):
        audio = np.zeros(8000, dtype=np.float32)
        wav = _audio_to_wav_bytes(audio, 16000)
        # data chunk size = 8000 samples * 2 bytes
        assert len(wav) == 44 + 8000 * 2


# ---------------------------------------------------------------------------
# WhisperCppBackend — lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_not_loaded_initially(self, backend: WhisperCppBackend):
        assert not backend.is_loaded()

    def test_load_marks_loaded(self, loaded_backend: WhisperCppBackend):
        assert loaded_backend.is_loaded()

    def test_unload_resets_state(self, loaded_backend: WhisperCppBackend):
        loaded_backend.unload()
        assert not loaded_backend.is_loaded()

    def test_backend_name(self, backend: WhisperCppBackend):
        assert backend.backend_name == "whispercpp"

    def test_supports_translation(self, backend: WhisperCppBackend):
        assert backend.supports_translation() is True

    def test_load_tolerates_server_error(self, backend: WhisperCppBackend, mock_httpx: MagicMock):
        """load() should succeed even if /load endpoint fails (server may pre-load)."""
        mock_httpx.post.side_effect = Exception("unexpected 500 from server")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            backend.load("ggml-base.bin", "cpu")
        assert backend.is_loaded()

    def test_load_raises_on_connect_error(self, backend: WhisperCppBackend, mock_httpx: MagicMock):
        """load() should raise RuntimeError with actionable message when sidecar is unreachable."""
        mock_httpx.post.side_effect = httpx.ConnectError("DNS lookup failed")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            with pytest.raises(RuntimeError, match="whisper.cpp sidecar is not reachable"):
                backend.load("ggml-base.bin", "cpu")
        assert not backend.is_loaded()

    def test_load_raises_on_dns_oserror(self, backend: WhisperCppBackend, mock_httpx: MagicMock):
        """load() should raise RuntimeError when DNS resolution fails with OSError."""
        mock_httpx.post.side_effect = OSError(5, "No address associated with hostname")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            with pytest.raises(RuntimeError, match="whisper.cpp sidecar is not reachable"):
                backend.load("ggml-base.bin", "cpu")


# ---------------------------------------------------------------------------
# WhisperCppBackend — transcribe
# ---------------------------------------------------------------------------


class TestTranscribe:
    def test_raises_when_not_loaded(self, backend: WhisperCppBackend):
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="not loaded"):
            backend.transcribe(audio)

    def test_sends_multipart_post(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert isinstance(segments, list)
        assert isinstance(info, BackendTranscriptionInfo)

    def test_parses_segments(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "segments": [
                        {
                            "text": " Hello world",
                            "t0": 0.0,
                            "t1": 2.5,
                            "tokens": [
                                {"text": "Hello", "t0": 0, "t1": 100, "p": 0.95},
                                {"text": "world", "t0": 110, "t1": 250, "p": 0.90},
                            ],
                        }
                    ],
                    "language": "en",
                }
            ),
        )
        audio = np.zeros(32000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert len(segments) == 1
        assert segments[0].text == "Hello world"
        assert len(segments[0].words) == 2
        assert segments[0].words[0]["word"] == "Hello"
        assert info.language == "en"

    def test_translate_task_sends_flag(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, task="translate")
        call_kwargs = mock_httpx.post.call_args
        assert call_kwargs is not None
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
        assert data.get("translate") == "true"

    def test_transcribe_raises_on_connect_error(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """transcribe() should raise RuntimeError with actionable message when sidecar is down."""
        mock_httpx.post.side_effect = httpx.ConnectError("connection refused")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="whisper.cpp sidecar is not reachable"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_dns_oserror(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """transcribe() should raise RuntimeError when DNS resolution fails."""
        mock_httpx.post.side_effect = OSError(5, "No address associated with hostname")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="whisper.cpp sidecar is not reachable"):
            loaded_backend.transcribe(audio)


# ---------------------------------------------------------------------------
# WhisperCppBackend — warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_warmup_when_loaded(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
        loaded_backend.warmup()  # should not raise

    def test_warmup_noop_when_not_loaded(self, backend: WhisperCppBackend):
        backend.warmup()  # should not raise


# ---------------------------------------------------------------------------
# WhisperCppBackend — diarization
# ---------------------------------------------------------------------------


class TestDiarization:
    def test_returns_none(self, backend: WhisperCppBackend):
        audio = np.zeros(16000, dtype=np.float32)
        result = backend.transcribe_with_diarization(audio)
        assert result is None
