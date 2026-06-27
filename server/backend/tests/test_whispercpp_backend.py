"""Tests for WhisperCppBackend — HTTP client to whisper-server sidecar."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest
from server.core.stt.backends.base import PartialTranscriptionError
from server.core.stt.backends.whispercpp_backend import (
    _INFERENCE_TIMEOUT,
    _MAX_CHUNK_DURATION_CEILING_S,
    _MAX_CHUNK_DURATION_S,
    _MAX_SEGMENTS_PER_AUDIO_SECOND,
    _MAX_WORDS_PER_AUDIO_SECOND,
    _SEGMENT_CAP_FLOOR,
    _TIMEOUT_SECONDS_PER_AUDIO_SECOND,
    _WORDS_CAP_FLOOR,
    WhisperCppBackend,
    WhisperCppResponseError,
    _audio_to_wav_bytes,
    _coerce_float,
    _inference_timeout_for,
    _resolve_chunk_duration_config,
    _resolve_server_url,
    _resolve_timeout_config,
    _sanitize_for_error_preview,
    _sanitize_language_code,
    _segment_cap_for,
    _validate_server_url,
    _word_cap_for,
)

# ---------------------------------------------------------------------------
# /inference response seam (GH #193)
# ---------------------------------------------------------------------------
#
# GH #193: production will read the /inference response via client.stream(...)
# (accumulating resp.iter_bytes() under a byte ceiling) instead of
# client.post(...) + resp.json(). To make that switch a ONE-LINE change here
# (flip _INFERENCE_METHOD), _inference_response() builds a DUAL-CAPABLE mock
# response usable by BOTH read paths:
#   * legacy post path: resp.json() returns the payload
#   * streaming path:   `with ... as resp: resp.iter_bytes()` yields the body
# /load still uses client.post directly, so its mocks stay on .post.
_INFERENCE_METHOD = "stream"  # production reads /inference via client.stream() (GH #193)


def _inf(mock_httpx: MagicMock) -> MagicMock:
    """The mocked httpx.Client method production uses to call /inference."""
    return getattr(mock_httpx, _INFERENCE_METHOD)


def _inference_response(
    payload: dict | None = None,
    *,
    raw: bytes | None = None,
    status_code: int = 200,
    headers: dict | None = None,
    raise_status: Exception | None = None,
) -> MagicMock:
    """Build a mock /inference response that works for BOTH the post path
    (resp.json()) and the stream path (context manager + resp.iter_bytes()).
    Pass `raw=` for a non-JSON body (resp.json() then raises ValueError and the
    streamed bytes fail json.loads). Pass `raise_status=` to make
    resp.raise_for_status() raise."""
    body = raw if raw is not None else json.dumps({} if payload is None else payload).encode()
    resp = MagicMock(status_code=status_code, content=body)
    resp.headers = dict(headers or {})
    if raise_status is not None:
        resp.raise_for_status.side_effect = raise_status
    else:
        resp.raise_for_status.return_value = None
    if raw is not None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = {} if payload is None else payload
    resp.iter_bytes.return_value = [body]
    # Context-manager protocol for the future streaming path.
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _inference_url(mock_httpx: MagicMock) -> str:
    """The URL of the last /inference call, regardless of post-vs-stream shape.
    post(url, ...) puts the url at args[0]; stream("POST", url, ...) at args[1]."""
    call = _inf(mock_httpx).call_args
    assert call is not None, "expected an /inference call to have been issued"
    if _INFERENCE_METHOD == "stream":
        return call.args[1] if len(call.args) > 1 else call.kwargs.get("url", "")
    return call.args[0] if call.args else call.kwargs.get("url", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend() -> WhisperCppBackend:
    return WhisperCppBackend()


@pytest.fixture()
def mock_httpx():
    """Patch httpx.Client so no real HTTP calls are made.

    IMPORTANT: only replace the ``Client`` attribute, not the whole ``httpx``
    module. The production code catches real exception classes
    (``httpx.NetworkError``, ``httpx.TimeoutException``, ``HTTPStatusError``);
    if those were replaced with MagicMocks the ``except`` clause would fail
    with ``TypeError: catching classes that do not inherit from
    BaseException``.

    PATCH-TARGET NOTE: the production code does ``self._client =
    httpx.Client(...)`` through the module-level ``httpx`` name. If a
    refactor changes that to ``from httpx import Client`` and ``Client(...)``
    directly, this patch silently stops applying and every test runs against
    real httpx. ``test_mock_httpx_patches_the_call_site`` below pins the
    coupling so such a refactor fails loudly.
    """
    mock_client = MagicMock()
    with patch(
        "server.core.stt.backends.whispercpp_backend.httpx.Client",
        return_value=mock_client,
    ):
        yield mock_client


@pytest.fixture()
def loaded_backend(backend: WhisperCppBackend, mock_httpx: MagicMock) -> WhisperCppBackend:
    """Return a backend that has already been loaded."""
    mock_httpx.post.return_value = MagicMock(status_code=200)
    with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
        backend.load("ggml-large-v3.bin", "cpu")
    # /load consumed the first POST; reset so transcribe-time assertions only
    # see the /inference call.
    mock_httpx.reset_mock()
    return backend


def _post_data(mock_httpx: MagicMock) -> dict:
    """Return the ``data`` kwarg of the last POST call on the mocked client."""
    call = _inf(mock_httpx).call_args
    assert call is not None, "expected a POST to have been issued"
    return call.kwargs.get("data") or call[1].get("data", {}) or {}


def _seconds_of_audio(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * 16000), dtype=np.float32)


# ---------------------------------------------------------------------------
# _resolve_server_url
# ---------------------------------------------------------------------------


class TestResolveServerUrl:
    def test_env_var_takes_precedence(self):
        """The env var wins even when config has a competing value.

        The previous version of this test did not mock config, so a swap
        of the env-read and config-read branch order would have passed
        silently. We now mock config to return a *different* URL and
        assert the env value is returned.
        """
        cfg = MagicMock()
        cfg.get.return_value = "http://from-config-not-picked:1111"
        with (
            patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://my-server:9999"}),
            patch("server.config.get_config", return_value=cfg),
        ):
            assert _resolve_server_url() == "http://my-server:9999"

    def test_strips_trailing_slash(self):
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://s:8080/"}):
            assert _resolve_server_url() == "http://s:8080"

    def test_falls_back_to_default(self):
        with patch.dict("os.environ", {}, clear=True):
            url = _resolve_server_url()
            assert "whisper-server" in url

    def test_reads_from_config_when_env_missing(self):
        cfg = MagicMock()
        cfg.get.return_value = "http://from-config:8080/"
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("server.config.get_config", return_value=cfg),
        ):
            assert _resolve_server_url() == "http://from-config:8080"
        cfg.get.assert_called_with("whisper_cpp", "server_url")

    def test_config_read_exception_falls_back_to_default(self):
        """A broken config loader must not break URL resolution.

        NOTE: we patch ``server.config.get_config`` — the name at its
        defining module — because ``_resolve_server_url`` imports it
        lazily *inside* the function. If the import is ever hoisted to
        module level, change this patch target to
        ``server.core.stt.backends.whispercpp_backend.get_config``.
        """
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("server.config.get_config", side_effect=RuntimeError("boom")),
        ):
            url = _resolve_server_url()
            assert "whisper-server" in url  # default

    def test_invalid_env_url_falls_through(self):
        """A non-http scheme in the env var must be ignored (SSRF guard)."""
        cfg = MagicMock()
        cfg.get.return_value = "http://config-fallback:8080"
        with (
            patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "file:///etc/passwd"}),
            patch("server.config.get_config", return_value=cfg),
        ):
            assert _resolve_server_url() == "http://config-fallback:8080"

    def test_invalid_env_and_config_falls_to_default(self):
        """If every source is invalid, return the built-in default rather than raising."""
        cfg = MagicMock()
        cfg.get.return_value = "gopher://nope"
        with (
            patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "file:///attack"}),
            patch("server.config.get_config", return_value=cfg),
        ):
            url = _resolve_server_url()
            assert url.startswith("http://")
            assert "whisper-server" in url


# ---------------------------------------------------------------------------
# _coerce_float
# ---------------------------------------------------------------------------


class TestCoerceFloat:
    def test_int(self):
        assert _coerce_float(3) == 3.0

    def test_float(self):
        assert _coerce_float(2.5) == 2.5

    def test_zero_survives(self):
        # A legitimate 0.0 must round-trip (not be confused with None / missing).
        assert _coerce_float(0.0) == 0.0
        assert _coerce_float(0) == 0.0

    def test_negative(self):
        assert _coerce_float(-0.5) == -0.5

    def test_none(self):
        assert _coerce_float(None) is None

    def test_string(self):
        assert _coerce_float("1.5") is None

    def test_bool(self):
        # bool is a subclass of int in Python — must be rejected or we'd turn
        # stray True/False values into 1.0/0.0 timestamps silently.
        assert _coerce_float(True) is None
        assert _coerce_float(False) is None

    def test_nan_rejected(self):
        import math

        assert _coerce_float(math.nan) is None

    def test_inf_rejected(self):
        import math

        assert _coerce_float(math.inf) is None
        assert _coerce_float(-math.inf) is None


# ---------------------------------------------------------------------------
# _sanitize_language_code
# ---------------------------------------------------------------------------


class TestSanitizeLanguageCode:
    def test_passes_iso_639_1(self):
        assert _sanitize_language_code("en") == "en"
        assert _sanitize_language_code("el") == "el"

    def test_passes_iso_639_3(self):
        assert _sanitize_language_code("eng") == "eng"

    def test_passes_bcp47_with_region(self):
        assert _sanitize_language_code("en-US") == "en-US"
        assert _sanitize_language_code("pt_BR") == "pt_BR"

    def test_rejects_non_string(self):
        assert _sanitize_language_code(None) is None
        assert _sanitize_language_code(42) is None
        assert _sanitize_language_code({"lang": "en"}) is None

    def test_rejects_empty(self):
        assert _sanitize_language_code("") is None
        assert _sanitize_language_code("   ") is None

    def test_rejects_log_injection_attempts(self):
        """A compromised sidecar must not be able to splice log lines."""
        # Newline splicing
        assert _sanitize_language_code("en\nCRITICAL root: fake log") is None
        # ANSI escape
        assert _sanitize_language_code("en\x1b[31mRED") is None
        # NUL byte
        assert _sanitize_language_code("en\x00") is None
        # CRLF
        assert _sanitize_language_code("en\r\nLOG INJECTION") is None

    def test_rejects_pathologically_long_input(self):
        """Guard against log-size amplification from long sidecar strings."""
        assert _sanitize_language_code("a" * 10_000) is None

    def test_rejects_spaces_or_punctuation(self):
        assert _sanitize_language_code("en us") is None
        assert _sanitize_language_code("en;DROP") is None


# ---------------------------------------------------------------------------
# _sanitize_for_error_preview
# ---------------------------------------------------------------------------


class TestSanitizeForErrorPreview:
    def test_passes_printable(self):
        assert _sanitize_for_error_preview(b"<html>error</html>") == "<html>error</html>"

    def test_escapes_control_chars(self):
        out = _sanitize_for_error_preview(b"a\x00b\x1bc")
        assert "\\x00" in out
        assert "\\x1b" in out
        # Real bytes should not leak through
        assert "\x00" not in out
        assert "\x1b" not in out

    def test_preserves_tabs_and_spaces(self):
        assert "\t" in _sanitize_for_error_preview(b"a\tb")
        assert " " in _sanitize_for_error_preview(b"a b")

    def test_truncates_at_limit(self):
        out = _sanitize_for_error_preview(b"x" * 500, limit=50)
        assert len(out) == 50
        assert out == "x" * 50

    def test_invalid_utf8_does_not_raise(self):
        # Lone continuation byte — invalid UTF-8
        out = _sanitize_for_error_preview(b"hello\xc3\x28world")
        assert "hello" in out
        assert "world" in out


# ---------------------------------------------------------------------------
# _validate_server_url
# ---------------------------------------------------------------------------


class TestValidateServerUrl:
    def test_accepts_http(self):
        assert _validate_server_url("http://whisper:8080") == "http://whisper:8080"

    def test_accepts_https(self):
        assert _validate_server_url("https://whisper.example:8443") == (
            "https://whisper.example:8443"
        )

    def test_strips_trailing_slash(self):
        assert _validate_server_url("http://host/") == "http://host"

    def test_rejects_file_scheme(self):
        """Classic SSRF vector — a file:// URL must not reach httpx."""
        assert _validate_server_url("file:///etc/passwd") is None

    def test_rejects_gopher(self):
        assert _validate_server_url("gopher://host:70") is None

    def test_rejects_scheme_only(self):
        assert _validate_server_url("http://") is None

    def test_rejects_no_scheme(self):
        assert _validate_server_url("whisper-server:8080") is None

    def test_strips_userinfo(self):
        """Credentials embedded in the URL must not survive validation."""
        out = _validate_server_url("http://alice:secret@whisper:8080")
        assert out == "http://whisper:8080"
        assert "alice" not in out  # type: ignore[operator]
        assert "secret" not in out  # type: ignore[operator]

    def test_rejects_control_chars(self):
        """CRLF or NUL in the URL would let a crafted value splice HTTP headers."""
        assert _validate_server_url("http://evil.com\r\nHost: internal") is None
        assert _validate_server_url("http://evil.com\x00") is None

    def test_strips_query_and_fragment(self):
        """Query strings and fragments are not meaningful for our sidecar endpoint."""
        assert _validate_server_url("http://h:8080/?x=1#y") == "http://h:8080"


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

    def test_rejects_zero_sample_rate(self):
        with pytest.raises(ValueError, match="sample_rate"):
            _audio_to_wav_bytes(np.zeros(100, dtype=np.float32), 0)

    def test_rejects_negative_sample_rate(self):
        with pytest.raises(ValueError, match="sample_rate"):
            _audio_to_wav_bytes(np.zeros(100, dtype=np.float32), -1)

    def test_rejects_excessive_sample_rate(self):
        """Prevents integer overflow in WAV's 32-bit byte_rate field."""
        with pytest.raises(ValueError, match="sample_rate"):
            _audio_to_wav_bytes(np.zeros(100, dtype=np.float32), 2_000_000)

    def test_rejects_non_int_sample_rate(self):
        with pytest.raises(ValueError, match="sample_rate"):
            _audio_to_wav_bytes(np.zeros(100, dtype=np.float32), 16000.5)  # type: ignore[arg-type]

    def test_nan_inf_samples_replaced_not_raised(self):
        """NaN/Inf in audio must not silently corrupt — nan_to_num replaces with 0."""
        audio = np.array([0.5, float("nan"), float("inf"), -float("inf"), -0.5], dtype=np.float32)
        wav = _audio_to_wav_bytes(audio, 16000)
        # No crash; header correct.
        assert wav[:4] == b"RIFF"
        # data_size = 5 samples * 2 bytes = 10
        assert len(wav) == 44 + 10


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
        """load() should succeed even if /load returns HTTP 4xx/5xx.

        The sidecar often pre-loads its model from the ``WHISPER_MODEL`` env
        var, which can make /load return a status error even though the
        server is ready to serve /inference. Tolerating HTTPStatusError
        keeps us compatible with that behaviour.

        In this branch the client MUST be kept — it's still valid for
        subsequent /inference calls. Unlike the connect/timeout branches
        (which close and nil the client), this branch should leave it alive.
        """
        resp = MagicMock(status_code=500)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=resp
        )
        mock_httpx.post.return_value = resp
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            backend.load("ggml-base.bin", "cpu")
        assert backend.is_loaded()
        assert backend._client is not None, (
            "tolerated HTTPStatusError must leave the client intact — a refactor "
            "that added _close_client_silently() here would silently introduce "
            "a per-transcribe reconnection storm"
        )
        mock_httpx.close.assert_not_called()

    def test_load_raises_on_unknown_exception(
        self, backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """An unexpected non-httpx exception from the client must propagate."""
        mock_httpx.post.side_effect = RuntimeError("something weird")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            with pytest.raises(RuntimeError, match="something weird"):
                backend.load("ggml-base.bin", "cpu")
        assert not backend.is_loaded()

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

    def test_load_raises_on_timeout(self, backend: WhisperCppBackend, mock_httpx: MagicMock):
        """load() timeout must surface the timeout message, not the generic one."""
        mock_httpx.post.side_effect = httpx.ReadTimeout("deadline")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            with pytest.raises(RuntimeError, match="model load timed out"):
                backend.load("ggml-base.bin", "cpu")
        assert not backend.is_loaded()

    def test_unload_is_idempotent(self, loaded_backend: WhisperCppBackend):
        """Unload must be safe to call twice."""
        loaded_backend.unload()
        loaded_backend.unload()  # second call must not raise
        assert not loaded_backend.is_loaded()

    def test_unload_before_load_is_safe(self, backend: WhisperCppBackend):
        """Unload on a never-loaded backend must not raise."""
        backend.unload()
        assert not backend.is_loaded()

    def test_unload_tolerates_client_close_failure(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A flaky client.close() must not leak past unload()."""
        mock_httpx.close.side_effect = RuntimeError("close failed")
        loaded_backend.unload()  # must swallow and log
        assert not loaded_backend.is_loaded()
        # _client must be nilled even when close() raised — otherwise the
        # broken client lingers and the next load() path would use it.
        assert loaded_backend._client is None

    def test_load_failure_closes_client_to_prevent_leak(
        self, backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Regression guard — a connect failure during load() must not leak the client.

        Without the fix, a caller retrying ``load()`` after a connect error
        would see ``_ensure_client()`` return the same leaked client, and
        the underlying socket from the failed attempt would never be closed.
        """
        mock_httpx.post.side_effect = httpx.ConnectError("refused")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            with pytest.raises(RuntimeError):
                backend.load("ggml-base.bin", "cpu")
        assert backend._client is None, (
            "load() must release _client on exception — otherwise a retry "
            "leaks the previous client's socket"
        )
        mock_httpx.close.assert_called_once()

    def test_load_failure_on_timeout_closes_client(
        self, backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Same leak fix, timeout branch."""
        mock_httpx.post.side_effect = httpx.ReadTimeout("slow")
        with patch.dict("os.environ", {"WHISPERCPP_SERVER_URL": "http://test:8080"}):
            with pytest.raises(RuntimeError):
                backend.load("ggml-base.bin", "cpu")
        assert backend._client is None


# ---------------------------------------------------------------------------
# WhisperCppBackend — transcribe
# ---------------------------------------------------------------------------


class TestTranscribe:
    def test_raises_when_not_loaded(self, backend: WhisperCppBackend):
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="not loaded"):
            backend.transcribe(audio)

    def test_sends_multipart_post(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        """Request must go to /inference and carry a multipart 'file' field.

        Tightened from an ``isinstance``-only check so a mutation that
        short-circuits the HTTP call (``return [], BackendTranscriptionInfo(...)``
        at the top of ``transcribe``) would no longer silently pass.
        """
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio)
        call = _inf(mock_httpx).call_args
        assert call is not None, "expected a POST to have been issued"
        # URL assertion — catches any routing regression.
        assert _inference_url(mock_httpx).endswith("/inference")
        files = call.kwargs.get("files")
        assert files is not None, "expected a multipart 'file' upload"
        assert "file" in files
        filename, wav_bytes, content_type = files["file"]
        assert filename == "audio.wav"
        assert content_type == "audio/wav"
        assert wav_bytes[:4] == b"RIFF", "body must be a real WAV, not a placeholder"

    def test_parses_segments(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        # Matches the real verbose_json shape emitted by whisper.cpp server:
        # - segment "start"/"end" are floats in seconds
        # - "tokens" is a flat list of int token IDs
        # - per-word timing lives in "words"
        _inf(mock_httpx).return_value = _inference_response(
            {
                "language": "en",
                "detected_language": "en",
                "detected_language_probability": 0.97,
                "segments": [
                    {
                        "id": 0,
                        "text": " Hello world",
                        "start": 0.0,
                        "end": 2.5,
                        "tokens": [50363, 31373, 995, 50257],
                        "words": [
                            {
                                "word": " Hello",
                                "start": 0.0,
                                "end": 1.0,
                                "probability": 0.95,
                            },
                            {
                                "word": " world",
                                "start": 1.1,
                                "end": 2.5,
                                "probability": 0.90,
                            },
                        ],
                    }
                ],
            }
        )
        audio = np.zeros(32000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert len(segments) == 1
        # Use text with BOTH leading and trailing whitespace so a mutation
        # ``.strip()`` → ``.lstrip()`` (or .rstrip) fails loudly.
        assert segments[0].text == "Hello world"
        assert segments[0].start == 0.0
        assert segments[0].end == 2.5
        assert len(segments[0].words) == 2
        # Leading space on raw word " Hello" must also be stripped; trailing
        # space asymmetry is exercised at the segment-text level above.
        assert segments[0].words[0]["word"] == "Hello"
        assert segments[0].words[0]["start"] == 0.0
        assert segments[0].words[0]["end"] == 1.0
        assert segments[0].words[0]["probability"] == 0.95
        assert info.language == "en"
        assert info.language_probability == pytest.approx(0.97)

    def test_text_strip_handles_both_ends(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Explicit guard against lstrip-vs-strip regressions."""
        _inf(mock_httpx).return_value = _inference_response(
            {
                "segments": [
                    {"text": "  Hello world   ", "start": 0.0, "end": 1.0},
                ]
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        assert segments[0].text == "Hello world", (
            "both leading and trailing whitespace must be stripped"
        )

    def test_does_not_crash_on_int_tokens(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Regression test for GH #62.

        Before the fix, _parse_response iterated seg["tokens"] and called
        ``tok.get("t0")`` on each entry, which raised
        ``AttributeError: 'int' object has no attribute 'get'`` because
        whisper.cpp's server returns a flat list of integer token IDs.
        """
        _inf(mock_httpx).return_value = _inference_response(
            {
                "language": "en",
                "segments": [
                    {
                        "id": 0,
                        "text": " hi",
                        "start": 0.0,
                        "end": 0.5,
                        "tokens": [50363, 23105, 50257],  # <-- int IDs
                        # NB: no "words" key — e.g. server ran with
                        # --no-timestamps, so callers must still succeed.
                    }
                ],
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert len(segments) == 1
        assert segments[0].text == "hi"
        assert segments[0].words == []
        assert info.language == "en"

    def test_skips_malformed_word_entries(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Non-dict or missing-field word entries must not crash the parser."""
        _inf(mock_httpx).return_value = _inference_response(
            {
                "language": "en",
                "segments": [
                    {
                        "text": " ok",
                        "start": 0.0,
                        "end": 1.0,
                        "words": [
                            42,  # stray int
                            {"word": "", "start": 0.0, "end": 0.1},  # empty text
                            {"word": "   ", "start": 0.0, "end": 0.1},  # whitespace only
                            {"word": "bad", "start": None, "end": 0.5},  # None start
                            {"word": "ok", "start": 0.0, "end": 1.0, "probability": 0.8},
                        ],
                    }
                ],
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _info = loaded_backend.transcribe(audio)
        assert len(segments[0].words) == 1
        assert segments[0].words[0]["word"] == "ok"

    def test_numeric_zero_word_does_not_fall_through_to_text(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Edge case: ``word`` field is integer ``0`` (rare but valid JSON).

        Before the fix, ``w.get("word") or w.get("text")`` would treat 0 as
        falsy and fall through to ``text``. Now we check explicitly for None.
        """
        _inf(mock_httpx).return_value = _inference_response(
            {
                "segments": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 1.0,
                        "words": [
                            # Integer 0 as "word" — must serialize as "0",
                            # not fall through to "text".
                            {
                                "word": 0,
                                "text": "wrong-fallback",
                                "start": 0.0,
                                "end": 0.5,
                            },
                        ],
                    }
                ]
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        assert segments[0].words[0]["word"] == "0"  # not "wrong-fallback"

    def test_tolerates_missing_top_level_fields(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Empty or absent segments list must return an empty transcription cleanly."""
        _inf(mock_httpx).return_value = _inference_response({})
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert segments == []
        assert info.language is None
        assert info.language_probability == 0.0

    def test_logs_warning_when_segment_timestamps_missing(
        self,
        loaded_backend: WhisperCppBackend,
        mock_httpx: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Segments without start/end must warn so downstream timing issues are visible."""
        import logging

        _inf(mock_httpx).return_value = _inference_response(
            {
                "language": "en",
                "segments": [
                    {"id": 0, "text": " hi"}  # no start/end
                ],
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        with caplog.at_level(logging.WARNING, logger="server.core.stt.backends.whispercpp_backend"):
            segments, _ = loaded_backend.transcribe(audio)
        assert len(segments) == 1
        assert segments[0].start == 0.0
        assert segments[0].end == 0.0
        assert any("without start/end" in rec.message for rec in caplog.records)

    def test_distinct_probabilities_round_trip(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Probabilities must be carried through verbatim, not defaulted.

        Previous ``test_zero_probability_is_preserved`` was tautological:
        the fallback for a missing probability is also ``0.0``, so asserting
        ``probability == 0.0`` could not distinguish "value preserved" from
        "silently defaulted". Using a unique non-default value per word
        makes the preservation contract observable.
        """
        _inf(mock_httpx).return_value = _inference_response(
            {
                "language": "en",
                "detected_language_probability": 0.42,
                "segments": [
                    {
                        "text": " a b c",
                        "start": 0.0,
                        "end": 0.3,
                        "words": [
                            {"word": "a", "start": 0.0, "end": 0.1, "probability": 0.0},
                            {"word": "b", "start": 0.1, "end": 0.2, "probability": 0.37},
                            {"word": "c", "start": 0.2, "end": 0.3, "probability": 0.91},
                        ],
                    }
                ],
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert [w["probability"] for w in segments[0].words] == [0.0, 0.37, 0.91]
        assert info.language_probability == pytest.approx(0.42)

    def test_missing_probability_defaults_to_zero(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Distinguishes the default-path from the preservation-path above."""
        _inf(mock_httpx).return_value = _inference_response(
            {
                "segments": [
                    {
                        "text": " a",
                        "start": 0.0,
                        "end": 0.1,
                        # Intentionally no "probability" key.
                        "words": [{"word": "a", "start": 0.0, "end": 0.1}],
                    }
                ],
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        assert segments[0].words[0]["probability"] == 0.0

    def test_nan_timestamps_are_dropped(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """NaN/Inf from a broken sidecar must not poison the segment list."""
        _inf(mock_httpx).return_value = _inference_response(
            {
                "segments": [
                    {
                        "text": "bad",
                        "start": float("nan"),
                        "end": float("inf"),
                        "words": [
                            {
                                "word": "x",
                                "start": float("nan"),
                                "end": 0.5,
                                "probability": 1.0,
                            },
                        ],
                    }
                ]
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        # Segment falls back to 0.0/0.0 (with a warning) because both bounds
        # failed validation.
        assert segments[0].start == 0.0
        assert segments[0].end == 0.0
        # The word with NaN start is dropped entirely.
        assert segments[0].words == []

    def test_segment_cap_applies_after_filter(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Non-dict entries must not consume cap budget, otherwise real data is dropped.

        If 500 stray ints are at the front of the list followed by 100
        real dicts, the filter-then-cap order should keep all 100 dicts.
        A cap-first-then-filter order (the pre-review bug) would drop
        everything beyond the cap regardless of validity.
        """
        noise = [42] * 500
        real = [{"text": f"s{i}", "start": float(i), "end": float(i) + 1.0} for i in range(100)]
        _inf(mock_httpx).return_value = _inference_response({"segments": noise + real})
        segments, _ = loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert len(segments) == 100
        assert segments[0].text == "s0"
        assert segments[-1].text == "s99"

    def test_language_injection_attempt_is_dropped(
        self,
        loaded_backend: WhisperCppBackend,
        mock_httpx: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """A compromised sidecar trying to inject log lines via language must fail quietly.

        Also verifies the spliced payload never reaches logs — a weaker
        earlier version of this test only checked the return value, which
        would still pass if the string reached a logger first.
        """
        import logging

        _inf(mock_httpx).return_value = _inference_response(
            {
                "language": "en\nCRITICAL root: spliced log line",
                "segments": [],
            }
        )
        audio = np.zeros(16000, dtype=np.float32)
        with caplog.at_level(logging.DEBUG):
            _, info = loaded_backend.transcribe(audio)
        assert info.language is None
        # The injected payload text (not just the sanitised empty) must not
        # appear in any log record.
        assert "CRITICAL root: spliced log line" not in caplog.text

    def test_non_json_response_preview_is_sanitized(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Non-JSON response body must be sanitized before embedding in the error."""
        _inf(mock_httpx).return_value = _inference_response(
            raw=b"<html>\x1b[31mcrash\x00boom</html>"
        )
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError) as excinfo:
            loaded_backend.transcribe(audio)
        msg = str(excinfo.value)
        # Literal ESC/NUL bytes must not appear in the message
        assert "\x1b" not in msg
        assert "\x00" not in msg
        # Escaped forms must appear instead
        assert "\\x1b" in msg or "\\x00" in msg

    def test_translate_task_sends_flag(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, task="translate")
        data = _post_data(mock_httpx)
        assert data.get("translate") == "true"

    def test_transcribe_task_omits_translate_flag(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """task='transcribe' must NOT set the translate flag.

        A mutation that always set ``data['translate'] = 'true'`` would
        otherwise slip past ``test_translate_task_sends_flag``.
        """
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, task="transcribe")
        data = _post_data(mock_httpx)
        assert "translate" not in data

    def test_word_timestamps_true_sets_split_on_word(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """word_timestamps=True must set split_on_word to the literal string ``"true"``.

        whisper.cpp's HTTP form parser (``server.cpp`` — search for the
        ``req.get_file_value("split_on_word").content`` read and the
        ``== "true"`` comparison) accepts *only* the lowercase string
        ``"true"``. A well-meaning refactor that passes the Python bool
        ``True`` would serialize as ``"True"`` and silently break
        word-boundary splitting. Assert the exact value, not just the key.
        """
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, word_timestamps=True)
        data = _post_data(mock_httpx)
        value = data.get("split_on_word")
        assert value == "true", (
            f"expected the literal lowercase string 'true', got {value!r}. "
            f"whisper.cpp does a case-sensitive string compare."
        )
        assert isinstance(value, str), "must not be sent as a Python bool"

    def test_word_timestamps_false_omits_split_on_word(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """word_timestamps=False must not send split_on_word."""
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, word_timestamps=False)
        data = _post_data(mock_httpx)
        assert "split_on_word" not in data

    def test_language_and_prompt_forwarded(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "el"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, language="el", initial_prompt="Καλημέρα")
        data = _post_data(mock_httpx)
        assert data.get("language") == "el"
        assert data.get("prompt") == "Καλημέρα"

    def test_none_language_and_prompt_omitted(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Missing language / prompt must NOT splice empty keys into the form.

        Mutation guard: ``if language:`` → ``if not language:`` would
        now fail loudly instead of quietly inverting the branch.
        """
        _inf(mock_httpx).return_value = _inference_response({"segments": []})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, language=None, initial_prompt=None)
        data = _post_data(mock_httpx)
        assert "language" not in data
        assert "prompt" not in data

    def test_whitespace_language_and_prompt_omitted(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Whitespace-only values must not be forwarded."""
        _inf(mock_httpx).return_value = _inference_response({"segments": []})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, language="   ", initial_prompt="  \t ")
        data = _post_data(mock_httpx)
        assert "language" not in data
        assert "prompt" not in data

    def test_prompt_is_capped(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        """A 10 MB initial_prompt must not be uploaded as-is — whisper.cpp only
        uses ~224 tokens anyway."""
        huge_prompt = "x" * 100_000
        _inf(mock_httpx).return_value = _inference_response({"segments": []})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, initial_prompt=huge_prompt)
        data = _post_data(mock_httpx)
        prompt = data.get("prompt", "")
        assert 0 < len(prompt) <= 10_000  # capped to _MAX_PROMPT_CHARS; upper bound is loose

    @pytest.mark.parametrize(
        "beam_size,expected",
        [
            (1, "1"),
            (4, "4"),  # just below default
            (6, "6"),  # just above default
            (10, "10"),
        ],
    )
    def test_non_default_beam_size_forwarded(
        self,
        loaded_backend: WhisperCppBackend,
        mock_httpx: MagicMock,
        beam_size: int,
        expected: str,
    ):
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, beam_size=beam_size)
        data = _post_data(mock_httpx)
        assert data.get("beam_size") == expected

    def test_default_beam_size_omitted(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Boundary case: when beam_size == server default, don't send it.

        Pairs with the non-default cases above to pin the ``!=`` semantics.
        A mutation ``!=`` → ``<`` would still pass the 1/4 cases but fail
        here; ``!=`` → ``>`` would still pass 6/10 but fail here.
        """
        _inf(mock_httpx).return_value = _inference_response({"segments": []})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, beam_size=5)
        data = _post_data(mock_httpx)
        assert "beam_size" not in data

    def test_rejects_non_positive_beam_size(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Negative/zero beam_size would either be forwarded as-is (and confuse
        whisper-server) or, worse, silently interpreted as greedy decode. Reject
        early."""
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(ValueError, match="beam_size"):
            loaded_backend.transcribe(audio, beam_size=0)
        with pytest.raises(ValueError, match="beam_size"):
            loaded_backend.transcribe(audio, beam_size=-1)

    def test_empty_audio_short_circuits(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Zero-length audio must return an empty result without hitting the sidecar."""
        segments, info = loaded_backend.transcribe(np.zeros(0, dtype=np.float32))
        assert segments == []
        assert info.language is None
        _inf(mock_httpx).assert_not_called()

    def test_unsupported_params_are_accepted_and_silently_dropped(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Callers can pass params the sidecar cannot honour without crashing.

        ``suppress_tokens``, ``vad_filter``, ``translation_target_language``
        and ``progress_callback`` have no HTTP-form equivalent on the current
        sidecar image, so they must be accepted (for interface parity with
        other backends) but never leak into the POST body.
        """
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(
            audio,
            suppress_tokens=[1, 2, 3],
            vad_filter=True,
            translation_target_language="fr",
            progress_callback=lambda cur, total: None,
        )
        data = _post_data(mock_httpx)
        for leaked in ("suppress_tokens", "vad", "vad_filter", "target_language"):
            assert leaked not in data

    def test_transcribe_raises_on_connect_error(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """transcribe() should raise RuntimeError with actionable message when sidecar is down."""
        _inf(mock_httpx).side_effect = httpx.ConnectError("connection refused")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="whisper.cpp sidecar is not reachable"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_dns_oserror(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """transcribe() should raise RuntimeError when DNS resolution fails."""
        _inf(mock_httpx).side_effect = OSError(5, "No address associated with hostname")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="whisper.cpp sidecar is not reachable"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_timeout(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Inference timeout must surface the inference-timeout message."""
        _inf(mock_httpx).side_effect = httpx.ReadTimeout("deadline")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="transcription timed out"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_http_5xx(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A 5xx from /inference must surface as an actionable RuntimeError."""
        _inf(mock_httpx).return_value = _inference_response(
            status_code=503,
            raise_status=httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=MagicMock(),
                response=MagicMock(status_code=503),
            ),
        )
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="returned HTTP 503"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_non_json_response(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A non-JSON body (HTML error page, empty string, etc.) must be surfaced."""
        _inf(mock_httpx).return_value = _inference_response(raw=b"<html>fatal</html>")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="non-JSON"):
            loaded_backend.transcribe(audio)


# ---------------------------------------------------------------------------
# /inference response byte guard (GH #193) — bound the read BEFORE deserializing
# ---------------------------------------------------------------------------


class TestResponseByteGuard:
    """The /inference body is bounded at HTTP read time so a hostile or
    misconfigured WHISPERCPP_SERVER_URL cannot exhaust memory before any
    segment/word cap (which only runs post-parse) gets a chance to reject it.

    Both the declared ``Content-Length`` (honest servers) and the actual
    streamed bytes (servers that omit/lie about it) are checked, and the read
    aborts as soon as the ceiling is crossed — this is the real memory bound
    the old post-parse list slice only pretended to be.
    """

    @staticmethod
    def _stream_resp(*, headers=None, iter_bytes=None):
        """A minimal streaming-response mock: a context manager exposing
        ``headers``/``raise_for_status``/``iter_bytes`` (the surface the byte
        guard reads), independent of the dual-capable ``_inference_response``."""
        resp = MagicMock(status_code=200)
        resp.headers = dict(headers or {})
        resp.raise_for_status.return_value = None
        if iter_bytes is not None:
            resp.iter_bytes = iter_bytes
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    def test_oversized_streamed_body_is_rejected_before_full_read(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A body with no/dishonest Content-Length that exceeds the cap must be
        rejected, and the read must STOP at the ceiling (proving the memory
        bound) rather than materialize the whole over-cap body."""
        from server.core.stt.backends.whispercpp_backend import _MAX_RESPONSE_BYTES

        piece = b"x" * (1024 * 1024)  # 1 MiB
        # Enough pieces to blow well past the cap if the read ran to completion.
        n_pieces = (_MAX_RESPONSE_BYTES // len(piece)) + 100
        consumed = {"n": 0}

        def iter_bytes():
            for _ in range(n_pieces):
                consumed["n"] += 1
                yield piece

        # No Content-Length header → the accumulator guard is what must fire.
        mock_httpx.stream.return_value = self._stream_resp(iter_bytes=iter_bytes)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))
        # Bounded memory: the guard stopped reading once the cap was crossed,
        # not after consuming every (over-cap) piece.
        assert consumed["n"] <= (_MAX_RESPONSE_BYTES // len(piece)) + 1

    def test_oversized_content_length_header_is_rejected_before_read(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """An honest server that declares a Content-Length above the cap must be
        rejected BEFORE the body is read at all."""
        from server.core.stt.backends.whispercpp_backend import _MAX_RESPONSE_BYTES

        def iter_bytes():
            raise AssertionError("must reject on Content-Length before reading the body")
            yield  # pragma: no cover — makes this a generator

        resp = self._stream_resp(
            headers={"Content-Length": str(_MAX_RESPONSE_BYTES + 1)},
            iter_bytes=iter_bytes,
        )
        mock_httpx.stream.return_value = resp
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))

    def test_non_ascii_content_length_is_ignored(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A bogus non-ASCII Content-Length must be ignored, not crash the read.

        A hostile sidecar can put raw byte 0xB2 in the header, which httpx
        decodes (latin-1) to ``"²"``. ``str.isdigit()`` is True for it but
        ``int("²")`` raises ValueError — which none of the read handlers catch.
        The guard must only honour ASCII digits and otherwise fall through to
        the streamed-bytes accumulator, reading the (valid) body normally.
        """
        body = json.dumps({"segments": [], "language": "en"}).encode()

        def iter_bytes():
            yield body

        mock_httpx.stream.return_value = self._stream_resp(
            headers={"Content-Length": "²"},  # superscript two: isdigit() True, int() raises
            iter_bytes=iter_bytes,
        )
        segments, info = loaded_backend.transcribe(_seconds_of_audio(1))
        assert segments == []
        assert info.language == "en"

    def test_response_at_cap_is_accepted(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A well-formed response whose body is at/under the cap streams through
        normally — the guard must not false-trip on legitimate transcripts."""
        from server.core.stt.backends.whispercpp_backend import _MAX_RESPONSE_BYTES

        body = json.dumps({"segments": [], "language": "en"}).encode()
        assert len(body) <= _MAX_RESPONSE_BYTES

        def iter_bytes():
            # Deliberately chunked to exercise the accumulator loop.
            yield body[: len(body) // 2]
            yield body[len(body) // 2 :]

        mock_httpx.stream.return_value = self._stream_resp(iter_bytes=iter_bytes)
        segments, info = loaded_backend.transcribe(_seconds_of_audio(1))
        assert segments == []
        assert info.language == "en"


# ---------------------------------------------------------------------------
# Proportional segment cap (GH #172) — fail loud instead of silently truncate
# ---------------------------------------------------------------------------


class TestSegmentProportionalCap:
    def _respond_with(self, mock_httpx, n_segments):
        bloated = [{"text": "x", "start": 0.0, "end": 0.1} for _ in range(n_segments)]
        _inf(mock_httpx).return_value = _inference_response({"segments": bloated})

    def test_legit_long_audio_is_not_truncated(self, loaded_backend, mock_httpx):
        """GH #172 regression: a real long transcript keeps ALL its segments."""
        # 100s audio -> cap = 2000; 1500 segments is legitimate and must survive.
        self._respond_with(mock_httpx, 1500)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(100))
        assert len(segments) == 1500

    def test_count_at_proportional_cap_is_kept(self, loaded_backend, mock_httpx):
        # 100s -> cap 2000; exactly at cap is kept (boundary).
        self._respond_with(mock_httpx, 2000)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(100))
        assert len(segments) == 2000

    def test_count_over_proportional_cap_raises(self, loaded_backend, mock_httpx):
        # 100s -> cap 2000; one over is an impossible payload -> raise, do NOT truncate.
        self._respond_with(mock_httpx, 2001)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(100))

    def test_floor_boundary_at_cap_is_kept(self, loaded_backend, mock_httpx):
        # 1s -> cap = floor 200; exactly at the floor is kept.
        self._respond_with(mock_httpx, 200)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(1))
        assert len(segments) == 200

    def test_floor_boundary_over_cap_raises(self, loaded_backend, mock_httpx):
        # 1s -> cap = floor 200; one over the floor raises.
        self._respond_with(mock_httpx, 201)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))

    def test_hostile_small_audio_huge_count_raises(self, loaded_backend, mock_httpx):
        # The literal #172 attack shape: thousands of segments for ~1s of audio.
        self._respond_with(mock_httpx, 11152)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))

    def test_chunked_earlier_segments_preserved_on_later_cap_raise(
        self, loaded_backend, mock_httpx
    ):
        """WhisperCppResponseError on chunk N+1 must not discard chunk N's segments."""
        good = [{"text": "ok", "start": 0.0, "end": 1.0}]
        bloated = [{"text": "x", "start": 0.0, "end": 0.1} for _ in range(201)]
        _inf(mock_httpx).side_effect = [
            _inference_response({"segments": good}),
            _inference_response({"segments": bloated}),
        ]
        loaded_backend._max_chunk_duration_s = 1  # force 1s chunks -> 2 chunks for 2s audio
        with pytest.raises(PartialTranscriptionError) as exc_info:
            loaded_backend.transcribe(_seconds_of_audio(2))
        assert len(exc_info.value.segments) == 1
        assert exc_info.value.segments[0].text == "ok"


# ---------------------------------------------------------------------------
# Proportional word cap (GH #172) — fail loud instead of silently truncate
# ---------------------------------------------------------------------------


class TestWordProportionalCap:
    def _respond_with_words(self, mock_httpx, n_words):
        bloated = [
            {"word": "x", "start": i * 0.001, "end": i * 0.001 + 0.0005} for i in range(n_words)
        ]
        _inf(mock_httpx).return_value = _inference_response(
            {"segments": [{"text": "seg", "start": 0.0, "end": 30.0, "words": bloated}]}
        )

    def test_legit_words_kept(self, loaded_backend, mock_httpx):
        # 100s audio -> word cap 4000; 800 words on one segment is fine.
        self._respond_with_words(mock_httpx, 800)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(100))
        assert len(segments[0].words) == 800

    def test_words_over_cap_raise(self, loaded_backend, mock_httpx):
        # 1s audio -> word cap = floor 1000; 1001 words is implausible -> raise.
        self._respond_with_words(mock_httpx, 1001)
        with pytest.raises(WhisperCppResponseError):
            loaded_backend.transcribe(_seconds_of_audio(1))

    def test_word_floor_boundary_at_cap_is_kept(self, loaded_backend, mock_httpx):
        # 1s audio -> word cap = floor 1000; exactly at cap is kept.
        self._respond_with_words(mock_httpx, 1000)
        segments, _ = loaded_backend.transcribe(_seconds_of_audio(1))
        assert len(segments[0].words) == 1000


# ---------------------------------------------------------------------------
# _inference_timeout_for — duration-scaled per-request timeout (GH #168)
# ---------------------------------------------------------------------------


class TestInferenceTimeoutFor:
    def test_floors_at_inference_timeout(self):
        # 10s of audio → 20s scaled, floored up to the 300s minimum.
        assert _inference_timeout_for(10 * 16000, 16000) == _INFERENCE_TIMEOUT

    def test_scales_above_floor(self):
        # A 10-min chunk → 600 * 2.0 = 1200s, comfortably above the floor.
        assert _inference_timeout_for(600 * 16000, 16000) == 1200

    def test_zero_samples_is_floor(self):
        assert _inference_timeout_for(0, 16000) == _INFERENCE_TIMEOUT

    def test_zero_sample_rate_is_guarded(self):
        # Must not divide by zero — fall back to the floor.
        assert _inference_timeout_for(16000, 0) == _INFERENCE_TIMEOUT

    def test_default_chunk_duration_is_ten_minutes(self):
        assert _MAX_CHUNK_DURATION_S == 10 * 60


# ---------------------------------------------------------------------------
# WhisperCppBackend — long-audio client-side chunking (GH #168)
# ---------------------------------------------------------------------------


class TestTranscribeChunking:
    """Audio longer than ``_max_chunk_duration_s`` is split into fixed-size
    chunks, each POSTed to /inference separately, with per-chunk timestamps
    offset back onto the global timeline. Ports the NeMo ``_transcribe_long``
    pattern so each request is bounded in size and read-timeout (fixing the
    300s ceiling on 5h+ files) and the backend can emit progress, which a
    single synchronous /inference cannot.
    """

    @staticmethod
    def _resp(payload: dict) -> MagicMock:
        return _inference_response(payload)

    def test_short_audio_uses_single_post(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Audio at/below the chunk threshold keeps the original single-POST path."""
        loaded_backend._max_chunk_duration_s = 600  # 1s of audio is well under
        _inf(mock_httpx).return_value = self._resp({"segments": [], "language": "en"})
        loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert _inf(mock_httpx).call_count == 1

    def test_long_audio_splits_into_chunks(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Audio longer than the threshold is split into ceil(total/chunk) POSTs."""
        loaded_backend._max_chunk_duration_s = 1  # 1s chunks
        _inf(mock_httpx).side_effect = [
            self._resp({"segments": [], "language": "en"}) for _ in range(3)
        ]
        loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32))
        assert _inf(mock_httpx).call_count == 3

    def test_chunk_timestamps_offset_to_global_timeline(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Each chunk reports local times 0..x; the stitched output is offset by
        the cumulative chunk duration (segment AND word level)."""
        loaded_backend._max_chunk_duration_s = 1

        def payload(i: int) -> dict:
            return {
                "language": "en",
                "segments": [
                    {
                        "text": f" seg{i}",
                        "start": 0.0,
                        "end": 0.5,
                        "words": [{"word": f" w{i}", "start": 0.0, "end": 0.5, "probability": 0.9}],
                    }
                ],
            }

        _inf(mock_httpx).side_effect = [self._resp(payload(i)) for i in range(3)]
        segments, _ = loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32))
        assert [s.start for s in segments] == [0.0, 1.0, 2.0]
        assert [s.end for s in segments] == [0.5, 1.5, 2.5]
        assert segments[1].words[0]["start"] == 1.0
        assert segments[1].words[0]["end"] == 1.5
        assert segments[2].words[0]["start"] == 2.0

    def test_progress_callback_fires_per_chunk(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"segments": [], "language": "en"}) for _ in range(3)
        ]
        calls: list[tuple[int, int]] = []
        loaded_backend.transcribe(
            np.zeros(3 * 16000, dtype=np.float32),
            progress_callback=lambda cur, total: calls.append((cur, total)),
        )
        assert calls == [(1, 3), (2, 3), (3, 3)]

    def test_info_comes_from_first_chunk(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Result language/probability is taken from the first chunk's detection."""
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"language": "el", "detected_language_probability": 0.83, "segments": []}),
            self._resp({"language": "en", "detected_language_probability": 0.10, "segments": []}),
        ]
        _, info = loaded_backend.transcribe(np.zeros(2 * 16000, dtype=np.float32), language=None)
        assert info.language == "el"
        assert info.language_probability == pytest.approx(0.83)

    def test_detected_language_pins_later_chunks(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """When auto-detecting, chunk 0's language is forwarded to later chunks so a
        quiet/ambiguous later chunk can't flip the language mid-file."""
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"language": "el", "segments": []}) for _ in range(3)
        ]
        loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32), language=None)
        calls = _inf(mock_httpx).call_args_list
        assert "language" not in (calls[0].kwargs.get("data") or {})  # chunk 0 auto-detects
        assert calls[1].kwargs["data"].get("language") == "el"  # pinned thereafter
        assert calls[2].kwargs["data"].get("language") == "el"

    def test_explicit_language_sent_to_every_chunk(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A user-pinned language is sent to every chunk and never overridden."""
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"language": "en", "segments": []}) for _ in range(2)
        ]
        loaded_backend.transcribe(np.zeros(2 * 16000, dtype=np.float32), language="fr")
        for call in _inf(mock_httpx).call_args_list:
            assert call.kwargs["data"].get("language") == "fr"

    def test_each_chunk_post_uses_scaled_timeout(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Every chunk POST carries the duration-scaled timeout (floored at 300)."""
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [self._resp({"segments": []}) for _ in range(2)]
        loaded_backend.transcribe(np.zeros(2 * 16000, dtype=np.float32))
        expected = _inference_timeout_for(16000, 16000)  # 1s chunk → floored at 300
        for call in _inf(mock_httpx).call_args_list:
            assert call.kwargs.get("timeout") == expected

    def test_single_post_timeout_scales_for_long_subthreshold_audio(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A 200s file (< 600s threshold) stays single-POST but its timeout scales past 300."""
        _inf(mock_httpx).return_value = self._resp({"segments": []})
        loaded_backend.transcribe(np.zeros(200 * 16000, dtype=np.float32))
        assert _inf(mock_httpx).call_count == 1
        assert _inf(mock_httpx).call_args.kwargs.get("timeout") == 400  # max(300, 200 * 2)

    def test_empty_middle_chunk_still_advances_offset(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A silent middle chunk (no segments) still advances the offset clock so the
        third chunk's segments land at the correct global time."""
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"language": "en", "segments": [{"text": "a", "start": 0.0, "end": 0.5}]}),
            self._resp({"language": "en", "segments": []}),  # silence
            self._resp({"language": "en", "segments": [{"text": "c", "start": 0.0, "end": 0.5}]}),
        ]
        segments, _ = loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32))
        assert [s.text for s in segments] == ["a", "c"]
        assert segments[1].start == 2.0  # offset by the two preceding 1s chunks


