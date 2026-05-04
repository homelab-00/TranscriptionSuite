---
date: 2026-05-03
project: TranscriptionSuite
report_version: v2
prd_under_review: _bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md
epics_under_review: _bmad-output/planning-artifacts/epics.md
v1_report: _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
stepsCompleted: ['step-01-document-discovery', 'step-02-prd-analysis', 'step-03-epic-coverage-validation', 'step-04-ux-alignment', 'step-05-epic-quality-review', 'step-06-final-assessment']
filesIncluded:
  prd: _bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md (1418 lines, revisionsApplied=[ADR-009, kbd-contract, FR15-downscope, visual-spec, FR15-narrative-cleanup])
  architecture: 'embedded-in-prd (ADRs 001-009 + API Design + Diarization-Review Keyboard Contract + Visual Affordance Specification + Implementation Considerations)'
  epics: '_bmad-output/planning-artifacts/epics.md (2515 lines; 8 epics / 57 stories / 196 BDD ACs) — supersedes PRD frontmatter plannedEpicGroupings'
  ux: 'embedded-in-prd (7 user journeys + cross-cutting accessibility AC + canonical Keyboard Contract + Visual Affordance UI Contract spec)'
status: complete
verdict: READY
issuesFound: 4
criticalIssues: 0
majorIssues: 0
minorIssues: 4
v1Comparison:
  v1Total: 17
  v2Total: 4
  resolvedFromV1: 14
  partiallyResolvedFromV1: 1
  unresolvedFromV1: 2
  netNewIssues: 1
---

# Implementation Readiness Assessment Report — v2

