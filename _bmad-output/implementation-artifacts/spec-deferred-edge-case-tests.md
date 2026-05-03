---
title: 'Deferred edge-case tests from P0/P2 review'
type: 'chore'
created: '2026-04-06'
status: 'done'
baseline_commit: 'fa7b67ba'
context: ['docs/TESTING.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Five edge-case test gaps were identified during P0/P2 code review but deferred as low-risk. They cover: a None-return fallback in model detach, empty job ID in orphan recovery, asymmetric date params in list_recordings, missing electronAPI guard in useDocker, and module-level cache preventing no-tool testing in pasteAtCursor.

**Approach:** Add targeted tests for each gap. For pasteAtCursor, expose a `_resetCommandCache()` test helper and add a "no tools" test using `vi.resetModules()`.

## Boundaries & Constraints

**Always:** Follow existing mock patterns in each test file. Run both backend and frontend test suites green before marking done.

**Ask First:** Any production code changes beyond the pasteAtCursor cache-reset export.

**Never:** Modify production behavior. Add tests only — no refactoring of the code under test.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Detach returns None | `can_share=True`, detach→None | Falls back to full unload, `_model_displaced=False` | Warning logged |
| Empty job ID | orphan row with `id=None` | `mark_failed("")` called, no crash | No-op UPDATE (0 rows) |
| Only start_date | `start_date="2026-01-01"`, no end_date | Date param silently ignored, returns all recordings | N/A |
| Only end_date | `end_date="2026-12-31"`, no start_date | Date param silently ignored, returns all recordings | N/A |
| No electronAPI | `window.electronAPI` undefined | Hook returns `loading=false`, all callbacks no-op | No error thrown |
| No paste tools | All `which` calls fail | `pasteAtCursor` throws descriptive error | Error message names installable tools |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/live.py:280-293` -- detach None fallback path
- `server/backend/core/model_manager.py:694-712` -- `detach_transcription_backend()`
- `server/backend/api/main.py:86-111` -- `recover_orphaned_jobs()` empty ID path
- `server/backend/api/routes/notebook.py:104-122` -- `list_recordings` date filtering
- `dashboard/src/hooks/useDocker.ts:116-143` -- electronAPI guard
- `dashboard/electron/pasteAtCursor.ts:19-32` -- `commandCache` + `hasCommand()`

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/tests/test_p0_model_swap.py` -- Add test: detach returns None → can_share fallback to full unload
- [x] `server/backend/tests/test_p2_orphan_recovery.py` -- Add test: orphan row with None/missing ID → mark_failed("") called
- [x] `server/backend/tests/test_p2_notebook_routes.py` -- Add 2 tests: only start_date provided, only end_date provided → returns all recordings
- [x] `dashboard/src/hooks/__tests__/useDocker.test.ts` -- Add test: no electronAPI on window → loading=false, callbacks no-op
- [x] `dashboard/electron/pasteAtCursor.ts` -- Export `_resetCommandCache()` test helper (guarded with `@internal` jsdoc)
- [x] `dashboard/electron/__tests__/pasteAtCursor.test.ts` -- Add test: all tools unavailable → throws descriptive error, using resetModules or cache reset

**Acceptance Criteria:**
- Given all new tests are added, when backend pytest suite runs, then all tests pass (0 failures)
- Given all new tests are added, when frontend vitest suite runs, then all tests pass (0 failures)
- Given pasteAtCursor cache reset is exported, when "no tools" test runs in isolation, then it correctly tests the fallback error path without cache bleed

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_p0_model_swap.py tests/test_p2_orphan_recovery.py tests/test_p2_notebook_routes.py -v --tb=short` -- expected: all pass
- `cd dashboard && npx vitest run src/hooks/__tests__/useDocker.test.ts electron/__tests__/pasteAtCursor.test.ts --reporter=verbose` -- expected: all pass

## Suggested Review Order

**Production change (only one)**

- Test-only cache reset export — enables isolated "no tools" testing
  [`pasteAtCursor.ts:21`](../../dashboard/electron/pasteAtCursor.ts#L21)

**Backend edge-case tests**

- Detach→None falls back to full unload + finally-block restore
  [`test_p0_model_swap.py:300`](../../server/backend/tests/test_p0_model_swap.py#L300)

- Missing vs explicit-None job ID — documents `dict.get` default semantics
  [`test_p2_orphan_recovery.py:101`](../../server/backend/tests/test_p2_orphan_recovery.py#L101)

- Asymmetric date params silently ignored — verifies `get_all_recordings` fallthrough
  [`test_p2_notebook_routes.py:88`](../../server/backend/tests/test_p2_notebook_routes.py#L88)

**Frontend edge-case tests**

- No electronAPI guard — hook degrades gracefully in browser dev mode
  [`useDocker.test.ts:128`](../../dashboard/src/hooks/__tests__/useDocker.test.ts#L128)

- No paste tools on Wayland/X11 — error message names installable tools
  [`pasteAtCursor.test.ts:118`](../../dashboard/electron/__tests__/pasteAtCursor.test.ts#L118)