# ---------------------------------------------------------------------------
# whisper.cpp config knobs — chunk duration + timeout (GH #168 follow-up)
# ---------------------------------------------------------------------------


class TestWhisperCppConfigResolution:
    def test_chunk_duration_env_wins_over_config(self):
        cfg = MagicMock()
        cfg.get.return_value = 90  # config says 90, env should win
        with (
            patch.dict("os.environ", {"WHISPERCPP_CHUNK_DURATION_S": "120"}),
            patch("server.config.get_config", return_value=cfg),
        ):
            assert _resolve_chunk_duration_config() == 120

    def test_chunk_duration_config_used_when_env_absent(self):
        cfg = MagicMock()
        cfg.get.return_value = 90
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("server.config.get_config", return_value=cfg),
        ):
            assert _resolve_chunk_duration_config() == 90

    def test_chunk_duration_invalid_env_falls_back_to_default(self):
        with patch.dict("os.environ", {"WHISPERCPP_CHUNK_DURATION_S": "not-a-number"}):
            assert _resolve_chunk_duration_config() == _MAX_CHUNK_DURATION_S

    def test_chunk_duration_floor_enforced(self):
        with patch.dict("os.environ", {"WHISPERCPP_CHUNK_DURATION_S": "10"}):
            assert _resolve_chunk_duration_config() == 60

    def test_chunk_duration_config_is_ceilinged(self):
        """A huge WHISPERCPP_CHUNK_DURATION_S must NOT disable chunking (GH #172):
        long audio must always be split so the per-chunk proportional cap applies."""
        with patch.dict("os.environ", {"WHISPERCPP_CHUNK_DURATION_S": "86400"}):  # 1 day
            assert _resolve_chunk_duration_config() == _MAX_CHUNK_DURATION_CEILING_S

    def test_chunk_duration_floor_still_applies_alongside_ceiling(self):
        with patch.dict("os.environ", {"WHISPERCPP_CHUNK_DURATION_S": "5"}):
            assert _resolve_chunk_duration_config() == 60

    def test_chunk_duration_defaults_when_no_source(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("server.config.get_config", side_effect=RuntimeError("no config")),
        ):
            assert _resolve_chunk_duration_config() == _MAX_CHUNK_DURATION_S

    def test_timeout_config_env_wins(self):
        with patch.dict(
            "os.environ",
            {
                "WHISPERCPP_INFERENCE_TIMEOUT_S": "500",
                "WHISPERCPP_TIMEOUT_SECONDS_PER_AUDIO_SECOND": "3.0",
            },
        ):
            assert _resolve_timeout_config() == (500, 3.0)

    def test_timeout_config_floors_enforced(self):
        with patch.dict(
            "os.environ",
            {
                "WHISPERCPP_INFERENCE_TIMEOUT_S": "10",  # below 60 floor
                "WHISPERCPP_TIMEOUT_SECONDS_PER_AUDIO_SECOND": "0.1",  # below 0.5 floor
            },
        ):
            assert _resolve_timeout_config() == (60, 0.5)

    def test_timeout_config_defaults_when_no_source(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("server.config.get_config", side_effect=RuntimeError("no config")),
        ):
            assert _resolve_timeout_config() == (
                _INFERENCE_TIMEOUT,
                _TIMEOUT_SECONDS_PER_AUDIO_SECOND,
            )

    def test_load_resolves_config_into_instance_vars(
        self, backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """load() must populate the chunk/timeout instance vars from env/config."""
        mock_httpx.post.return_value = MagicMock(status_code=200)
        with patch.dict(
            "os.environ",
            {
                "WHISPERCPP_SERVER_URL": "http://test:8080",
                "WHISPERCPP_CHUNK_DURATION_S": "300",
                "WHISPERCPP_INFERENCE_TIMEOUT_S": "450",
                "WHISPERCPP_TIMEOUT_SECONDS_PER_AUDIO_SECOND": "1.5",
            },
        ):
            backend.load("ggml-large-v3.bin", "cpu")
        assert backend._max_chunk_duration_s == 300
        assert backend._inference_timeout == 450
        assert backend._timeout_seconds_per_audio_second == 1.5


# ---------------------------------------------------------------------------
# WhisperCppBackend — chunk-boundary cancellation (GH #168 follow-up)
# ---------------------------------------------------------------------------


class TestTranscribeCancellation:
    @staticmethod
    def _resp(payload: dict) -> MagicMock:
        return _inference_response(payload)

    def test_supports_cancellation_is_true(self, backend: WhisperCppBackend):
        assert backend.supports_cancellation() is True

    def test_cancellation_between_chunks_raises_and_stops(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A cancel that flips True before chunk 1 stops after chunk 0's POST."""
        from server.core.model_manager import TranscriptionCancelledError

        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"segments": [], "language": "en"}) for _ in range(3)
        ]
        polls = {"n": 0}

        def cancel() -> bool:
            polls["n"] += 1
            return polls["n"] > 1  # False before chunk 0, True before chunk 1

        with pytest.raises(TranscriptionCancelledError):
            loaded_backend.transcribe(
                np.zeros(3 * 16000, dtype=np.float32), cancellation_check=cancel
            )
        assert _inf(mock_httpx).call_count == 1  # only chunk 0 was sent before the cancel

    def test_cancellation_before_first_chunk_sends_nothing(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        from server.core.model_manager import TranscriptionCancelledError

        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"segments": [], "language": "en"}) for _ in range(3)
        ]
        with pytest.raises(TranscriptionCancelledError):
            loaded_backend.transcribe(
                np.zeros(3 * 16000, dtype=np.float32), cancellation_check=lambda: True
            )
        assert _inf(mock_httpx).call_count == 0

    def test_none_cancellation_check_completes_all_chunks(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"segments": [], "language": "en"}) for _ in range(3)
        ]
        loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32))  # no cancellation_check
        assert _inf(mock_httpx).call_count == 3

    def test_cancellation_never_true_completes(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"segments": [], "language": "en"}) for _ in range(3)
        ]
        loaded_backend.transcribe(
            np.zeros(3 * 16000, dtype=np.float32), cancellation_check=lambda: False
        )
        assert _inf(mock_httpx).call_count == 3


