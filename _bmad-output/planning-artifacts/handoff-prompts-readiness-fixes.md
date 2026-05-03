---
date: 2026-05-03
purpose: Three sequential handoff prompts for fresh Claude Code sessions to address the 17 issues found in implementation-readiness-report-2026-05-03.md
sequence: prompt-1 (edit PRD) → prompt-2 (create epics+stories) → prompt-3 (re-run readiness check)
session_origin: implementation-readiness-check-v1
---

# Handoff Prompts — Implementation Readiness Fixes

> Run each prompt in a **fresh** Claude Code session (`/clear` then paste, or open a new terminal). Each is self-contained.

---

## Prompt 1 of 3 — Edit the PRD (apply 4 fixes inline)

```
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
/bmad-edit-prd

Apply the four PRD fixes called out as Critical/Major in the readiness
report. All four edits land INSIDE prd.md (do not create separate
architecture or UX files). Keep edits surgical — preserve the existing
structure, FR/NFR/R-EL/ADR numbering, and Appendix A/B/C cross-references.

Fix 1 — Add ADR-009 to the ADR table in `## Project-Type Specific Requirements`:

  ADR-009 — Diarization-review state persistence
  Decision: persist review state in a new `recording_diarization_review`
  table with columns (recording_id PK, status TEXT CHECK IN ('pending',
  'in_review', 'completed', 'released'), reviewed_turns_json, created_at,
  updated_at). Auto-summary HOLD reads `status != 'released'`. Banner
  visibility reads `status IN ('pending', 'in_review')`. Lifecycle: created
  on transcription completion when low-confidence turns detected (pending) →
  user opens review (in_review) → user clicks "Run summary now" (completed)
  → auto-summary fires + status flips to released. Survives DB restore;
  queryable for diagnostics. Rationale: durability invariant matches
  Persist-Before-Deliver discipline; rejected Zustand-persist (local-only,
  not crash-safe) and column-on-aliases (couples F4 MVP slice to Growth
  scope). Cross-references: R-EL19, R-EL20, FR25, FR27, FR28, NFR23.

Also append a row to Appendix B's "Speaker Aliasing" line: ADRs cell becomes
"ADR-005, ADR-009".

Fix 2 — Resolve J4↔J7 keyboard navigation contract conflict.
  Pick: WAI-ARIA Authoring Practices model
    - Tab / Shift+Tab traverse between turns (focusable elements)
    - ↑/↓ move selection within a focused turn-list (composite widget)
    - ←/→ switch attribution within a focused turn
    - Enter accept; Esc skip; Space bulk-accept visible turns
  Update J4 narrative (rising action / climax) to match this model
  exactly. J7 narrative is already aligned — just re-verify it after edit.
  Add a new short subsection at the end of `## Project-Type Specific
  Requirements` titled "Diarization-Review Keyboard Contract" pinning the
  above as the canonical spec, referenced by FR26, FR51, R-EL15.

Fix 3 — Decide FR15 wizard scope. Downscope to:
  "FR15 [Growth]: Empty-profile screen pre-populates fields with sane
  defaults (today's filename template, OS user-Documents folder) and shows
  a single inline help banner explaining the field-first flow. No
  multi-step wizard — deferred to Vision."
  Update Appendix B's "Profile Management" line if needed (no new ADR).
  Add a Vision item to `## Project Scoping & Phased Development → Phase 3`:
  "Multi-step setup wizard for first-time profile creation."

Fix 4 — Add a small visual-spec block at the end of `## Project-Type
Specific Requirements` titled "Visual Affordance Specification (UI
Contract)". Cover three new affordance classes; cross-reference existing
primitives in `dashboard/components/ui/` so the implementer reuses them:

  Status Badges (R-EL1, NFR41) — reuse StatusLight primitive; severity
    levels: ok (green), warn (amber, e.g. "summary truncated"), error (red,
    e.g. "LLM unavailable"); single-click retry button inline; auto-dismiss
    on success.

  Persistent Banners (R-EL20, NFR43) — reuse QueuePausedBanner pattern;
    yellow/amber background; persistent until user action; appears at top
    of recording detail view; "Review uncertain turns" CTA inline.

  Per-Turn Confidence Indicators (R-EL4) — small chip beside the speaker
    label in transcript view; three buckets: high (no chip), medium
    (60-80%, neutral chip), low (<60%, amber chip); chip shows percentage
    on hover.

  Migration AC: any new visual element triggers
  `npm run ui:contract:check` per dashboard CLAUDE.md rules.

After applying all four fixes:
  1. Re-validate Appendix B is internally consistent (no broken
     FR/NFR/R-EL references).
  2. Bump the PRD frontmatter `completionDate` to today (2026-05-03)
     and add `revisionsApplied: ['ADR-009', 'kbd-contract', 'FR15-downscope',
     'visual-spec']` to frontmatter.
  3. Optionally invoke `bmad-validate-prd` to confirm structural integrity.

Report at the end: which sections you touched, which line ranges,
and whether anything blocked the edits.
```

---

## Prompt 2 of 3 — Create epics and stories (8-epic restructure)

```
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
/bmad-create-epics-and-stories

Use the restructured 8-epic plan from the readiness report (Step 5 §G,
"Recommended Restructuring"). Do NOT use the PRD's frontmatter
`plannedEpicGroupings` (epic-a/b/c) — that structure was rejected by the
readiness check for forward-dependency and unhomed-FR violations.

