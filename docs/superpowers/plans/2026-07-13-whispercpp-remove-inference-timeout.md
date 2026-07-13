# Remove the whisper.cpp Inference Time Limit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the ~2x-real-time cap on whisper.cpp inference so low-end machines can take as long as they need, without letting a wedged sidecar hang the server forever.

**Architecture:** An unbounded read is permitted only where an abort path exists. First we restore the abort path (the Cancel button is currently not wired to the main longform path at all), then we replace the sync `httpx.Client` `/inference` call with an abortable `httpx.AsyncClient` request whose read timeout is `None` and which is cancelled via `asyncio.Task.cancel()`. Chunking is unchanged — it bounds memory, and was never the time limit.

**Tech Stack:** Python 3.13, httpx 0.28.1 (sync `Client` for `/load`, async `AsyncClient` for `/inference`), pytest, FastAPI, React/TypeScript (Vitest).

**Spec:** `docs/superpowers/specs/2026-07-13-whispercpp-remove-inference-timeout-design.md`

**Branch:** `fix/whispercpp-remove-inference-timeout` (already created; spec already committed)

---

## Background the engineer needs

**Why the timeout exists.** `_transcribe_chunk` POSTs one audio chunk to the whisper.cpp sidecar and sets an httpx read timeout of `max(300, ceil(chunk_seconds * 2.0))`. httpx's `read` timeout bounds a *single socket read*, not the whole request — but whisper-server sends **zero bytes** until inference finishes, so the first read blocks for the entire inference. The read timeout therefore behaves as a work deadline of ~2x real-time.

**Why it cannot just be deleted.** Two verified facts:

1. `resp.close()` / `client.close()` from another thread do **not** abort a blocked sync read on Linux. `httpcore/_backends/sync.py:141` calls `self._sock.close()`, and closing an fd does not wake a thread already blocked in `recv()`. Measured: the request hung the full 30s and then *completed normally*.
2. `httpx.AsyncClient` + `asyncio.Task.cancel()` **does** abort promptly (measured: 2.04s against a server that stalls 30s before sending headers), because asyncio uses a selector rather than a blocking `recv()`. This is the primitive we build on. Public API only.

**Why Task 1 must land first.** The read timeout is currently the *only* thing that terminates a stuck job, because `websocket.py:459` binds `cancellation_check` to `_client_disconnected` (set only on a real socket drop) rather than `job_tracker.is_cancelled` (what `POST /cancel` flips). Removing the timeout before fixing this would turn "slow machines get truncated" into "slow machines can wedge the server".

**Testing commands.** Backend tests run from `server/backend/` using the **build venv**:
```bash
cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short
```
Frontend tests need Node 22: `cd dashboard && nvm use && npm test`.

---

## File Structure

**Create:**
- `server/backend/core/stt/backends/whispercpp_transport.py` — the abortable HTTP POST to `/inference`. Owns timeouts, the response-size ceiling, and the cancel-abort loop. Extracted because `whispercpp_backend.py` is already 957 lines (the style rules cap files at 800), and because a standalone transport can be tested against a **real stalling socket server** instead of a mock.
- `server/backend/tests/test_whispercpp_transport.py` — tests for the above, using a real localhost server.

**Modify:**
- `server/backend/api/routes/websocket.py:459` — bind cancel to the job tracker.
- `server/backend/api/routes/notebook.py:1031` — pass `cancellation_check`.
- `server/backend/api/routes/transcription.py:1103` — pass `cancellation_check`.
- `server/backend/api/routes/transcription.py:1466` — let `/retry` accept a partial job.
- `server/backend/core/stt/backends/whispercpp_backend.py` — use the transport; delete the timeout knobs; make cancel preserve completed chunks.
- `server/config.yaml:159-180` — delete the two timeout knobs.
- `server/backend/config.py:250-254` — delete their env mappings.
- `server/backend/tests/test_whispercpp_backend.py` — async mock seam; delete knob tests.
- `dashboard/src/hooks/useTranscription.ts:22` — add `partial` / `partialReason` to `TranscriptionResult`.
- `dashboard/components/views/SessionView.tsx` — partial banner with Retry.

---

## Task 1: Wire the Cancel button to the backend

**Files:**
- Modify: `server/backend/api/routes/websocket.py:459`
- Modify: `server/backend/api/routes/notebook.py:1031`
- Modify: `server/backend/api/routes/transcription.py:1103`
- Test: `server/backend/tests/test_cancel_wiring.py` (create)

