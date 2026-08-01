# VRAM Discipline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the transcription model warm while returning every byte of VRAM the app does not actively need, so the server coexists safely with other GPU workloads (LM Studio LLMs on the same RTX 3060).

**Architecture:** Five independent improvements, ordered so each commit is self-contained: (1) honest GPU memory reporting + a reusable post-job cleanup helper, (2) wiring that helper into every job-completion path, (3) fixing the parallel-diarization VRAM leak, (4) fixing `AudioToTextRecorder.shutdown()` dropping backends without unloading, (5) an opt-in `low_vram_mode` config key that caps batch size at 4. The dashboard UI for (5) comes for free: `ServerConfigEditor.tsx` is template-driven and auto-renders any new boolean key in `server/config.yaml` as a toggle.

**Explicitly out of scope (user decision, 2026-08-01):** do NOT release the WhisperX wav2vec2 alignment model between jobs, in any mode. The alignment model stays warm exactly like the transcription model. Any suggestion to shed it during review must be rejected.

**Tech Stack:** Python 3.13 / FastAPI backend (`server/backend/`), pytest via the build venv, PyTorch CUDA APIs (`empty_cache`, `mem_get_info`), TypeScript/React dashboard (types-only change).

**Evidence base (measured 2026-08-01 on the RTX 3060):** idle baseline ~5.83 GB = CT2 large-v3 + CUDA context + WhisperX VAD (~4.5 GB) + alignment model (~1.2 GB, loads on first job, never released). Transient peaks during batched inference reach +2.8 GB. torch reserved-minus-allocated at idle ≈ 0.6 GB (what `empty_cache` reclaims). No job-completion path currently touches the GPU; the only `clear_gpu_cache()` at the route layer is the retry pre-flight (`transcription.py:1566`).

---

## Project conventions (read first, they bite)

- **Branch:** create `feat/vram-discipline` off `main` before the first commit.
- **Backend tests** run from `server/backend/` using the **build venv**:
  ```bash
  cd server/backend
  ../../build/.venv/bin/pytest tests/ -v --tb=short
  ```
  Always finish with the FULL suite, not just the new files.
- **GitNexus:** before modifying any listed function, run `impact({target: "<symbol>", direction: "upstream", repo: "TranscriptionSuite"})` and report blast radius. Before committing run `detect_changes()`. Warn on HIGH/CRITICAL.
- **Patch `audio_utils.*`, never `model_manager.*`** when mocking GPU helpers in tests (established project pattern).
- **Never `pip`, always `uv`** (not expected to be needed here).
- **Commit style** (no line-splitting of long lines, NO AI attribution of any kind):
  ```
  feat(server): <summary>

  * feat(server): change 1
  * fix(server): change 2
  ```
- **Dashboard tests:** `cd dashboard && nvm use` first (vitest needs Node 22), then `npx vitest run`.
- The user's Docker container is running their live server. Do NOT restart or touch the container; all work is code + host-venv tests.

---

### Task 1: Honest GPU memory numbers + `post_job_gpu_cleanup()` helper

The current `get_gpu_memory_info()` reports only the torch caching-allocator view; the CT2 model (~4 GB) is invisible to it and `free_gb` is misleading. Add device-wide numbers via `torch.cuda.mem_get_info()` and a never-raising post-job cleanup helper that clears the cache and logs the after-state.

**Files:**
- Modify: `server/backend/core/audio_utils.py` (functions at lines 195-210 and 397-420)
- Test: `server/backend/tests/test_audio_utils.py` (class `TestGetGpuMemoryInfo` at line 460)

- [ ] **Step 1: Write the failing tests**

Add to `server/backend/tests/test_audio_utils.py`, inside/after the existing `TestGetGpuMemoryInfo` class (line 460; the file already imports `MagicMock`, `patch`, and `server.core.audio_utils as au`):

