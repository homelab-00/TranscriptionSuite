---
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
lastSaved: '2026-04-05'
inputDocuments:
  - docs/project-overview.md
  - docs/architecture-server.md
  - docs/architecture-dashboard.md
  - docs/integration-architecture.md
  - docs/api-contracts-server.md
  - docs/data-models-server.md
  - docs/project-context.md
  - _bmad/tea/agents/bmad-tea/resources/knowledge/adr-quality-readiness-checklist.md
  - _bmad/tea/agents/bmad-tea/resources/knowledge/test-levels-framework.md
  - _bmad/tea/agents/bmad-tea/resources/knowledge/risk-governance.md
  - _bmad/tea/agents/bmad-tea/resources/knowledge/test-quality.md
---

# Test Design Progress

## Step 1: Detect Mode & Prerequisites

**Mode:** System-Level
**Rationale:** User requested full codebase review; no sprint-status.yaml; system-wide scope.

### Prerequisite Mapping

| Requirement | Source |
|---|---|
| PRD (functional + non-functional) | `docs/project-overview.md` (features, capabilities, metrics) |
| ADR / architecture decisions | `docs/project-context.md` (90 rules encoding decisions) |
| Architecture — Server | `docs/architecture-server.md` |
| Architecture — Dashboard | `docs/architecture-dashboard.md` |
| Integration Architecture | `docs/integration-architecture.md` |
| API Contracts | `docs/api-contracts-server.md` |
| Data Models | `docs/data-models-server.md` |

### Existing Test Baseline

- 804 backend tests, 45 test files (pytest)
- Frontend tests via Vitest
- Existing plans: `TESTING.md`, `TESTING_PLAN.md`, `TESTING_PLAN_STAGE-2.md`

## Step 2: Load Context & Knowledge Base

**Stack:** fullstack (Python 3.13/FastAPI + TypeScript 5.9/React 19/Electron 40)
**Config:** All TEA features disabled (no Playwright Utils, no Pact, no browser automation)

### Loaded Artifacts

- Project: project-overview, architecture-server, architecture-dashboard, integration-architecture, api-contracts-server, data-models-server
- Knowledge: adr-quality-readiness-checklist, test-levels-framework, risk-governance, test-quality

### Current Test Inventory

- Backend: 48 files, 804+ tests (pytest)
- Frontend: 6 files, 188 tests (Vitest)
- Total: 54 files, ~992 tests

### Identified Coverage Gaps (Pre-Risk Assessment)

- No frontend tests for views, most hooks (18/20), or services (websocket, audioCapture)
- No E2E tests
- No WebSocket protocol tests
- No integration tests for server↔dashboard communication

## Step 3: Testability & Risk Assessment

### HIGH Risks (Score ≥6)

| ID | Risk | Cat | P×I | Mitigation |
|---|---|---|---|---|
| R-001 | WS transcription data loss on persistence failure (zombie jobs) | DATA | 2×3=6 | WS disconnect + persistence failure tests |
| R-002 | Live mode zero durability (session lost on crash) | DATA | 2×3=6 | Sentence persistence tests; document limitation |
| R-003 | Model swap orphaned backend (server loses main model) | TECH | 2×3=6 | Model swap interrupt/recovery tests |

### MEDIUM Risks (Score 4)

| ID | Risk | Cat | P×I | Mitigation |
|---|---|---|---|---|
| R-004 | Frontend state desync (18/20 hooks untested) | BUS | 2×2=4 | Hook tests for useTranscription, useLiveMode |
| R-005 | Docker lifecycle failure (2480-line module, 0 tests) | OPS | 2×2=4 | Compose file selection unit tests |
| R-006 | Orphan recovery timestamp gap | DATA | 2×2=4 | Orphan sweep edge case tests |
| R-008 | Cross-platform breakage (Wayland, macOS MLX) | OPS | 2×2=4 | Platform-specific unit tests |

### ASRs Identified

- ASR-1: Data Durability (ACTIONABLE, P0)
- ASR-2: Single Model GPU constraint (ACTIONABLE, P0)
- ASR-3: 10 Interchangeable STT Backends (FYI, well-tested)
- ASR-4: 3-Tier State Management (ACTIONABLE, P1)
- ASR-5: WebSocket Auth (ACTIONABLE, P1)
- ASR-6: Durability 3-Wave System (ACTIONABLE, P0)

### NFR Assessment: 15/29 criteria met (52%), ⚠️ CONCERNS
Excluding N/A items (desktop app): 15/22 (68%)

## Step 4: Coverage Plan & Execution Strategy

### New Tests Summary: ~124 tests across 4 priority tiers

| Priority | Tests | Focus |
|---|---|---|
| P0 (26) | Durability, model swap, live mode | Protect critical invariant |
| P1 (44) | Frontend hooks, WS auth/service, Docker | Core user journeys |
| P2 (45) | Edge cases, views, routes, platform | Coverage hardening |
| P3 (9) | Perf benchmarks, compliance | Nice-to-have |

### Execution: PR (<8 min) / Nightly (<20 min) / Weekly (<45 min)

### Quality Gates
- P0: 100% pass | P1: ≥95% | P2: ≥90%
- Backend core: ≥80% coverage | Frontend hooks: ≥60%
- HIGH risks (R-001/R-002/R-003): ≥1 integration test each before next release

## Step 5: Generate Outputs

### Output Files Generated

| Document | Path |
|---|---|
| Architecture Test Design | `docs/testing/test-design-architecture.md` |
| QA Test Design | `docs/testing/test-design-qa.md` |
| BMAD Handoff | `docs/testing/test-design/TranscriptionSuite-handoff.md` |
| Progress Tracker | `docs/testing/test-design-progress.md` (this file) |

### Workflow Complete
- Mode: System-Level
- Execution: Sequential (no TEA config, auto-resolved)
- All 5 steps completed successfully
