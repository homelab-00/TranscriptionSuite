---
title: 'P0 test implementation — durability, model swap, live history'
type: 'chore'
created: '2026-04-05'
status: 'done'
baseline_commit: '5f783fc'
context:
  - docs/testing/test-design-qa.md
  - docs/TESTING.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** P0 tests from the QA test design are unimplemented. All 12 test IDs (26 scenarios) covering data durability (R-001), model swap recovery (R-003), and live mode history (R-002) have zero automated coverage despite the code fixes being merged.

**Approach:** Implement all P0 tests using the existing direct-call test pattern, organized into 3 new test files with pytest `p0`/`durability`/`live_mode` markers. Register markers in pyproject.toml.

## Boundaries & Constraints

**Always:**
- Use existing direct-call pattern (monkeypatch, no HTTP test client)
- Follow test-design-qa.md test IDs exactly (P0-DURA-*, P0-SWAP-*, P0-LIVE-*)
- All 992 existing tests must still pass after adding new tests
- Use `pytest.mark.p0` marker on every test
- Run tests via `../../build/.venv/bin/pytest tests/ -v --tb=short`

**Ask First:**
- Adding new dependencies to pyproject.toml
- Changing production code (these are test-only changes)

**Never:**
- Modify existing test files
- Import heavy ML dependencies (torch, faster-whisper, nemo) — use stubs/mocks
- Create real database files outside tmp_path

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| DURA-001: save_result raises | DB error during save | mark_failed called with persistence message | Continues to deliver result to client |
| DURA-002: WS disconnect mid-process | _client_disconnected=True after save | save_result already called — result safe | mark_failed for cancelled |
| DURA-004: >1MB result | Large result_json | send_message("result_ready") not "final"; mark_delivered NOT called | HTTP fetch path marks delivered |
| DURA-006: orphan recovery | 3 stale jobs (with audio, without, normal) | All marked failed with appropriate reasons | Wraps in try/except, logs, continues |
| DURA-007: periodic sweep + busy | job_tracker.is_busy()=True | Sweep skipped; no mark_failed calls | Logs skip and continues |
| SWAP-001: disconnect during swap | _model_displaced=True, CancelledError | _restore_or_reload_main_model called | asyncio.shield prevents cancel |
| SWAP-002: engine.start() fails | start() returns False | finally restores main model | Engine stopped+discarded |
| LIVE-001: history cap | 60 sentences pushed | Only last 50 retained | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/websocket.py` -- TranscriptionSession.process_transcription() persistence flow
- `server/backend/api/routes/live.py` -- LiveModeSession.start_engine() model swap + finally
- `server/backend/api/main.py` -- recover_orphaned_jobs() + periodic_orphan_sweep()
- `server/backend/database/job_repository.py` -- save_result, mark_failed, get_orphaned_jobs
- `server/backend/core/live_engine.py` -- LiveModeEngine._process_sentence, sentence_history, clear_history
- `server/backend/tests/conftest.py` -- _ensure_server_package_alias (must run before imports)
- `server/backend/tests/test_transcription_durability_routes.py` -- reference pattern

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/pyproject.toml` -- register pytest markers (p0, p1, durability, live_mode, model_swap)
- [x] `server/backend/tests/test_p0_durability.py` -- P0-DURA-001 through P0-DURA-007 (7 IDs, 21 scenarios)
- [x] `server/backend/tests/test_p0_model_swap.py` -- P0-SWAP-001 through P0-SWAP-003 (3 IDs, 8 scenarios)
- [x] `server/backend/tests/test_p0_live_mode.py` -- P0-LIVE-001, P0-LIVE-002 (2 IDs, 6 scenarios)

**Acceptance Criteria:**
- Given `pytest -m p0`, when all P0 tests run, then 26+ tests pass
- Given `pytest tests/`, when full suite runs, then 992+ existing tests still pass
- Given a save_result() failure in DURA-001, when process_transcription completes, then mark_failed is called with persistence message
- Given _model_displaced=True in SWAP-001, when CancelledError fires, then _restore_or_reload_main_model runs via asyncio.shield
- Given 60 sentences pushed in LIVE-001, when history checked, then exactly 50 retained (oldest dropped)

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_p0_durability.py tests/test_p0_model_swap.py tests/test_p0_live_mode.py -v --tb=short` -- expected: all P0 tests pass
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: 992+ existing tests unaffected
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -m p0 --co -q` -- expected: 26+ tests collected

## Suggested Review Order

**Durability persistence (R-001)**

- Entry point: save_result failure → mark_failed zombie guard
  [`test_p0_durability.py:130`](../../server/backend/tests/test_p0_durability.py#L130)

- WS disconnect simulation with save-before-deliver proof
  [`test_p0_durability.py:196`](../../server/backend/tests/test_p0_durability.py#L196)

- Double-failure resilience: both save_result and mark_failed raise
  [`test_p0_durability.py:237`](../../server/backend/tests/test_p0_durability.py#L237)

- Large result reference delivery (>1MB → result_ready, not final)
  [`test_p0_durability.py:269`](../../server/backend/tests/test_p0_durability.py#L269)

- Audio persistence ordering — file exists before STT called
  [`test_p0_durability.py:314`](../../server/backend/tests/test_p0_durability.py#L314)

- Orphan recovery with audio/without/missing file variants
  [`test_p0_durability.py:357`](../../server/backend/tests/test_p0_durability.py#L357)

- Periodic sweep is_busy guard via mocked asyncio.sleep loop
  [`test_p0_durability.py:468`](../../server/backend/tests/test_p0_durability.py#L468)

**Model swap recovery (R-003)**

- CancelledError during shared backend → reattach via finally
  [`test_p0_model_swap.py:75`](../../server/backend/tests/test_p0_model_swap.py#L75)

- Engine start failure → stop then restore ordering
  [`test_p0_model_swap.py:137`](../../server/backend/tests/test_p0_model_swap.py#L137)

- 5 rapid start/stop cycles — call-count invariants
  [`test_p0_model_swap.py:226`](../../server/backend/tests/test_p0_model_swap.py#L226)

**Live mode history (R-002)**

- Push 60 sentences, retain last 50 — boundary assertion
  [`test_p0_live_mode.py:45`](../../server/backend/tests/test_p0_live_mode.py#L45)

- Session loss clears history, allows fresh accumulation
  [`test_p0_live_mode.py:102`](../../server/backend/tests/test_p0_live_mode.py#L102)

**Config**

- Pytest marker registration (p0, p1, durability, live_mode, model_swap)
  [`pyproject.toml:94`](../../server/backend/pyproject.toml#L94)
