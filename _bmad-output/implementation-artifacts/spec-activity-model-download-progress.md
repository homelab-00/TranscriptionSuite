---
title: 'Activity System — Model Download Progress (Phase 4)'
type: 'feature'
created: '2026-04-01'
status: 'done'
baseline_commit: '0cf996e'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** When a model isn't cached, downloading takes minutes (1-3 GB) with zero progress feedback — the user sees only a spinner. This is the biggest remaining gap in startup transparency after Phases 1-3.

**Approach:** Monkey-patch `huggingface_hub`'s tqdm progress class during model loading to intercept byte-level download progress. Emit throttled `emit_event()` calls with `progress`, `downloadedSize`, and `totalSize` fields. Detect cache hits (no download triggered) and label them accordingly. Integrate at the `model_manager` level so all model loads (startup preload, live mode switch) get tracking automatically.

## Boundaries & Constraints

**Always:**
- Use the existing `emit_event()` from `startup_events.py`
- Restore the original tqdm class after model loading completes (try/finally)
- Throttle event emission to <=1 write/second
- Handle cache hits gracefully (no tqdm created = no progress events, just timing)
- Include `durationMs` on all completion events

**Ask First:**
- If huggingface_hub 0.36's tqdm import path differs from expected and patching doesn't intercept downloads
- If NeMo's `from_pretrained()` uses a different progress mechanism than huggingface_hub tqdm

**Never:**
- Modify huggingface_hub source or add external dependencies
- Break cached model loading
- Emit events for non-model downloads (pip packages, configs)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First download | Model not in cache | `model-download` active with progress 0-100%, downloadedSize, totalSize | N/A |
| Cached model | Model files exist locally | `model-load` complete with durationMs, no progress fields | N/A |
| Download failure | Network error mid-download | `model-load` error event | Tqdm class restored; exception propagates |
| Multiple HF files | snapshot_download fetches weights + config + tokenizer | Single event ID per model; largest file dominates progress | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/startup_events.py` -- Existing event writer (no changes)
- `server/backend/core/download_progress.py` (NEW) -- ProgressTqdm class + `track_model_download()` context manager
- `server/backend/core/model_manager.py` -- Wrap `engine.load_model()` in `load_transcription_model()` with download tracking

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/download_progress.py` (NEW) -- Create `_ProgressTqdm` class (tqdm-compatible: `__init__(total, desc, ...)`, `update(n)`, `close()`, context manager protocol) that emits throttled `emit_event()` calls with category `"download"`, progress percentage, downloadedSize, totalSize. Create `track_model_download(model_name)` context manager that: emits `model-load` active event on entry, patches huggingface_hub's tqdm class, tracks whether any download tqdm was instantiated, and on exit emits complete (with durationMs) — including "Loaded from cache" label when no download occurred.
- [x] `server/backend/core/model_manager.py` -- In `load_transcription_model()`, wrap the `engine.load_model()` call with `track_model_download(engine.model_name)` context manager so all model loads (preload + live swap) get download tracking automatically.
- [x] `server/backend/tests/test_download_progress.py` (NEW) -- Unit tests: ProgressTqdm emits events on update; throttling suppresses rapid writes; context manager detects cache hit when no tqdm created; original tqdm restored on both success and exception; event IDs use model name.

**Acceptance Criteria:**
- Given a model not in cache, when model preload runs, then the events file contains download progress events with increasing byte counts
- Given a cached model, when model preload runs, then a "Loaded from cache" complete event appears with durationMs and no progress fields
- Given any outcome, when model loading finishes, then the original huggingface_hub tqdm class is restored

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: all tests pass including new download_progress tests

**Manual checks:**
- Start container with uncached model, inspect `startup-events.jsonl` for download progress events with bytes and percentages
- Start container with cached model, verify "Loaded from cache" event with timing only

## Suggested Review Order

**Core module — download progress tracking**

- Thread-local tracker + throttled event emitter
  [`download_progress.py:34`](../../server/backend/core/download_progress.py#L34)

- _ProgressTqdm: tqdm-compatible class with get_lock/set_lock for thread_map, mutable total for snapshot_download
  [`download_progress.py:91`](../../server/backend/core/download_progress.py#L91)

- track_model_download context manager: patch → yield → restore with try/except/else/finally
  [`download_progress.py:218`](../../server/backend/core/download_progress.py#L218)

**Integration**

- Wrap engine.load_model() in load_transcription_model() with lazy import
  [`model_manager.py:620`](../../server/backend/core/model_manager.py#L620)
