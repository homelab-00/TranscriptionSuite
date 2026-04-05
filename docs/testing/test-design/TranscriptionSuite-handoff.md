---
title: 'TEA Test Design -> BMAD Handoff Document'
version: '1.0'
workflowType: 'testarch-test-design-handoff'
inputDocuments:
  - docs/testing/test-design-architecture.md
  - docs/testing/test-design-qa.md
sourceWorkflow: 'testarch-test-design'
generatedBy: 'TEA Master Test Architect'
generatedAt: '2026-04-05'
projectName: 'TranscriptionSuite'
---

# TEA -> BMAD Integration Handoff

## Purpose

This document bridges TEA's test design outputs with BMAD's epic/story decomposition workflow. It provides structured integration guidance so that quality requirements, risk assessments, and test strategies flow into implementation planning.

## TEA Artifacts Inventory

| Artifact | Path | BMAD Integration Point |
|---|---|---|
| Architecture Test Design | `docs/testing/test-design-architecture.md` | Epic quality requirements, blocker identification |
| QA Test Design | `docs/testing/test-design-qa.md` | Story acceptance criteria, test scenarios |
| Risk Assessment | Embedded in architecture doc | Epic risk classification, story priority |
| Coverage Strategy | Embedded in QA doc (124 tests, P0-P3) | Story test requirements |
| Progress Tracker | `docs/testing/test-design-progress.md` | Workflow state |

## Epic-Level Integration Guidance

### Risk References

The following HIGH risks (score >=6) should appear as epic-level quality gates:

| Risk ID | Category | Score | Epic Gate |
|---|---|---|---|
| R-001 | DATA | 6 | No release without P0-DURA tests passing: WS persistence failure must trigger mark_failed() |
| R-002 | DATA | 6 | PM decision required: accept live mode zero-durability or implement sentence persistence |
| R-003 | TECH | 6 | No release without P0-SWAP tests passing: model swap must guarantee backend restoration |

### Quality Gates

| Epic Scope | Gate Criteria |
|---|---|
| Server durability improvements | All P0-DURA-* tests pass (26 tests); no zombie job paths untested |
| Frontend hook coverage | P1-HOOK-* tests pass; useTranscription + useLiveMode state machines validated |
| Docker lifecycle reliability | P1-DOCK-* tests pass; compose file selection covers all platforms |

## Story-Level Integration Guidance

### P0/P1 Test Scenarios -> Story Acceptance Criteria

These critical test scenarios MUST be acceptance criteria in their corresponding stories:

| Scenario | Acceptance Criterion |
|---|---|
| P0-DURA-001 | Given a DB write failure during save_result(), when the WS handler catches the exception, then the job must be marked as `failed` (not left in `processing`) |
| P0-DURA-002 | Given a client WS disconnect during transcription, when the server completes STT processing, then the result must already be persisted in the jobs table |
| P0-SWAP-001 | Given a client disconnect during live mode model swap, when the engine start is interrupted, then the main transcription model must be restored |
| P0-SWAP-003 | Given 5 rapid live mode start/stop cycles, when the model manager is queried, then exactly one model is loaded and no backends are orphaned |
| P1-WSAUTH-002 | Given a WS connection with an expired/missing/invalid token, when the auth message is processed, then the server rejects the session |

### Data-TestId Requirements

Not applicable — TranscriptionSuite is a desktop Electron app, not a web application. Backend tests use the direct-call pattern; frontend tests mock hooks. No `data-testid` attributes are recommended at this time.

## Risk-to-Story Mapping

| Risk ID | Category | P x I | Recommended Story/Epic | Test Level |
|---|---|---|---|---|
| R-001 | DATA | 2x3=6 | Epic: Server Durability Hardening | Integration |
| R-002 | DATA | 2x3=6 | Epic: Live Mode Improvements (PM decision) | Unit |
| R-003 | TECH | 2x3=6 | Epic: Server Durability Hardening | Integration |
| R-004 | BUS | 2x2=4 | Epic: Frontend Test Coverage | Unit |
| R-005 | OPS | 2x2=4 | Epic: Dashboard Reliability | Unit |
| R-006 | DATA | 2x2=4 | Epic: Server Durability Hardening | Unit |
| R-007 | SEC | 1x3=3 | Story: WS Auth Tests (within Frontend Coverage) | Unit |
| R-008 | OPS | 2x2=4 | Epic: Dashboard Reliability | Unit |

## Recommended BMAD -> TEA Workflow Sequence

1. **TEA Test Design** (this workflow) -> produces this handoff document
2. **BMAD Create Epics & Stories** -> consumes this handoff, embeds quality requirements
3. **TEA ATDD** -> generates acceptance tests per story (start with P0 scenarios)
4. **Implementation** -> developers fix R-001/R-003, implement tests
5. **TEA Trace** -> validates coverage completeness against risk register

## Phase Transition Quality Gates

| From Phase | To Phase | Gate Criteria |
|---|---|---|
| Test Design | Epic/Story Creation | All P0 risks have mitigation strategy (done) |
| Epic/Story Creation | ATDD | Stories have acceptance criteria from test design |
| ATDD | Implementation | Failing acceptance tests exist for all P0 scenarios |
| Implementation | Test Complete | All P0/P1 tests pass; no HIGH-risk paths untested |
| Test Complete | Release | Backend core >=80% coverage; 992 existing + 124 new tests green |