This is an independent, user-facing bug fix: today, pressing Cancel on a whisper.cpp longform job does nothing. The job transcribes to completion, persists, auto-adds to the notebook, fires the webhook, and holds the single job slot so no new recording can start.

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_cancel_wiring.py`:

```python
"""The Cancel button (POST /cancel -> job_tracker) must reach every transcribe path.

Regression guard for the bug where websocket.py bound cancellation_check to
_client_disconnected, so POST /cancel never reached the backend on the main
longform path.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTES = Path(__file__).resolve().parents[1] / "api" / "routes"


def _transcribe_calls(path: Path) -> list[ast.Call]:
    """Every engine.transcribe_file(...) call in a route module."""
    tree = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "transcribe_file"
    ]


def _cancellation_source(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "cancellation_check":
            return ast.unparse(kw.value)
    return None


@pytest.mark.parametrize("module", ["websocket.py", "notebook.py", "transcription.py"])
def test_every_transcribe_call_passes_cancellation_check(module: str) -> None:
    calls = _transcribe_calls(ROUTES / module)
    assert calls, f"expected at least one transcribe_file call in {module}"
    for call in calls:
        src = _cancellation_source(call)
        assert src is not None, (
            f"{module}: transcribe_file() called without cancellation_check — "
            "a job started here can never be cancelled"
        )


@pytest.mark.parametrize("module", ["websocket.py", "notebook.py", "transcription.py"])
def test_cancellation_check_consults_the_job_tracker(module: str) -> None:
    """POST /cancel flips job_tracker._cancelled. Every path must read it."""
    for call in _transcribe_calls(ROUTES / module):
        src = _cancellation_source(call) or ""
        assert "job_tracker.is_cancelled" in src, (
            f"{module}: cancellation_check={src!r} does not consult "
            "job_tracker.is_cancelled, so POST /cancel cannot stop this job"
        )
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_cancel_wiring.py -v --tb=short
```
Expected: `test_every_transcribe_call_passes_cancellation_check[notebook.py]` and `[transcription.py]` FAIL (no `cancellation_check` kwarg), and `test_cancellation_check_consults_the_job_tracker[websocket.py]` FAILS (it binds `_client_disconnected`).

- [ ] **Step 3: Fix websocket.py**

`server/backend/api/routes/websocket.py:459`. `model_manager` is already in scope (bound at line 429). Replace:

```python
                    cancellation_check=lambda: self._client_disconnected,
```
with:
```python
                    # Two independent stop signals, both of which must reach the
                    # backend: the client vanished, or the user pressed Cancel
                    # (POST /cancel -> job_tracker). Binding only the former left
                    # Cancel a no-op on this, the main longform path.
                    cancellation_check=lambda: (
                        self._client_disconnected or model_manager.job_tracker.is_cancelled()
                    ),
```

Flag hygiene is already safe: `try_start_job` / `end_job` reset `_cancelled` (`model_manager.py:90, 113`) and `_release_job()` runs in `stop_recording`'s `finally` (`websocket.py:786-788`), so no stale flag leaks into the next job.

- [ ] **Step 4: Fix notebook.py**

`server/backend/api/routes/notebook.py:1031`. `model_manager` is in scope (used at line 1025). Add the kwarg to the `engine.transcribe_file(...)` call:

```python
                result = engine.transcribe_file(
                    str(tmp_path),
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    word_timestamps=need_word_timestamps,
                    progress_callback=on_progress,
                    cancellation_check=model_manager.job_tracker.is_cancelled,
                )
```

Note `notebook.py:1345` already calls `job_tracker.cancel_job()` — until now that flag had no reader.

- [ ] **Step 5: Fix transcription.py (_run_file_import)**

`server/backend/api/routes/transcription.py:1103`. `model_manager` is in scope (used at line 1098). Same addition:

```python
                result = engine.transcribe_file(
                    str(tmp_path),
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    word_timestamps=need_word_timestamps,
                    progress_callback=on_progress,
                    cancellation_check=model_manager.job_tracker.is_cancelled,
                )
```

- [ ] **Step 6: Run the tests and watch them pass**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_cancel_wiring.py -v --tb=short
```
Expected: 6 passed.

- [ ] **Step 7: Run the affected route suites for regressions**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/ -k "websocket or notebook or transcription or cancel" -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/api/routes/notebook.py \
        server/backend/api/routes/transcription.py server/backend/tests/test_cancel_wiring.py
git commit -m "fix(server): make the Cancel button actually stop a running transcription

* fix(websocket): bind cancellation_check to the job tracker, not just client disconnect
  * websocket.py:459 polled _client_disconnected, which is only set on a real socket drop
  * POST /cancel flips job_tracker._cancelled, which the longform path never read, so Cancel was a no-op on the main dashboard path

* fix(notebook): pass cancellation_check to transcribe_file (notebook.py:1345 already called cancel_job(), a flag with no reader)

* fix(transcription): pass cancellation_check to transcribe_file in _run_file_import

* test(server): AST guard asserting every transcribe_file call consults job_tracker.is_cancelled"
```

---

## Task 2: Build the abortable transport

**Files:**
- Create: `server/backend/core/stt/backends/whispercpp_transport.py`
- Test: `server/backend/tests/test_whispercpp_transport.py`

The read timeout is `None` (no time limit) whenever a `cancellation_check` is supplied, and finite otherwise. Tested against a **real** localhost server that stalls before sending headers — the exact shape of a wedged whisper-server — because a MagicMock cannot prove an abort actually interrupts a blocked read.

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_whispercpp_transport.py`:

```python
"""Transport tests against a REAL stalling socket server.

A wedged whisper-server accepts the POST, drains the body, and then sends
nothing at all — not even response headers — while the GPU chews. Mocks cannot
prove an abort interrupts that, so these tests use a real socket.
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


class StallingSidecar:
    """Accepts a POST, drains it, waits `stall` seconds, then optionally replies."""

    def __init__(self, stall: float, reply: dict | None = None) -> None:
        self._stall = stall
        self._reply = reply
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/inference"

    def _accept_loop(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(0.5)
        try:
            while conn.recv(65536):
                pass
        except OSError:
            pass
        time.sleep(self._stall)
        if self._reply is not None:
            body = json.dumps(self._reply).encode()
            try:
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: %d\r\n\r\n" % len(body) + body
                )
            except OSError:
                pass
        try:
            conn.close()
        except OSError:
            pass

    def close(self) -> None:
        self._sock.close()


@pytest.fixture()
def wav() -> bytes:
    return b"RIFF" + b"\x00" * 2048


def test_slow_but_healthy_completes_with_no_time_limit(wav: bytes) -> None:
    """The whole point: work that exceeds the old 2x budget must still finish."""
    sidecar = StallingSidecar(stall=3.0, reply={"segments": [{"text": "ok"}]})
    try:
        started = time.monotonic()
        body = post_inference(
            sidecar.url, wav, {"response_format": "verbose_json"},
            cancellation_check=lambda: False,
        )
        elapsed = time.monotonic() - started
    finally:
        sidecar.close()
    assert json.loads(body) == {"segments": [{"text": "ok"}]}
    assert elapsed >= 3.0, "should have waited for the slow sidecar, not timed out"


