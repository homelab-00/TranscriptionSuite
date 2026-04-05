---
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
lastSaved: '2026-04-05'
workflowType: 'testarch-test-design'
inputDocuments:
  - docs/project-overview.md
  - docs/architecture-server.md
  - docs/architecture-dashboard.md
  - docs/integration-architecture.md
  - docs/api-contracts-server.md
  - docs/data-models-server.md
  - docs/project-context.md
---

# Test Design for Architecture: TranscriptionSuite

**Purpose:** Architectural concerns, testability gaps, and risk assessment for review by the development team. Serves as a contract on what must be addressed before new test development begins.

**Date:** 2026-04-05
**Author:** TEA Master Test Architect
**Status:** Architecture Review Pending
**Project:** TranscriptionSuite
**Architecture References:** `docs/architecture-server.md`, `docs/architecture-dashboard.md`, `docs/integration-architecture.md`

---

## Executive Summary

**Scope:** Full-system test design for TranscriptionSuite — a self-hosted GPU-accelerated STT platform (FastAPI server + Electron dashboard) with 10 STT backends, live mode, speaker diarization, and an audio notebook.

**Architecture:**

- **Layered backend:** API routes → Core engine (ModelManager, STT, Live, Diarization) → SQLite + FTS5
- **Desktop frontend:** Electron 40 main process (12 modules) + React 19 renderer (5 views, 20+ hooks)
- **Communication:** REST (~50 endpoints) + WebSocket (longform + live mode) over port 9786

**Risk Summary:**

- **Total risks:** 11
- **High-priority (score ≥6):** 3 risks requiring immediate mitigation — all threaten the critical invariant ("AVOID DATA LOSS AT ALL COSTS")
- **Test effort:** ~124 new tests (~75–120 hours)

---

## Quick Guide

### BLOCKERS — Must Address Before New Test Development

1. **R-001: WS persistence failure creates zombie jobs** — `save_result()` failure in `websocket.py` logs CRITICAL but continues; job stays in `processing` forever, undetectable by orphan recovery. Add finally-block to guarantee `mark_failed()`. (Owner: Backend)

2. **R-003: Model swap disconnect orphans backend** — Disconnect during `unload_main → load_live` in `live.py` leaves server without a loaded model; no finally-block to guarantee restoration. Add try/finally around engine start. (Owner: Backend)

### HIGH PRIORITY — Validate Recommendations

1. **R-002: Live mode has zero durability** — 50-sentence in-memory cap, no DB persistence. **Decision (2026-04-05): Accepted as known limitation.** Tests validate cap behavior only.

2. **R-006: Orphan recovery timestamp gap** — `recover_orphaned_jobs()` at startup doesn't check `is_busy()` (unlike periodic sweep). Fast re-crash within timeout window may miss jobs. Align startup and periodic recovery logic. (Owner: Backend)

### INFO ONLY — No Decisions Needed

1. **Test strategy:** ~85% unit / ~15% integration (no E2E infra yet)
2. **Frameworks:** pytest (backend), Vitest (frontend) — both already established
3. **Execution:** PR (<8 min) / Nightly (<20 min) / Weekly (<45 min)
4. **Coverage:** 124 new test scenarios prioritized P0–P3 with risk-based classification
5. **Existing baseline:** 992 tests across 54 files — STT backends well-covered

---

## Risk Assessment

**Total risks identified:** 11 (3 high, 4 medium, 4 low)

### High-Priority Risks (Score ≥6)

| Risk ID | Category | Description | P | I | Score | Mitigation | Owner | Timeline |
|---|---|---|---|---|---|---|---|---|
| **R-001** | **DATA** | WS transcription data loss: `save_result()` failure creates zombie job stuck in `processing`; no `mark_failed()` fallback | 2 | 3 | **6** | Add finally-block in WS handler; add persistence failure tests | Backend | Pre-release |
| **R-002** | **DATA** | Live mode zero durability: 50-sentence in-memory cap, all lost on crash/disconnect | 2 | 3 | **6** | Accepted as known limitation (2026-04-05) | N/A | N/A |
| **R-003** | **TECH** | Model swap orphaned backend: disconnect during `unload_main → load_live` leaves server without model | 2 | 3 | **6** | Add try/finally in `live.py` to guarantee backend restoration | Backend | Pre-release |

### Medium-Priority Risks (Score 3–5)

| Risk ID | Category | Description | P | I | Score | Mitigation | Owner |
|---|---|---|---|---|---|---|---|
| R-004 | BUS | Frontend state desync: 18/20 hooks untested; useTranscription dual state tracking | 2 | 2 | 4 | Add hook unit tests | Frontend |
| R-005 | OPS | Docker lifecycle: 2480-line dockerManager.ts with 0 tests; no timeout on startContainer | 2 | 2 | 4 | Extract/test compose file selection | Frontend |
| R-006 | DATA | Orphan recovery timestamp gap: startup recovery doesn't check is_busy() | 2 | 2 | 4 | Align startup and periodic sweep logic | Backend |
| R-008 | OPS | Cross-platform breakage: Wayland shortcuts, macOS MLX, Windows installer untested | 2 | 2 | 4 | Platform-specific unit tests | Frontend |

### Low-Priority Risks (Score 1–2)

| Risk ID | Category | Description | P | I | Score | Action |
|---|---|---|---|---|---|---|
| R-007 | SEC | WS auth: REST auth tested, WS first-message auth has zero tests | 1 | 3 | 3 | Add WS auth tests |
| R-009 | DATA | Large result (>1MB) delivery: HTTP fetch may not call mark_delivered() | 1 | 3 | 3 | Verify fetch path |
| R-010 | BUS | OpenAI API format deviation | 2 | 1 | 2 | Monitor (16 tests exist) |
| R-011 | BUS | Audio format compatibility | 2 | 1 | 2 | Monitor (73 tests exist) |