```python
class TestGetGpuMemoryInfo:
    def test_unavailable_when_no_cuda(self):
        with patch.object(au, "HAS_TORCH", False):
            info = au.get_gpu_memory_info()

        assert info == {"available": False}

    def test_reports_torch_and_device_wide_numbers(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 2 * 1024**3
        mock_torch.cuda.memory_reserved.return_value = 3 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = MagicMock(
            total_memory=12 * 1024**3
        )
        mock_torch.cuda.mem_get_info.return_value = (4 * 1024**3, 12 * 1024**3)

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            info = au.get_gpu_memory_info()

        assert info["allocated_gb"] == 2.0
        assert info["reserved_gb"] == 3.0
        assert info["total_gb"] == 12.0
        assert info["free_gb"] == 9.0
        assert info["device_free_gb"] == 4.0
        assert info["device_used_gb"] == 8.0

    def test_device_wide_failure_keeps_torch_view(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 2 * 1024**3
        mock_torch.cuda.memory_reserved.return_value = 3 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = MagicMock(
            total_memory=12 * 1024**3
        )
        mock_torch.cuda.mem_get_info.side_effect = RuntimeError("not supported")

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            info = au.get_gpu_memory_info()

        assert info["allocated_gb"] == 2.0
        assert "device_free_gb" not in info
        assert "device_used_gb" not in info


class TestPostJobGpuCleanup:
    def test_clears_cache_and_logs(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 1 * 1024**3
        mock_torch.cuda.memory_reserved.return_value = 1 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = MagicMock(
            total_memory=12 * 1024**3
        )
        mock_torch.cuda.mem_get_info.return_value = (6 * 1024**3, 12 * 1024**3)

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            au.post_job_gpu_cleanup("test job")

        mock_torch.cuda.empty_cache.assert_called_once()
        mock_torch.cuda.synchronize.assert_called_once()

    def test_never_raises(self):
        with patch.object(au, "clear_gpu_cache", side_effect=RuntimeError("boom")):
            au.post_job_gpu_cleanup("test job")  # must not raise

    def test_noop_without_cuda(self):
        with patch.object(au, "HAS_TORCH", False):
            au.post_job_gpu_cleanup("test job")  # must not raise
```

Note: `test_unavailable_when_no_cuda` already exists — keep it, add the new methods to the same class.

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_audio_utils.py -v --tb=short -k "GpuMemoryInfo or PostJobGpuCleanup"
```
Expected: the two new `TestGetGpuMemoryInfo` tests FAIL (KeyError `device_free_gb`), `TestPostJobGpuCleanup` FAILS with `AttributeError: ... has no attribute 'post_job_gpu_cleanup'`.

- [ ] **Step 3: Implement**

In `server/backend/core/audio_utils.py`, replace the body of `get_gpu_memory_info()` (currently lines 397-420):

```python
def get_gpu_memory_info(device_index: int = 0) -> dict:
    """Get GPU memory usage information.

    Reports two views that measure different things:
    - allocated_gb/reserved_gb/free_gb: THIS process's PyTorch caching
      allocator only. The CTranslate2 transcription model allocates outside
      this allocator and is invisible here.
    - device_free_gb/device_used_gb: the whole device as the driver sees it
      (includes CTranslate2 and other processes). Best-effort — absent when
      the runtime does not support mem_get_info.

    Args:
        device_index: GPU device index to query (default 0).
    """
    if not check_cuda_available():
        return {"available": False}

    try:
        allocated = torch.cuda.memory_allocated(device_index) / (1024**3)  # GB
        reserved = torch.cuda.memory_reserved(device_index) / (1024**3)  # GB
        total = torch.cuda.get_device_properties(device_index).total_memory / (1024**3)  # GB

        info = {
            "available": True,
            "allocated_gb": round(allocated, 2),
            "reserved_gb": round(reserved, 2),
            "total_gb": round(total, 2),
            "free_gb": round(total - reserved, 2),
        }

        try:
            device_free, device_total = torch.cuda.mem_get_info(device_index)
            info["device_free_gb"] = round(device_free / (1024**3), 2)
            info["device_used_gb"] = round((device_total - device_free) / (1024**3), 2)
        except Exception:
            logger.debug("torch.cuda.mem_get_info unavailable", exc_info=True)

        return info
    except Exception as e:
        logger.error(f"Error getting GPU memory info: {e}")
        return {"available": True, "error": str(e)}
```

Then add the helper directly below `clear_gpu_cache()` (after line 210):

```python
def post_job_gpu_cleanup(context: str = "job") -> None:
    """Release cached GPU memory after a transcription job completes.

    Hands the caching allocators' unused blocks back to the driver so
    co-resident GPU workloads (e.g. a local LLM sharing the card) get the
    VRAM between jobs. The transcription model itself stays warm — only
    freed-but-cached blocks are returned. Best-effort: never raises.

    Args:
        context: Short label for the completed job type, used in the log line.
    """
    try:
        clear_gpu_cache()
        info = get_gpu_memory_info()
        if info.get("available"):
            logger.info(
                "GPU memory after %s: torch allocated=%s GB reserved=%s GB, device used=%s GB",
                context,
                info.get("allocated_gb", "n/a"),
                info.get("reserved_gb", "n/a"),
                info.get("device_used_gb", "n/a"),
            )
    except Exception as e:
        logger.debug("Post-job GPU cleanup failed (non-critical): %s", e)
```

- [ ] **Step 4: Run the tests again**

Same command as Step 2. Expected: all PASS. Then run the full `test_audio_utils.py` to catch regressions.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/audio_utils.py server/backend/tests/test_audio_utils.py
git commit -m "feat(server): device-wide GPU memory reporting and a post-job cleanup helper"
```

---

### Task 2: Run the cleanup at every job-completion site