def test_cancel_aborts_a_wedged_request_promptly(wav: bytes) -> None:
    """A wedged sidecar must be escapable — this is what makes read=None safe."""
    sidecar = StallingSidecar(stall=30.0)
    cancelled = {"value": False}
    threading.Timer(1.0, lambda: cancelled.update(value=True)).start()
    try:
        started = time.monotonic()
        with pytest.raises(InferenceAborted):
            post_inference(
                sidecar.url, wav, {}, cancellation_check=lambda: cancelled["value"]
            )
        elapsed = time.monotonic() - started
    finally:
        sidecar.close()
    assert elapsed < 5.0, f"abort took {elapsed:.1f}s; it must not wait out the sidecar"


def test_connect_stays_bounded_against_a_dead_host(wav: bytes) -> None:
    """read=None must not disable the connect timeout (httpx expands a bare
    scalar to all four fields, which is how the old code hung 20-60min here)."""
    started = time.monotonic()
    with pytest.raises(httpx.ConnectError):
        post_inference(
            "http://127.0.0.1:1/inference", wav, {}, cancellation_check=lambda: False
        )
    assert time.monotonic() - started < 15.0


def test_uncancellable_caller_gets_a_finite_read(wav: bytes) -> None:
    """warmup/live/preview pass no cancellation_check, so they must NOT get an
    unbounded read — a wedge there would be unrecoverable."""
    sidecar = StallingSidecar(stall=30.0)
    try:
        started = time.monotonic()
        with pytest.raises(httpx.ReadTimeout):
            post_inference(sidecar.url, wav, {}, cancellation_check=None, read_timeout_s=2.0)
        assert time.monotonic() - started < 10.0
    finally:
        sidecar.close()


def test_oversized_response_is_rejected_during_the_read(wav: bytes) -> None:
    big = {"segments": [{"text": "x" * 5000}]}
    sidecar = StallingSidecar(stall=0.0, reply=big)
    try:
        with pytest.raises(ResponseTooLarge):
            post_inference(
                sidecar.url, wav, {}, cancellation_check=lambda: False, max_response_bytes=100
            )
    finally:
        sidecar.close()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_transport.py -v --tb=short
