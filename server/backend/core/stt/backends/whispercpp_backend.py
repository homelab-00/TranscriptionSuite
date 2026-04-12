"""whisper.cpp sidecar backend — HTTP client to whisper-server."""

from __future__ import annotations

import io
import logging
import math
import os
import re
import struct
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx
import numpy as np
from httpx import DecodingError as HttpxDecodingError
from httpx import HTTPStatusError as HttpxHTTPStatusError
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_URL = "http://whisper-server:8080"
_INFERENCE_TIMEOUT = 300  # seconds — long audio can take a while
# TODO(GH-62-followup): scale _INFERENCE_TIMEOUT with audio duration. At
# 300s a ~2h file on a slow Vulkan GPU can legitimately exceed the ceiling
# and get mis-reported as a sidecar timeout. Provisional: max(300, dur*10).
_LOAD_TIMEOUT = 60

# whisper-server's own default for beam_size (see
# ``examples/server/server.cpp``). Named so the client-vs-server default
# coupling is grep-able.
_WHISPER_SERVER_DEFAULT_BEAM_SIZE = 5

# Defensive caps on the sidecar response. A compromised whisper-server —
# or one reached through a misconfigured ``WHISPERCPP_SERVER_URL`` pointing
# at a hostile service — could otherwise return a payload that exhausts
# memory while being "parsed". A real 2-hour transcript holds ~5k segments
# at whisper.cpp's default chunking, so 10k gives a 2× safety margin; real
# words-per-segment is bounded by whisper's 30s audio window (< a few hundred
# tokens), so 5k is already generous.
_MAX_SEGMENTS = 10_000
_MAX_WORDS_PER_SEGMENT = 5_000

# Practical cap on user-supplied initial_prompt. whisper.cpp uses the prompt
# as a decoder hint in the context window (~224 tokens ≈ ~1 KB of text). A
# 10 MB prompt is only going to be truncated anyway — cap it client-side so
# we don't upload megabytes that will be discarded.
_MAX_PROMPT_CHARS = 4_096

# Plausible audio sample-rate range — guards against 0 (divide-by-zero in
# downstream consumers) and integer overflow into the WAV ``byte_rate`` field.
_MIN_SAMPLE_RATE_HZ = 1
_MAX_SAMPLE_RATE_HZ = 384_000

# Language codes we propagate must look like BCP-47 fragments
# (ISO-639 alpha-2/alpha-3, plus optional region/script suffix). Anything
# else is replaced with None so a malicious sidecar cannot inject newlines
# or ANSI control sequences via ``language`` into logs or the dashboard.
_LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8})*$")

_SIDECAR_UNREACHABLE_MSG = (
    "whisper.cpp sidecar is not reachable at {url}. "
    "This usually means the Vulkan runtime profile is not selected or the "
    "sidecar container failed to start. GGML models (whisper.cpp) require "
    'the Vulkan runtime profile — switch to "Vulkan" in Settings and restart '
    "the container, or choose a non-GGML model for CPU mode."
)

_SIDECAR_LOAD_TIMEOUT_MSG = (
    "whisper.cpp sidecar at {url} is reachable but the model load timed out "
    "after {timeout}s. The sidecar may still be downloading or initialising "
    "the model. Wait a moment and retry, or check the sidecar container logs."
)

_SIDECAR_INFERENCE_TIMEOUT_MSG = (
    "whisper.cpp sidecar at {url} accepted the request but transcription "
    "timed out after {timeout}s. This usually means the audio is too long for "
    "the current timeout, or the Vulkan device is under heavy load. Try "
    "shorter audio or check the sidecar container logs."
)