Today no job-completion path touches the GPU (verified). Add `post_job_gpu_cleanup()` to the `finally` of all five completion sites. Explicitly EXCLUDED: `preview_transcription()` (`websocket.py:339-346`) — the rolling preview fires every few seconds during recording and clearing the cache per preview chunk would thrash the allocator.

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (`process_transcription` finally, lines ~645-658)
- Modify: `server/backend/api/routes/transcription.py` (`_run_file_import` finally ~1182-1187; `_run_retry` finally ~1642-1644)
- Modify: `server/backend/api/routes/notebook.py` (`_run_transcription` finally ~1250-1255)
- Modify: `server/backend/api/routes/openai_audio.py` (`create_transcription` finally ~465-468; `create_translation` finally ~583-586)
- Test: `server/backend/tests/test_post_job_gpu_cleanup_sites.py` (new), `server/backend/tests/test_p0_durability.py` (extend), `server/backend/tests/test_retry_clears_gpu_cache.py` (extend)

- [ ] **Step 1: Write the failing tests — new file**

Create `server/backend/tests/test_post_job_gpu_cleanup_sites.py`:

```python
"""Every job completion must hand cached GPU memory back to the driver.

The cleanup lives in each site's ``finally`` so it runs on success, failure
and cancellation alike. These tests drive the cheapest deterministic path
(usually a failure right at engine load) and assert the cleanup still fired.

Run:  ../../build/.venv/bin/pytest tests/test_post_job_gpu_cleanup_sites.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from server.api.routes import openai_audio, transcription
from server.api.routes import notebook as notebook_routes


def _trace_cleanup(monkeypatch) -> list[str]:
    calls: list[str] = []
    audio_utils = importlib.import_module("server.core.audio_utils")
    monkeypatch.setattr(
        audio_utils,
        "post_job_gpu_cleanup",
        lambda ctx="job": calls.append(ctx),
        raising=False,
    )
    return calls


def _raise_boom() -> Any:
    raise RuntimeError("boom")


def test_file_import_runs_gpu_cleanup_even_on_failure(monkeypatch, tmp_path):
    calls = _trace_cleanup(monkeypatch)
    ended: list[Any] = []
    model_manager = SimpleNamespace(
        job_tracker=SimpleNamespace(
            update_progress=lambda *a: None,
            set_phase=lambda *_: None,
            end_job=lambda job_id, result=None: ended.append(result),
            is_cancelled=lambda: False,
        ),
        ensure_transcription_loaded=_raise_boom,
    )
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    transcription._run_file_import(
        model_manager=model_manager,
        tmp_path=wav,
        filename="a.wav",
        language=None,
        translation_enabled=False,
        translation_target_language=None,
        enable_diarization=False,
        enable_word_timestamps=True,
        expected_speakers=None,
        parallel_diarization=None,
        use_parallel_default=False,
        multitrack=False,
        job_id="job12345",
        event_loop=None,
    )

    assert calls == ["file import"]
    assert ended and "error" in ended[-1]


def test_notebook_import_runs_gpu_cleanup_even_on_failure(monkeypatch, tmp_path):
    calls = _trace_cleanup(monkeypatch)
    ended: list[Any] = []
    model_manager = SimpleNamespace(
        job_tracker=SimpleNamespace(
            update_progress=lambda *a: None,
            set_phase=lambda *_: None,
            end_job=lambda job_id, result=None: ended.append(result),
            is_cancelled=lambda: False,
        ),
        ensure_transcription_loaded=_raise_boom,
    )
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    notebook_routes._run_transcription(
        model_manager=model_manager,
        tmp_path=wav,
        filename="a.wav",
        language=None,
        translation_enabled=False,
        translation_target_language=None,
        enable_diarization=False,
        enable_word_timestamps=True,
        file_created_at=None,
        expected_speakers=None,
        parallel_diarization=None,
        use_parallel_default=False,
        title=None,
        job_id="job12345",
        event_loop=None,
    )

    assert calls == ["notebook import"]
    assert ended and "error" in ended[-1]


def _openai_request(mm: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_manager=mm)))


def _openai_model_manager(ended: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(
        ensure_transcription_loaded=lambda: None,
        job_tracker=SimpleNamespace(
            try_start_job=lambda _c: (True, "job-1", None),
            end_job=lambda job_id: ended.append(job_id),
        ),
    )


def test_openai_transcription_runs_gpu_cleanup(monkeypatch):
    calls = _trace_cleanup(monkeypatch)
    monkeypatch.setattr(openai_audio, "_assert_model_loaded", lambda _r: None)
    monkeypatch.setattr(openai_audio, "get_client_name", lambda _r: "test-client")

    async def _boom(**_kw: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(openai_audio, "_run_transcription", _boom)
    ended: list[Any] = []
    mm = _openai_model_manager(ended)
    file = MagicMock()
    file.filename = "a.wav"
    file.read = AsyncMock(return_value=b"riff")

    asyncio.run(openai_audio.create_transcription(request=_openai_request(mm), file=file))

    assert calls == ["openai transcription"]
    assert ended == ["job-1"]


def test_openai_translation_runs_gpu_cleanup(monkeypatch):
    calls = _trace_cleanup(monkeypatch)
    monkeypatch.setattr(openai_audio, "_assert_model_loaded", lambda _r: None)
    monkeypatch.setattr(openai_audio, "get_client_name", lambda _r: "test-client")

    async def _boom(**_kw: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(openai_audio, "_run_transcription", _boom)
    ended: list[Any] = []
    mm = _openai_model_manager(ended)
    file = MagicMock()
    file.filename = "a.wav"
    file.read = AsyncMock(return_value=b"riff")

    asyncio.run(openai_audio.create_translation(request=_openai_request(mm), file=file))

    assert calls == ["openai translation"]
    assert ended == ["job-1"]
```