```
Expected: collection error — `ModuleNotFoundError: server.core.stt.backends.whispercpp_transport`.

- [ ] **Step 3: Write the transport**

Create `server/backend/core/stt/backends/whispercpp_transport.py`:

```python
"""Abortable HTTP transport for the whisper.cpp sidecar's /inference endpoint.

WHY THIS EXISTS AS ITS OWN MODULE
---------------------------------
whisper-server sends no bytes at all — not even response headers — until
inference completes. httpx's ``read`` timeout bounds a single socket read, so
that first read blocks for the entire inference and the read timeout therefore
behaves as a *work deadline*. Bounding it at ~2x real-time failed honest but
slow machines and silently truncated their transcripts (see the design spec).

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
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_transport.py -v --tb=short
```
Expected: 5 passed. `test_cancel_aborts_a_wedged_request_promptly` is the load-bearing one — it must abort in ~1s against a sidecar that would stall for 30.

- [ ] **Step 5: Do NOT commit yet**

The transport is dead code until Task 3 wires it in, and this PR ships as three commits (one per wave). Leave these two files staged; Task 3's commit covers them.

```bash
git add server/backend/core/stt/backends/whispercpp_transport.py \
        server/backend/tests/test_whispercpp_transport.py
```

---

## Task 3: Use the transport, delete the knobs, preserve work on cancel

**Files:**
- Modify: `server/backend/core/stt/backends/whispercpp_backend.py`
- Modify: `server/backend/tests/test_whispercpp_backend.py`

Three things at once because they are one behavioural change: the chunk POST moves to the transport, the timeout knobs disappear, and cancel stops discarding completed chunks.

**On that last point:** `whispercpp_backend.py:683` currently raises `TranscriptionCancelledError` on cancel, discarding every completed chunk. That is survivable today only because the *timeout* produces a partial instead. Once the escape hatch from a wedge **is** cancel, a user cancelling at chunk 29/30 would throw away 29 chunks — a durability regression. `engine.py:969-975` already refuses to discard salvaged work on a late cancel ("discarding salvaged work to honour a late cancel would violate the avoid-data-loss invariant"); we make the backend consistent with it.

- [ ] **Step 1: Write the failing tests**

Append to `server/backend/tests/test_whispercpp_backend.py`:

```python
class TestUnboundedInference:
    """The 2x-real-time cap is gone; cancellation is the only interrupt."""

    def test_no_timeout_knobs_remain(self):
        """The knobs are deleted, not merely defaulted to something generous."""
        import server.core.stt.backends.whispercpp_backend as mod

        for gone in (
            "_INFERENCE_TIMEOUT",
            "_TIMEOUT_SECONDS_PER_AUDIO_SECOND",
            "_inference_timeout_for",
            "_resolve_timeout_config",
        ):
            assert not hasattr(mod, gone), f"{gone} should have been deleted"

    def test_chunk_post_is_unbounded_when_cancellable(
        self, loaded_backend: WhisperCppBackend
    ):
        """A cancellable caller must get read_timeout_s=None (no work deadline)."""
        seen: dict = {}

        def _fake_post(url, wav, data, *, cancellation_check, **kwargs):
            seen["cancellation_check"] = cancellation_check
            seen["read_timeout_s"] = kwargs.get("read_timeout_s")
            return json.dumps({"segments": [{"text": "hi", "start": 0, "end": 1}]}).encode()

        with patch(
            "server.core.stt.backends.whispercpp_backend.post_inference", _fake_post
        ):
            loaded_backend.transcribe(
                np.zeros(16000, dtype=np.float32), cancellation_check=lambda: False
            )
        assert seen["cancellation_check"] is not None
        assert seen["read_timeout_s"] is None

    def test_chunk_post_is_bounded_when_not_cancellable(
        self, loaded_backend: WhisperCppBackend
    ):
        """warmup/live/preview pass no cancellation_check -> must get a finite read."""
        seen: dict = {}

        def _fake_post(url, wav, data, *, cancellation_check, **kwargs):
            seen["cancellation_check"] = cancellation_check
            seen["read_timeout_s"] = kwargs.get("read_timeout_s")
            return json.dumps({"segments": []}).encode()

        with patch(
            "server.core.stt.backends.whispercpp_backend.post_inference", _fake_post
        ):
            loaded_backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert seen["cancellation_check"] is None
        assert seen["read_timeout_s"] == _UNCANCELLABLE_READ_TIMEOUT_S


class TestCancelPreservesCompletedChunks:
    def test_cancel_midway_returns_a_partial_not_an_empty_discard(
        self, loaded_backend: WhisperCppBackend
    ):
        """Cancelling at chunk 3/4 must persist chunks 1-2, not throw them away."""
        loaded_backend._max_chunk_duration_s = 1  # 1s chunks
        audio = np.zeros(16000 * 4, dtype=np.float32)  # 4 chunks
        calls = {"n": 0}

        def _fake_post(url, wav, data, *, cancellation_check, **kwargs):
            calls["n"] += 1
            if cancellation_check and cancellation_check():
                raise InferenceAborted("cancelled while awaiting the sidecar")
            return json.dumps(
                {"segments": [{"text": f"chunk{calls['n']}", "start": 0, "end": 1}]}
            ).encode()

        # Cancel becomes true once two chunks are done.
        with (
            patch("server.core.stt.backends.whispercpp_backend.post_inference", _fake_post),
            pytest.raises(PartialTranscriptionError) as exc,
        ):
            loaded_backend.transcribe(audio, cancellation_check=lambda: calls["n"] >= 2)

        assert len(exc.value.segments) == 2
        assert exc.value.segments[0].text == "chunk1"
        assert exc.value.completed_seconds == pytest.approx(2.0, abs=0.01)

    def test_cancel_before_any_chunk_completes_still_cancels(
        self, loaded_backend: WhisperCppBackend
    ):
        """Nothing to salvage -> a real cancellation, not a bogus empty partial."""
        from server.core.model_manager import TranscriptionCancelledError

        loaded_backend._max_chunk_duration_s = 1
        audio = np.zeros(16000 * 4, dtype=np.float32)

        with (
            patch(
                "server.core.stt.backends.whispercpp_backend.post_inference",
                lambda *a, **k: (_ for _ in ()).throw(InferenceAborted("cancelled")),
            ),
            pytest.raises(TranscriptionCancelledError),
        ):
            loaded_backend.transcribe(audio, cancellation_check=lambda: True)
```

Add to the module's imports at the top of the test file:
```python
from server.core.stt.backends.whispercpp_backend import _UNCANCELLABLE_READ_TIMEOUT_S
from server.core.stt.backends.whispercpp_transport import InferenceAborted
```
and **delete** `_INFERENCE_TIMEOUT`, `_TIMEOUT_SECONDS_PER_AUDIO_SECOND`, `_inference_timeout_for`, `_resolve_timeout_config` from that same import block.

- [ ] **Step 2: Delete the obsolete knob tests**

In `server/backend/tests/test_whispercpp_backend.py`, delete these four tests (they assert on the knobs we are removing):
- `test_timeout_config_env_wins` (~line 1652)
- `test_timeout_config_floors_enforced` (~line 1661)
- `test_timeout_config_defaults_when_no_source` (~line 1671)

and in `test_load_resolves_config_into_instance_vars` (~line 1682) remove the two timeout env vars and the two timeout assertions, keeping only the chunk-duration ones:

```python
    def test_load_resolves_config_into_instance_vars(
        self, backend: WhisperCppBackend, mock_httpx: MagicMock
    ):
        """load() must populate the chunk instance var from env/config."""
        mock_httpx.post.return_value = MagicMock(status_code=200)
        with patch.dict(
            "os.environ",
            {
                "WHISPERCPP_SERVER_URL": "http://test:8080",
                "WHISPERCPP_CHUNK_DURATION_S": "300",
            },
        ):
            backend.load("ggml-large-v3.bin", "cpu")
        assert backend._max_chunk_duration_s == 300
```

Also delete any `_inference_timeout_for` tests (grep for them).

- [ ] **Step 3: Run and watch the new tests fail**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py -k "Unbounded or CancelPreserves" -v --tb=short
```
Expected: FAIL — `post_inference` is not imported in `whispercpp_backend`, `_UNCANCELLABLE_READ_TIMEOUT_S` does not exist.

- [ ] **Step 4: Rewrite `_transcribe_chunk` in whispercpp_backend.py**

Add to the imports:
```python
from server.core.stt.backends.whispercpp_transport import (
    InferenceAborted,
    ResponseTooLarge,
    post_inference,
)
```

Replace the timeout constants block (lines ~39-53) with:
```python
_DEFAULT_SERVER_URL = "http://whisper-server:8080"
_MAX_CHUNK_DURATION_S = 10 * 60  # 10 min per /inference POST (mirrors the NeMo backends)
# Hard ceiling on the configurable chunk duration. Even a deliberately huge
# WHISPERCPP_CHUNK_DURATION_S must not route a whole multi-hour file through a
# single un-chunked /inference request — that path re-exposes the GH #172
# truncation and defeats per-chunk progress/cancellation.
_MAX_CHUNK_DURATION_CEILING_S = 30 * 60
_LOAD_TIMEOUT = 60

# Inference has NO time limit when the caller can cancel (the normal longform
# case): a slow machine is allowed to take as long as it needs. Callers with no
# cancellation_check — warmup, live mode, preview — have no way out of a wedged
# sidecar, so they keep a finite read. Their audio is seconds long, so this is
# already orders of magnitude above any honest inference time.
_UNCANCELLABLE_READ_TIMEOUT_S = 300.0
```

Delete `_INFERENCE_TIMEOUT`, `_TIMEOUT_SECONDS_PER_AUDIO_SECOND`, `_MAX_RESPONSE_BYTES`, `_SIDECAR_INFERENCE_TIMEOUT_MSG`, `_inference_timeout_for` (lines ~124-140) and `_resolve_timeout_config` (lines ~204-231).

Fix the dead client default at line 514 (it never applied, because httpx replaces the client default wholesale when a per-request `timeout=` is passed — and `/load` passes one):
```python
        if self._client is None:
            # Only /load uses this sync client now; /inference goes through the
            # abortable async transport. /load passes its own explicit timeout.
            self._client = httpx.Client(timeout=_LOAD_TIMEOUT)
```

In `load()` (line ~527), drop the timeout resolution and the log fields:
```python
        self._max_chunk_duration_s = _resolve_chunk_duration_config()
        logger.info(
            "WhisperCppBackend: loading model %s via %s (chunk=%ds, inference=unbounded)",
            model_name,
            self._server_url,
            self._max_chunk_duration_s,
        )
```
and delete `self._inference_timeout` / `self._timeout_seconds_per_audio_second` from `__init__` (lines ~499-500).

Replace the whole body of `_transcribe_chunk` (lines ~743-840) with:

```python
    def _transcribe_chunk(
        self,
        chunk: np.ndarray,
        sample_rate: int,
        data: dict[str, Any],
        cancellation_check: Callable[[], bool] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """POST a single (already-bounded) audio chunk to /inference and parse it.

        There is no time limit on inference when ``cancellation_check`` is given:
        a slow machine takes as long as it takes, and the only interrupt is the
        user. See whispercpp_transport for why an unbounded read is safe there
        and why it is refused everywhere else.
        """
        wav_bytes = _audio_to_wav_bytes(chunk, sample_rate)
        try:
            body = post_inference(
                f"{self._server_url}/inference",
                wav_bytes,
                data,
                cancellation_check=cancellation_check,
                read_timeout_s=(
                    None if cancellation_check is not None else _UNCANCELLABLE_READ_TIMEOUT_S
                ),
            )
        except InferenceAborted:
            raise
        except ResponseTooLarge as exc:
            raise WhisperCppResponseError(
                f"whisper.cpp sidecar at {self._server_url}: {exc}"
            ) from exc
        except (httpx.NetworkError, OSError) as exc:
            raise RuntimeError(_SIDECAR_UNREACHABLE_MSG.format(url=self._server_url)) from exc
        except httpx.TimeoutException as exc:
            # Only reachable on the uncancellable paths (warmup/live/preview).
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} did not respond within "
                f"{_UNCANCELLABLE_READ_TIMEOUT_S:.0f}s. The sidecar may be wedged; "
                "check the container logs."
            ) from exc
        except HttpxHTTPStatusError as exc:
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned HTTP "
                f"{exc.response.status_code} for /inference"
            ) from exc

        audio_duration_s = len(chunk) / sample_rate if sample_rate > 0 else 0.0
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            body_preview = _sanitize_for_error_preview(body)
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned a non-JSON "
                f"response from /inference: {body_preview}"
            ) from exc
        return self._parse_response(result, audio_duration_s)
```

`_parse_response` (defined at line 854) is unchanged, and the `_segment_cap_for` / `_word_cap_for` proportional caps come with it. The rewritten `_transcribe_chunk` still ends by calling it exactly as the current code does at line 836.

- [ ] **Step 5: Thread `cancellation_check` through `transcribe()` and preserve work on cancel**

In `transcribe()`, the short-audio fast path (line ~672) becomes:
```python
        if chunk_samples <= 0 or total_samples <= chunk_samples:
            try:
                return self._transcribe_chunk(audio, audio_sample_rate, data, cancellation_check)
            except InferenceAborted as exc:
                from server.core.model_manager import TranscriptionCancelledError

                raise TranscriptionCancelledError("Transcription cancelled by user") from exc
```

In the chunk loop, replace the between-chunk cancel block (lines ~683-691) and the call at line ~696:
```python
        for i in range(num_chunks):
            if cancellation_check is not None and cancellation_check():
                logger.info(
                    "WhisperCppBackend: transcription cancelled at chunk %d/%d", i + 1, num_chunks
                )
                raise self._cancelled_or_partial(all_segments, first_info, offset)

            start = i * chunk_samples
            chunk = audio[start : min(start + chunk_samples, total_samples)]
            try:
                segments, info = self._transcribe_chunk(
                    chunk, audio_sample_rate, chunk_data, cancellation_check
                )
            except InferenceAborted:
                # The user cancelled while this chunk was in flight. Completed
                # chunks are real transcription work — surface them rather than
                # discard them ("avoid data loss at all costs").
                logger.info(
                    "WhisperCppBackend: cancelled mid-chunk %d/%d", i + 1, num_chunks
                )
                raise self._cancelled_or_partial(all_segments, first_info, offset) from None
            except Exception as exc:
                if first_info is None:
                    raise
                logger.warning(
                    "WhisperCppBackend: chunk %d/%d failed (%s); returning %.0fs partial transcript",
                    i + 1,
                    num_chunks,
                    exc,
                    offset,
                )
                raise PartialTranscriptionError(
                    str(exc),
                    segments=all_segments,
                    info=first_info,
                    completed_seconds=offset,
                ) from exc
```

Add the helper next to `_transcribe_chunk`:
```python
    @staticmethod
    def _cancelled_or_partial(
        segments: list[BackendSegment],
        info: BackendTranscriptionInfo | None,
        completed_seconds: float,
    ) -> Exception:
        """The exception to raise when the user cancels mid-file.

        With completed chunks in hand, cancelling must NOT throw them away — a
        cancel five hours into a six-hour file would otherwise destroy five hours
        of real transcription. Mirrors engine.py's own refusal to discard salvaged
        work on a late cancel. With nothing done yet, it is a plain cancellation.
        """
        from server.core.model_manager import TranscriptionCancelledError

        if info is None or not segments:
            return TranscriptionCancelledError("Transcription cancelled by user")
        return PartialTranscriptionError(
            "Cancelled by user",
            segments=segments,
            info=info,
            completed_seconds=completed_seconds,
        )
```

- [ ] **Step 6: Run the whole whispercpp suite**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_whispercpp_backend.py tests/test_whispercpp_transport.py -v --tb=short
```
Expected: all pass. Some pre-existing `/inference` tests mock `httpx.Client.stream`; those now need to patch `whispercpp_backend.post_inference` instead. Update each by replacing the `_inf(mock_httpx).return_value = _inference_response({...})` setup with:
```python
        with patch(
            "server.core.stt.backends.whispercpp_backend.post_inference",
            return_value=json.dumps({...}).encode(),
        ):
```
The `/load` tests are untouched — `/load` still uses the sync client.

- [ ] **Step 7: Delete the config knobs**

`server/config.yaml` — delete lines 167-180 (the `inference_timeout_s` and `timeout_seconds_per_audio_second` blocks, comments included). Leave `chunk_duration_s`. Add above it:
```yaml
    # NOTE: inference has no time limit. A slow machine takes as long as it needs;
    # the only interrupt is the user pressing Cancel. (Previously capped at ~2x
    # real-time, which silently truncated transcripts on low-end hardware.)
```

`server/backend/config.py` — delete lines 250-254:
```python
        ("WHISPERCPP_INFERENCE_TIMEOUT_S", ("whisper_cpp", "inference_timeout_s")),
        (
            "WHISPERCPP_TIMEOUT_SECONDS_PER_AUDIO_SECOND",
            ("whisper_cpp", "timeout_seconds_per_audio_second"),
        ),
```

- [ ] **Step 8: Verify no references survive**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
grep -rn "WHISPERCPP_INFERENCE_TIMEOUT_S\|WHISPERCPP_TIMEOUT_SECONDS_PER_AUDIO_SECOND\|inference_timeout_s\|timeout_seconds_per_audio_second\|_inference_timeout_for" \
  --include="*.py" --include="*.yaml" --include="*.yml" --include="*.md" . | grep -v node_modules | grep -v "\.venv" | grep -v docs/superpowers
```
Expected: no output.

- [ ] **Step 9: Full backend suite**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/ -q
```
Expected: all pass (2 known pre-existing failures: db migration version, swr_linear resample).

- [ ] **Step 10: Lint**

```bash
cd server/backend && ../../build/.venv/bin/ruff check . && ../../build/.venv/bin/ruff format --check .
```

- [ ] **Step 11: Commit**

```bash
git add server/backend/core/stt/backends/whispercpp_transport.py \
        server/backend/tests/test_whispercpp_transport.py \
        server/backend/core/stt/backends/whispercpp_backend.py \
        server/backend/tests/test_whispercpp_backend.py \
        server/config.yaml server/backend/config.py
git commit -m "fix(stt): remove the ~2x-real-time cap on whisper.cpp inference

* fix(stt): inference now has no time limit — a slow machine takes as long as it needs
  * the read timeout was max(300, chunk_seconds * 2.0); whisper-server sends no bytes until inference completes, so that read timeout acted as a work deadline
  * exceeding it raised PartialTranscriptionError, which save_result() wrote as status='completed' — low-end hardware got a silently truncated transcript it could not retry
  * cancellation is now the only interrupt

* feat(stt): add whispercpp_transport.post_inference() — an abortable /inference request
  * a blocked SYNC read cannot be interrupted: httpcore's close() calls sock.close(), which does not wake a thread already in recv(), so the request just completes later
  * asyncio uses a selector instead, so task.cancel() aborts a pending read immediately, using public API only
  * read=None when the caller can cancel; a finite read_timeout_s is REQUIRED otherwise (warmup/live/preview have no way out of a wedge)
  * connect/write/pool stay bounded — httpx expands a bare scalar timeout to all four fields, which is why the old code could hang 20-60min in connect

* fix(stt): cancelling mid-file no longer discards completed chunks
  * cancel with >=1 chunk done now raises PartialTranscriptionError so the work is persisted, matching engine.py's existing refusal to discard salvaged work on a late cancel

* chore(stt): delete the inference_timeout_s and timeout_seconds_per_audio_second knobs
* chore(stt): drop the dead client-level httpx timeout default (a per-request timeout replaces it wholesale)

* test(stt): exercise the transport against a real stalling socket server, not a mock"
```

---

## Task 4: Stop laundering partial results into "completed"

**Files:**
- Modify: `server/backend/api/routes/transcription.py` (`/retry`, ~line 1466)
- Test: `server/backend/tests/test_partial_result_retry.py` (create)

`engine.py:99-100` already serializes `partial` / `partial_reason` into `result_json`, so `GET /result` already returns them nested under `result` — the client simply never reads them. The only server-side gap is `/retry`, which refuses anything that is not `'failed'`.

Keep `status='completed'`. **No migration, no new status value:** a new status would have to be retrofitted into `get_recent_undelivered` and `get_jobs_for_cleanup`, and the failure mode of forgetting either is silent data loss. Staying inside `'completed'` means partial jobs keep being re-delivered on reconnect and keep having their audio GC'd, for free.

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_partial_result_retry.py`. Uses the direct-call route pattern from `CLAUDE.md`:

```python
"""A partial transcript must be retryable.

