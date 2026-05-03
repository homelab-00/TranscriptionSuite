---
title: 'Implement P2 test suite — coverage hardening'
type: 'chore'
created: '2026-04-05'
status: 'done'
baseline_commit: '222e925'
context: ['docs/testing/test-design-qa.md', 'docs/TESTING.md', 'docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** P2 tests (~45 tests across 13 test IDs) are defined in the test design but unimplemented. These cover secondary flows, edge cases, and route-level coverage — orphan recovery edge cases, notebook/LLM/admin API routes, platform utilities (Wayland, paste-at-cursor, MLX), view component rendering, and remaining hook coverage.

**Approach:** Implement all P2 tests using existing patterns — direct-call pattern for backend routes (pytest), renderHook + vi.mock for frontend hooks/views (Vitest). Split into backend and frontend work streams for parallel execution.

## Boundaries & Constraints

**Always:**
- Follow `[P2]` describe-block tagging convention from test design Appendix A
- Use direct-call pattern (monkeypatch, no HTTP server) for backend route tests
- Use renderHook with mocked IPC/hooks for frontend tests
- Each test file < 300 lines (test quality standard)
- All existing 992+ tests must remain passing

**Ask First:**
- If a route handler requires structural changes to become testable
- If a platform utility has no viable mock strategy (e.g., D-Bus in jsdom)

**Never:**
- Real GPU inference, real Docker, real D-Bus connections in tests
- Modify production code to make tests pass (test the code as-is)
- Skip platform tests just because they target non-current OS

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Orphan fast re-crash | Job created_at = now - (timeout - 1min) | NOT marked as orphan (within window) | N/A |
| Orphan startup vs periodic | Startup sweep with active job | Startup: marks failed anyway; Periodic: skips | N/A |
| Notebook CRUD 404 | GET /recordings/999 | HTTPException 404 | Caught by test |
| LLM status unreachable | httpx.ConnectError on /api/v0/models | available=false, error message | Error field set |
| Admin PATCH empty | {"updates": {}} | 400 Bad Request | Validation error |
| Wayland init fail | D-Bus proxy throws | initWaylandShortcuts returns false | Cleanup called |
| Paste-at-cursor no tool | All paste tools missing | Error thrown with guidance | Platform-specific msg |
| MLX server crash | Child process exit code 1 | status='error', logs captured | Error state emitted |
| SessionView idle | useTranscription returns idle state | Renders start button, no waveform | N/A |
| useDocker no runtime | docker.available() returns false | available=false, guidance shown | Detection guidance |

</frozen-after-approval>

## Code Map

**Backend targets:**
- `server/backend/api/main.py` -- recover_orphaned_jobs(), periodic_orphan_sweep()
- `server/backend/database/job_repository.py` -- get_orphaned_jobs()
- `server/backend/api/routes/notebook.py` -- 15 CRUD endpoints
- `server/backend/api/routes/llm.py` -- 5 LLM endpoints
- `server/backend/api/routes/admin.py` -- 8 admin endpoints

**Frontend targets:**
- `dashboard/electron/waylandShortcuts.ts` -- D-Bus portal shortcuts
- `dashboard/electron/pasteAtCursor.ts` -- cross-platform paste
- `dashboard/electron/mlxServerManager.ts` -- macOS MLX lifecycle
- `dashboard/components/views/SessionView.tsx` -- main session UI
- `dashboard/components/views/NotebookView.tsx` -- recordings + calendar
- `dashboard/components/views/ServerView.tsx` -- connection status
- `dashboard/src/hooks/useDocker.ts` -- container state machine
- `dashboard/src/hooks/useAuthTokenSync.ts` -- token detection edge cases

**Test files to create:**
- `server/backend/tests/test_p2_orphan_recovery.py`
- `server/backend/tests/test_p2_notebook_routes.py`
- `server/backend/tests/test_p2_llm_routes.py`
- `server/backend/tests/test_p2_admin_routes.py`
- `dashboard/electron/__tests__/waylandShortcuts.test.ts`
- `dashboard/electron/__tests__/pasteAtCursor.test.ts`
- `dashboard/electron/__tests__/mlxServerManager.test.ts`
- `dashboard/components/__tests__/SessionView.test.tsx`
- `dashboard/components/__tests__/NotebookView.test.tsx`
- `dashboard/components/__tests__/ServerView.test.tsx`
- `dashboard/src/hooks/__tests__/useDocker.test.ts`
- `dashboard/src/hooks/__tests__/useAuthTokenSync.test.ts`

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/tests/test_p2_orphan_recovery.py` -- P2-ORPH-001/002: fast re-crash timestamp edge case + startup-vs-periodic is_busy difference
- [x] `server/backend/tests/test_p2_notebook_routes.py` -- P2-ROUTE-001: 8 notebook CRUD tests (list, detail, delete, update title/summary/date, calendar, export)
- [x] `server/backend/tests/test_p2_llm_routes.py` -- P2-ROUTE-002: 6 LLM route tests (status available/unavailable, process success/error, model list, load)
- [x] `server/backend/tests/test_p2_admin_routes.py` -- P2-ROUTE-003: 4 admin config tests (PATCH valid/empty/missing, GET full config)
- [x] `dashboard/electron/__tests__/waylandShortcuts.test.ts` -- P2-PLAT-001: init success, init D-Bus failure, rebind, destroy cleanup
- [x] `dashboard/electron/__tests__/pasteAtCursor.test.ts` -- P2-PLAT-002: Linux wtype path, xdotool fallback, macOS osascript, no-tool error
- [x] `dashboard/electron/__tests__/mlxServerManager.test.ts` -- P2-PLAT-003: start lifecycle, crash→error, stop with SIGTERM, missing uvicorn
- [x] `dashboard/components/__tests__/SessionView.test.tsx` -- P2-VIEW-001: idle/recording/processing/complete renders with mocked hooks
- [x] `dashboard/components/__tests__/NotebookView.test.tsx` -- P2-VIEW-002: calendar renders, date click shows recordings
- [x] `dashboard/components/__tests__/ServerView.test.tsx` -- P2-VIEW-003: active/inactive/warning/error status light states
- [x] `dashboard/src/hooks/__tests__/useDocker.test.ts` -- P2-HOOK-007: container state transitions, runtime detection, operation error handling
- [x] `dashboard/src/hooks/__tests__/useAuthTokenSync.test.ts` -- P2-HOOK-008: non-Electron no-op, remote mode skip, stale token cleared on validation failure, network error retains token

**Acceptance Criteria:**
- Given all P2 tests written, when `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` runs, then all backend tests pass including new P2 tests
- Given all P2 tests written, when `cd dashboard && npx vitest run` runs, then all frontend tests pass including new P2 tests
- Given each test file, when inspected, then it uses `[P2]` tagging in describe blocks / pytest markers
- Given the full suite, when existing tests are re-run, then no regressions (all pre-existing tests still pass)

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_p2_*.py -v --tb=short` -- expected: all P2 backend tests pass
- `cd dashboard && npx vitest run --reporter=verbose` -- expected: all P2 frontend tests pass
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: full suite green, no regressions

## Suggested Review Order

**Orphan recovery edge cases**

- Timeout boundary + audio_path branch distinction
  [`test_p2_orphan_recovery.py:53`](../../server/backend/tests/test_p2_orphan_recovery.py#L53)

**Backend route tests**

- Notebook CRUD: 8 endpoints, direct-call pattern with DB monkeypatch
  [`test_p2_notebook_routes.py:72`](../../server/backend/tests/test_p2_notebook_routes.py#L72)

- LLM routes: fake httpx module with canned AsyncClient responses
  [`test_p2_llm_routes.py:70`](../../server/backend/tests/test_p2_llm_routes.py#L70)

- Admin config: PATCH validation + config tree retrieval
  [`test_p2_admin_routes.py:57`](../../server/backend/tests/test_p2_admin_routes.py#L57)

**Platform utilities**

- Wayland shortcuts: pure XDG↔Electron format conversion functions
  [`waylandShortcuts.test.ts:1`](../../dashboard/electron/__tests__/waylandShortcuts.test.ts#L1)

- Paste-at-cursor: clipboard write/restore with mocked child_process
  [`pasteAtCursor.test.ts:68`](../../dashboard/electron/__tests__/pasteAtCursor.test.ts#L68)

- MLX server: lifecycle state machine with mocked child process spawn
  [`mlxServerManager.test.ts:1`](../../dashboard/electron/__tests__/mlxServerManager.test.ts#L1)

**View component rendering**

- SessionView: 4 state combinations (idle/recording/processing/complete)
  [`SessionView.test.tsx:235`](../../dashboard/components/__tests__/SessionView.test.tsx#L235)

- NotebookView: calendar tab + import tab rendering
  [`NotebookView.test.tsx:147`](../../dashboard/components/__tests__/NotebookView.test.tsx#L147)

- ServerView: status light states + operation error display
  [`ServerView.test.tsx:1`](../../dashboard/components/__tests__/ServerView.test.tsx#L1)

**Hook edge cases**

- useDocker: container transitions, runtime detection, IPC error handling
  [`useDocker.test.ts:1`](../../dashboard/src/hooks/__tests__/useDocker.test.ts#L1)

- useAuthTokenSync: non-Electron no-op, remote skip, stale token clearing
  [`useAuthTokenSync.test.ts:73`](../../dashboard/src/hooks/__tests__/useAuthTokenSync.test.ts#L73)

**Infrastructure**

- Register p2 pytest marker to suppress warnings
  [`pyproject.toml:97`](../../server/backend/pyproject.toml#L97)