Adaptation notes for the executor: (a) check `create_translation`'s actual signature in `openai_audio.py` before writing its test — mirror `create_transcription`'s calling convention with that function's own required params; (b) if either notebook/import function requires an additional keyword not listed in its signature shown here, read the signature at `transcription.py:839-857` / `notebook.py:835-852` — both were verified current at plan time.

- [ ] **Step 2: Extend the WS durability tests**

In `server/backend/tests/test_p0_durability.py`, add at the end (the file already has `_make_session`, `_BaseProcessTranscription`, `asyncio`, `ws_mod`; add `import importlib` to its imports if missing):

```python
@pytest.mark.p0
@pytest.mark.durability
class TestPostJobGpuCleanupOnWs(_BaseProcessTranscription):
    """The longform WS path must release cached VRAM in its finally."""

    def _trace(self, monkeypatch) -> list[str]:
        calls: list[str] = []
        audio_utils = importlib.import_module("server.core.audio_utils")
        monkeypatch.setattr(
            audio_utils,
            "post_job_gpu_cleanup",
            lambda ctx="job": calls.append(ctx),
            raising=False,
        )
        return calls

    def test_cleanup_runs_after_success(self, monkeypatch):
        calls = self._trace(monkeypatch)
        session = _make_session()

        asyncio.run(session.process_transcription())

        assert calls == ["longform recording"]

    def test_cleanup_runs_when_transcription_fails(self, monkeypatch):
        calls = self._trace(monkeypatch)
        self._engine.transcribe_file.side_effect = RuntimeError("CUDA OOM")
        session = _make_session()

        asyncio.run(session.process_transcription())

        assert calls == ["longform recording"]
```

- [ ] **Step 3: Extend the retry test**

In `server/backend/tests/test_retry_clears_gpu_cache.py`, inside `_drive_retry` where `clear_gpu_cache` is monkeypatched (line ~101), add a second monkeypatch right after it:

```python
    monkeypatch.setattr(
        audio_utils,
        "post_job_gpu_cleanup",
        lambda ctx="job": trace.append("post_job_gpu_cleanup"),
        raising=False,
    )
```

and add a new test asserting the full order:

```python
def test_gpu_cleanup_runs_after_retry_completes(monkeypatch):
    trace = _drive_retry(monkeypatch)
    assert trace == ["clear_gpu_cache", "transcribe_file", "post_job_gpu_cleanup"]
```

(If `_drive_retry` needs other assertions updated because the trace list now has an extra entry, adjust existing assertions to check membership/prefix rather than exact equality — do NOT delete existing order checks between `clear_gpu_cache` and `transcribe_file`.)

- [ ] **Step 4: Run all three test files — expect the new tests to FAIL**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_post_job_gpu_cleanup_sites.py tests/test_p0_durability.py tests/test_retry_clears_gpu_cache.py -v --tb=short
```

- [ ] **Step 5: Implement the five site edits**

Context strings must match the tests exactly. All five files already use lazy imports for audio_utils; use the absolute form (`from server.core.audio_utils import ...`) — the relative import inside `_run_retry` is a one-off, don't copy it.

**(a) `websocket.py` `process_transcription` finally (lines ~645-658).** Insert at the TOP of the existing `finally:` block, before the temp-file cleanup:

```python
        finally:
            # Hand cached GPU blocks back to the driver so co-resident
            # workloads (e.g. a local LLM) get the VRAM between jobs. The
            # model stays warm; run in a thread because empty_cache blocks.
            from server.core.audio_utils import post_job_gpu_cleanup

            await asyncio.to_thread(post_job_gpu_cleanup, "longform recording")

            # Only delete files in /tmp — persistent audio in recordings_dir must survive
```
(`asyncio` is already imported in websocket.py — verify, add if not.)

**(b) `transcription.py` `_run_file_import` finally (lines ~1182-1187)** — this is a sync function running in a thread; call directly. Insert at the top of the `finally:` block:

```python
    finally:
        from server.core.audio_utils import post_job_gpu_cleanup

        post_job_gpu_cleanup("file import")

        # Cleanup temp file