A partial is saved with status='completed' (so it is still delivered and its
audio still GC'd), with result_json.partial = true. /retry previously refused
it, leaving the user with a truncated transcript and no recourse.

Direct-call route pattern per CLAUDE.md; mirrors tests/test_transcription_durability_routes.py.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from server.api.routes import transcription


class _BG:
    """Stand-in for FastAPI's BackgroundTasks."""

    def __init__(self) -> None:
        self.tasks: list = []

    def add_task(self, fn, *args, **kwargs) -> None:
        self.tasks.append((fn, args, kwargs))


def _request() -> SimpleNamespace:
    """A Request whose app.state.model_manager reports an idle job tracker.

    /retry pre-checks model_manager.job_tracker.is_busy() before resetting the
    job (transcription.py:1475-1481), so an idle tracker is required to reach
    the status gate under test.
    """
    job_tracker = SimpleNamespace(is_busy=lambda: (False, None))
    model_manager = SimpleNamespace(job_tracker=job_tracker)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_manager=model_manager)))


def _job(status: str, *, partial: bool, audio_path: str) -> dict:
    return {
        "id": "job-1",
        "status": status,
        "client_name": "test-client",
        "audio_path": audio_path,
        "result_json": json.dumps({"text": "half a transcript", "partial": partial}),
    }