# ---------------------------------------------------------------------------
# Duration-proportional segment/word cap helpers (GH #172)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "duration_s,expected",
    [
        (0.0, _SEGMENT_CAP_FLOOR),  # empty/floor
        (1.0, _SEGMENT_CAP_FLOOR),  # short clip pinned to floor
        (10.0, _SEGMENT_CAP_FLOOR),  # exact crossover (200/20=10s): still floor
        (11.0, 220),  # first step above crossover: proportional wins
        (100.0, 100 * _MAX_SEGMENTS_PER_AUDIO_SECOND),  # proportional regime
        (600.0, 600 * _MAX_SEGMENTS_PER_AUDIO_SECOND),  # 10-min chunk
    ],
)
def test_segment_cap_for_is_proportional_with_floor(duration_s, expected):
    assert _segment_cap_for(duration_s) == expected


@pytest.mark.parametrize(
    "duration_s,expected",
    [
        (0.0, _WORDS_CAP_FLOOR),
        (1.0, _WORDS_CAP_FLOOR),
        (25.0, _WORDS_CAP_FLOOR),  # exact crossover (1000/40=25s)
        (26.0, 1_040),  # proportional wins
        (100.0, 100 * _MAX_WORDS_PER_AUDIO_SECOND),
        (600.0, 600 * _MAX_WORDS_PER_AUDIO_SECOND),  # 10-min chunk (symmetry with segment test)
    ],
)
def test_word_cap_for_is_proportional_with_floor(duration_s, expected):
    assert _word_cap_for(duration_s) == expected