```

**(c) `transcription.py` `_run_retry` finally (lines ~1642-1644)** — async function; keep the existing pre-flight `clear_gpu_cache` untouched and add post-job cleanup before `end_job`:

```python
    finally:
        from server.core.audio_utils import post_job_gpu_cleanup

        await asyncio.to_thread(post_job_gpu_cleanup, "retry")
        if tracker_job_id:
            model_manager.job_tracker.end_job(tracker_job_id)
```

**(d) `notebook.py` `_run_transcription` finally (lines ~1250-1255)** — sync, direct call:

```python
    finally:
        from server.core.audio_utils import post_job_gpu_cleanup

        post_job_gpu_cleanup("notebook import")

        # Cleanup temp file
```

**(e) `openai_audio.py` both handlers' finally blocks (~465-468 and ~583-586)** — async; cleanup BEFORE `end_job` so the single job slot is still held while the cache clears (no race with the next job):

```python
    finally:
        from server.core.audio_utils import post_job_gpu_cleanup

        await asyncio.to_thread(post_job_gpu_cleanup, "openai transcription")
        model_manager.job_tracker.end_job(job_id)
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
```
(second handler: context string `"openai translation"`.)

- [ ] **Step 6: Run the three test files again — all PASS — then the FULL suite**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/api/routes/transcription.py server/backend/api/routes/notebook.py server/backend/api/routes/openai_audio.py server/backend/tests/test_post_job_gpu_cleanup_sites.py server/backend/tests/test_p0_durability.py server/backend/tests/test_retry_clears_gpu_cache.py
git commit -m "feat(server): release cached GPU memory after every transcription job"
```

---

### Task 3: Fix the parallel-diarization VRAM leak

`transcribe_and_diarize()` (`parallel_diarize.py:120-259`) loads the diarization model and never unloads it — it stays resident forever after the first parallel-diarize job. Its sequential sibling `transcribe_then_diarize()` unloads in a `finally` (lines 103-117). Mirror that. Known tradeoff (accepted): back-to-back diarized imports in parallel mode will reload the diarization model per job (~10-20 s); consistency and VRAM discipline win.

**Files:**
- Modify: `server/backend/core/parallel_diarize.py:120-259`
- Test: `server/backend/tests/test_parallel_diarize.py`

- [ ] **Step 1: Write the failing tests** — add to `test_parallel_diarize.py` (imports/patterns already in the file):

```python
@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_parallel_success_unloads_diarization_model(mock_load_audio):
    """After a successful parallel run the diarization model must be unloaded."""
    engine = MagicMock()
    engine.transcribe_file.return_value = MagicMock(words=[], segments=[])
    mm = MagicMock()
    diar_engine = MagicMock()
    diar_result = MagicMock()
    diar_result.segments = [MagicMock()]
    diar_result.num_speakers = 2
    diar_engine.diarize_audio.return_value = diar_result
    mm.diarization_engine = diar_engine

    result, diar = transcribe_and_diarize(
        engine=engine, model_manager=mm, file_path="/tmp/test.wav"
    )

    assert diar is diar_result
    mm.unload_diarization_model.assert_called_once()


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_parallel_transcribe_failure_still_unloads_diarization_model(mock_load_audio):
    """A transcription crash must not leave the diarization model resident."""
    engine = MagicMock()
    engine.transcribe_file.side_effect = RuntimeError("boom")
    mm = MagicMock()
    mm.diarization_engine = MagicMock()

    with pytest.raises(RuntimeError):
        transcribe_and_diarize(engine=engine, model_manager=mm, file_path="/tmp/test.wav")

    mm.unload_diarization_model.assert_called_once()
```

- [ ] **Step 2: Run — expect FAIL** (`unload_diarization_model` never called):

```bash
../../build/.venv/bin/pytest tests/test_parallel_diarize.py -v --tb=short
```

- [ ] **Step 3: Implement.** Two edits in `transcribe_and_diarize()`:

(1) In the pre-load-failed fallback branch (the `if diar_engine is None or audio_data is None:` block), add a best-effort unload before transcribing — `load_diarization_model()` may have succeeded before `load_audio()` failed:

```python
    if diar_engine is None or audio_data is None:
        # Pre-load may have loaded the diarization model before load_audio
        # failed — release it, we are about to run transcription-only.
        model_manager.unload_diarization_model()
        result = engine.transcribe_file(
```