@pytest.fixture()
def repo(monkeypatch):
    mod = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(transcription, "get_client_name", lambda _: "test-client")
    return mod


@pytest.fixture()
def audio(tmp_path):
    """/retry 410s unless the saved audio still exists on disk."""
    path = tmp_path / "saved.wav"
    path.write_bytes(b"RIFF")
    return str(path)


def test_retry_accepts_a_partial_completed_job(monkeypatch, repo, audio):
    reset: list[str] = []
    monkeypatch.setattr(repo, "get_job", lambda _id: _job("completed", partial=True, audio_path=audio))
    monkeypatch.setattr(repo, "reset_for_retry", lambda job_id: reset.append(job_id))

    bg = _BG()
    resp = asyncio.run(transcription.retry_transcription("job-1", _request(), bg))

    assert resp.status_code == 202
    assert reset == ["job-1"], "a partial retry must actually reset the job"
    assert bg.tasks, "a partial retry must schedule the re-transcription"


def test_retry_still_refuses_a_fully_complete_job(monkeypatch, repo, audio):
    monkeypatch.setattr(repo, "get_job", lambda _id: _job("completed", partial=False, audio_path=audio))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(transcription.retry_transcription("job-1", _request(), _BG()))
    assert exc.value.status_code == 409


def test_retry_still_accepts_a_failed_job(monkeypatch, repo, audio):
    """The pre-existing path must not regress."""
    monkeypatch.setattr(repo, "get_job", lambda _id: _job("failed", partial=False, audio_path=audio))
    monkeypatch.setattr(repo, "reset_for_retry", lambda _id: None)
    resp = asyncio.run(transcription.retry_transcription("job-1", _request(), _BG()))
    assert resp.status_code == 202
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_partial_result_retry.py -v --tb=short
```
Expected: `test_retry_accepts_a_partial_completed_job` FAILS with HTTP 409 "Only failed jobs can be retried".

- [ ] **Step 3: Let /retry accept a partial**

In `server/backend/api/routes/transcription.py`, replace the status gate (~line 1466):

```python
    if job["status"] == "processing":
        raise HTTPException(status_code=409, detail="Job is already processing")

    # A partial transcript is stored with status='completed' (so it is still
    # delivered, and its audio still GC'd) but with result_json.partial = true.
    # It is an incomplete transcription, so it MUST be retryable — otherwise the
    # user is stuck with a truncated transcript and no recourse.
    is_partial = False
    if job.get("result_json"):
        try:
            is_partial = bool(_json.loads(job["result_json"]).get("partial"))
        except _json.JSONDecodeError:
            is_partial = False

    if job["status"] != "failed" and not is_partial:
        raise HTTPException(
            status_code=409,
            detail=f"Only failed or partial jobs can be retried (current status: {job['status']})",
        )