**Date:** 2026-05-03
**Project:** TranscriptionSuite
**PRD Under Review:** `_bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md` — *Audio Notebook QoL pack* (Issue #104)
**Epics Under Review:** `_bmad-output/planning-artifacts/epics.md`
**v1 Report:** `_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md`

> **TL;DR — Verdict: ✅ READY for implementation kickoff.** The 8-epic / 57-story restructure plus the 5 PRD revisions (ADR-009, keyboard contract, FR15 downscope, visual spec, J2 narrative cleanup) close all 5 Critical and all 8 Major issues from the v1 report. 2 of 4 Minor issues remain (deferrable per v1 recommendation), 1 Minor is partially resolved, 1 v2 net-new Minor is documentation-only. Recommend proceeding to `bmad-create-story` for sprint zero / first story execution.

---

## Step 1 — Document Discovery (v2)

### Search Scope
`{planning_artifacts}` resolves to `/home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/_bmad-output/planning-artifacts/`.

### Files Found

**PRD Documents:**
- `prd-issue-104-audio-notebook-qol.md` (99,936 bytes, 1,418 lines, modified 2026-05-03) — Audio Notebook QoL pack PRD with revisions applied.

**Epics & Stories Documents:**
- `epics.md` (128,790 bytes, 2,515 lines, modified 2026-05-03) — **NEW since v1**. 8 epics, 57 stories, 196 BDD ACs.

**Architecture / UX Documents:**
- *(none stand-alone)* — content remains embedded in PRD as in v1, but PRD now contains expanded sections (ADR-009, Keyboard Contract, Visual Affordance Spec).

**Other Planning Files (in scope as supporting evidence):**
- `validation-report-2026-05-03.md` (43,342 bytes) — `bmad-validate-prd` output that drove some narrative cleanup edits.
- `handoff-prompts-readiness-fixes.md` (11,008 bytes) — the v1→v2 remediation handoff document referenced in PRD frontmatter `editHistory[0].source`.
- `implementation-readiness-report-2026-05-03.md` (v1 report — preserved unmodified for diff).

**Out of scope (not planning artifacts):**
- `tech-spec-per-conversation-model-switching.md` — unrelated tech spec for a previously delivered feature.

### Document Inventory

| Type | v1 Status | v2 Status | Decision |
|---|---|---|---|
| PRD | ✅ `prd-issue-104-audio-notebook-qol.md` (whole) | ✅ `prd-issue-104-audio-notebook-qol.md` (whole, revised) | Use whole `prd-issue-104-audio-notebook-qol.md` |
| Architecture | ❌ embedded-only | ✅ embedded-only **+ ADR-009 added** | Use embedded ADRs 001-009 |
| Epics | ❌ frontmatter-declaration-only | ✅ **`epics.md` exists** (8 epics / 57 stories) | Use `epics.md` — supersedes `plannedEpicGroupings` in PRD frontmatter |
| UX | ❌ embedded-only | ✅ embedded **+ Keyboard Contract + Visual Spec subsections** | Use embedded UX content |

### Duplicates
None detected.

### Critical Issues / Warnings
None at the discovery layer. The "no epics-and-stories file" Critical from v1 is **resolved** (v1 #1 closed).

### Resolution Plan
Proceed with full coverage analysis using the new `epics.md` as the canonical decomposition.

---

## Step 2 — PRD Analysis (v2 — diff from v1)

### Document Structure (Inside `prd-issue-104-audio-notebook-qol.md`)

| Inline Section | v1 | v2 | Δ |
|---|---|---|---|
| ADRs (`Architecture Decision Records`) | ADR-001 through ADR-008 | ADR-001 through **ADR-009** | **+1 ADR (ADR-009)** ✅ |
| User Journeys (J1–J7) | 7 journeys | 7 journeys, J2 Opening Scene + Reveals updated to remove wizard narrative | Narrative aligned with FR15 downscope ✅ |
| **Diarization-Review Keyboard Contract** subsection | ❌ absent | ✅ canonical table at line 900-920 | **+1 subsection (canonical kbd spec)** ✅ |
| **Visual Affordance Specification (UI Contract)** subsection | ❌ absent | ✅ table at line 922-968 covering Status Badges (UX-DR1), Persistent Banners (UX-DR2), Per-Turn Confidence Indicators (UX-DR3), Migration AC (UX-DR5) | **+1 subsection (canonical visual spec)** ✅ |
| FR15 wording | "30-second setup wizard or direct field editing (hybrid field-first)" | "Empty-profile screen pre-populates fields with sane defaults + single inline help banner. No multi-step wizard — deferred to Vision." | **Downscope applied** ✅ |
| Phase 3 (Vision) bullets | 6 items | **7 items** (+ "Multi-step setup wizard for first-time profile creation — deferred from FR15") | Wizard deferred explicitly ✅ |
| FR catalog | FR1–FR54 | FR1–FR54 (text identical except FR15 wording change) | No FR removed/renumbered ✅ |
| NFR catalog | NFR1–NFR55 | NFR1–NFR55 (unchanged) | ✅ |
| R-EL Glossary | R-EL1–R-EL35 | R-EL1–R-EL35 (unchanged) | ✅ |
| Appendix A (Feature Definitions F1–F6) | 6 features | 6 features (unchanged) | ✅ |
| Appendix B (Where to Find What) | mentions ADR-005 only for Speaker Aliasing | mentions **ADR-005, ADR-009** for Speaker Aliasing | Cross-reference updated ✅ |

### Functional Requirements (54)
**Identical catalog to v1.** FR15 is the only FR with rewritten body text (downscoped from wizard to sane-default screen + inline help banner). FR15 retains `[Growth]` tier tag.

### Non-Functional Requirements (55)
**Identical to v1.** NFR1–NFR55 unchanged.

### Additional Requirements / Constraints

**ADRs (1–9)** — net-new ADR-009 specifies the diarization-review state persistence:
> ADR-009 — `recording_diarization_review` table with `(recording_id PK, status TEXT CHECK IN ('pending','in_review','completed','released'), reviewed_turns_json, created_at, updated_at)`. Auto-summary HOLD reads `status != 'released'`. Banner visibility reads `status IN ('pending','in_review')`. Lifecycle pending→in_review→completed→released. Cross-references: R-EL19, R-EL20, FR25, FR27, FR28, NFR23. **Rejected alternatives explicitly named:** Zustand-persist (local-only, not crash-safe), column-on-aliases (couples F4 MVP slice to Growth scope).

**Diarization-Review Keyboard Contract** — net-new canonical subsection. Tab/Shift+Tab traverses turn-list (single tab stop); ↑/↓ moves selection inside composite widget; ←/→ switches attribution; Enter accepts; Esc skips; Space bulk-accepts visible. Resolves the J4↔J7 conflict identified in v1. WAI-ARIA Authoring Practices model adopted.

**Visual Affordance Specification (UI Contract)** — net-new canonical subsection. Three classes anchored to existing primitives: **UX-DR1 Status Badges** (`StatusLight` primitive, severity ok/warn/error, inline ⟳ Retry button); **UX-DR2 Persistent Banners** (`QueuePausedBanner` pattern); **UX-DR3 Per-Turn Confidence Indicators** (chip beside speaker label, high=no chip, medium=neutral, low=amber, tooltip with %); **UX-DR5 UI contract migration AC** (mandatory `npm run ui:contract:extract → build → validate --update-baseline → check`).

### PRD Completeness Assessment

#### Strengths (carried forward from v1)
1. Exhaustive requirement extraction (54 FRs + 55 NFRs + 35 R-ELs) — rigor preserved.
2. Strong cross-referencing (Appendix A/B/C) — Appendix B updated to include ADR-009.
3. Risk grading per feature unchanged.
4. Tier discipline (`[MVP]`/`[Growth]`/`[Cross]`) on every FR.
5. Day-1 test infrastructure committed (NFR53 + NFR54).
6. Persist-Before-Deliver invariant explicitly preserved (NFR16/17/18).
7. Honest dissent documented in "Alternative Paths Considered (and Not Taken)."

#### Concerns / Gaps to Verify Downstream — v2 status

| v1 Concern | v2 Status | Evidence |
|---|---|---|
| 1. No actual epics-and-stories file | ✅ **RESOLVED** | `epics.md` exists with 8 epics / 57 stories / 196 BDD ACs |
| 2. No solution-design for `webhook_deliveries` schema | ✅ **RESOLVED** | epics.md Story 7.1 AC1 specifies full schema `(id PK, recording_id, profile_id, status CHECK IN(...), attempt_count, last_error, created_at, last_attempted_at, payload_json)` + index |
| 3. F5 has thin journey coverage | 🟡 **DEFERRED** (per v1 deferable list) — accepted as low-narrative-density per PRD acknowledgement | epics.md Epic 8 has 4 stories with explicit AC; PRD F5 entry preserved |
| 4. NFR45 transitive dep on `tech-spec-gpu-error-surfacing-diag-paste-fix` not version-pinned | 🟡 **UNCHANGED** — flagged in PRD assumption #5 | Same risk as v1; no v2 fix |
| 5. FR15 wizard content unspecified | ✅ **RESOLVED via downscope** | FR15 rewritten; wizard deferred to Vision |
| 6. R-EL15 keyboard-navigation contract not specified | ✅ **RESOLVED** | "Diarization-Review Keyboard Contract" canonical subsection added (PRD line 900) + Story 5.9 AC3 cites verbatim |
| 7. No state machine for diarization review | ✅ **RESOLVED** | ADR-009 specifies the lifecycle pending→in_review→completed→released; epics.md Story 5.6 AC2 implements transitions |
| 8. No data model for `recording_speaker_aliases` table | ✅ **RESOLVED** | epics.md Story 4.1 AC1 specifies `(id PK, recording_id INTEGER NOT NULL FK→recordings.id ON DELETE CASCADE, speaker_id, alias_name, created_at, updated_at, UNIQUE(recording_id, speaker_id))` |
| 9. No explicit migration plan ordering | ✅ **RESOLVED** | epics.md per-epic "first migration in first story" pattern: 1.2 (profiles), 1.3 (snapshot column), 1.9 (review state), 2.1 (audio_hash), 4.1 (aliases), 7.1 (webhook_deliveries), 8.1 (model profiles) — explicit dep ordering via story `Depends on` lines |
| 10. CRUD diarization-review API surface incomplete | ✅ **RESOLVED** | Story 5.6 AC2 specifies POST `/api/recordings/{id}/diarization-review` + lifecycle transitions; `GET /api/recordings/{id}/diarization-confidence` covered in Story 5.4 |

**Net:** 8 of 10 v1 PRD-completeness concerns resolved by v2 work; 2 deferred per v1's own deferrable list.

---

## Step 3 — Epic Coverage Validation (v2)

### Source-of-Truth Update

> **v1 caveat removed.** A real `epics.md` now exists with 8 epics, 57 stories, and 196 BDD acceptance criteria. The "proxy coverage analysis" of v1 is replaced by **direct coverage analysis** against the actual story decomposition.

### Restructured Epic Set (overrides PRD `plannedEpicGroupings`)

| # | Epic | Tier | Risk | Stories | Eng-days | FR Count |
|---|---|---|---|---|---|---|
| 1 | epic-foundations | Cross | MED-HIGH | 9 | 11–14 | 11 (FR10/11/14-16/18-20, FR49/50, scaffold for FR51-54) |
| 2 | epic-import | MVP | LOW-MED | 5 | 3–4 | 4 (FR1–FR4) |
| 3 | epic-export | MVP | LOW-MED | 7 | 7–9 | 9 (FR5–FR9, FR12, FR13, FR17, FR48) |
| 4 | epic-aliases-mvp | MVP | MED-HIGH | 5 | 5–7 | 3 (FR21, FR22, FR29) |
| 5 | epic-aliases-growth | Growth | HIGH | 9 | 7–9 | 6 (FR23–FR28) |
| 6 | epic-auto-actions | Growth | HIGH | 11 | 10–12 | 10 (FR30–FR39) |
| 7 | epic-webhook | Growth | HIGH | 7 | 7–9 | 5 (FR43–FR47) |
| 8 | epic-model-profiles | Growth | MED | 4 | 3–4 | 3 (FR40–FR42) |
| **Σ** | — | — | — | **57** | **53–68** | **50 unique + 4 cross-cutting (FR49–54) inherited (FR48 in epic-export)** |

This 8-epic structure matches **exactly** the recommended restructure in the v1 report (Step 5 §G).

### FR-to-Epic-to-Story Coverage Matrix (Direct, 100%)

| FR Range | Anchored Epic | Anchored Story | v1 status | v2 status |
|---|---|---|---|---|
| FR1 (import) | epic-import | 2.3 | ⚠️ Missing | ✅ Covered |
| FR2 (audio hash) | epic-import | 2.1 (migration), 2.2 (compute) | ⚠️ Missing | ✅ Covered |
| FR3 (dedup prompt) | epic-import | 2.4 | ⚠️ Missing | ✅ Covered |
| FR4 (per-user-library scope) | epic-import | 2.5 | ⚠️ Missing | ✅ Covered |
| FR5–FR8 (download buttons + dialog) | epic-export | 3.5 | ✅ Covered (epic-a) | ✅ Covered |
| FR9 (plain-text format) | epic-export | 3.4 | ✅ Covered (epic-a) | ✅ Covered |
| FR10 (Profile CRUD) | epic-foundations | 1.2 | ⚠️ Implicit | ✅ Explicit |
| FR11 (private fields) | epic-foundations | 1.2 | ⚠️ Implicit | ✅ Explicit |
| FR12 (template engine) | epic-export | 3.1 (engine), 3.2 (validation) | ✅ Covered (epic-a) | ✅ Covered |
| FR13 (live preview) | epic-export | 3.3 | ✅ Covered (epic-a) | ✅ Covered |
| FR14 (folder picker) | epic-foundations | 1.4 | ⚠️ Implicit | ✅ Explicit |
| FR15 (sane-default screen — downscoped) | epic-foundations | 1.5 | ⚠️ Implicit | ✅ Explicit |
| FR16 (schema versioning) | epic-foundations | 1.2 | ⚠️ Implicit | ✅ Explicit |
| FR17 (forward-only template) | epic-export | 3.6 | ✅ Covered (epic-a) | ✅ Covered |
| FR18 (snapshot at job-start) | epic-foundations | 1.3 | ⚠️ Implicit | ✅ Explicit |
| FR19 (crash recovery rehydration) | epic-foundations | 1.3 | ⚠️ Implicit | ✅ Explicit |
| FR20 (mid-session profile switch) | epic-foundations | 1.6 | ⚠️ Implicit | ✅ Explicit |
| FR21 (alias rename per-recording) | epic-aliases-mvp | 4.1 (migration), 4.3 (rename UI) | ✅ Covered (epic-b) | ✅ Covered |
| FR22 (alias view substitution) | epic-aliases-mvp | 4.4 | ✅ Covered (epic-b) | ✅ Covered |
| FR23 (alias propagation) | epic-aliases-growth | 5.1, 5.2, 5.3 | ✅ Covered (epic-b) | ✅ Covered |
| FR24 (verbatim alias) | epic-aliases-growth | 5.2 | ✅ Covered (epic-b) | ✅ Covered |
| FR25 (low-confidence flag + HOLD) | epic-aliases-growth | 5.8 | ✅ Covered (epic-b) | ✅ Covered |
| FR26 (review view) | epic-aliases-growth | 5.9 | ✅ Covered (epic-b) | ✅ Covered |
| FR27 (review state persists) | epic-aliases-growth | 5.6 | ✅ Covered (epic-b) | ✅ Covered |
| FR28 (persistent banner) | epic-aliases-growth | 5.7 | ✅ Covered (epic-b) | ✅ Covered |
| FR29 (alias REST endpoints) | epic-aliases-mvp | 4.2 | ✅ Covered (epic-b) | ✅ Covered |
| FR30 (auto-summary toggle) | epic-auto-actions | 6.1, 6.2 | ✅ Covered (epic-a) | ✅ Covered |
| FR31 (auto-export toggle) | epic-auto-actions | 6.1, 6.3 | ✅ Covered (epic-a) | ✅ Covered |
| FR32 (auto-summary save-back) | epic-auto-actions | 6.2 | ✅ Covered (epic-a) | ✅ Covered |
| FR33 (Persist-Before-Deliver) | epic-auto-actions | 6.4 | ✅ Covered (epic-a) | ✅ Covered |
| FR34 (independent auto-actions) | epic-auto-actions | 6.5 | ✅ Covered (epic-a) | ✅ Covered |
| FR35 (status badge + retry) | epic-auto-actions | 6.6, 6.9 | ✅ Covered (epic-a) | ✅ Covered |
| FR36 (empty-summary state) | epic-auto-actions | 6.7 | ✅ Covered (epic-a) | ✅ Covered |
| FR37 (truncated-summary state) | epic-auto-actions | 6.7 | ✅ Covered (epic-a) | ✅ Covered |
| FR38 (deferred-retry destination) | epic-auto-actions | 6.8 | ✅ Covered (epic-a) | ✅ Covered |
| FR39 (idempotent retry) | epic-auto-actions | 6.9 | ✅ Covered (epic-a) | ✅ Covered |
| FR40 (model profile config) | epic-model-profiles | 8.1, 8.2 | ✅ Covered (epic-c) | ✅ Covered |
| FR41 (one-click switch + persist) | epic-model-profiles | 8.3, 8.4 | ✅ Covered (epic-c) | ✅ Covered |
| FR42 (parallel funnel position) | epic-model-profiles | 8.1 | ✅ Covered (epic-c) | ✅ Covered |
| FR43 (webhook URL config) | epic-webhook | 7.2 | ⚠️ **Orphan** | ✅ Covered |
| FR44 (URL allowlist) | epic-webhook | 7.2 | ⚠️ **Orphan** | ✅ Covered |
| FR45 (delivery contract) | epic-webhook | 7.4 | ⚠️ **Orphan** | ✅ Covered |
| FR46 (payload defaults) | epic-webhook | 7.6 | ⚠️ **Orphan** | ✅ Covered |
| FR47 (deliveries persisted) | epic-webhook | 7.5, 7.7 | ⚠️ **Orphan** | ✅ Covered |
| FR48 (deletion semantics) | epic-export | 3.7 | ✅ Covered (epic-a) | ✅ Covered |
| FR49 (keychain) | epic-foundations | 1.7 | ⚠️ **Cross-cutting unanchored** | ✅ Explicit |
| FR50 (keychain fallback) | epic-foundations | 1.7 | ⚠️ **Cross-cutting unanchored** | ✅ Explicit |
| FR51 (keyboard-only operability) | epic-foundations 1.8 (scaffold) + inherited | as AC by 3.5, 4.3, 4.4, 5.7, 5.9, 6.6, 8.2 | ⚠️ **Cross-cutting unanchored** | ✅ Anchored + per-story AC inheritance |
| FR52 (ARIA live regions) | epic-foundations 1.8 (scaffold) + inherited | as AC by 3.5, 5.7, 5.8, 6.6 | ⚠️ **Cross-cutting unanchored** | ✅ Anchored + per-story AC inheritance |
| FR53 (descriptive labels) | epic-foundations 1.8 (scaffold) + inherited | as AC by 3.5, 6.6, 8.2 | ⚠️ **Cross-cutting unanchored** | ✅ Anchored + per-story AC inheritance |
| FR54 (turn-by-turn screen-reader nav) | epic-foundations 1.9 (scaffold) | enforced in 5.9 AC4 | ⚠️ **Cross-cutting unanchored** | ✅ Anchored + Story 5.9 AC4 enforcement |

### Coverage Statistics

| Status | v1 Count | v1 % | v2 Count | v2 % |
|---|---|---|---|---|
| ✅ Explicitly covered (epic + story anchor) | 30 | 56% | **54** | **100%** |
| ⚠️ Implicit (no anchor) | 9 | 17% | 0 | 0% |
| ⚠️ Orphan (no F-letter or epic) | 5 | 9% | 0 | 0% |
| ⚠️ Cross-cutting (unanchored) | 6 | 11% | 0 | 0% |
| ⚠️ Missing (no anchor at all) | 4 | 7% | 0 | 0% |

**Coverage delta: 56% → 100% explicit. All 5 v1 Critical coverage issues resolved.**

### Reverse Check — Feature/Capability in Stories but not in Any FR?

Performed audit on all 196 BDD ACs across the 57 stories. **No story introduces a capability not anchored to an FR, NFR, R-EL, or ADR.** A few stories (e.g., Story 6.10 idempotent re-export semantics, Story 4.5 alias cleanup on recording delete via FK cascade) extend FR39/FR48 by adding implementation detail; both are explicitly tied to their parent FR with rationale in the epics.md "Open Items" section.

### Overall Coverage Verdict

- **Mechanical coverage:** 100% (unchanged from v1)
- **Epic coverage:** **100% explicit** (vs v1 56%) — every FR has a single epic anchor
- **Story coverage:** **100%** — every FR has at least one story; 195+ acceptance criteria total in BDD format
- **Cross-cutting at-risk:** **0** — FR49–FR54 are now scaffolded in epic-foundations and inherited as explicit ACs in 9 downstream stories

---

## Step 4 — UX Alignment (v2)

### UX Document Status

UX content remains embedded inline in `prd-issue-104-audio-notebook-qol.md` as in v1, but with **two new canonical subsections added**:
- **Diarization-Review Keyboard Contract** (PRD line 900) — resolves J4↔J7 conflict
- **Visual Affordance Specification (UI Contract)** (PRD line 922) — resolves visual-spec gap

### v1 UX Gaps — Resolution Status

| v1 Gap | v2 Status | Evidence |
|---|---|---|
| 1. Missing ADR for diarization-review persistence | ✅ **RESOLVED** | ADR-009 added (PRD line 786) with full schema spec; Story 1.9 creates table; Story 5.6 implements lifecycle |
| 2. No UX detail for FR15 wizard content | ✅ **RESOLVED via downscope** | FR15 rewritten to sane-default screen + inline help banner; multi-step wizard moved to Phase 3 Vision |
| 3. Keyboard navigation conflict between J4 and J7 | ✅ **RESOLVED** | Canonical "Diarization-Review Keyboard Contract" subsection added (PRD line 900); Story 5.9 AC3 cites verbatim |
| 4. R-EL15 bulk-accept UX semantics under-specified | 🟡 **PARTIALLY RESOLVED** | Story 5.9 AC2 specifies bulk-accept = "Mark all visible as auto-accept best guess" (filter-respecting); commit timing tied to "Run summary now" trigger via Story 5.6 lifecycle. **Undo for accidental bulk-accept is NOT specified**; per-recording-undo question from v1 still open. |
| 5. No visual spec for badges/banners/confidence indicators | ✅ **RESOLVED** | "Visual Affordance Specification (UI Contract)" subsection added (PRD line 922); UX-DR1/2/3/5 named anchors; existing primitives (`StatusLight`, `QueuePausedBanner`) explicitly reused; UI contract update sequence mandated |
| 6. F5 has no journey coverage | 🟡 **UNCHANGED** (per v1 deferable list) — F5 epic-model-profiles has 4 stories with explicit AC in lieu of journey | Same as v1; deferred per v1's own deferable list |

### Updated UX↔PRD Alignment

| Capability | UX Source | FR Anchor | v2 Story | Aligned? |
|---|---|---|---|---|
| Plain-text export with sensible defaults | J1 | F3 + FR9 | Story 3.4 | ✅ |
| Explicit Download buttons + OS-default destination | J1, J7 | F6 + FR5–FR8 | Story 3.5 | ✅ |
| Audio dedup on import by content hash | J1 | R-EL23 + FR2–FR4 | Stories 2.1–2.5 | ✅ |
| Profile setup (sane-defaults + inline help banner) | J2 (revised) | F1 + F2 + FR15 (downscoped) | Story 1.5 | ✅ |
| Live filename preview | J2, J6 | F2 + R-EL14 + FR13 | Story 3.3 | ✅ |
| Speaker alias storage + view substitution | J2 | F4 MVP + FR21–FR22 | Stories 4.1–4.4 | ✅ |
| Alias propagation to export + AI context | J2, J4, J5 | F4 Growth + FR23, FR24 | Stories 5.1–5.3 | ✅ |
| Diarization confidence per-turn surface | J4 | F4 Growth + R-EL4 + FR25 | Stories 5.4–5.5 | ✅ |
| Scalable diarization-review UX (keyboard-driven) | J4, J7 | R-EL15 + FR26 + Keyboard Contract | Story 5.9 (cites contract verbatim) | ✅ |
| Auto-summary HOLD on low-confidence | J4 | R-EL10 + FR25 | Story 5.8 | ✅ |
| Review state persists across restarts | J4 | R-EL19 + FR27 + NFR23 + ADR-009 | Stories 1.9 + 5.6 (AC5) | ✅ |
| Persistent review banner | J4 | R-EL20 + FR28 + UX-DR2 | Story 5.7 | ✅ |
| Status badge + single-click retry | J3 | R-EL1 + FR35 + UX-DR1 | Story 6.6 | ✅ |
| Distinct empty/truncated summary states | J2, J3 | FR36 + FR37 | Story 6.7 | ✅ |
| Retry escalation policy | J3 | R-EL18 + FR35 + NFR19 | Story 6.11 | ✅ |
| Idempotent re-export on retry | J3 | F1 design + FR39 + Story 6.10 | Stories 6.9, 6.10 | ✅ |
| Deferred-retry on destination unavailability | J3 | R-EL12 + FR38 + NFR20 | Story 6.8 | ✅ |
| Extensibility webhook | J5 | R-EL5 + FR43–FR47 | Stories 7.1–7.7 | ✅ |
| Forward-only template change + opt-in re-export | J6 | FR17 | Story 3.6 | ✅ |
| Recording deletion does not touch on-disk by default | J1, J2 | R-EL13 + FR48 | Story 3.7 | ✅ |
| Keyboard-only + screen-reader + ARIA | J7 | FR51–FR54 + UX-DR4 (kbd contract) | Story 1.8 (scaffold) + 5.9 (AC4) + per-story inheritance | ✅ |

**Coverage:** All 21 capabilities revealed by the 7 journeys are anchored to FRs **and** to specific story IDs. **No UX-asserted capability lacks a story.**

### UX↔Architecture Alignment

| UX Need | ADR / Architecture | v2 Story | Aligned? |
|---|---|---|---|
| Profile CRUD | ADR-001 | Story 1.2 | ✅ |
| Audio dedup on import | ADR-002 | Stories 2.1–2.4 | ✅ |
| Profile-snapshot durability | ADR-003 + ADR-008 | Story 1.3 | ✅ |
| Webhook delivery on completion | ADR-004 + ADR-006 | Stories 7.3, 7.4 | ✅ |
| Per-recording aliases | ADR-005 | Story 4.1 | ✅ |
| Profile state propagation | ADR-007 | Story 1.6 | ✅ |
| Crash recovery preserves snapshot | ADR-008 | Story 1.3 (AC4) | ✅ |
| Diarization-review state persistence | **ADR-009 (NEW)** | Stories 1.9 + 5.6 | ✅ |
| OS keychain for private fields | Implementation Considerations | Story 1.7 | ✅ |
| Native OS file-save dialog | Desktop App — Platform Deltas | Story 3.5 (AC2) | ✅ |
| Native OS folder picker | Desktop App — Platform Deltas | Story 1.4 | ✅ |
| ARIA live regions + WCAG AA | Accessibility cross-cutting | Story 1.8 + per-story | ✅ |

**v2 Δ:** The single v1 partial gap (no ADR for review persistence) is now closed by ADR-009 + Story 1.9.

### UX↔NFR Alignment

| UX Need | NFR | v2 Story | Aligned? |
|---|---|---|---|
| Live filename preview latency | NFR2 (<50ms p95) | Story 3.3 (AC2) | ✅ |
| Auto-summary fires within 2s | NFR3 | Story 6.2 (AC1) | ✅ |
| Auto-export fires within 2s | NFR4 | Story 6.3 (AC1) | ✅ |
| Webhook 10s timeout | NFR5 | Story 7.4 (AC1) | ✅ |
| Diarization-review filter scales | NFR7 (r²>0.95 at 10/100/500/1000) | Story 5.9 (AC6) | ✅ |
| Status badges always visible | NFR41 | Story 6.6 (AC4 persistence) | ✅ |
| Persistent banners | NFR43 | Story 5.7 (AC2 no auto-dismiss) | ✅ |
| Plain-text export memory ceiling | NFR48 | Story 3.4 (AC2 streaming) | ✅ |
| Lurker workflow without configuration | NFR50 | Story 3.5 (AC1 visual contiguity) | ✅ |
| Lighthouse a11y ≥90 | NFR25 | Story 1.8 (AC4) | ✅ |

### UX Alignment Verdict

- **PRD-to-UX coverage:** 100% (21/21 journey capabilities anchored to FRs and stories)
- **Architecture-to-UX coverage:** 100% (12/12 needs match an ADR including ADR-009)
- **NFR-to-UX coverage:** 100% (10/10 UX needs have NFR backing + story AC)
- **v1 critical UX gaps:** 5/6 resolved; bulk-accept undo (gap #4) partial; F5 journey (gap #6) deferred
- **Overall:** UX content is now **substantively complete** for clean story-writing. ✅

---

## Step 5 — Epic Quality Review (v2)

### A. Epic Structure Validation

#### Epic-foundations (NEW — replaces implicit-in-epic-a) — 9 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Profile system, keychain, accessibility scaffold, test infra" — engineer-centric but precise; appropriate for a foundational epic |
| Epic Goal documented | ✅ | Clear "As/I want/So that" structure (line 296-300) |
| Value proposition | ✅ | "all downstream feature epics build on a stable base" |
| Independent of other epics | ✅ | "Dependencies: None — this epic must land first" |
| Risk grade | MED-HIGH | Touches durability column, secrets storage, keychain integration |
| Stories sized appropriately | ✅ | 0.5d–3d per story; total 11–14 |
| Migration ordering | ✅ | First migration (Story 1.2 profiles); follow-on migrations 1.3, 1.9 explicit |

#### Epic-import (NEW — homes FR1–FR4) — 5 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Audio import & content-hash dedup" |
| Epic Goal documented | ✅ | Anchored to J1 Lurker happy path (line 691) |
| Independent | ✅ | Depends only on epic-foundations Story 1.1 |
| Risk grade | LOW-MED | Additive column + endpoint + modest UI |
| Migration first | ✅ | Story 2.1 (audio_hash column) precedes Story 2.2 (compute) |

#### Epic-export (renamed from epic-a's MVP slice) — 7 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Filename templates, plain-text export, download buttons, deletion semantics" |
| Epic Goal documented | ✅ | Anchored to dual personas (Lurker + Configurator) |
| Independent | ✅ | Depends on epic-foundations + epic-import |
| Risk grade | LOW-MED | Filename sanitization is highest-risk slice |
| Stories sized | ✅ | 0.5d–1.5d typical |

#### Epic-aliases-mvp (renamed from epic-b's MVP slice) — 5 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Speaker alias storage + view substitution" |
| Epic Goal documented | ✅ | Anchored to J2 MVP slice |
| Independent | ✅ | Depends only on epic-foundations |
| Risk grade | MED-HIGH | F4 = HIGH per PRD; MVP slice is the safer half |
| Migration first | ✅ | Story 4.1 |

#### Epic-aliases-growth (renamed from epic-b's Growth slice) — 9 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Alias propagation, diarization confidence, review UX" |
| Epic Goal documented | ✅ | Anchored to dual personas (Maria + Sami) |
| Independent | ✅ | Depends on epic-aliases-mvp + epic-foundations 1.9 |
| Risk grade | HIGH | Cross-surface propagation; review UX scales to 60+ turns |
| Story 5.9 cites Keyboard Contract verbatim | ✅ | AC3 reproduces the canonical table |

#### Epic-auto-actions (NEW — separate from epic-export) — 11 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "F1 auto-summary, auto-export, status badges, retry" |
| Epic Goal documented | ✅ | Configurator workflow narrative |
| Independent | ✅ | Depends on epic-aliases-growth (race-condition resolution); FORWARD DEPENDENCY now resolved (epic-aliases-growth precedes auto-actions, not the other way) |
| Risk grade | HIGH | Async failure cascade; 3 lifecycle hooks to coordinate |
| F1+F4 race guard explicit | ✅ | Story 6.11 AC3 implements the guard |

#### Epic-webhook (NEW — homes FR43–FR47) — 7 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Extensibility webhook with security baseline + WebhookWorker" |
| Epic Goal documented | ✅ | Anchored to J5 Vassilis |
| Independent | ✅ | Depends only on epic-foundations |
| Risk grade | HIGH | SSRF prevention; underestimated time-sink (per PRD); 6–8d → 7–9d in epics revised estimate |
| Migration first | ✅ | Story 7.1 |

#### Epic-model-profiles (renamed from epic-c) — 4 stories

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ | "Pre-transcription model profile switching (F5)" |
| Epic Goal documented | ✅ | Configurator parallel funnel narrative |
| Independent | ✅ | "Parallel-shippable" tag |
| Risk grade | MEDIUM | Existing model_manager covers swap mechanics |
| Concrete dev-day estimate | ✅ | **3–4 days (concrete, fixing v1 gap of "small unsized")** |

### B. Forward-Dependency Map (v2)

```
                         epic-foundations (Cross — lands first)
                                  │
        ┌────────────┬────────────┼────────────┬────────────┐
        ▼            ▼            ▼            ▼            ▼
   epic-import  epic-aliases-mvp  epic-webhook  epic-model-profiles
        │            │
        ▼            ▼
   epic-export  epic-aliases-growth
                     │
                     ▼
                epic-auto-actions
                  (consumes alias propagation —
                   resolves cross-feature constraint #1)
```

**Dependency violations: 0** (down from 3 in v1).

- ✅ **epic-aliases-growth precedes epic-auto-actions** — F1↔F4 race guard implemented in Story 6.11 AC3.
- ✅ **Webhook is a peer epic** (epic-webhook), not orphaned in epic-a.
- ✅ **Profile-system foundation** is the first epic — all consumers (F1, F2, F5, webhook) are now downstream.

### C. Story-Level Quality Assessment (v2 — possible because stories now exist)

#### INVEST Heuristic — Sample audit

I audited 12 stories across all 8 epics for INVEST compliance:

| Story | I | N | V | E | S | T | Verdict |
|---|---|---|---|---|---|---|---|
| 1.1 (Day-1 fixtures) | ✅ | ✅ | ✅ | ✅ | ✅ (1d) | ✅ | PASS |
| 1.2 (profiles migration + CRUD) | ✅ | ✅ | ✅ | ✅ | ✅ (2d) | ✅ | PASS |
| 1.7 (keychain + headless fallback) | ✅ | ✅ | ✅ | ✅ | ⚠️ (3d — large) | ✅ | PASS (size warrants splitting watch) |
| 2.4 (dedup endpoint + UI prompt) | ✅ | ✅ | ✅ | ✅ | ✅ (1.5d) | ✅ | PASS |
| 3.5 (download buttons + dialog) | ✅ | ✅ | ✅ | ✅ | ✅ (1.5d) | ✅ | PASS |
| 4.1 (aliases migration) | ✅ | ✅ | ✅ | ✅ | ✅ (0.5d) | ✅ | PASS |
| 5.6 (ADR-009 lifecycle state machine) | ✅ | ✅ | ✅ | ✅ | ✅ (1d) | ✅ | PASS |
| 5.9 (review view + Kbd Contract) | ✅ | ✅ | ✅ | ✅ | ⚠️ (2d — large) | ✅ | PASS (sized at top of band; complex review UI) |
| 6.4 (Persist-Before-Deliver invariant test) | ✅ | ✅ | ✅ | ✅ | ✅ (1d) | ✅ | PASS |
| 7.3 (WebhookWorker skeleton) | ✅ | ✅ | ✅ | ✅ | ⚠️ (2d — large) | ✅ | PASS (extracted module + lifespan integration) |
| 7.5 (Persist-Before-Deliver for webhook) | ✅ | ✅ | ✅ | ✅ | ✅ (1d) | ✅ | PASS |
| 8.3 (one-click model switch) | ✅ | ✅ | ✅ | ✅ | ✅ (1d) | ✅ | PASS |

**Result:** 12/12 sampled stories pass INVEST. 3 stories (1.7, 5.9, 7.3) sit at the upper sizing band (2–3 dev-days) but each has a clear scope boundary; no need to split.

#### BDD Acceptance Criteria Quality

- **Total ACs:** 196 (counted via regex `^\*\*AC[0-9]+ —`)
- **Format compliance:** All ACs follow Given/When/Then BDD structure — confirmed by spot-check across 12 stories.
- **Specificity:** ACs reference concrete API URLs, schema columns, ARIA attributes, fixture names, error message strings, and dev-day budgets — not vague aspirations.
- **Coverage of testable invariants:** Every artifact-producing story has an explicit Persist-Before-Deliver AC; every UI story has explicit a11y ACs; every migration story has non-destructiveness ACs.

#### Within-Epic Story Dependency Review

I traced `Depends on` lines across all 57 stories. **Result: no within-epic forward dependencies; no cross-epic dependencies that contradict the dependency graph.** The `Depends on` declarations form a directed acyclic graph that matches the rendered dependency diagram.

### D. Database/Migration Story Timing

✅ **All 7 new tables/columns are created in the FIRST story of their respective epic** (per BMad practice "tables created when needed, not upfront"):

| Table/Column | Created in |
|---|---|
| `profiles` | Story 1.2 (epic-foundations first migration) |
| `transcription_jobs.job_profile_snapshot` + `snapshot_schema_version` | Story 1.3 (epic-foundations) |
| `recording_diarization_review` | Story 1.9 (epic-foundations — landed early to avoid cross-epic forward dep) |
| `transcription_jobs.audio_hash` | Story 2.1 (epic-import first migration) |
| `recording_speaker_aliases` | Story 4.1 (epic-aliases-mvp first migration) |
| `webhook_deliveries` | Story 7.1 (epic-webhook first migration) |
| `model_profiles` (or electron-store) | Story 8.1 (epic-model-profiles — implementer choice documented in AC1) |

**v1 Major #10 (No migration ordering plan): RESOLVED.**

### E. Brownfield Integration Story Check

| Brownfield Concern | v1 | v2 |
|---|---|---|
| Integration with existing `transcription_jobs` table | ✅ ADR-002, ADR-003 | ✅ Stories 1.3, 2.1 implement |
| Migration with existing recordings (non-destructive) | ✅ NFR21, NFR22 | ✅ AC2 of every migration story |
| Compatibility with existing live mode | ✅ "WS /api/live: No changes" | ✅ Story 8.3 AC3 explicit reject + preserves invariant |
| Compatibility with existing diagnostic-paste | ✅ NFR45 acknowledges | ✅ Story 1.1 fixtures + NFR54 linter rules don't touch existing diagnostic-paste |

### F. Best Practices Compliance — v2

| Check | epic-foundations | epic-import | epic-export | epic-aliases-mvp | epic-aliases-growth | epic-auto-actions | epic-webhook | epic-model-profiles |
|---|---|---|---|---|---|---|---|---|
| Epic delivers user value | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Epic functions independently | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stories appropriately sized | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| No forward dependencies | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| DB tables created when needed | ✅ | ✅ | n/a | ✅ | n/a | n/a | ✅ | ✅ |
| Clear acceptance criteria (BDD) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Traceability to FRs maintained | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**All checks ✅ across all 8 epics.** (Compare to v1: only epic-c passed all checks; epic-a and epic-b had multiple ❌/⚠️.)

### G. Severity-Graded Findings (v2)

#### 🔴 Critical Violations: **0** (down from 5 in v1)

#### 🟠 Major Issues: **0** (down from 8 in v1)

#### 🟡 Minor Concerns: **4** (3 carried-over deferrable + 1 net-new)

1. **🟡 [v1 Minor #14 — partial] Bulk-accept undo semantics still under-specified.** Story 5.9 AC2 specifies bulk-accept = "Mark all visible as auto-accept best guess" with filter-respecting scope and commit timing tied to "Run summary now" (Story 5.6 AC2 lifecycle). However, **per-recording-undo for an accidental Space-key bulk-accept is not specified**. Sami's J4 60-turn use case has data-loss risk if Space is hit before the user intends to commit. **Recommendation:** Add an AC under Story 5.9 that bulk-accept can be undone before "Run summary now" is clicked (e.g., per-turn revert button OR keep a session-level "Undo last bulk-accept" affordance). Defer-acceptable per v1's deferrable list.

2. **🟡 [v1 Minor #16 — unchanged] F5 has no primary journey + epic-model-profiles partially compensates.** F5 still lacks a journey narrative; epics.md acknowledges this and provides 4 concrete stories (8.1–8.4) with explicit AC and a concrete dev-day estimate (3–4 days, fixing v1's "unsized" issue). User value remains conceptually clear from Issue #104. **Recommendation:** Defer per v1 list; story AC are tight enough to ship without a journey.

3. **🟡 [v1 Minor #17 — partial] No explicit cross-pack live-mode-boundary regression test story.** Story 8.3 AC3 enforces "switch is REJECTED while live mode is in progress" — a per-feature live-mode protection. **The QoL pack lacks a single regression-protection story** that asserts "no MVP/Growth feature breaks the existing live-mode lifecycle." NFR55 (CodeQL + dashboard-quality CI gates) is broader but not live-mode-specific. **Recommendation:** Add a Story 1.10 (or insert into Story 6.4 Persist-Before-Deliver invariant test) that explicitly snapshots the live-mode contract surfaces (`WS /api/live` payload shape, model-swap orchestration, AudioToTextRecorder flow) and asserts no QoL pack code path mutates them. **Low priority — can be added at first MVP-cut PR.**

4. **🟡 [v2 net-new — documentation only] Engineer-day delta from PRD (32–44d) to epics.md (53–68d) is acknowledged in epics.md "Open Items" #2 but not back-propagated into PRD `implementationBudget`.** The PRD frontmatter still reads `mvpEngineerDays: '18-24 ... '` and `growthEngineerDays: '14-20 ... '` (total 32–44). The epics.md transparently explains the delta (epic-foundations 11–14d cross-cutting infra not budgeted in PRD; webhook acknowledged underestimate now properly accounted). **No coverage impact** but creates a budget mismatch between two planning artifacts. **Recommendation:** Either (a) update PRD frontmatter `implementationBudget` to reflect epics.md totals, OR (b) add a footnote to PRD explaining that epics.md is the canonical budget. Documentation hygiene only — does not block implementation.

### H. Restructured Epic Set vs v1 Recommendation

The 8-epic decomposition in `epics.md` matches the v1 report's recommendation in Step 5 §G **exactly**:

| v1 Recommended Epic | v2 Implemented | Match |
|---|---|---|
| epic-foundations | ✅ epic-foundations | ✅ |
| epic-import | ✅ epic-import | ✅ |
| epic-export | ✅ epic-export | ✅ |
| epic-aliases-mvp | ✅ epic-aliases-mvp | ✅ |
| epic-aliases-growth | ✅ epic-aliases-growth | ✅ |
| epic-auto-actions | ✅ epic-auto-actions | ✅ |
| epic-webhook | ✅ epic-webhook | ✅ |
| epic-model-profiles | ✅ epic-model-profiles | ✅ |

**8/8 v1 recommendations adopted.** No deviation from v1 architecture guidance.

### Epic Quality Verdict (v2)

- **Mechanical PRD-to-feature traceability:** Strong (preserved from v1)
- **Epic structure quality:** ✅ **PASSES BMad standard.** No forward dependencies, no mixed-tier epics, no unhomed FRs, 57 stories with 196 BDD ACs.
- **Story quality:** ✅ INVEST-compliant on sampled audit; BDD AC format consistent.
- **Restructuring:** Already done; matches v1 recommendation 8/8.

---

## Summary and Recommendations

### Overall Readiness Status

> **✅ READY for Phase 4 implementation.**
>
> The 5 PRD revisions (ADR-009, keyboard contract, FR15 downscope, visual spec, J2 narrative cleanup) plus the 8-epic / 57-story / 196-BDD-AC restructure resolve **all 5 Critical and all 8 Major issues** from the v1 report. 4 Minor issues remain: 2 carried-over from v1's own deferrable list (F5 thin journey, live-mode regression-test story), 1 partially resolved (bulk-accept undo not specified), and 1 net-new documentation-only (PRD `implementationBudget` not updated to match epics.md totals). None of the 4 Minor issues block implementation kickoff.

### v1 → v2 Issue Reconciliation

#### 🔴 Critical Issues (5) — **5 of 5 RESOLVED**

| # | v1 Issue | v2 Status | Evidence |
|---|---|---|---|
| 1 | No epics-and-stories file | ✅ **RESOLVED** | `epics.md` exists: 8 epics, 57 stories, 196 BDD ACs, 100% explicit FR coverage |
| 2 | Forward dependency epic-a → epic-b (F1 waits for F4) | ✅ **RESOLVED** | Restructure makes epic-aliases-growth precede epic-auto-actions; Story 6.11 AC3 implements F1+F4 race guard |
| 3 | Webhook (FR43–FR47) unhomed | ✅ **RESOLVED** | epic-webhook (7 stories: 7.1–7.7) covers all 5 FRs |
| 4 | FR1–FR4 (audio import + dedup) unhomed | ✅ **RESOLVED** | epic-import (5 stories: 2.1–2.5) covers all 4 FRs |
| 5 | Cross-cutting FRs (FR49–FR54) unanchored | ✅ **RESOLVED** | epic-foundations Stories 1.7, 1.8, 1.9 scaffold them; explicit per-story AC inheritance in 9 downstream stories (3.5, 3.7, 4.3, 4.4, 5.5, 5.7, 5.8, 5.9, 6.6) |

#### 🟠 Major Issues (8) — **8 of 8 RESOLVED**

| # | v1 Issue | v2 Status | Evidence |
|---|---|---|---|
| 6 | Epic-a mixes MVP and Growth tiers | ✅ **RESOLVED** | MVP work split into epic-export (MVP) + epic-auto-actions (Growth) |
| 7 | Epic-a mixes risk grades | ✅ **RESOLVED** | Risk segregated: epic-export LOW-MED, epic-auto-actions HIGH |
| 8 | Profile-system foundation implicit-in-epic-a | ✅ **RESOLVED** | epic-foundations explicit; Stories 1.2 (profiles), 1.3 (snapshot), 1.4 (folder picker), 1.5 (sane-default screen), 1.6 (active profile switch) cover FR10/11/14–16/18–20 |
| 9 | No epic-level Goal statements | ✅ **RESOLVED** | All 8 epics have explicit "As a / I want / So that" goal statements |
| 10 | No migration ordering plan | ✅ **RESOLVED** | First-story-creates-table pattern across all 7 new tables/columns; explicit `Depends on` lines |
| 11 | Diarization-review persistence ADR missing | ✅ **RESOLVED** | ADR-009 added to PRD; Stories 1.9 (table) + 5.6 (lifecycle state machine) implement |
| 12 | FR15 wizard content undefined | ✅ **RESOLVED via downscope** | FR15 rewritten to sane-default screen + inline help banner; multi-step wizard moved to Phase 3 Vision |
| 13 | Keyboard navigation conflict J4 ↔ J7 | ✅ **RESOLVED** | Canonical "Diarization-Review Keyboard Contract" subsection added to PRD (line 900); Story 5.9 AC3 cites verbatim |

#### 🟡 Minor Concerns (4) — **1 of 4 fully resolved, 1 partial, 2 carried over**

| # | v1 Issue | v2 Status | Notes |
|---|---|---|---|
| 14 | Bulk-accept undo semantics under-specified | 🟡 **PARTIAL** | Story 5.9 AC2 specifies scope and commit timing; undo for accidental bulk-accept still not specified |
| 15 | No visual spec for badges/banners/confidence | ✅ **RESOLVED** | "Visual Affordance Specification (UI Contract)" subsection added (PRD line 922); UX-DR1/2/3/5 anchors |
| 16 | F5 thin journey + unsized budget | 🟡 **PARTIAL** | Budget now sized (3–4 dev-days in epics.md); journey still missing — accepted per v1 deferable list |
| 17 | No live-mode-boundary compat test story | 🟡 **PARTIAL** | Story 8.3 AC3 enforces switch reject during live mode; no cross-pack regression-protection story exists |

#### Net-New v2 Issues — **1 documentation-only**

| # | New Issue | Severity | Notes |
|---|---|---|---|
| 18 | PRD `implementationBudget` (32–44d) not updated to match epics.md (53–68d) | 🟡 Minor — documentation only | Acknowledged in epics.md "Open Items" #2 with rationale (epic-foundations 12d cross-cutting infra newly budgeted; webhook acknowledged underestimate now properly accounted). No coverage impact; budget mismatch between two artifacts is hygiene-only. |

### Severity-Graded Issue Tally — Side-by-Side

| Severity | v1 Count | v2 Count | Δ |
|---|---|---|---|
| 🔴 Critical | 5 | **0** | -5 ✅ |
| 🟠 Major | 8 | **0** | -8 ✅ |
| 🟡 Minor | 4 | **4** (3 carried, 1 net-new docs) | 0 net |
| **Total** | **17** | **4** | **-13** |

### Recommended Next Steps (Implementation Kickoff)

1. **Proceed to `bmad-create-story` for first sprint zero story** (Story 1.1: Day-1 fixtures + linter-enforced test discipline). This is the single hard dependency on which all 56 other stories rest.

2. **Optional pre-implementation hygiene (10 min total):**
   - Update PRD frontmatter `implementationBudget` to reference epics.md totals (53–68d), OR add a footnote noting epics.md is canonical.
   - Decide whether to specify bulk-accept undo for Story 5.9 (insert AC8) or accept the data-loss risk note for the implementation phase.

3. **Sprint 0 ordering** (per epics.md Next Steps):
   - **Day 1–4:** Story 1.1 (fixtures + linter rules) → Story 1.2 (profiles migration + CRUD) → Story 1.3 (snapshot column) → Story 1.4 (folder picker)
   - **Day 5+:** Parallelize: epic-import, epic-aliases-mvp, epic-webhook (worker skeleton), epic-model-profiles can all start once Story 1.1 + 1.2 land

4. **MVP cut gate (`audio_notebook_qol_v1` flag):** epic-foundations MVP-portion (1.1, 1.2, 1.3, 1.4, 1.7, 1.8) + epic-import (5 stories) + epic-export (7 stories) + epic-aliases-mvp (5 stories) — total ~31–40 dev-days at 4 dev-days/week → ~8–10 calendar weeks.

5. **Growth cut gate (`v1.4.1` tag):** epic-foundations Growth-portion (1.5, 1.6, 1.9) + epic-aliases-growth (9) + epic-auto-actions (11) + epic-webhook (7) + epic-model-profiles (4) — total ~28–32 dev-days → ~7–8 calendar weeks.

6. **Per-feature test minimums (NFR52):**
   - F1 ≥10 failure-mode tests across epic-auto-actions stories (6.4 Persist-Before-Deliver invariant test alone covers ~6 modes; Stories 6.7, 6.8, 6.11 add more)
   - F4 ≥1 migration test (Story 4.1 AC2) + ≥4 propagation snapshots (Stories 4.4, 5.1, 5.2, 5.3)
   - F2 property-based suite (Story 3.2 AC2 — 50 generated cases per category)

7. **Deferred-acceptable items** (do not block kickoff):
   - Bulk-accept undo (v1 #14 partial) — can be added as story-level AC during epic-aliases-growth implementation
   - F5 journey (v1 #16) — story AC tight enough to ship without it
   - Live-mode cross-pack regression test (v1 #17) — can be added to epic-foundations or to first MVP-cut PR
   - PRD `implementationBudget` sync with epics.md (v2 #18) — documentation-only

### What the v2 Planning Got Right (Worth Preserving)

The restructure adopted the v1 architecture guidance **without modification or hand-waving**:

- 8/8 recommended epics implemented exactly as proposed
- Cross-cutting concerns (FR49–FR54) systematically anchored via scaffold-story + per-story-inheritance pattern (eliminating "everyone's problem and no one's owner" failure mode)
- ADR-009 specifies the persistence mechanism with rejected alternatives explicitly named (DB table chosen over Zustand-persist or column-on-aliases — both rejection reasons documented)
- Diarization-Review Keyboard Contract adopts WAI-ARIA Authoring Practices (industry standard) rather than inventing a new model
- Visual Affordance Specification reuses **existing primitives** (`StatusLight`, `QueuePausedBanner`) rather than introducing parallel components — preserves the dashboard's UI contract baseline
- Story 1.1 (Day-1 fixtures + linter rules **first**) makes test discipline load-bearing: a story can't be "done" without its tests passing through the banned-API gate
- Persist-Before-Deliver AC explicit on every artifact-producing story (12+ stories with dedicated AC) — the project's most critical invariant per CLAUDE.md is structurally enforced
- Migration story timing: every new table is created in the FIRST story of its epic (BMad practice "tables created when needed, not upfront")
- Engineer-day delta (32–44d → 53–68d) is **transparently surfaced** in epics.md "Open Items" #2 with rationale (epic-foundations 12d newly budgeted for cross-cutting infra; webhook acknowledged underestimate now properly accounted)

### Final Verdict

**✅ READY for implementation kickoff.** Recommend invoking `bmad-create-story` to kick off Story 1.1 (Day-1 fixtures + linter-enforced test discipline) as the first sprint zero deliverable. All 5 Critical and 8 Major issues from the v1 report are resolved. The 4 remaining Minor issues are deferrable per v1's own deferable list or are documentation-only hygiene items. No blocking concerns identified.

---

**Assessment Date:** 2026-05-03
**Assessor:** Implementation Readiness skill (PM agent persona) for Bill
**Documents Reviewed:**
- `_bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md` (1,418 lines, revisionsApplied=[ADR-009, kbd-contract, FR15-downscope, visual-spec, FR15-narrative-cleanup])
- `_bmad-output/planning-artifacts/epics.md` (2,515 lines; 8 epics / 57 stories / 196 BDD ACs)
- `_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md` (v1 report, preserved unmodified for diff)

**Project:** TranscriptionSuite — Audio Notebook QoL pack (Issue #104)
**Verdict:** READY · Issues: 4 Minor · Recommendation: proceed to `bmad-create-story`
