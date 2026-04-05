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
---

# Test Design for QA: TranscriptionSuite

**Purpose:** Test execution recipe. Defines what to test, how to test it, and what's needed from other teams.

**Date:** 2026-04-05
**Author:** TEA Master Test Architect
**Status:** Draft
**Project:** TranscriptionSuite

**Related:** See Architecture doc (`test-design-architecture.md`) for testability concerns and architectural blockers.

---

## Executive Summary

**Scope:** System-level test design covering the full TranscriptionSuite stack — FastAPI server (10 STT backends, durability system, WebSocket protocols) and Electron dashboard (hooks, services, views, Docker lifecycle).

**Risk Summary:**

- Total Risks: 11 (3 high score >=6, 4 medium, 4 low)
- Critical Categories: DATA (3 risks), TECH (1 risk), BUS (1 risk), OPS (2 risks)

**Coverage Summary:**

- P0 tests: ~26 (durability, model swap, live mode)
- P1 tests: ~44 (frontend hooks, WS auth/service, Docker)
- P2 tests: ~45 (edge cases, views, routes, platform)
- P3 tests: ~9 (benchmarks, compliance)
- **Total:** ~124 new tests (~75–120 hours)

---

## Not in Scope

| Item | Reasoning | Mitigation |
|---|---|---|
| **E2E browser tests** | No E2E infrastructure established; Electron app complicates browser automation | Unit + integration tests cover critical paths; E2E deferred to future phase |
| **Real GPU inference tests** | CUDA/Metal/Vulkan not available in CI; heavy ML dependencies | torch_stub + lazy import stubs isolate backend logic; real GPU tests are manual |
| **Performance load testing** | No k6/locust infrastructure; single-user desktop app | P3 benchmarks deferred; single-user latency acceptable |

---

## Dependencies & Test Blockers

### Backend Code Fixes (Pre-Implementation)

**Source:** See Architecture doc "Quick Guide" for details

1. **R-001 fix: Add finally-block in websocket.py** — Backend
   - QA needs: `mark_failed()` guaranteed on any exception after `create_job()`
   - Blocks: All P0-DURA tests (persistence failure scenarios)

2. **R-003 fix: Add finally-block in live.py** — Backend
   - QA needs: `_restore_or_reload_main_model()` guaranteed on exception/disconnect
   - Blocks: All P0-SWAP tests (model swap interrupt scenarios)

### QA Infrastructure Setup

1. **Backend test patterns** — Use existing direct-call pattern from `test_transcription_durability_routes.py`
2. **Frontend hook test patterns** — Use `renderHook` from `@testing-library/react` with mocked WebSocket/IPC
3. **Tmp database fixture** — For integration tests that need real DB operations without polluting shared state

**Backend test pattern (existing):**

```python
# Direct-call route test pattern (from CLAUDE.md)
import importlib
import asyncio
import pytest
from server.api.routes import transcription

def test_durability_save_before_deliver(monkeypatch):
    """Verify result persisted before WebSocket delivery."""
    repo = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(transcription, "get_client_name", lambda _: "test-client")
    # ... test logic
```

**Frontend hook test pattern:**

```typescript
// Hook test with mocked WebSocket
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

describe('useTranscription', () => {
  it('transitions to processing on stop', async () => {
    const mockSocket = { send: vi.fn(), close: vi.fn() };
    // ... setup and assertions
  });
});
```

---

## Risk Assessment

**Full details in Architecture doc. Summarized for QA test planning.**

### High-Priority Risks (Score >=6)

| Risk ID | Category | Description | Score | QA Test Coverage |
|---|---|---|---|---|
| **R-001** | DATA | WS persistence failure creates zombie job | **6** | P0-DURA-001 through P0-DURA-007: persistence failure, WS disconnect, large result, orphan recovery |
| **R-002** | DATA | Live mode zero durability | **6** | P0-LIVE-001/002: history cap validation, known-limitation documentation test |
| **R-003** | TECH | Model swap disconnect orphans backend | **6** | P0-SWAP-001 through P0-SWAP-003: swap interrupt, failure recovery, rapid start/stop |

### Medium/Low-Priority Risks