```

- [ ] **Step 4: Run and watch it pass**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_partial_result_retry.py -v --tb=short
```
Expected: 3 passed.

- [ ] **Step 5: Add the retry call to the API client**

`dashboard/src/api/client.ts` — there is no retry method yet. Add one next to
`fetchTranscriptionResult` (line 312), using the existing private `post<T>()` helper (line 232),
which already handles `ensureConfigured`, auth headers, and `APIError`:

```typescript
  /** POST /api/transcribe/retry/{jobId} — re-transcribe from the job's saved audio. */
  async retryTranscription(jobId: string): Promise<{ job_id: string; status: string }> {
    return this.post(`/api/transcribe/retry/${jobId}`);
  }
```

- [ ] **Step 6: Surface partial in the dashboard type**

`dashboard/src/hooks/useTranscription.ts:22` — extend the interface:

```typescript
export interface TranscriptionResult {
  text: string;
  words: Word[];
  language?: string;
  duration?: number;
  /** True when the backend salvaged an incomplete transcript (sidecar failure
   * or user cancellation partway through). The text stops early. */
  partial?: boolean;
  /** Human-readable reason the transcript is incomplete. */
  partialReason?: string | null;
}
```

Then, everywhere the hook builds a `TranscriptionResult` from a server payload (the `result_ready` WebSocket handler and the `resp.status === 200` recovery poll around lines 245 and 380), carry the fields through:

```typescript
                  setResult({
                    text: r.text ?? '',
                    words: r.words ?? [],
                    language: r.language,
                    duration: r.duration,
                    partial: r.partial ?? false,
                    partialReason: r.partial_reason ?? null,
                  });
```

- [ ] **Step 7: Add the banner**

In `dashboard/components/views/SessionView.tsx`, where the transcript result is rendered, add a
handler and the banner above the transcript body. `jobId` is already tracked by `useTranscription`;
expose it from the hook's return value if it is not already exposed.

```tsx
const [retrying, setRetrying] = useState(false);

const handleRetryPartial = async () => {
  if (!jobId) return;
  setRetrying(true);
  try {
    await apiClient.retryTranscription(jobId);
  } catch (err) {
    setError(err instanceof Error ? err.message : 'Retry failed');
  } finally {
    setRetrying(false);
  }
};
```

```tsx
{result?.partial && (
  <div className="transcript-partial-banner" role="alert">
    <span className="transcript-partial-banner__text">
      This transcript is incomplete{result.partialReason ? ` (${result.partialReason})` : ''}.
      It may be missing the end of the recording.
    </span>
    <button
      type="button"
      className="transcript-partial-banner__retry"
      onClick={() => void handleRetryPartial()}
      disabled={retrying || !jobId}
    >
      {retrying ? 'Retrying…' : 'Retry'}
    </button>
  </div>
)}
```