(2) Wrap everything from the Sortformer check to the end of the function in `try/finally` (re-indent the existing code one level; the Sortformer branch's inner `transcribe_then_diarize` unloads on its own, so the outer finally is a harmless no-op there — `unload_diarization_model()` is idempotent):

```python
    try:
        # Sortformer uses MLX/Metal — running it in parallel with MLX Whisper
        # (also Metal) deadlocks the GPU.  Fall back to sequential mode.
        from server.core.sortformer_engine import SortformerEngine
        ...  # existing code through the end of the ThreadPoolExecutor block,
        ...  # unchanged apart from one indentation level
    finally:
        # Mirror transcribe_then_diarize: the diarization model is only
        # needed during this job — release its VRAM instead of keeping it
        # resident forever (it was never unloaded on this path before).
        model_manager.unload_diarization_model()
```

- [ ] **Step 4: Run `test_parallel_diarize.py` — all PASS** (the pre-existing 12 tests use a MagicMock model_manager, so the new unload call cannot break them).

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/parallel_diarize.py server/backend/tests/test_parallel_diarize.py
git commit -m "fix(server): unload the diarization model after parallel diarization jobs"
```

---

### Task 4: `shutdown()` must unload owned backends

`AudioToTextRecorder.shutdown()` (`engine.py:1165-1187`) drops `self._backend` without calling `backend.unload()`, so VRAM release is left to the garbage collector and cached allocator blocks are never returned. `unload_model()` (lines 1196-1206) does it correctly — mirror it.

**Files:**
- Modify: `server/backend/core/stt/engine.py:1180-1184` (the "Cleanup backend" tail of `shutdown()`)
- Test: `server/backend/tests/test_stt_engine_helpers.py` (this file already imports the engine module successfully — follow ITS import style; do not invent a new import path, the engine module needs the conftest-provided mocks)

- [ ] **Step 1: Write the failing tests** — add to `test_stt_engine_helpers.py`, reusing that file's existing engine-module import (call it `engine_mod` below) plus `threading` and `MagicMock`:

```python
def _make_recorder_for_shutdown(owns_backend: bool):
    rec = object.__new__(engine_mod.AudioToTextRecorder)
    rec.instance_name = "test"
    rec.is_shut_down = False
    rec.is_running = True
    rec.start_recording_event = threading.Event()
    rec.stop_recording_event = threading.Event()
    rec.shutdown_event = threading.Event()
    rec.recording_thread = None
    rec._backend = MagicMock()
    rec._owns_backend = owns_backend
    rec._model_loaded = True
    return rec


class TestShutdownUnloadsBackend:
    def test_shutdown_unloads_owned_backend(self):
        rec = _make_recorder_for_shutdown(owns_backend=True)
        backend = rec._backend

        rec.shutdown()

        backend.unload.assert_called_once()
        assert rec._backend is None
        assert rec._model_loaded is False

    def test_shutdown_leaves_shared_backend_alone(self):
        """A borrowed backend (Live Mode sharing) belongs to the caller."""
        rec = _make_recorder_for_shutdown(owns_backend=False)
        backend = rec._backend

        rec.shutdown()

        backend.unload.assert_not_called()
        assert rec._backend is None

    def test_shutdown_is_idempotent(self):
        rec = _make_recorder_for_shutdown(owns_backend=True)
        backend = rec._backend

        rec.shutdown()
        rec.shutdown()

        backend.unload.assert_called_once()

    def test_shutdown_survives_unload_failure(self):
        rec = _make_recorder_for_shutdown(owns_backend=True)
        rec._backend.unload.side_effect = RuntimeError("CUDA context gone")

        rec.shutdown()  # must not raise

        assert rec._backend is None
```

- [ ] **Step 2: Run — expect FAIL** (`unload` never called):

```bash
../../build/.venv/bin/pytest tests/test_stt_engine_helpers.py -v --tb=short -k Shutdown
```

- [ ] **Step 3: Implement.** In `shutdown()`, replace:

```python
        # Cleanup backend
        self._backend = None
        self._model_loaded = False
```

with:

```python
        # Cleanup backend — actually unload owned backends instead of just
        # dropping the reference: a dropped reference leaves the model's VRAM
        # to the garbage collector and never returns cached allocator blocks
        # to the driver. Shared backends belong to the caller (Live Mode).
        if self._backend is not None and self._owns_backend:
            try:
                self._backend.unload()
            except Exception:
                logger.warning("Backend unload during shutdown failed", exc_info=True)
        self._backend = None
        self._model_loaded = False
```

- [ ] **Step 4: Run the file's full tests, then commit**

```bash
../../build/.venv/bin/pytest tests/test_stt_engine_helpers.py -v --tb=short
git add server/backend/core/stt/engine.py server/backend/tests/test_stt_engine_helpers.py
git commit -m "fix(server): shutdown() unloads owned STT backends instead of dropping the reference"
```

---

### Task 5: `low_vram_mode` — batch cap

One opt-in boolean (`main_transcriber.low_vram_mode`, default `false`). When ON, the transcription batch size is capped at 4, which shrinks the measured +2.8 GB transient peak roughly in half. Both the transcription model and the alignment model always stay warm — this mode changes nothing about model residency, only the per-job working set. **Dashboard UI is free:** `ServerConfigEditor.tsx` auto-renders every boolean template key as an AppleSwitch with the yaml comment as description — no dashboard code changes.

**Do NOT** touch `whisperx_backend.py` or `engine.py` in this task. An earlier draft of this plan also released the alignment model in this mode; the user removed that from scope. There is no engine→backend plumbing to add: `_scale_batch_size` reads `self.config` directly.

**Files:**
- Modify: `server/backend/config.py` (constant near line 37; new resolver after `resolve_parallel_diarization_default`, line 552)
- Modify: `server/config.yaml` (main_transcriber section, after the `beam_size` block at line 76)
- Modify: `server/backend/core/model_manager.py` (`_scale_batch_size`, lines 672-712)
- Test: `server/backend/tests/test_low_vram_mode.py` (new)

- [ ] **Step 1: Write the failing tests — new file** `server/backend/tests/test_low_vram_mode.py`:

```python
"""Low VRAM mode: cap the transcription batch size at 4.

The mode is an opt-in trade of throughput for GPU headroom so the server
coexists with other GPU workloads (e.g. a local LLM). Loaded models are
never affected: the transcription and alignment models stay warm in both
modes, only the per-job working set shrinks.

Run:  ../../build/.venv/bin/pytest tests/test_low_vram_mode.py -v --tb=short
"""

from __future__ import annotations

from unittest.mock import patch

from server.config import DEFAULT_LOW_VRAM_MODE, resolve_low_vram_mode


class TestResolveLowVramMode:
    def test_default_is_off(self):
        assert DEFAULT_LOW_VRAM_MODE is False
        assert resolve_low_vram_mode({}) is False

    def test_dict_config_on(self):
        assert resolve_low_vram_mode({"main_transcriber": {"low_vram_mode": True}}) is True

    def test_dict_config_explicit_off(self):
        assert resolve_low_vram_mode({"main_transcriber": {"low_vram_mode": False}}) is False


class TestScaleBatchSizeLowVram:
    def _manager(self, config: dict):
        from server.core.model_manager import ModelManager

        mm = object.__new__(ModelManager)
        mm.gpu_available = True
        mm.config = config
        mm._gpu_device_index = 0
        return mm

    def test_low_vram_caps_at_4_even_on_big_gpus(self):
        mm = self._manager({"main_transcriber": {"low_vram_mode": True}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 24.0},
        ):
            assert mm._scale_batch_size(16) == 4

    def test_low_vram_never_raises_a_smaller_configured_size(self):
        mm = self._manager({"main_transcriber": {"low_vram_mode": True}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 24.0},
        ):
            assert mm._scale_batch_size(2) == 2

    def test_tiered_caps_unchanged_when_off(self):
        mm = self._manager({"main_transcriber": {"low_vram_mode": False}})
        with patch(
            "server.core.audio_utils.get_gpu_memory_info",
            return_value={"available": True, "total_gb": 12.0},
        ):
            assert mm._scale_batch_size(16) == 8
```

- [ ] **Step 2: Run the new test file — expect FAIL** (`ImportError: cannot import name 'resolve_low_vram_mode'`):

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_low_vram_mode.py -v --tb=short
```

- [ ] **Step 3: Implement — config layer.**

`server/backend/config.py`: next to `DEFAULT_PARALLEL_DIARIZATION = False` (line 37) add:

```python
DEFAULT_LOW_VRAM_MODE = False
```

After `resolve_parallel_diarization_default` (line 552) add:

```python
def resolve_low_vram_mode(config: "ServerConfig | dict[str, Any]") -> bool:
    """
    Resolve ``main_transcriber.low_vram_mode`` (default OFF).

    When ON, the transcription batch size is capped at 4, trading throughput
    for smaller transient VRAM peaks during jobs. Intended for GPUs shared
    with other workloads (e.g. a local LLM). Loaded models are unaffected:
    the transcription and alignment models stay warm either way.
    """
    if isinstance(config, ServerConfig):
        value = config.get("main_transcriber", "low_vram_mode", default=DEFAULT_LOW_VRAM_MODE)
    else:
        value = _dict_get(config, "main_transcriber", "low_vram_mode")
        if value is None:
            value = DEFAULT_LOW_VRAM_MODE
    return bool(value)
```

`server/config.yaml`: in the `main_transcriber:` section, after the `beam_size` entry (line 76), add (4-space indent matching the section):

```yaml
    # Low VRAM mode: trade some speed for a smaller GPU footprint. Caps the
    # transcription batch size at 4, which roughly halves the extra VRAM used
    # while a job runs. Useful when sharing the GPU with other apps (e.g. a
    # local LLM). Loaded models are not affected - they stay in VRAM either way.
    low_vram_mode: false
```

- [ ] **Step 4: Implement — batch cap.** In `model_manager.py` `_scale_batch_size`, insert after the `if not self.gpu_available:` early return:

```python
        from server.config import resolve_low_vram_mode

        if resolve_low_vram_mode(self.config):
            if configured_batch_size > 4:
                logger.info(
                    "Low VRAM mode: capping batch_size %d -> 4", configured_batch_size
                )
                return 4
            return configured_batch_size
```

- [ ] **Step 5: Run the new test file — PASS — then the FULL backend suite.** Also check `test_model_manager*.py` specifically: any existing `_scale_batch_size` test builds its manager without a `low_vram_mode` key, so the resolver must tolerate a missing key (it does — that is what `test_default_is_off` pins).

The toggle needs no dashboard work: `ServerConfigEditor` renders template keys generically (boolean → AppleSwitch, yaml comment → description). Note in the PR that the new key needs a server restart to apply, like every `main_transcriber` key.

- [ ] **Step 6: Commit**

```bash
git add server/backend/config.py server/config.yaml server/backend/core/model_manager.py server/backend/tests/test_low_vram_mode.py
git commit -m "feat(server): opt-in low VRAM mode that caps the transcription batch size at 4"
```

---

### Task 6: Fix the stale dashboard type for `gpu_memory`

`dashboard/src/api/types.ts:28` declares `gpu_memory?: string` at the top level of `ServerStatus`, but the backend actually nests a dict under `models.gpu_memory` (and sends no top-level `gpu_memory` at all). Verified: there are ZERO runtime consumers of this field anywhere in `dashboard/` — the fix is type-only, no UI, no ui-contract impact (no CSS classes touched).

**Files:**
- Modify: `dashboard/src/api/types.ts:18-47`

- [ ] **Step 1: Implement** (no test-first for a type-only change; the vitest suite is the regression net). In `types.ts`, add above `ServerStatus`:

```typescript
export interface GpuMemoryInfo {
  available: boolean;
  /** This process's PyTorch caching allocator only (excludes CTranslate2). */
  allocated_gb?: number;
  reserved_gb?: number;
  total_gb?: number;
  free_gb?: number;
  /** Device-wide numbers from the driver (include all processes). */
  device_free_gb?: number;
  device_used_gb?: number;
  error?: string;
}
```

Then inside `ServerStatus`: extend the `models` intersection to include the real location and remove the wrong top-level field:

```typescript
  models?: Record<string, unknown> & {
    transcription?: { selected_model?: string; loaded?: boolean; disabled?: boolean };
    gpu_memory?: GpuMemoryInfo | null;
  };
```

and delete the line `gpu_memory?: string;`.

- [ ] **Step 2: Run the dashboard suite**

```bash
cd dashboard
nvm use
npx vitest run
```
Expected: green (nothing consumes the field). If the project exposes a typecheck script in `package.json`, run it too.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/api/types.ts
git commit -m "fix(dashboard): correct the ServerStatus gpu_memory type to the real nested dict shape"
```

---

### Task 7: Final verification and PR

- [ ] **Step 1: Full backend suite** (must be green):

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

- [ ] **Step 2: Dashboard suite** (`cd dashboard && nvm use && npx vitest run`).

- [ ] **Step 3: GitNexus regression check:** `detect_changes({scope: "compare", base_ref: "main", repo: "TranscriptionSuite"})` — confirm only the intended symbols/flows changed.

- [ ] **Step 4: Safety sweep:** `git diff main...HEAD` and check: no AI attribution anywhere, no leftover debug prints, comments state constraints (not narration).

- [ ] **Step 5: Open the PR directly on GitHub** (no local draft files):

```bash
gh pr create --title "feat(server): VRAM discipline — post-job cache release, leak fixes, low VRAM mode" --body "..."
```

PR body should cover: the measured baseline (5.83 GB anatomy, +2.8 GB transient peaks, motivation = LM Studio coexistence on a shared 3060), the five changes with one line each, the accepted tradeoffs (parallel diarization reloads the diarization model per job; low_vram_mode roughly halves batched throughput), and a **hardware smoke checklist** (not run in CI):

```
- [ ] With low_vram_mode OFF: idle VRAM after a job returns to ~baseline; log line "GPU memory after ..." appears after each job
- [ ] With low_vram_mode ON (toggle visible in Server tab config editor; restart server): peak VRAM during a long import noticeably lower; idle baseline unchanged (models stay warm)
- [ ] Parallel diarization import: diarization model unloaded after the job (nvidia-smi settles back)
- [ ] Longform recording end-to-end still transcribes with word timestamps
```

---

## Self-review notes (already applied)

- The preview path (`preview_transcription`) is deliberately NOT wired to the cleanup — do not "fix" that during review.
- The retry route keeps its pre-flight `clear_gpu_cache` AND gains the post-job cleanup; both are wanted.
- `post_job_gpu_cleanup` contexts are load-bearing strings — tests assert them verbatim.
- `_scale_batch_size`'s existing tiered caps are unchanged when the mode is off; `test_tiered_caps_unchanged_when_off` pins that.
- The WhisperX alignment model is never released between jobs (user decision). `whisperx_backend.py` is not touched by this plan at all.
- All five completion-site edits use the absolute import form (`from server.core.audio_utils import post_job_gpu_cleanup`), matching house style; the relative import inside `_run_retry` predates this plan and stays as-is.