| Risk ID | Category | Description | Score | QA Test Coverage |
|---|---|---|---|---|
| R-004 | BUS | Frontend state desync (18/20 hooks untested) | 4 | P1-HOOK-*: useTranscription + useLiveMode state machines |
| R-005 | OPS | Docker lifecycle (0 tests) | 4 | P1-DOCK-*: compose selection, runtime detection, event parsing |
| R-006 | DATA | Orphan recovery timestamp gap | 4 | P2-ORPH-*: fast re-crash, is_busy check |
| R-007 | SEC | WS auth untested | 3 | P1-WSAUTH-*: valid/expired/missing/invalid tokens |
| R-008 | OPS | Cross-platform breakage | 4 | P2-PLAT-*: Wayland, paste-at-cursor, MLX server |

---

## Entry Criteria

- [ ] R-001 code fix merged (finally-block in websocket.py)
- [ ] R-003 code fix merged (finally-block in live.py)
- [x] PM decision on R-002 — accepted as known limitation (2026-04-05)
- [ ] Existing 992 tests still passing
- [ ] Backend and frontend dev environments functional

## Exit Criteria

- [ ] All P0 tests passing (26 tests)
- [ ] All P1 tests passing or failures triaged (44 tests)
- [ ] No HIGH-risk paths left untested
- [ ] Backend core coverage >= 80%
- [ ] Frontend hooks/services coverage >= 60%

---

## Test Coverage Plan

**P0/P1/P2/P3 = priority and risk level, NOT execution timing. See Execution Strategy for when tests run.**

### P0 (Critical)

**Criteria:** Data integrity + security-critical paths that block core functionality. These protect the critical invariant: "AVOID DATA LOSS AT ALL COSTS."

| Test ID | Requirement | Test Level | Risk | Notes |
|---|---|---|---|---|
| **P0-DURA-001** | `save_result()` failure triggers `mark_failed()` | Unit | R-001 | 3 scenarios: DB error, serialization error, timeout |
| **P0-DURA-002** | WS disconnect during transcription: result already persisted | Integration | R-001 | Simulate close event mid-processing |
| **P0-DURA-003** | WS disconnect after `save_result()` failure: job marked failed | Integration | R-001 | Compound failure: DB fails then client disconnects |
| **P0-DURA-004** | Large result (>1MB): reference delivery + mark_delivered on fetch | Integration | R-009 | Verify HTTP fetch path calls mark_delivered() |
| **P0-DURA-005** | Audio file written BEFORE transcription begins (Wave 2) | Unit | R-001 | Assert file exists before STT backend called |
| **P0-DURA-006** | `recover_orphaned_jobs()` marks stale processing jobs as failed | Unit | R-006 | 3 scenarios: normal orphan, with audio, without audio |
| **P0-DURA-007** | Orphan sweep respects `is_busy()` on periodic runs | Unit | R-006 | Periodic sweep skips active job; startup sweep doesn't |
| **P0-SWAP-001** | Disconnect during model swap: main model restored | Integration | R-003 | Interrupt between unload_main and load_live |
| **P0-SWAP-002** | `start_engine()` failure: backend returned to main engine | Unit | R-003 | Engine init exception triggers finally-block |
| **P0-SWAP-003** | Rapid live start/stop: no backend leak, no stuck state | Integration | R-003 | 5 rapid cycles; assert model_manager healthy after |
| **P0-LIVE-001** | Sentence history cap: 50 max, oldest dropped | Unit | R-002 | Push 60 sentences, verify only last 50 retained |
| **P0-LIVE-002** | Session loss on disconnect: history cleared | Unit | R-002 | Validates known zero-durability limitation |

**Total P0:** ~26 tests (including multiple scenarios per ID)

---

### P1 (High)

**Criteria:** Core user journeys, frequently used features, integration points between systems.

