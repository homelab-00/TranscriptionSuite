"""Tests for WhisperCppBackend — HTTP client to whisper-server sidecar."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest
from server.core.stt.backends.whispercpp_backend import (
    _MAX_SEGMENTS,
    _MAX_WORDS_PER_SEGMENT,
    WhisperCppBackend,
    _audio_to_wav_bytes,
    _coerce_float,
    _resolve_server_url,
    _sanitize_for_error_preview,
    _sanitize_language_code,
    _validate_server_url,
)

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
    call = mock_httpx.post.call_args
    assert call is not None, "expected a POST to have been issued"
    return call.kwargs.get("data") or call[1].get("data", {}) or {}


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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio)
        call = mock_httpx.post.call_args
        assert call is not None, "expected a POST to have been issued"
        # URL assertion — catches any routing regression.
        assert call.args[0].endswith("/inference") or call.kwargs.get("url", "").endswith(
            "/inference"
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "segments": [
                        {"text": "  Hello world   ", "start": 0.0, "end": 1.0},
                    ]
                }
            ),
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        assert segments[0].words[0]["word"] == "0"  # not "wrong-fallback"

    def test_tolerates_missing_top_level_fields(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Empty or absent segments list must return an empty transcription cleanly."""
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={}),
        )
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

        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "language": "en",
                    "segments": [
                        {"id": 0, "text": " hi"}  # no start/end
                    ],
                }
            ),
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = loaded_backend.transcribe(audio)
        assert [w["probability"] for w in segments[0].words] == [0.0, 0.37, 0.91]
        assert info.language_probability == pytest.approx(0.42)

    def test_missing_probability_defaults_to_zero(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Distinguishes the default-path from the preservation-path above."""
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        assert segments[0].words[0]["probability"] == 0.0

    def test_nan_timestamps_are_dropped(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """NaN/Inf from a broken sidecar must not poison the segment list."""
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
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
            ),
        )
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = loaded_backend.transcribe(audio)
        # Segment falls back to 0.0/0.0 (with a warning) because both bounds
        # failed validation.
        assert segments[0].start == 0.0
        assert segments[0].end == 0.0
        # The word with NaN start is dropped entirely.
        assert segments[0].words == []

    @pytest.mark.parametrize(
        "count,expected",
        [
            (_MAX_SEGMENTS - 1, _MAX_SEGMENTS - 1),  # below cap — all kept
            (_MAX_SEGMENTS, _MAX_SEGMENTS),  # exactly at cap — all kept
            (_MAX_SEGMENTS + 1, _MAX_SEGMENTS),  # one over — truncated
            (_MAX_SEGMENTS + 50, _MAX_SEGMENTS),  # far over — truncated
        ],
    )
    def test_segment_cap_boundary(
        self,
        loaded_backend: WhisperCppBackend,
        mock_httpx: MagicMock,
        count: int,
        expected: int,
    ):
        """Boundary matrix for the cap — catches off-by-one mutations (>= vs >, -1 slice)."""
        bloated = [{"text": "x", "start": 0.0, "end": 0.1} for _ in range(count)]
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": bloated}),
        )
        segments, _ = loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert len(segments) == expected

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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": noise + real}),
        )
        segments, _ = loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert len(segments) == 100
        assert segments[0].text == "s0"
        assert segments[-1].text == "s99"

    @pytest.mark.parametrize(
        "count,expected",
        [
            (_MAX_WORDS_PER_SEGMENT - 1, _MAX_WORDS_PER_SEGMENT - 1),
            (_MAX_WORDS_PER_SEGMENT, _MAX_WORDS_PER_SEGMENT),
            (_MAX_WORDS_PER_SEGMENT + 1, _MAX_WORDS_PER_SEGMENT),
            (_MAX_WORDS_PER_SEGMENT + 10, _MAX_WORDS_PER_SEGMENT),
        ],
    )
    def test_word_cap_boundary(
        self,
        loaded_backend: WhisperCppBackend,
        mock_httpx: MagicMock,
        count: int,
        expected: int,
    ):
        """Same boundary matrix as the segment cap."""
        bloated = [
            {"word": "x", "start": i * 0.001, "end": i * 0.001 + 0.0005} for i in range(count)
        ]
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "segments": [{"text": "seg", "start": 0.0, "end": 999.0, "words": bloated}]
                }
            ),
        )
        segments, _ = loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert len(segments[0].words) == expected

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

        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "language": "en\nCRITICAL root: spliced log line",
                    "segments": [],
                }
            ),
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
        resp = MagicMock(
            status_code=200,
            content=b"<html>\x1b[31mcrash\x00boom</html>",
        )
        resp.json.side_effect = ValueError("not json")
        mock_httpx.post.return_value = resp
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, word_timestamps=False)
        data = _post_data(mock_httpx)
        assert "split_on_word" not in data

    def test_language_and_prompt_forwarded(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "el"}),
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": []}),
        )
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, language=None, initial_prompt=None)
        data = _post_data(mock_httpx)
        assert "language" not in data
        assert "prompt" not in data

    def test_whitespace_language_and_prompt_omitted(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Whitespace-only values must not be forwarded."""
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": []}),
        )
        audio = np.zeros(16000, dtype=np.float32)
        loaded_backend.transcribe(audio, language="   ", initial_prompt="  \t ")
        data = _post_data(mock_httpx)
        assert "language" not in data
        assert "prompt" not in data

    def test_prompt_is_capped(self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock):
        """A 10 MB initial_prompt must not be uploaded as-is — whisper.cpp only
        uses ~224 tokens anyway."""
        huge_prompt = "x" * 100_000
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": []}),
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
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
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": []}),
        )
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
        mock_httpx.post.assert_not_called()

    def test_unsupported_params_are_accepted_and_silently_dropped(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Callers can pass params the sidecar cannot honour without crashing.

        ``suppress_tokens``, ``vad_filter``, ``translation_target_language``
        and ``progress_callback`` have no HTTP-form equivalent on the current
        sidecar image, so they must be accepted (for interface parity with
        other backends) but never leak into the POST body.
        """
        mock_httpx.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"segments": [], "language": "en"}),
        )
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

    def test_transcribe_raises_on_timeout(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """Inference timeout must surface the inference-timeout message."""
        mock_httpx.post.side_effect = httpx.ReadTimeout("deadline")
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="transcription timed out"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_http_5xx(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A 5xx from /inference must surface as an actionable RuntimeError."""
        resp = MagicMock(status_code=503)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable", request=MagicMock(), response=resp
        )
        mock_httpx.post.return_value = resp
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="returned HTTP 503"):
            loaded_backend.transcribe(audio)

    def test_transcribe_raises_on_non_json_response(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A non-JSON body (HTML error page, empty string, etc.) must be surfaced."""
        resp = MagicMock(status_code=200, content=b"<html>fatal</html>")
        resp.json.side_effect = ValueError("not json")
        mock_httpx.post.return_value = resp
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="non-JSON"):
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

    def test_warmup_swallows_transcribe_failure(
        self, loaded_backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """A failing inference during warmup must not propagate."""
        mock_httpx.post.side_effect = httpx.ConnectError("oops")
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
        segments, info = WhisperCppBackend._parse_response(result)
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
        segments, _ = WhisperCppBackend._parse_response(result)
        assert len(segments) == 1
        assert segments[0].text == "ok"

    def test_parse_response_accepts_segments_as_none(self):
        """``segments: null`` must not blow up the parser."""
        segments, info = WhisperCppBackend._parse_response({"segments": None})
        assert segments == []
        assert info.language is None

    def test_parse_response_swaps_non_monotonic_bounds(self):
        """Segment with end<start should be swapped (with a warning), not emitted as-is."""
        result = {"segments": [{"text": "bad", "start": 5.0, "end": 2.0}]}
        segments, _ = WhisperCppBackend._parse_response(result)
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
        segments, _ = WhisperCppBackend._parse_response(result)
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
        segments, _ = WhisperCppBackend._parse_response(result)
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