def _resolve_server_url() -> str:
    """Resolve whisper-server URL from env → config → default.

    Any user-provided value that does not parse as an ``http``/``https`` URL
    with a host is rejected and falls through to the default. This is a
    lightweight SSRF guard: we cannot prevent a determined desktop user from
    pointing the backend at their own LAN, but we can refuse schemes like
    ``file://`` or ``gopher://`` that httpx would otherwise pass through.
    """
    env_url = os.environ.get("WHISPERCPP_SERVER_URL", "").strip()
    if env_url:
        validated = _validate_server_url(env_url)
        if validated:
            return validated
        logger.warning("Ignoring invalid WHISPERCPP_SERVER_URL (expected http(s)://host[:port])")

    try:
        from server.config import get_config

        cfg = get_config()
        cfg_url = (cfg.get("whisper_cpp", "server_url") or "").strip()
        if cfg_url:
            validated = _validate_server_url(cfg_url)
            if validated:
                return validated
            logger.warning(
                "Ignoring invalid whisper_cpp.server_url in config (expected http(s)://host[:port])"
            )
    except Exception as _exc:
        logger.debug("Could not read whisper_cpp server_url from config: %s", repr(_exc))

    return _DEFAULT_SERVER_URL


def _validate_server_url(url: str) -> str | None:
    """Return a sanitised http(s) URL (no userinfo, no trailing slash), else None.

    Userinfo (``user:pass@host``) is stripped so credentials embedded in a
    mis-configured URL cannot leak into the error messages or logs that
    interpolate ``self._server_url``. Any ASCII control character in the
    input is rejected outright — urlparse happily accepts CRLF and NUL
    within the netloc on some Python versions, which would let a crafted
    value splice fake headers into httpx's request.
    """
    if any(ch < " " or ch == "\x7f" for ch in url):
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.hostname:
        return None
    # Rebuild without userinfo/query/fragment — we only use scheme + host[:port].
    port = f":{parsed.port}" if parsed.port else ""
    rebuilt = f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path}"
    return rebuilt.rstrip("/")


def _coerce_float(value: Any) -> float | None:
    """Return ``value`` as a *finite* float, otherwise ``None``.

    Guards ``_parse_response`` against malformed sidecar payloads (strings,
    nulls, bools, NaN, +Inf, -Inf) without masking the real schema — callers
    only skip fields that truly can't be turned into a finite number. NaN
    and Inf are rejected because they round-trip through JSON badly (the
    stdlib encoder raises by default) and would poison downstream
    serialization.

    We deliberately accept numpy scalar types (``np.float32``, ``np.int64``,
    etc.) as well as built-in ``int``/``float`` because an intermediate
    deserialiser (e.g. a future httpx→numpy bridge, or a unit test that
    passes prebuilt arrays) can legitimately hand us numpy numbers. They're
    detected by module (``type(value).__module__ == "numpy"``) rather than
    by ``isinstance(value, np.generic)`` to avoid a hard import dependency
    ordering that would otherwise ripple through the test suite.
    """
    if isinstance(value, bool):  # bool is a subclass of int — reject
        return None
    if isinstance(value, (int, float)) or type(value).__module__ == "numpy":
        try:
            as_float = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(as_float):
            return None
        return as_float
    return None


def _coerce_text(value: Any) -> str:
    """Return a stripped string for scalar input, empty string for everything else.

    ``str(x).strip()`` on a list or dict produces a Python ``repr`` string
    (e.g. ``"[1, 2]"``) that slips past later ``if not text`` guards and
    would be appended as transcript output. Restrict to real scalars.
    """
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if type(value).__module__ == "numpy":
        return str(value).strip()
    return ""


def _sanitize_language_code(value: Any) -> str | None:
    """Return ``value`` if it parses as a plausible BCP-47 code, else ``None``.

    The sidecar is treated as untrusted: its ``language`` / ``detected_language``
    is eventually logged and written to the database, so a value containing
    newlines, ANSI escape sequences, or hundreds of kilobytes of garbage
    must not propagate. A code that fails the regex is dropped with a debug
    log rather than being cleaned in-place, because we cannot safely guess
    the intended code.
    """
    if not isinstance(value, str):
        return None
    # Hard cap before regex so a pathological input can't drive catastrophic
    # backtracking or log-message size.
    candidate = value.strip()[:32]
    if not candidate:
        return None
    if not _LANGUAGE_CODE_RE.match(candidate):
        logger.debug("whisper-server returned a non-BCP-47 language code; dropping")
        return None
    return candidate


