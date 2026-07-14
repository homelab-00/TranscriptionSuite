"""Behavioural tests for the abortable whisper.cpp /inference transport.

These run against a REAL localhost socket server, not a mock. That is
deliberate: the property under test is that an abort actually interrupts a
socket read that is blocked with zero bytes received. A mock transport cannot
prove that — it would happily "abort" something that was never really blocked,
which is exactly the failure mode that made the previous sync-httpx approach
look correct while being impossible.

The fake sidecar reproduces whisper-server's defining wire behaviour: it accepts
the POST, drains the request body, and then sends NOTHING AT ALL — not even
response headers — for ``stall`` seconds. Every timeout/abort property of the
transport hangs off that silence.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
from server.core.stt.backends.whispercpp_transport import (
    InferenceAborted,
    ResponseTooLarge,
    post_inference,
)

# A stall long enough that any accidental "it just completed normally" would be
# unmistakable in the elapsed time.
WEDGED_STALL_S = 30.0

WAV = b"RIFF____WAVEfmt " + b"\x00" * 32
FORM = {"response_format": "json", "temperature": "0.0"}


def _drain_request(conn: socket.socket) -> None:
    """Read the full HTTP request (headers + Content-Length body) off the wire.

    Without this the client could block writing, and we would be testing the
    wrong silence.
    """
    conn.settimeout(10.0)
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(65536)
        if not chunk:
            return
        buf += chunk

    head, _, rest = buf.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())

    remaining = length - len(rest)
    while remaining > 0:
        chunk = conn.recv(min(65536, remaining))
        if not chunk:
            return
        remaining -= len(chunk)
    conn.settimeout(None)


def _http_reply(body: bytes, *, declare_length: bool) -> bytes:
    """A 200 response, either Content-Length framed or close-framed."""
    if declare_length:
        headers = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
        )
    else:
        # No Content-Length and no chunked encoding: the body is terminated by
        # the connection close. This forces the transport to discover the size
        # WHILE streaming rather than from a header it can pre-check.
        headers = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
    return headers + body


def _start_fake_sidecar(
    stall_s: float,
    reply: bytes | None,
) -> tuple[str, socket.socket]:
    """Serve exactly one /inference request: drain, stay silent, then reply.

    Returns the URL and the listening socket (the caller must close it).
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def _serve() -> None:
        try:
            conn, _ = listener.accept()
        except OSError:  # listener closed by the test's finally block
            return
        with conn:
            try:
                _drain_request(conn)
                # The whole point: total silence, no headers, for stall_s.
                threading.Event().wait(stall_s)
                if reply is not None:
                    conn.sendall(reply)
            except OSError:
                # Client aborted mid-flight — that is a passing outcome here.
                pass

    threading.Thread(target=_serve, daemon=True).start()
    return f"http://127.0.0.1:{port}/inference", listener


def test_slow_but_healthy_completes_with_no_time_limit() -> None:
    """A slow-but-honest sidecar must be waited for, not cut off.

    This is the entire reason for the change: the old ~2x-real-time read cap
    killed requests like this one and silently truncated the transcript.
    """
    payload = json.dumps({"text": "the slow machine finished"}).encode()
    url, listener = _start_fake_sidecar(3.0, _http_reply(payload, declare_length=True))
    try:
        started = time.monotonic()
        body = post_inference(url, WAV, dict(FORM), cancellation_check=lambda: False)
        elapsed = time.monotonic() - started
    finally:
        listener.close()

    assert json.loads(body)["text"] == "the slow machine finished"
    # It waited rather than timing out — no work deadline is being applied.
    assert elapsed >= 3.0, f"returned in {elapsed:.2f}s, so it cannot have waited out the stall"


def test_cancel_aborts_a_wedged_request_promptly() -> None:
    """LOAD-BEARING: cancellation must interrupt a read blocked on zero bytes.

    An unbounded read is only defensible because of this. If this ever regresses,
    a wedged sidecar pins a worker thread forever and the Cancel button lies.
    """
    url, listener = _start_fake_sidecar(WEDGED_STALL_S, None)
    cancelled = threading.Event()
    timer = threading.Timer(1.0, cancelled.set)
    timer.start()
    try:
        started = time.monotonic()
        with pytest.raises(InferenceAborted):
            post_inference(url, WAV, dict(FORM), cancellation_check=cancelled.is_set)
        elapsed = time.monotonic() - started
    finally:
        timer.cancel()
        listener.close()

    assert elapsed < 5.0, (
        f"abort took {elapsed:.2f}s against a {WEDGED_STALL_S:.0f}s stall — "
        "the read was not actually interrupted"
    )


def test_connect_stays_bounded_against_a_dead_host() -> None:
    """No cancellation_check means read=None, but connect must STILL be bounded.

    A bare scalar timeout would have expanded to all four phases; the regression
    this guards is the inverse — that removing the read cap does not also remove
    the connect cap and let a blackholed host hang for tens of minutes.
    """
    started = time.monotonic()
    with pytest.raises(httpx.ConnectError):
        post_inference(
            "http://127.0.0.1:1/inference",
            WAV,
            dict(FORM),
            cancellation_check=lambda: False,
        )
    elapsed = time.monotonic() - started

    assert elapsed < 15.0, f"connect phase took {elapsed:.2f}s; it is not bounded"


def test_uncancellable_caller_gets_a_finite_read() -> None:
    """Callers with no abort path (warmup/live/preview) keep a real read deadline."""
    url, listener = _start_fake_sidecar(WEDGED_STALL_S, None)
    try:
        started = time.monotonic()
        with pytest.raises(httpx.ReadTimeout):
            post_inference(url, WAV, dict(FORM), cancellation_check=None, read_timeout_s=2.0)
        elapsed = time.monotonic() - started
    finally:
        listener.close()

    assert elapsed < 10.0, f"read timeout did not fire (took {elapsed:.2f}s)"


def test_uncancellable_caller_without_a_read_timeout_is_rejected() -> None:
    """An unbounded read with no way out is a hang, so it must be refused up front."""
    with pytest.raises(ValueError, match="read_timeout_s"):
        post_inference(
            "http://127.0.0.1:1/inference",
            WAV,
            dict(FORM),
            cancellation_check=None,
            read_timeout_s=None,
        )


@pytest.mark.parametrize("declare_length", [True, False], ids=["declared", "undeclared"])
def test_oversized_response_is_rejected_during_the_read(declare_length: bool) -> None:
    """The ceiling must hold whether or not the sidecar declares Content-Length.

    A post-parse cap is too late: the memory is already spent. The undeclared
    case is the one that matters — it proves the guard fires while streaming.
    """
    payload = json.dumps({"text": "x" * 500}).encode()
    assert len(payload) > 100
    url, listener = _start_fake_sidecar(0.0, _http_reply(payload, declare_length=declare_length))
    try:
        with pytest.raises(ResponseTooLarge):
            post_inference(
                url,
                WAV,
                dict(FORM),
                cancellation_check=lambda: False,
                max_response_bytes=100,
            )
    finally:
        listener.close()