| Test ID | Requirement | Test Level | Risk | Notes |
|---|---|---|---|---|
| **P1-HOOK-001** | useTranscription: state machine idle->connecting->recording->processing->complete | Unit | R-004 | 6 transition scenarios |
| **P1-HOOK-002** | useTranscription: unmount during polling cancels interval | Unit | R-004 | Verify no orphaned timers |
| **P1-HOOK-003** | useTranscription: cancel during processing -> clean state | Unit | R-004 | Ref cleanup verified |
| **P1-HOOK-004** | useLiveMode: state machine idle->connecting->starting->listening->idle | Unit | R-004 | 5 transition scenarios |
| **P1-HOOK-005** | useLiveMode: unmount during model swap -> no orphaned capture | Unit | R-004 | AudioCapture.stop() called |
| **P1-HOOK-006** | useLiveMode: sentence accumulation + partial buffering | Unit | R-004 | Sentences array grows; partials replaced |
| **P1-WSAUTH-001** | WS auth: valid token -> session starts | Unit | R-007 | Server returns auth_ok |
| **P1-WSAUTH-002** | WS auth: expired/missing/invalid token -> rejected | Unit | R-007 | 3 rejection scenarios |
| **P1-WS-001** | TranscriptionSocket: reconnect backoff 1s->2s->4s->30s max | Unit | R-004 | Timer progression verified |
| **P1-WS-002** | TranscriptionSocket: intentional disconnect prevents reconnect | Unit | R-004 | No reconnect attempts after .disconnect() |
| **P1-WS-003** | TranscriptionSocket: malformed JSON handling | Unit | R-004 | onError callback fires, no crash |
| **P1-WS-004** | Binary audio frame encoding/decoding | Unit | R-004 | Round-trip PCM Int16 |
| **P1-DOCK-001** | Compose file selection: Linux/VM/GPU/Vulkan/Podman | Unit | R-005 | 6 platform scenarios |
| **P1-DOCK-002** | Container runtime detection: Docker vs Podman | Unit | R-005 | 3 detection scenarios |
| **P1-DOCK-003** | Startup event parsing from JSONL | Unit | R-005 | All event types parsed |

**Total P1:** ~44 tests

---

### P2 (Medium)

**Criteria:** Secondary flows, edge cases, coverage hardening.

| Test ID | Requirement | Test Level | Risk | Notes |
|---|---|---|---|---|
| **P2-ORPH-001** | Orphan recovery: fast re-crash within timeout window | Unit | R-006 | Timestamp edge case |
| **P2-ORPH-002** | Startup recovery without is_busy check | Unit | R-006 | Differs from periodic sweep |
| **P2-PLAT-001** | Wayland shortcut registration/unregistration | Unit | R-008 | Mocked D-Bus |
| **P2-PLAT-002** | Paste-at-cursor (xdotool/AppleScript) | Unit | R-008 | Mocked child_process |
| **P2-PLAT-003** | MLX server manager lifecycle | Unit | R-008 | macOS bare-metal path |
| **P2-VIEW-001** | SessionView: renders with mock hooks | Component | R-004 | 4 state combinations |
| **P2-VIEW-002** | NotebookView: calendar interaction | Component | — | Recording list renders |
| **P2-VIEW-003** | ServerView: connection status display | Component | — | Status light states |
| **P2-ROUTE-001** | Notebook CRUD routes: full lifecycle | Unit | — | 8 endpoint tests |
| **P2-ROUTE-002** | LLM routes: status, summarize | Unit | — | 6 endpoint tests |
| **P2-ROUTE-003** | Admin config routes: PATCH config | Unit | — | 4 endpoint tests |
| **P2-HOOK-007** | useDocker: container state transitions | Unit | R-005 | IPC mocked |
| **P2-HOOK-008** | useAuthTokenSync: edge cases | Unit | — | Token parsing |

**Total P2:** ~45 tests

---

### P3 (Low)

**Criteria:** Benchmarks, exploratory, nice-to-have.

| Test ID | Requirement | Test Level | Notes |
|---|---|---|---|
| **P3-PERF-001** | Transcription latency per backend (small/medium/large) | Perf | Requires real GPU |
| **P3-PERF-002** | WS message throughput under sustained load | Perf | Requires server |
| **P3-PERF-003** | FTS5 search latency with 1000+ recordings | Perf | Synthetic data |
| **P3-OAPI-001** | OpenAI API format edge cases | Unit | Extend existing 16 tests |

**Total P3:** ~9 tests

---

## Execution Strategy

**Philosophy:** Run everything in PRs if under 15 minutes. Only defer if expensive or requires special infrastructure.