def _sanitize_for_error_preview(body: bytes, *, limit: int = 200) -> str:
    """Produce a safe short preview of an untrusted response body for an error.

    Non-printable and control characters are replaced so the resulting string
    is safe to splice into a ``RuntimeError`` that the UI may render as-is.
    Input bytes are pre-sliced so a multi-gigabyte error page doesn't force
    decoding the whole body just to throw most of it away.
    """
    import unicodedata

    # Pre-slice on bytes so we don't allocate a huge ``str`` for a huge body.
    # ×4 is the worst-case UTF-8 expansion per codepoint; after decoding we
    # slice again to ``limit`` codepoints.
    prefix = body[: limit * 4].decode("utf-8", errors="replace")[:limit]

    def _safe(ch: str) -> str:
        # Reject Unicode control (Cc), format (Cf — e.g. U+200B, U+202E) and
        # surrogate (Cs) characters regardless of ``isprintable()``. The RLO
        # mark (U+202E) is printable but can reverse displayed text and
        # mislead users reading the error in a rich log viewer.
        cat = unicodedata.category(ch)
        if cat in {"Cc", "Cf", "Cs"} and ch not in " \t":
            return f"\\x{ord(ch):02x}"
        if ch.isprintable() or ch in " \t":
            return ch
        return f"\\x{ord(ch):02x}"

    return "".join(_safe(c) for c in prefix)