---

## Testability Concerns and Architectural Gaps

### Blockers to Fast Feedback

| Concern | Impact | What Must Be Provided | Owner | Timeline |
|---|---|---|---|---|
| **No finally-block in WS transcription handler** | Zombie jobs on DB write failure; untestable recovery | Add `try/finally` guaranteeing `mark_failed()` on any exception after `create_job()` | Backend | Pre-release |
| **No finally-block in live mode engine start** | Orphaned backend on disconnect during model swap | Add `try/finally` in `live.py:start_engine()` guaranteeing `_restore_or_reload_main_model()` | Backend | Pre-release |
| **Global `apiClient` singleton in websocket.ts** | Cannot inject test tokens; WS auth untestable in isolation | Accept token as constructor parameter or hook argument | Frontend | P1 |

### Architectural Improvements Needed

1. **WebSocket message logging for test replay**
   - **Current:** WS messages not structurally logged
   - **Change needed:** Add structured log entries for WS auth, start, stop, result events
   - **Impact if not fixed:** Cannot reproduce test failures from logs
   - **Owner:** Backend | **Timeline:** P2

2. **`startContainer()` needs timeout**
   - **Current:** Waits indefinitely for "Server started" event
   - **Change needed:** Add configurable timeout (default: 300s) with error escalation
   - **Impact if not fixed:** Tests hang on Docker failure, CI pipeline blocks
   - **Owner:** Frontend | **Timeline:** P1

---

### Testability Assessment Summary

#### What Works Well

- Backend uses layered architecture with abstract `STTBackend` base class — all 10 backends are independently testable via factory pattern
- Direct-call route testing pattern avoids full HTTP server lifecycle — fast, isolated tests
- `conftest.py` provides mature shared fixtures (torch_stub, _TestTokenStore, tmp config)
- Pydantic schemas validate all API inputs — boundary validation is automatic
- Durability system's job state machine is well-defined (create → save → deliver), just needs more test coverage
- Frontend model capabilities/selection logic has 114 tests — the most critical frontend path

#### Accepted Trade-offs (No Action Required)

- **No E2E test infrastructure** — desktop Electron app makes browser automation non-trivial; unit + integration coverage is adequate for current maturity
- **GPU operations untestable in CI** — ML backends use lazy imports and torch_stub for test isolation; real GPU tests are manual
- **Single SQLite DB** — no per-test DB isolation; acceptable for unit tests using monkeypatch, but integration tests should use tmp databases

---

## Risk Mitigation Plans (High-Priority ≥6)

### R-001: WS Transcription Data Loss (Score: 6)

**Strategy:**
1. Add `try/finally` block in `websocket.py` transcription handler to guarantee `mark_failed()` on any exception after `create_job()`
2. Verify that `GET /api/transcribe/result/{job_id}` calls `mark_delivered()` (large result path)
3. Add integration tests for: persistence failure → job marked failed; WS disconnect mid-transcription → result persisted

**Owner:** Backend
**Timeline:** Pre-release
**Status:** Planned
**Verification:** Test suite passes all P0-DURA-* scenarios; no zombie jobs in test runs

### R-003: Model Swap Orphaned Backend (Score: 6)

**Strategy:**
1. Add `try/finally` in `live.py:start_engine()` to guarantee `_restore_or_reload_main_model()` runs even on exception/disconnect
2. Add timeout to engine thread join (currently 5s — verify it works)
3. Add integration tests for: disconnect during model swap → main model restored; rapid start/stop → no backend leak

**Owner:** Backend
**Timeline:** Pre-release
**Status:** Planned
**Verification:** After any live mode test, verify `model_manager` has a loaded model

### R-002: Live Mode Zero Durability (Score: 6)

**Strategy:**
1. **PM decision required:** Accept as known limitation (document in user-facing docs), OR implement sentence persistence to DB
2. If accepted: Add unit tests verifying history cap behavior and documenting loss on disconnect
3. If implementing persistence: Design sentence table, add Wave 1 integration tests

**Owner:** Backend + PM
**Timeline:** N/A — accepted as known limitation
**Status:** Decision made: zero-durability accepted (2026-04-05)
**Verification:** If accepted, tests validate known-limitation behavior; if implemented, tests validate sentence persistence

---

## Assumptions and Dependencies

### Assumptions

1. Test development uses existing pytest/Vitest infrastructure — no new framework adoption required
2. GPU-dependent tests remain manual; CI tests use lazy import stubs
3. Desktop app context: SLA, multi-region failover, and zero-downtime deployment are N/A

### Dependencies

1. **R-001 code fix** (finally-block in websocket.py) — required before P0 durability tests can pass
2. **R-003 code fix** (finally-block in live.py) — required before P0 model swap tests can pass
3. **PM decision on R-002** (live mode durability) — determines scope of P0-LIVE tests

### Risks to Plan

- **Risk:** Backend fixes for R-001/R-003 may change API behavior
  - **Impact:** P0 integration tests need to track code changes
  - **Contingency:** Write tests against expected behavior; update if implementation differs

---

**Next Steps for Development Team:**

1. Review Quick Guide — prioritize the 2 BLOCKER code fixes (R-001, R-003)
2. Make PM decision on R-002 (live mode durability scope)
3. Assign owners and timelines for medium-priority risks

**Next Steps for Test Development:**

1. Refer to companion QA doc (`test-design-qa.md`) for test scenarios and implementation guidance
2. Begin P0 test development once blocker code fixes are merged
