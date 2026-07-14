"""Abortable HTTP transport for the whisper.cpp sidecar's /inference endpoint.

WHY THIS EXISTS AS ITS OWN MODULE
---------------------------------
whisper-server sends no bytes at all — not even response headers — until
inference completes. httpx's ``read`` timeout bounds a single socket read, so
that first read blocks for the entire inference and the read timeout therefore
behaves as a *work deadline*. Bounding it at ~2x real-time failed honest but
slow machines and silently truncated their transcripts.

We want no time limit. But an unbounded read is only safe if the request can be
aborted, and a blocked SYNC read cannot be: ``resp.close()`` / ``client.close()``
from another thread are no-ops, because httpcore's close() calls ``sock.close()``
and closing an fd does not wake a thread already blocked in ``recv()`` (the
request completes normally when the data finally arrives).

asyncio does not issue a blocking ``recv()``; it registers the fd with a
selector. So ``asyncio.Task.cancel()`` aborts a pending read immediately, using
only public API. This module therefore runs the request on a private event loop
inside the calling worker thread, polling ``cancellation_check`` while it waits.

RULE: an unbounded read is permitted only where an abort path exists.
Callers with a ``cancellation_check`` get ``read=None``; callers without one
(warmup, live, preview — all short audio) must pass a finite ``read_timeout_s``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# A wedged sidecar is indistinguishable from a busy one on the wire, so these
# bound only the phases where silence genuinely means "broken".
CONNECT_TIMEOUT_S = 10.0
WRITE_TIMEOUT_S = 120.0
POOL_TIMEOUT_S = 10.0

# How often the in-flight request is checked against cancellation_check.
CANCEL_POLL_INTERVAL_S = 0.25

# Hard ceiling on a single /inference response body, enforced WHILE reading so a
# hostile or misconfigured sidecar cannot exhaust memory before any post-parse
# cap could reject it (GH #193).
MAX_RESPONSE_BYTES = 256 * 1024 * 1024  # 256 MiB


class InferenceAborted(RuntimeError):
    """The caller's cancellation_check went True while the request was in flight.

    Distinct from a sidecar crash: the caller asked for this, so the caller is
    responsible for deciding whether completed work should still be persisted.
    """


class ResponseTooLarge(RuntimeError):
    """The sidecar's response body exceeded the ceiling; the read was aborted."""


def post_inference(
    url: str,
    wav_bytes: bytes,
    data: dict[str, Any],
    *,
    cancellation_check: Callable[[], bool] | None,
    read_timeout_s: float | None = None,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> bytes:
    """POST one audio chunk to /inference and return the raw response body.

    Blocking; call from a worker thread (the backend already runs inside one).

    ``read_timeout_s`` is ignored when ``cancellation_check`` is supplied — such
    a caller gets an unbounded read, because it has a way out. A caller with no
    ``cancellation_check`` MUST supply a finite ``read_timeout_s``; without one
    a wedged sidecar would hang that thread forever with no recovery.

    Raises:
        InferenceAborted: cancellation_check went True mid-flight.
        ResponseTooLarge: response body exceeded ``max_response_bytes``.
        httpx.*: connect/read/protocol failures, unchanged, for the caller to map.
    """
    cancellable = cancellation_check is not None
    if not cancellable and read_timeout_s is None:
        raise ValueError(
            "post_inference() requires a finite read_timeout_s when no "
            "cancellation_check is given — an unbounded read with no abort path "
            "would hang forever on a wedged sidecar"
        )

    timeout = httpx.Timeout(
        None if cancellable else read_timeout_s,
        connect=CONNECT_TIMEOUT_S,
        write=WRITE_TIMEOUT_S,
        pool=POOL_TIMEOUT_S,
    )

    async def _run() -> bytes:
        # The AsyncClient must be created inside this loop; asyncio.run() makes a
        # fresh one per call. Per-chunk client construction is negligible next to
        # inference, and it sidesteps httpx keep-alive connection reuse.
        async with httpx.AsyncClient(timeout=timeout) as client:

            async def _request() -> bytes:
                async with client.stream(
                    "POST",
                    url,
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                    data=data,
                ) as resp:
                    resp.raise_for_status()
                    declared = resp.headers.get("Content-Length")
                    # isascii() first: str.isdigit() is True for non-ASCII digit
                    # codepoints (e.g. "²") that int() then rejects, and a hostile
                    # sidecar can smuggle byte 0xB2 -> "²" into the header.
                    if (
                        declared
                        and declared.isascii()
                        and declared.isdigit()
                        and int(declared) > max_response_bytes
                    ):
                        raise ResponseTooLarge(
                            f"sidecar declared a {int(declared)}-byte /inference "
                            f"response (max {max_response_bytes}); refusing to read it"
                        )
                    body = bytearray()
                    async for piece in resp.aiter_bytes():
                        body += piece
                        if len(body) > max_response_bytes:
                            raise ResponseTooLarge(
                                f"sidecar returned a /inference response exceeding "
                                f"{max_response_bytes} bytes; aborting read to bound memory"
                            )
                    return bytes(body)

            task = asyncio.create_task(_request())
            while True:
                done, _ = await asyncio.wait({task}, timeout=CANCEL_POLL_INTERVAL_S)
                if done:
                    return task.result()
                if cancellation_check is not None and cancellation_check():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    raise InferenceAborted("cancelled while awaiting the sidecar")

    return asyncio.run(_run())