Style `.transcript-partial-banner`, `.transcript-partial-banner__text`, and
`.transcript-partial-banner__retry` alongside the existing transcript styles. Use a warning
tone, not an error tone — the transcript is usable, just incomplete.

- [ ] **Step 8: Frontend tests + UI contract**

```bash
cd dashboard && nvm use && npm test
npm run ui:contract:extract && npm run ui:contract:build
node scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```
Remember to bump `meta.spec_version` in the contract YAML **before** `--update-baseline`, or validate fails `semver_bump_required`. Note the scanner gotchas: an apostrophe in a `//` comment silently swallows subsequent className tokens, and `#NNN` hex-shaped text in a comment is read as a CSS color — write "GH-125", not "GH #125".

- [ ] **Step 9: Commit**

```bash
git add server/backend/api/routes/transcription.py \
        server/backend/tests/test_partial_result_retry.py \
        dashboard/src/api/client.ts \
        dashboard/src/hooks/useTranscription.ts \
        dashboard/components/views/SessionView.tsx \
        dashboard/ui-contract/
git commit -m "fix(server,dashboard): surface partial transcripts and let them be retried

* fix(server): /retry now accepts a partial job
  * a partial is stored with status='completed' + result_json.partial, so /retry refused it — the user was left with a truncated transcript and no recourse
  * kept inside status='completed' deliberately: a new status value would have to be retrofitted into get_recent_undelivered and get_jobs_for_cleanup, and forgetting either is silent data loss

* feat(dashboard): show a banner with a Retry action when a transcript is incomplete
* feat(dashboard): carry partial/partial_reason through TranscriptionResult"
```

---

## Task 5: Full verification and PR

- [ ] **Step 1: Full backend suite**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/ -q
```
Expected: all pass except the 2 known pre-existing failures (db migration version, swr_linear resample). Run the FULL suite, not a `-k` subset — a past change passed its own subset while breaking 15 audio-durability tests.

- [ ] **Step 2: Full frontend suite**

```bash
cd dashboard && nvm use && npm test && npm run typecheck && npm run ui:contract:check
```

- [ ] **Step 3: Confirm the change scope**

```bash
npx gitnexus analyze   # index is stale
```
Then `gitnexus_detect_changes()` and confirm only the expected symbols/flows are affected.

- [ ] **Step 4: Open the PR**

Open the PR directly on GitHub (no local draft file, per CLAUDE.md):

```bash
git push -u origin fix/whispercpp-remove-inference-timeout
gh pr create --title "fix(stt): remove the ~2x-real-time cap on whisper.cpp inference" --body "$(cat <<'EOF'
## The bug

`WhisperCppBackend` capped each `/inference` request at a read timeout of
`max(300, ceil(chunk_seconds * 2.0))` — about 2x real-time. whisper-server sends no bytes at all
until inference completes, so httpx's read timeout (which bounds a single socket read) was acting
as a **work deadline**. A healthy machine that is merely slow was being failed.

Worse, it failed *silently*. Exceeding the budget raised `PartialTranscriptionError`, which
`engine.py` turns into a partial result, which `save_result()` writes as **`status='completed'`**.
The dashboard never read the `partial` flag, and `/retry` refused the job because it only accepted
`'failed'`. A user on low-end hardware recorded a 2-hour lecture, got 40 minutes back, saw it
marked complete, and had no way to retry.

## Why it could not just be deleted

Removing the timeout naively would have made things worse, for two reasons:

1. **Cancel was never wired to the main path.** `websocket.py:459` bound `cancellation_check` to
   `_client_disconnected` (set only on a real socket drop), not `job_tracker.is_cancelled` (what
   `POST /cancel` flips). The read timeout was therefore the *only* thing that terminated a stuck
   job. Fixed in commit 1 — this is a user-facing bug fix in its own right.
2. **A blocked sync read cannot be aborted.** `resp.close()` / `client.close()` from another thread
   are no-ops: httpcore calls `sock.close()`, and closing an fd does not wake a thread already
   blocked in `recv()`. Measured against a stalling server, the request hung the full 30s and then
   *completed normally*. `httpx.AsyncClient` + `asyncio.Task.cancel()` aborts in ~2s instead,
   because asyncio uses a selector rather than a blocking read. Public API only.

## The rule

**An unbounded read is permitted only where an abort path exists.** Longform paths (which have a
`cancellation_check`) get `read=None` — no time limit, ever. warmup / live / preview have no way
out of a wedge, so they keep a finite read; their audio is seconds long.

Chunking is unchanged — it bounds memory per forward pass and was never the time limit.

## Also fixed

- Cancelling mid-file no longer discards completed chunks (it would have thrown away 29 of 30).
- A bare scalar `timeout=` expands to all four httpx fields, so a blackholed sidecar used to hang
  in the **connect** phase for 20-60 minutes. Connect is now bounded at 10s.
- The client-level httpx default was dead code (a per-request timeout replaces it wholesale).

## Test plan

- [x] Backend suite green (full run, not a subset)
- [x] Transport tested against a real stalling socket server: slow-but-healthy completes with no
      limit; cancel aborts a wedged request in ~1s; connect stays bounded against a dead host
- [x] Frontend suite + typecheck + UI contract green
- [ ] **Manual smoke test on real hardware**: a genuinely slow / CPU-only run against the Vulkan
      sidecar, confirming a transcript that previously truncated now completes
- [ ] **Windows and macOS check** — the abort primitive was only verified on Linux/CPython 3.13
EOF
)"
```

---

## Out of scope

- `/import` never calls `save_result` / `mark_failed`, so every completed import stays `'processing'` and is later marked **failed** by the orphan sweep (`transcription.py:1241-1245` acknowledges the row is unused). Real bug, unrelated to this one. File separately.
- Chunking (`_MAX_CHUNK_DURATION_S`, `_MAX_CHUNK_DURATION_CEILING_S`) stays exactly as-is. It bounds memory per forward pass and preserves per-chunk progress and cancellation; it was never the time limit.