The 8 epics to produce, in dependency order:

  1. epic-foundations — Cross-tier; lands first
     Scope: profile-system core (FR10, FR11, FR14, FR15, FR16, FR18,
     FR19, FR20), keychain (FR49, FR50), accessibility scaffold
     (FR51-54), Day-1 test fixtures (NFR53), security ADR-009
     persistence table migration.

  2. epic-import — MVP; depends on epic-foundations
     Scope: FR1, FR2, FR3, FR4 + R-EL23 dedup + ADR-002 audio_hash
     column on transcription_jobs.

  3. epic-export — MVP; depends on epic-foundations + epic-import
     Scope: F2 templates (FR12, FR13, FR17), F3 plain-text (FR9),
     F6 download buttons (FR5-8), R-EL13 deletion semantics (FR48).

  4. epic-aliases-mvp — MVP; depends on epic-foundations
     Scope: F4 MVP slice (FR21, FR22, FR29) +
     `recording_speaker_aliases` table migration.

  5. epic-aliases-growth — Growth; depends on epic-aliases-mvp +
     epic-foundations
     Scope: F4 Growth slice (FR23-28), diarization-review UX, ADR-009
     persistence consumption.

  6. epic-auto-actions — Growth; depends on epic-aliases-growth +
     epic-foundations
     Scope: F1 (FR30-39) + cross-feature constraint #1 (F1+F4 race
     guard) + R-EL1 status badges + R-EL18 retry escalation +
     R-EL12 deferred retry.

  7. epic-webhook — Growth; depends on epic-foundations
     Scope: FR43-47 + WebhookWorker service + ADR-006 webhook_deliveries
     table + security baseline (NFR9-12) + R-EL33 persistence.

  8. epic-model-profiles — Growth; independent (parallel-shippable)
     Scope: F5 (FR40-42).

For each epic produce:
  - Epic Goal (formal user-outcome statement, not just a rationale)
  - User-centric Title
  - Tier (MVP/Growth/Cross)
  - Dependencies (which epics must complete first)
  - FRs covered (explicit list)
  - Cross-cutting AC inheritance (FR49-54 inherited by which epics)
  - Risk grade
  - Engineer-day budget (use Appendix A budgets as starting point)
  - Stories with INVEST-compliant structure:
      - Title (user-centric, "As a USER I want X so that Y")
      - Story Goal
      - Acceptance Criteria in Given/When/Then BDD format
      - FR traceability (which FR this story closes)
      - Dependencies on prior stories within the epic
      - Estimated dev-days
  - First story of each epic that needs new tables/columns must include
    the migration as part of its scope (per BMad "create tables when
    needed" rule)

Critical constraints to enforce:
  - No story may depend on a story in a later epic (forward dependency
    forbidden).
  - Cross-feature constraint #1 (F1 must wait for F4 propagation) must
    be enforced by epic ordering: epic-aliases-growth before
    epic-auto-actions.
  - Persist-Before-Deliver invariant (NFR16) must be reflected in any
    story that produces or delivers a transcription/summary/webhook
    artifact.
  - Each story under epic-aliases-growth, epic-auto-actions, epic-export
    must have an explicit accessibility AC (FR51-54 inheritance).
  - Diarization-review keyboard contract (added to PRD by Prompt 1) must
    be cited verbatim in epic-aliases-growth review-UI stories.

Output: a single `_bmad-output/planning-artifacts/epics.md` (or sharded
`epics/` folder, your call — pick whichever the create skill recommends
for 8 epics). Include a top-level FR-coverage map showing 100% explicit
coverage of FR1-FR54.

If any FR cannot be cleanly anchored to a story without violating
forward-dependency rules, STOP and flag it — do not invent a workaround.
```

---

## Prompt 3 of 3 — Re-run readiness check

```
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/planning-artifacts/epics.md
@_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
/bmad-check-implementation-readiness

Re-run the implementation readiness check on the updated planning
artifacts. The previous run (2026-05-03 v1) found 17 issues across 5
critical / 8 major / 4 minor — see the v1 report for the full list.

The intervening work was:
  1. PRD edits applied (ADR-009, keyboard contract, FR15 downscope, visual
     spec block) — see PRD frontmatter `revisionsApplied`.
  2. Epics-and-stories file created with 8-epic restructure
     (epic-foundations, epic-import, epic-export, epic-aliases-mvp,
     epic-aliases-growth, epic-auto-actions, epic-webhook,
     epic-model-profiles) replacing the original epic-a/b/c grouping.

Save the new report as
`_bmad-output/planning-artifacts/implementation-readiness-report-{{today}}-v2.md`
so the v1 report stays preserved for diff comparison.

In the final summary section, explicitly compare against v1:
  - Which of the 5 Critical issues are resolved? Which remain?
  - Which of the 8 Major issues are resolved? Which remain?
  - Which of the 4 Minor issues are resolved? Which remain?
  - Net new issues introduced by the restructure (if any)?
  - Updated overall verdict: READY / NEEDS WORK / NOT READY?

If the verdict is READY, recommend the next BMad workflow step
(implementation kickoff). If NEEDS WORK, list the remaining items in
priority order.
```

---

## Notes for the operator

- Run prompts in order — each depends on the prior session's artifacts being saved.
- Each prompt references files via `@` — Claude Code will pre-load them automatically.
- If a prompt's skill prompts you for menu selections (e.g. `[C] Continue`), respond inline.
- Between sessions, no manual file editing is needed — every artifact is produced by the skill.
- Total expected wall-time: Prompt 1 ~30 min, Prompt 2 ~1-2 days (the heaviest), Prompt 3 ~15 min.