def _audio_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Encode a float32 mono ndarray as a WAV byte buffer.

    Rejects invalid sample rates up front so ``struct.pack("<I", ...)`` cannot
    ``OverflowError`` on a negative/huge value, and replaces NaN/Inf samples
    with 0 — ``np.int16`` conversion of a non-finite float is
    implementation-defined and silently corrupts the audio sent to the
    sidecar.
    """
    if not isinstance(sample_rate, (int, np.integer)):
        raise ValueError(f"sample_rate must be an int, got {type(sample_rate).__name__}")
    if not _MIN_SAMPLE_RATE_HZ <= int(sample_rate) <= _MAX_SAMPLE_RATE_HZ:
        raise ValueError(
            f"sample_rate out of range [{_MIN_SAMPLE_RATE_HZ}..{_MAX_SAMPLE_RATE_HZ}]: "
            f"{sample_rate}"
        )
    # Replace NaN/+Inf/-Inf with zero so the int16 conversion is well-defined.
    if not np.all(np.isfinite(audio)):
        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    raw = pcm.tobytes()
    buf = io.BytesIO()
    # WAV header
    num_samples = len(pcm)
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))  # chunk size
    buf.write(struct.pack("<H", 1))  # PCM
    buf.write(struct.pack("<H", 1))  # mono
    buf.write(struct.pack("<I", int(sample_rate)))
    buf.write(struct.pack("<I", int(sample_rate) * 2))  # byte rate
    buf.write(struct.pack("<H", 2))  # block align
    buf.write(struct.pack("<H", 16))  # bits per sample
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(raw)
    return buf.getvalue()


def _parse_words(raw_words: Any) -> list[dict[str, Any]]:
    """Convert a sidecar ``words`` array into the normalised word-dict list.

    Applies the same filter-then-cap discipline as the segment-level parser
    and silently drops per-word entries that fail validation (non-dict,
    missing text, missing bounds, non-monotonic bounds).
    """
    if not isinstance(raw_words, list):
        return []
    dict_words = [w for w in raw_words if isinstance(w, dict)]
    if len(dict_words) > _MAX_WORDS_PER_SEGMENT:
        logger.warning(
            "whisper-server segment had %d word dicts, truncating to %d",
            len(dict_words),
            _MAX_WORDS_PER_SEGMENT,
        )
        dict_words = dict_words[:_MAX_WORDS_PER_SEGMENT]

    words: list[dict[str, Any]] = []
    for w in dict_words:
        # Prefer ``word`` but fall back to ``text``. Use explicit None check
        # so a legitimate ``0`` (rare but valid JSON) survives.
        raw_word = w.get("word")
        if raw_word is None:
            raw_word = w.get("text")
        text = _coerce_text(raw_word)
        start = _coerce_float(w.get("start"))
        end = _coerce_float(w.get("end"))
        if not text or start is None or end is None:
            continue
        if end < start:
            # Same non-monotonic handling as at the segment level.
            logger.debug(
                "dropping word with non-monotonic bounds (start=%.3f > end=%.3f)",
                start,
                end,
            )
            continue
        prob = _coerce_float(w.get("probability"))
        words.append(
            {
                "word": text,
                "start": start,
                "end": end,
                "probability": prob if prob is not None else 0.0,
            }
        )
    return words


class WhisperCppBackend(STTBackend):
    """STTBackend that delegates to a whisper.cpp whisper-server via HTTP."""

    def __init__(self) -> None:
        self._server_url: str = ""
        self._model_name: str | None = None
        self._loaded: bool = False
        self._client: httpx.Client | None = None

    def _ensure_client(self) -> httpx.Client:
        """Return (or create) a persistent httpx.Client.

        TODO(GH-62-followup #G): this is not thread-safe — two concurrent
        callers both passing the ``self._client is None`` check would each
        construct a Client, and one would be leaked. In practice all
        entrypoints hold the engine's ``transcription_lock`` so concurrent
        invocation cannot happen, but the invariant is undocumented. A
        ``threading.Lock`` around construction is cheap and removes the
        ambient assumption.
        """
        if self._client is None:
            self._client = httpx.Client(timeout=_INFERENCE_TIMEOUT)
        return self._client

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        self._server_url = _resolve_server_url()
        self._model_name = model_name
        logger.info(
            "WhisperCppBackend: loading model %s via %s",
            model_name,
            self._server_url,
        )

        client = self._ensure_client()
        try:
            resp = client.post(
                f"{self._server_url}/load",
                json={"model": model_name},
                timeout=_LOAD_TIMEOUT,
            )
            resp.raise_for_status()
        except (httpx.NetworkError, OSError) as exc:
            self._close_client_silently()
            raise RuntimeError(_SIDECAR_UNREACHABLE_MSG.format(url=self._server_url)) from exc
        except httpx.TimeoutException as exc:
            self._close_client_silently()
            raise RuntimeError(
                _SIDECAR_LOAD_TIMEOUT_MSG.format(url=self._server_url, timeout=_LOAD_TIMEOUT)
            ) from exc
        except HttpxHTTPStatusError:
            logger.warning(
                "WhisperCppBackend: /load returned an error status (server may "
                "pre-load the model); continuing anyway",
            )

        self._loaded = True
        logger.info("WhisperCppBackend: model ready")

    def _close_client_silently(self) -> None:
        """Close and release the httpx client, swallowing any close error.

        Extracted so error paths in :py:meth:`load` and :py:meth:`unload` share
        a single implementation. Without this, a caller that retries ``load``
        after a connect/timeout failure would leak one socket per attempt
        (see review finding #13 from the GH-62 iteration-2 audit).
        """
        if self._client is None:
            return
        try:
            self._client.close()
        except Exception as _exc:
            logger.debug("Failed to close HTTP client cleanly: %s", repr(_exc))
        self._client = None

    def unload(self) -> None:
        self._model_name = None
        self._loaded = False
        self._close_client_silently()

    def is_loaded(self) -> bool:
        return self._loaded

    def warmup(self) -> None:
        if not self._loaded:
            return
        logger.info("WhisperCppBackend: warmup — sending silent audio")
        silence = np.zeros(16000, dtype=np.float32)  # 1 second
        try:
            self.transcribe(silence)
        except Exception:
            logger.warning("WhisperCppBackend: warmup inference failed (non-fatal)")

    def transcribe(  # noqa: PLR0913 — matches STTBackend.transcribe() contract
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = 16000,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = _WHISPER_SERVER_DEFAULT_BEAM_SIZE,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,  # noqa: ARG002 — see NOTE below
        vad_filter: bool = True,  # noqa: ARG002
        word_timestamps: bool = True,
        translation_target_language: str | None = None,  # noqa: ARG002
        progress_callback: Callable[[int, int], None] | None = None,  # noqa: ARG002
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        # NOTE: the following parameters are part of the STTBackend contract
        # but have no equivalent on whisper.cpp's /inference HTTP form API
        # (or on the current sidecar image), so we accept and ignore them
        # instead of raising — matching how the base-class default handles
        # unsupported kwargs. See GH-62-followup: a base-class ``supports()``
        # capability probe would let the engine reject these at call time
        # instead of silently discarding user intent.
        #   * suppress_tokens — not exposed by whisper.cpp HTTP form.
        #   * vad_filter      — a ``vad`` form field exists but only works
        #     when the server was started with --vad-model, which
        #     docker-compose.vulkan.yml does not mount.
        #   * translation_target_language — whisper always translates to
        #     English; non-English targets are rejected upstream in
        #     capabilities.py::validate_translation_request.
        #   * progress_callback — /inference is synchronous, so we cannot
        #     emit incremental ticks. Caller will only see a single
        #     final result after the whole file finishes.

        if not self._loaded:
            raise RuntimeError("WhisperCppBackend: model is not loaded")

        if beam_size <= 0:
            raise ValueError(f"beam_size must be positive, got {beam_size}")

        if audio is None or len(audio) == 0:
            # Nothing to transcribe — return an empty result instead of sending
            # a zero-sample WAV that some sidecar versions error on.
            return [], BackendTranscriptionInfo(language=None, language_probability=0.0)

        wav_bytes = _audio_to_wav_bytes(audio, audio_sample_rate)

        data: dict[str, Any] = {
            "response_format": "verbose_json",
        }
        # ``language`` and ``initial_prompt`` are user-controlled; a stray
        # whitespace-only value would be forwarded verbatim and trigger
        # spurious server-side warnings. Strip before truthiness check.
        if language and language.strip():
            data["language"] = language.strip()
        if task == "translate":
            data["translate"] = "true"
        if initial_prompt and initial_prompt.strip():
            data["prompt"] = initial_prompt.strip()[:_MAX_PROMPT_CHARS]
        if beam_size != _WHISPER_SERVER_DEFAULT_BEAM_SIZE:
            data["beam_size"] = str(beam_size)
        if word_timestamps:
            # Tell the sidecar to split tokens at word boundaries so the
            # per-word ``start``/``end`` timings in the response line up with
            # whole words rather than sub-word BPE pieces. MUST be the
            # lowercase string ``"true"`` — whisper.cpp's server compares the
            # form value to that literal (see server.cpp ``req.has_file``).
            data["split_on_word"] = "true"

        client = self._ensure_client()
        try:
            resp = client.post(
                f"{self._server_url}/inference",
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data=data,
                timeout=_INFERENCE_TIMEOUT,
            )
            resp.raise_for_status()
        except (httpx.NetworkError, OSError) as exc:
            raise RuntimeError(_SIDECAR_UNREACHABLE_MSG.format(url=self._server_url)) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                _SIDECAR_INFERENCE_TIMEOUT_MSG.format(
                    url=self._server_url, timeout=_INFERENCE_TIMEOUT
                )
            ) from exc
        except HttpxHTTPStatusError as exc:
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned HTTP "
                f"{exc.response.status_code} for /inference"
            ) from exc
        except HttpxDecodingError as exc:
            # Unexpected Content-Encoding (e.g. brotli without the optional
            # dep installed) raises DecodingError, which doesn't inherit from
            # NetworkError. Without this handler it bubbles as an opaque
            # trace. Treat it the same as a malformed response.
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned an "
                f"undecodable response for /inference: {exc}"
            ) from exc

        try:
            result = resp.json()
        except ValueError as exc:
            # Sidecar returned non-JSON (e.g. plain-text error page).
            body_preview = _sanitize_for_error_preview(resp.content) or "(empty)"
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned non-JSON "
                f"response from /inference: {body_preview}"
            ) from exc

        return self._parse_response(result)

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "whispercpp"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(
        result: dict[str, Any],
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Convert whisper-server /inference verbose_json into segments + info.

        whisper.cpp's server emits (see ``examples/server/server.cpp``)::

            {
              "language": "en",
              "detected_language": "en",                 # optional
              "detected_language_probability": 0.98,     # optional
              "segments": [{
                "id": 0,
                "text": " Hello world",
                "start": 0.0,                # seconds
                "end":   2.5,                # seconds
                "tokens": [3, 7, 12, ...],   # int token IDs — NOT dicts
                "words":  [                  # per-word timing
                  {"word": " Hello", "start": 0.0, "end": 0.5,
                   "probability": 0.95, "t_dtw": -1}
                ]
              }]
            }
        """
        segments: list[BackendSegment] = []
        raw_segments = result.get("segments")
        if not isinstance(raw_segments, list):
            raw_segments = []

        # Filter to dict-typed segments FIRST, cap afterwards. If we capped
        # first and the payload had thousands of stray non-dict entries at
        # the front, the cap would slice them out and drop the real segments
        # that followed.
        dict_segments = [s for s in raw_segments if isinstance(s, dict)]
        if len(dict_segments) > _MAX_SEGMENTS:
            logger.warning(
                "whisper-server returned %d segment dicts, truncating to %d to bound memory",
                len(dict_segments),
                _MAX_SEGMENTS,
            )
            dict_segments = dict_segments[:_MAX_SEGMENTS]

        for seg in dict_segments:
            words = _parse_words(seg.get("words"))

            seg_start = _coerce_float(seg.get("start"))
            seg_end = _coerce_float(seg.get("end"))
            if seg_start is None or seg_end is None:
                # whisper.cpp only omits timestamps when run with
                # ``--no-timestamps`` — surface it so downstream layers that
                # rely on segment timing (speaker merge, SRT export) do not
                # silently collapse the segment onto t=0.
                logger.warning(
                    "whisper-server returned a segment without start/end; "
                    "falling back to 0.0 for missing bound(s). "
                    "Enable timestamps on the sidecar to get correct timing."
                )
                seg_start_f = seg_start if seg_start is not None else 0.0
                seg_end_f = seg_end if seg_end is not None else 0.0
            elif seg_end < seg_start:
                # Non-monotonic bounds break SRT export and speaker merge; the
                # sidecar has a real bug but we can't correct it — swap so
                # downstream code at least sees a valid interval and log loudly.
                logger.warning(
                    "whisper-server returned non-monotonic segment bounds "
                    "(start=%.3f > end=%.3f); swapping",
                    seg_start,
                    seg_end,
                )
                seg_start_f, seg_end_f = seg_end, seg_start
            else:
                seg_start_f, seg_end_f = seg_start, seg_end

            segments.append(
                BackendSegment(
                    text=_coerce_text(seg.get("text")),
                    start=seg_start_f,
                    end=seg_end_f,
                    words=words,
                )
            )

        raw_lang = result.get("language") or result.get("detected_language")
        detected_lang = _sanitize_language_code(raw_lang)
        prob = _coerce_float(result.get("detected_language_probability"))
        info = BackendTranscriptionInfo(
            language=detected_lang,
            language_probability=prob if prob is not None else 0.0,
        )
        return segments, info