# ---------------------------------------------------------------------------
# WhisperCppBackend — partial persistence on mid-chunk failure (GH #168 follow-up)
# ---------------------------------------------------------------------------


class TestTranscribePartialPersistence:
    @staticmethod
    def _resp(payload: dict) -> MagicMock:
        return _inference_response(payload)

    def test_mid_chunk_failure_raises_partial_with_completed_work(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Chunks 0-1 succeed, chunk 2 times out → PartialTranscriptionError that
        carries the completed (offset) transcript and the transcribed span."""
        from server.core.stt.backends.base import PartialTranscriptionError

        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [
            self._resp({"language": "en", "segments": [{"text": "a", "start": 0.0, "end": 0.5}]}),
            self._resp({"language": "en", "segments": [{"text": "b", "start": 0.0, "end": 0.5}]}),
            httpx.ReadTimeout("sidecar died"),  # chunk 2 fails
        ]
        with pytest.raises(PartialTranscriptionError) as excinfo:
            loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32))
        err = excinfo.value
        assert [s.text for s in err.segments] == ["a", "b"]
        assert err.segments[1].start == 1.0  # second chunk offset onto global timeline
        assert err.completed_seconds == 2.0  # two 1s chunks finished
        assert err.info.language == "en"

    def test_first_chunk_failure_propagates_original_error(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A failure on the very first chunk is a total failure, not a partial."""
        from server.core.stt.backends.base import PartialTranscriptionError

        loaded_backend._max_chunk_duration_s = 1
        _inf(mock_httpx).side_effect = [httpx.ReadTimeout("sidecar died")]  # chunk 0 fails
        with pytest.raises(RuntimeError) as excinfo:
            loaded_backend.transcribe(np.zeros(3 * 16000, dtype=np.float32))
        assert not isinstance(excinfo.value, PartialTranscriptionError)
        assert "transcription timed out" in str(excinfo.value)

    def test_short_audio_failure_is_not_partial(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Single-POST (sub-threshold) failures keep the original error."""
        from server.core.stt.backends.base import PartialTranscriptionError

        _inf(mock_httpx).side_effect = httpx.ReadTimeout("boom")
        with pytest.raises(RuntimeError) as excinfo:
            loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))  # 1s, single POST
        assert not isinstance(excinfo.value, PartialTranscriptionError)


# ---------------------------------------------------------------------------
# WhisperCppBackend — warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_warmup_when_loaded(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        _inf(mock_httpx).return_value = _inference_response({"segments": [], "language": "en"})
        loaded_backend.warmup()  # should not raise

    def test_warmup_noop_when_not_loaded(self, backend: WhisperCppBackend):
        backend.warmup()  # should not raise

    def test_warmup_swallows_transcribe_failure(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A failing inference during warmup must not propagate."""
        _inf(mock_httpx).side_effect = httpx.ConnectError("oops")
        loaded_backend.warmup()  # must not raise
        # The backend should still be marked loaded — warmup failure is cosmetic.
        assert loaded_backend.is_loaded()


# ---------------------------------------------------------------------------
# WhisperCppBackend — diarization
# ---------------------------------------------------------------------------


class TestDiarization:
    def test_returns_none(self, backend: WhisperCppBackend):
        audio = np.zeros(16000, dtype=np.float32)
        result = backend.transcribe_with_diarization(audio)
        assert result is None


# ---------------------------------------------------------------------------
# WhisperCppBackend — internals
# ---------------------------------------------------------------------------


class TestInternals:
    def test_ensure_client_reuses_one_instance(self):
        """_ensure_client() must not create a new httpx.Client on each call.

        whisper-server transcription can be long-running; creating a fresh
        client per call would leak connections and bypass keep-alive.
        ``side_effect`` is used (not ``return_value``) so if the impl were
        to call ``httpx.Client()`` twice the two calls would return two
        *distinct* MagicMocks and the ``is`` check would fail — catching the
        regression the original ``return_value`` form would have silently
        passed.
        """
        backend_ = WhisperCppBackend()
        with patch(
            "server.core.stt.backends.whispercpp_backend.httpx.Client",
            side_effect=[MagicMock(), MagicMock()],
        ) as client_cls:
            c1 = backend_._ensure_client()
            c2 = backend_._ensure_client()
        assert c1 is c2
        assert client_cls.call_count == 1

    def test_parse_response_iterates_every_segment(self):
        """A multi-segment payload yields every segment in input order.

        Renamed from ``test_parse_response_handles_multiple_segments`` per
        review — the new name + first/last assertions catch off-by-one
        mutations (e.g. slicing with ``[:-1]`` or skipping the first).
        """
        result = {
            "language": "en",
            "segments": [
                {"text": "one", "start": 0.0, "end": 1.0},
                {"text": "two", "start": 1.0, "end": 2.0},
                {"text": "three", "start": 2.0, "end": 3.0},
            ],
        }
        segments, info = WhisperCppBackend._parse_response(result, 1.0)
        assert len(segments) == 3
        assert segments[0].text == "one"
        assert segments[1].text == "two"
        assert segments[-1].text == "three"
        assert [s.start for s in segments] == [0.0, 1.0, 2.0]
        assert info.language == "en"

    def test_parse_response_skips_non_dict_segments(self):
        """Stray non-dict entries in the segments list must not crash."""
        result = {
            "segments": [
                "not a segment",
                42,
                None,
                {"text": "ok", "start": 0.0, "end": 1.0},
            ]
        }
        segments, _ = WhisperCppBackend._parse_response(result, 1.0)
        assert len(segments) == 1
        assert segments[0].text == "ok"

    def test_parse_response_accepts_segments_as_none(self):
        """``segments: null`` must not blow up the parser."""
        segments, info = WhisperCppBackend._parse_response({"segments": None}, 1.0)
        assert segments == []
        assert info.language is None

    def test_parse_response_swaps_non_monotonic_bounds(self):
        """Segment with end<start should be swapped (with a warning), not emitted as-is."""
        result = {"segments": [{"text": "bad", "start": 5.0, "end": 2.0}]}
        segments, _ = WhisperCppBackend._parse_response(result, 1.0)
        assert len(segments) == 1
        assert segments[0].start == 2.0
        assert segments[0].end == 5.0

    def test_parse_response_drops_non_monotonic_word(self):
        """Word with end<start should be dropped (mirrors segment behaviour)."""
        result = {
            "segments": [
                {
                    "text": "ok",
                    "start": 0.0,
                    "end": 1.0,
                    "words": [
                        {"word": "bad", "start": 0.5, "end": 0.2},
                        {"word": "good", "start": 0.0, "end": 0.4},
                    ],
                }
            ]
        }
        segments, _ = WhisperCppBackend._parse_response(result, 1.0)
        assert [w["word"] for w in segments[0].words] == ["good"]

    def test_parse_response_rejects_list_word_text(self):
        """``word`` field being a list/dict must not produce a repr-string word."""
        result = {
            "segments": [
                {
                    "text": "ok",
                    "start": 0.0,
                    "end": 1.0,
                    "words": [
                        {"word": [1, 2, 3], "start": 0.0, "end": 0.5},
                        {"word": "good", "start": 0.5, "end": 1.0},
                    ],
                }
            ]
        }
        segments, _ = WhisperCppBackend._parse_response(result, 1.0)
        assert [w["word"] for w in segments[0].words] == ["good"]

    def test_mock_httpx_patches_the_call_site(self, mock_httpx: MagicMock):
        """Regression probe: the fixture must actually replace the real Client.

        If a refactor hoists ``from httpx import Client`` to module top-level,
        the patch target ``whispercpp_backend.httpx.Client`` stops applying
        and real HTTP calls happen in tests. Pinning the coupling here means
        that refactor fails loudly instead of sleep-walking into real requests.
        """
        from server.core.stt.backends import whispercpp_backend

        # Instantiating through the module should return the mocked client.
        backend_ = whispercpp_backend.WhisperCppBackend()
        client = backend_._ensure_client()
        assert client is mock_httpx