### Every PR: pytest + Vitest (~8 min)

**All functional tests:**

- Backend: `uv run pytest tests/ -v --tb=short` (~5 min with 804+ existing + new P0/P1 unit tests)
- Frontend: `npm test` (~1 min with 188+ existing + new P0/P1 unit tests)
- Total: ~8 min with parallelization

### Nightly: Integration Suite (~20 min)

**Tests requiring mocked async state:**

- P0 integration tests (WS disconnect, model swap interrupt)
- P2 component tests (views with mocked hooks)
- Full coverage report generation

### Weekly: Benchmarks + Platform (~45 min)

**Special infrastructure tests:**

- P3 performance benchmarks (if GPU CI available)
- Cross-platform matrix tests (if CI matrix established)

---

## QA Effort Estimate

| Priority | Count | Effort Range | Notes |
|---|---|---|---|
| P0 | ~26 | ~30–45 hours | Complex: async state, DB mocking, model lifecycle |
| P1 | ~44 | ~25–40 hours | Moderate: hook rendering, WS mocking, IPC mocking |
| P2 | ~45 | ~15–25 hours | Straightforward: route tests, component renders |
| P3 | ~9 | ~5–10 hours | Optional: benchmarks, compliance edge cases |
| **Total** | **~124** | **~75–120 hours** | **3–5 sprints at ~20–30 test hours/sprint** |

**Assumptions:**

- Includes test design, implementation, debugging, CI integration
- Excludes ongoing maintenance (~10% effort)
- Assumes backend code fixes for R-001/R-003 are merged first

---

## Implementation Planning Handoff

| Work Item | Owner | Dependencies |
|---|---|---|
| Fix R-001: finally-block in websocket.py | Backend | None — code fix |
| Fix R-003: finally-block in live.py | Backend | None — code fix |
| Decide R-002: live mode durability scope | PM + Backend | Architecture review |
| P0 durability tests (P0-DURA-*) | Test dev | R-001 fix merged |
| P0 model swap tests (P0-SWAP-*) | Test dev | R-003 fix merged |
| P1 frontend hook tests (P1-HOOK-*) | Test dev | None |
| P1 WS auth tests (P1-WSAUTH-*) | Test dev | None |
| P1 Docker lifecycle tests (P1-DOCK-*) | Test dev | None |
| P2/P3 tests | Test dev | P0/P1 complete |

---

## Interworking & Regression

| Component | Impact | Regression Scope | Validation |
|---|---|---|---|
| **server/api/routes/websocket.py** | R-001 code fix changes error handling | All existing WS-related tests | Run full backend suite after fix |
| **server/api/routes/live.py** | R-003 code fix changes model swap flow | `test_live_engine_config.py`, `test_live_mode_model_constraints.py` | Run live mode tests after fix |
| **dashboard/src/hooks/** | New tests add test infrastructure | All existing frontend tests | Run `npm test` after new tests |

**Regression strategy:** All 992 existing tests must pass before and after new test additions. CI enforces this via PR checks.

---

## Appendix A: Tagging Convention

**Backend (pytest markers):**

```python
@pytest.mark.p0
@pytest.mark.durability
def test_save_result_failure_marks_failed():
    ...

# Run by priority:
# uv run pytest tests/ -m p0
# uv run pytest tests/ -m "p0 or p1"
# uv run pytest tests/ -m durability
```

**Frontend (Vitest describe blocks):**

```typescript
describe('[P1] useTranscription', () => {
  it('transitions idle -> connecting on start()', () => { ... });
});

// Run by pattern:
// npm test -- --grep "P0"
// npm test -- --grep "P1"
```

---

## Appendix B: Knowledge Base References

- **Risk Governance:** `risk-governance.md` — Scoring methodology (P x I = 1–9)
- **Test Priorities:** `test-priorities-matrix.md` — P0–P3 criteria definitions
- **Test Levels:** `test-levels-framework.md` — Unit vs Integration vs E2E selection
- **Test Quality:** `test-quality.md` — DoD: no hard waits, <300 lines, <1.5 min, self-cleaning

---

**Generated by:** TEA Master Test Architect
**Workflow:** `bmad-testarch-test-design` (System-Level Mode)
