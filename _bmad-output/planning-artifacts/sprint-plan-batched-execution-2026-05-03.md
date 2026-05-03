---
date: 2026-05-03
purpose: Five sequential sprint prompts for batched execution of the Audio Notebook QoL pack (Issue #104), replacing per-story BMad cycle with sprint-scoped sessions
sequence: sprint-1 (foundations) → sprint-2 (files) → sprint-3 (speakers) → sprint-4 (auto-actions) → sprint-5 (webhook)
session_origin: post-readiness conversational planning, 2026-05-03
prd_under_execution: _bmad-output/planning-artifacts/prd.md
epics_under_execution: _bmad-output/planning-artifacts/epics.md
readiness_verdict: READY (per implementation-readiness-report-2026-05-03-v2.md)
target_runtime: Claude Code, Opus 4.7, xHigh thinking, 1M token context
stories_total: 57
stories_completed_pre_plan: 1 (Story 1.1 — commits cca1a83 + 076022e)
stories_to_execute: 56
sprints_planned: 5
---

# Sprint Plan — Batched Execution for Issue #104

> **TL;DR.** The 8-epic / 57-story breakdown in `epics.md` would normally take 56 trips through `bmad-create-story → bmad-dev-story → bmad-code-review`. This document defines a **5-sprint batched alternative** that fits the work into 5 fresh Claude Code sessions on Opus 4.7 + 1M context, using a **design-pass → implement-all → review-all** pattern per sprint. Each sprint groups stories by dependency-graph layer + thematic cohesion.

> Run each prompt in a **fresh** Claude Code session (`/clear` then paste, or open a new terminal). Each is self-contained.

---

## Why batched execution?

Per-story BMad cycle is calibrated for smaller context windows (~200K) where holding multiple stories in head simultaneously is expensive. With Opus 4.7's 1M-token window + xHigh thinking, the bottleneck shifts from *context* to *diff fatigue + compounding-mistake risk*. The unlock is **intra-sprint amortization**: one design pass + one review pass for ~12 stories, instead of 12 × (design + review).

Tradeoffs accepted:
- ✅ ~5–10× speedup on planning/review overhead per story
- ✅ Cross-story design contradictions caught earlier (single design.md per sprint covers all)
- ✅ Logical commit cadence (~2–3 stories per commit) instead of 1-commit-per-story noise
- ⚠️ Larger end-of-sprint diffs (3.5K LOC ceiling per sprint) require disciplined review
- ⚠️ A structural mistake in the design pass affects more stories — design.md must be reviewed before implementation begins
- ⚠️ Skips per-story validation gates from `bmad-validate-story`; sprint-level review compensates

---

## Dependency-graph constraints

Reproduced from `epics.md` § "Epic Dependency Graph":

```
                     Epic 1 (Foundations)  ← MUST be first
                              │
         ┌──────────┬─────────┼─────────┬──────────┐
         ▼          ▼         ▼         ▼          ▼
      Epic 2    Epic 4    Epic 7    Epic 8     (parallel-shippable)
         │         │
         ▼         ▼
      Epic 3    Epic 5
                   │
                   ▼
               Epic 6
```

**Critical-path:** E1 → E4 → E5 → E6 (cannot be parallelized)
**Parallel after E1:** E2 → E3 chain, E7, E8

**Ship gates (per epics.md § "Ship sequencing"):**
- **MVP gate (`audio_notebook_qol_v1` flag):** E1 (MVP-portion) + E2 + E3 + E4 — covered by Sprints 1–3
- **Growth gate (`v1.4.1` tag):** E1 (Growth-portion) + E5 + E6 + E7 + E8 — covered by Sprints 1, 3, 4, 5

---

## The 5-sprint plan

| # | Sprint | Stories | Story Count | Eng-days | Critical-path? | Sprint LOC ceiling |
|---|---|---|---|---|---|---|
| 1 | Platform Foundations | 1.2–1.9, 8.1–8.4 | 12 | 13–17 | YES (gates everything) | 3500 |
| 2 | File Pipeline | 2.1–2.5, 3.1–3.7 | 12 | 10–13 | No (parallel-shippable) | 3500 |
| 3 | Speakers MVP + Growth | 4.1–4.5, 5.1–5.9 | 14 | 12–16 | YES (gates Sprint 4) | 4500 |
| 4 | Auto-Actions | 6.1–6.11 | 11 | 10–12 | YES (consumes Sprint 3) | 3500 |
| 5 | Webhook Delivery | 7.1–7.7 | 7 | 7–9 | No (any time after S1) | 2500 |
| **Σ** | — | — | **56** | **52–67** | — | — |

### Sprint grouping rationale

- **Sprint 1 (E1 + E8)** — Both are "profile-shaped" data with CRUD + persistence patterns. E8 (model profiles) piggybacks for free since you've already built the muscle on E1 (user profiles).
- **Sprint 2 (E2 + E3)** — The full file lifecycle: dedup on import (E2), templates + export on output (E3). Both depend only on E1; no cross-dependencies with other sprints.
- **Sprint 3 (E4 + E5)** — Critical-path chain. E5 (alias propagation, diarization review) is useless without E4 (alias data + REST + UI). Doing them together keeps the alias data model coherent in one head. Largest sprint by design.
- **Sprint 4 (E6)** — The auto-summary/auto-export lifecycle is one cohesive state machine with retry/idempotency invariants. Splitting it across sessions risks contradictions in the persist-before-deliver invariant (CLAUDE.md durability rule).
- **Sprint 5 (E7)** — Self-contained delivery pipeline. Reuses persist-before-deliver patterns from Sprint 4, so going *after* Sprint 4 (not before) keeps the prior art warm in cache.

### Workflow pattern (per sprint)

1. **Design pass (~15–30 min)** — Read all sprint stories' ACs in `epics.md`. Pay special attention to inline `Important:` notes that override the AC text (Story 1.1 demonstrated this pattern: existing `conftest.py` not empty, no `[tool.ruff]` section yet, no ESLint installed). Write `_bmad-output/implementation-artifacts/sprint-N-design.md` covering the cross-story decisions.
2. **Implement-all** — Land logical commits (~2–3 stories each), in dependency order. Don't generate per-story spec files; the epic AC content is sufficient.
3. **Review-all** — Dispatch `code-reviewer` agent on the full sprint diff. Run backend tests (build venv per CLAUDE.md), frontend tests, and ui-contract update if CSS classes changed.
4. **Mark DONE** — Append `Status: DONE (sprint N)` under each story heading in `epics.md`. Commit as final commit of the sprint.

### Stop-and-ask triggers (universal)

- Sprint diff exceeds its LOC ceiling — split, don't ship.
- Schema deviation from a referenced ADR (e.g. ADR-009 in Story 1.9 / 5.6).
- Persist-before-deliver invariant requires changing existing transcription pipeline structure beyond the sprint's stated scope.
- A new dependency must be added beyond what the sprint's gotchas list.

---

## Prompt 1 of 5 — Sprint 1: Platform Foundations (12 stories)

```
@_bmad-output/planning-artifacts/epics.md
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03-v2.md
@CLAUDE.md
@docs/index.md

# Sprint 1 of 5 — Platform Foundations (Issue #104)

Implement Stories 1.2–1.9 (epic-foundations remaining; lines 348–686 of epics.md)
plus Stories 8.1–8.4 (epic-model-profiles; lines 2342–2459). 12 stories total.
Story 1.1 is already DONE (commits cca1a83, 076022e — Day-1 fixtures + linter).

## Workflow (do not use bmad-create-story per story)

1. DESIGN PASS — Read all 12 stories' ACs in epics.md. Pay special attention to
   inline "Important:" notes that override the AC text (the existing conftest is
   not empty; pyproject.toml has no [tool.ruff] section yet; etc — Story 1.1
   showed this pattern). Write `_bmad-output/implementation-artifacts/sprint-1-design.md`
   covering: profiles table schema, profile snapshot column shape, keychain
   abstraction (with keyrings.alt fallback for headless Linux), folder picker
   IPC contract, ARIA scaffold conventions, recording_diarization_review schema
   (per ADR-009), model profile data model. Cross-check that user-profiles
   (E1) and model-profiles (E8) share the same persistence patterns so E8 rides
   along for free.

2. IMPLEMENT — Land logical commits (~2–3 stories each), in dependency order.
   Suggested grouping:
   • commit A: Stories 1.2 + 1.3 (profiles table + snapshot column migration)
   • commit B: Story 1.4 (folder picker primitive)
   • commit C: Stories 1.5 + 1.6 (empty-profile screen + active-profile switch)
   • commit D: Story 1.7 (keychain + keyrings.alt fallback)
   • commit E: Story 1.8 (a11y scaffold)
   • commit F: Story 1.9 (recording_diarization_review migration — ADR-009)
   • commit G: Stories 8.1–8.4 (model profile data + CRUD UI + switch + persistence)

3. REVIEW — At end of sprint, dispatch the `code-reviewer` agent on the full
   sprint diff (`git diff main..HEAD`). Run backend tests
   (`cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short`)
   and frontend tests (`cd dashboard && npm test`). If UI classes changed,
   run the ui-contract update sequence per CLAUDE.md. Address blockers, defer
   polish to deferred-work.md.

4. MARK DONE — Append "Status: DONE (sprint 1)" under each story heading in
   epics.md. Commit as final commit of the sprint.

## Gotchas

- NEVER `pip` — always `uv` (per CLAUDE.md).
- Profile snapshot on transcription_jobs (1.3) is durability-critical: persist
  before any delivery. Write a regression test using `frozen_clock`.
- Keychain (1.7): tests must use `fake_keyring` fixture — no real keyring access.
- Folder picker (1.4): primary target is Linux KDE Wayland; document Windows
  + macOS behavior even if not fully tested.
- ADR-009 lifecycle (1.9): just the table + smoke CRUD — actual state-machine
  consumers land in Sprint 3 (Story 5.6).
- Model profile (8.x): if you find E1 + E8 share a base class cleanly, refactor
  it; if not, leave duplication for now (don't speculate).

## Stop and ask before continuing if:

- Story 1.7 keychain abstraction needs a new dep beyond `keyring` + `keyrings.alt`.
- Story 1.9 schema deviates from ADR-009 (lines ~115–120 of v2 readiness report).
- Sprint diff exceeds ~3500 LOC — escalate for split.

Use Opus 4.7 reasoning fully. 1M context — load files freely.
```

---

## Prompt 2 of 5 — Sprint 2: File Pipeline (12 stories)

```
@_bmad-output/planning-artifacts/epics.md
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/implementation-artifacts/sprint-1-design.md
@CLAUDE.md

# Sprint 2 of 5 — File Pipeline: Import Dedup + Templates + Export (Issue #104)

Implement Stories 2.1–2.5 (epic-import; lines 687–855 of epics.md) plus
Stories 3.1–3.7 (epic-export; lines 856–1122). 12 stories total. Depends
on Sprint 1 having merged.

## Workflow

1. DESIGN PASS — Read all 12 stories' ACs. Verify Sprint 1 landed by checking
   that `profiles` table, profile snapshot column, and keychain are present.
   Write `_bmad-output/implementation-artifacts/sprint-2-design.md` covering:
   audio hash storage + dedup-check API contract, filename template grammar
   (extensible — design for future placeholders), template sanitization rules
   (no path traversal, no shell metas), plain-text export streaming format,
   recording-deletion artifact options matrix (R-EL13, R-EL32).

2. IMPLEMENT — Logical commit groups in dependency order:
   • commit A: Story 2.1 (audio_hash column migration)
   • commit B: Story 2.2 (SHA-256 hash on import) + Story 2.3 (file-picker
     idempotence verification)
   • commit C: Stories 2.4 + 2.5 (dedup endpoint + UI + per-user scope)
   • commit D: Story 3.1 (template engine) + Story 3.2 (server-side validation)
   • commit E: Story 3.3 (live preview UI)
   • commit F: Story 3.4 (plain-text formatter) + Story 3.5 (download buttons +
     native save dialog)
   • commit G: Story 3.6 (forward-only template change + Re-export)
   • commit H: Story 3.7 (deletion dialog + on-disk artifact options)

3. REVIEW — code-reviewer agent on full sprint diff. Run backend tests
   (use the build venv per CLAUDE.md), frontend tests, and ui-contract update
   if classes changed.

4. MARK DONE in epics.md.

## Gotchas

- Story 2.2 hash: use streaming SHA-256 (don't load file into memory) — audio
  files are large.
- Story 3.2 sanitization: reject `..`, leading `/`, control chars, and any
  Windows-reserved chars (CON, PRN, AUX, NUL, COM1-9, LPT1-9). Test with
  `frozen_clock` for deterministic timestamps.
- Story 3.4 streaming: must yield chunks — never `''.join()` the whole thing.
- Story 3.5 native save dialog: Electron-side IPC. Use existing dialog
  primitive from dashboard if one exists; don't add a new lib.
- Story 3.7 deletion: every option must be REVERSIBLE-by-default — i.e. soft
  delete or trash, never `os.remove()` without a "permanently delete" toggle.
  Durability invariant from CLAUDE.md still applies.

## Stop and ask before continuing if:

- Template grammar collides with an existing format in the codebase (check
  existing export paths before designing).
- Sprint diff exceeds ~3500 LOC.

Use Opus 4.7 reasoning fully. 1M context — load files freely.
```

---

## Prompt 3 of 5 — Sprint 3: Speakers MVP + Growth (14 stories)

```
@_bmad-output/planning-artifacts/epics.md
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/implementation-artifacts/sprint-1-design.md
@_bmad-output/implementation-artifacts/sprint-2-design.md
@CLAUDE.md

# Sprint 3 of 5 — Speakers (MVP + Propagation + Diarization Review) (Issue #104)

Implement Stories 4.1–4.5 (epic-aliases-mvp; lines 1123–1294 of epics.md)
plus Stories 5.1–5.9 (epic-aliases-growth; lines 1295–1651). 14 stories.
Largest sprint — all tightly coupled to one alias data model.
Depends on Sprint 1. Sprint 2 not strictly required but assumed merged.

## Workflow

1. DESIGN PASS — Read all 14 stories' ACs PLUS the PRD's "Diarization-Review
   Keyboard Contract" subsection (~prd.md line 900–920) and "Visual Affordance
   Specification" UX-DR3 (per-turn confidence chip — prd.md ~line 922–968)
   and ADR-009 lifecycle (v2 readiness report ~line 112–115). Write
   `_bmad-output/implementation-artifacts/sprint-3-design.md` covering:
   alias storage (with FK cascade), REST shape, alias substitution algorithm
   (must NOT mutate stored transcript), confidence-per-turn API contract,
   ADR-009 state transitions (pending→in_review→completed→released), and
   how auto-summary HOLD reads `status != 'released'`.

2. IMPLEMENT — Logical commits in dependency order:
   • commit A: Story 4.1 (table migration) + Story 4.2 (REST endpoints)
   • commit B: Story 4.3 (rename UI) + Story 4.4 (substitution rendering)
   • commit C: Story 4.5 (FK cascade verification) — ends epic-aliases-MVP
   • commit D: Stories 5.1 + 5.2 + 5.3 (alias propagation to plain-text/
     subtitles + AI summary verbatim + AI chat context)
   • commit E: Story 5.4 (confidence per-turn API)
   • commit F: Story 5.5 (confidence chip UI — UX-DR3)
   • commit G: Story 5.6 (ADR-009 lifecycle state machine)
   • commit H: Story 5.7 (persistent banner — UX-DR2) + Story 5.8 (auto-
     summary HOLD wiring)
   • commit I: Story 5.9 (focused review view + canonical Keyboard Contract)

3. REVIEW — code-reviewer agent + tests + ui-contract update.

4. MARK DONE in epics.md.

## Gotchas

- R-EL3 verbatim: alias-substituted text feeds the summary prompt. The stored
  transcript must NOT be modified — substitution happens at read time.
- ADR-009 state machine (5.6) is the spec — do not improvise transitions.
  pending→in_review (user opens review), in_review→completed (user clicks
  "Run summary now"), completed→released (auto-summary fires).
- Keyboard Contract (5.9) is non-negotiable: Tab/Shift+Tab traverse turns,
  ↑/↓ select within turn-list, ←/→ switch attribution, Enter accept,
  Esc skip, Space bulk-accept. WAI-ARIA Authoring Practices model.
- Auto-summary HOLD (5.8): exposes the hook only — the auto-summary lifecycle
  itself lands in Sprint 4 (Story 6.2). Test the hook with a fake consumer.
- Story 5.5 confidence chip: high=no chip, medium=neutral, low=amber, with %
  in tooltip.

## Stop and ask before continuing if:

- Alias substitution shows up as a perf hotspot (>10ms render added) — design
  pass should have caught this; flag for caching strategy.
- Sprint diff exceeds ~4500 LOC (this sprint runs larger by design).

Use Opus 4.7 reasoning fully. 1M context — load files freely.
```

---

## Prompt 4 of 5 — Sprint 4: Auto-Actions Lifecycle (11 stories)

```
@_bmad-output/planning-artifacts/epics.md
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/implementation-artifacts/sprint-3-design.md
@CLAUDE.md

# Sprint 4 of 5 — Auto-Actions: summary, export, retry, idempotency (Issue #104)

Implement Stories 6.1–6.11 (epic-auto-actions; lines 1652–2032 of epics.md).
11 stories — one cohesive state machine. Depends on Sprint 3 having merged
(consumes alias propagation per dependency-graph cross-feature constraint #1).

## Workflow

1. DESIGN PASS — Read all 11 stories' ACs PLUS the durability invariant in
   CLAUDE.md ("AVOID DATA LOSS AT ALL COSTS") and FR30–39 in prd.md. Write
   `_bmad-output/implementation-artifacts/sprint-4-design.md` covering:
   auto-action toggle schema on profiles, auto-summary lifecycle hook
   (where it fires in transcription pipeline), auto-export lifecycle hook,
   the persist-before-deliver invariant (write to DB BEFORE attempting
   delivery — non-negotiable per CLAUDE.md), partial-success semantics
   (one auto-action failing must not block the other), idempotent retry
   contract (FR39 — same retry call must not duplicate side effects),
   F1+F4 race-condition guard (Story 6.11 cross-feature constraint #1).

2. IMPLEMENT — Logical commits in dependency order:
   • commit A: Story 6.1 (toggle persistence)
   • commit B: Story 6.2 (auto-summary lifecycle hook) + Story 6.3 (auto-
     export lifecycle hook)
   • commit C: Story 6.4 (Persist-Before-Deliver invariant — applies to both)
   • commit D: Story 6.5 (independence + partial success)
   • commit E: Story 6.6 (StatusLight primitive — UX-DR1, with retry button)
   • commit F: Stories 6.7 (empty/truncated summary states) + 6.8 (deferred-
     retry on destination unavailability)
   • commit G: Story 6.9 (idempotent retry endpoint + manual retry button) +
     Story 6.10 (idempotent re-export semantics)
   • commit H: Story 6.11 (escalation policy + F1+F4 race-condition guard)

3. REVIEW — code-reviewer agent + tests. Pay extra attention to:
   • Durability tests (do summaries persist on WS disconnect?)
   • Idempotency tests (does retry produce the same row, not a new one?)
   • Race-condition tests (F1 firing while F4 review in-flight?)

4. MARK DONE in epics.md.

## Gotchas

- Story 6.4 is the heart of the sprint. Every auto-action artifact (summary,
  export) must hit durable storage BEFORE the delivery attempt. If WebSocket
  drops, the summary still exists. Add a regression test for each path.
- Story 6.5 partial success: if auto-summary fails but auto-export succeeds,
  the recording must reflect BOTH statuses independently — not a single
  "auto-actions failed" badge.
- Story 6.9 idempotency: use a request-id / job-id as dedup key. The retry
  must be safe to call N times.
- Story 6.11 race: F4 (diarization review) must NOT be invalidated by F1
  (auto-summary) firing first. Coordinate via the ADR-009 status field —
  auto-summary HOLD if status != 'released' (Story 5.8 already ships the
  hook).

## Stop and ask before continuing if:

- The persist-before-deliver invariant requires changing existing transcription
  pipeline structure beyond auto-action paths — escalate.
- Sprint diff exceeds ~3500 LOC.

Use Opus 4.7 reasoning fully. 1M context — load files freely.
```

---

## Prompt 5 of 5 — Sprint 5: Webhook Delivery (7 stories)

```
@_bmad-output/planning-artifacts/epics.md
@_bmad-output/planning-artifacts/prd.md
@_bmad-output/implementation-artifacts/sprint-4-design.md
@CLAUDE.md

# Sprint 5 of 5 — Webhook Delivery: WebhookWorker + persist-before-deliver (Issue #104)

Implement Stories 7.1–7.7 (epic-webhook; lines 2033–2322 of epics.md).
7 stories — self-contained delivery pipeline. Depends on Sprint 1 only,
but running last keeps Sprint 4's persist-before-deliver patterns warm.

## Workflow

1. DESIGN PASS — Read all 7 stories' ACs PLUS Sprint 4's design notes on
   persist-before-deliver (you'll reuse the pattern). Write
   `_bmad-output/implementation-artifacts/sprint-5-design.md` covering:
   webhook_deliveries table schema (R-EL33, ADR-006), URL allowlist
   validation (scheme: https only by default; IP: block private + loopback
   ranges per the `private_ip_resolver` fixture), WebhookWorker lifecycle
   (lifespan integration with FastAPI — start on app startup, drain on
   shutdown), delivery contract (10s timeout, no redirects, no decompression),
   payload versioning strategy (v1 schema with metadata-default, opt-in
   transcript-text).

2. IMPLEMENT — Logical commits in dependency order:
   • commit A: Story 7.1 (webhook_deliveries table migration)
   • commit B: Story 7.2 (URL config on profile + allowlist validation)
   • commit C: Story 7.3 (WebhookWorker skeleton + lifespan)
   • commit D: Story 7.4 (delivery contract — timeout, no redirects, no
     decompression)
   • commit E: Story 7.5 (Persist-Before-Deliver — attempt row written
     BEFORE HTTP fired)
   • commit F: Story 7.6 (payload v1 — metadata-default + opt-in transcript)
   • commit G: Story 7.7 (failed-delivery surfacing + retention cleanup)

3. REVIEW — code-reviewer agent + tests. Use:
   • `webhook_mock_receiver` fixture (from Story 1.1) — programmable
     status/delay/redirect.
   • `private_ip_resolver` fixture — for SSRF prevention tests.
   • Verify NO ssrf path: try webhook URL = http://127.0.0.1, http://10.0.0.1,
     http://[::1], http://localhost — all must be rejected.

4. MARK DONE in epics.md.

5. FINAL CLEANUP — All 56 stories now DONE. Run `/bmad-retrospective` to
   capture lessons learned (Issue #104 epic complete) before merging
   to main.

## Gotchas

- Story 7.4 contract is security-critical. NO redirects (otherwise SSRF
  bypass). NO automatic decompression (zip-bomb DoS). 10s hard timeout.
- Story 7.5 persist-before-deliver: the `webhook_deliveries` row with status
  'pending' must exist BEFORE the HTTP request is fired. If the request
  succeeds, flip to 'delivered'; on failure, 'failed' + scheduled retry.
- Story 7.6 payload version: include `"webhook_version": 1` at the top
  level so future schema changes are non-breaking.
- Tests must NOT make real network calls — use `webhook_mock_receiver`.
  ruff's banned-api rule (Story 1.1) will fail the build if you reach for
  raw httpx.

## Stop and ask before continuing if:

- IP allowlist requires a new dep (ipaddress stdlib should suffice).
- Sprint diff exceeds ~2500 LOC (this is the smallest sprint).

Use Opus 4.7 reasoning fully. 1M context — load files freely.
```

---

## Workflow tips (cross-sprint)

- Open each sprint in a **fresh** Claude Code session (`/clear` then paste). Don't continue from a prior sprint's session — the prior context is dead weight and just inflates token usage.
- Between sprints, read the prior sprint's `sprint-N-design.md` + `git log main..HEAD` before starting the next — takes 2 min, calibrates expectations.
- If a sprint's diff blows past the LOC ceiling, **stop and split** rather than ship a 5K-line PR — that's the kind of regression the sprint plan exists to prevent.
- Each sprint's design.md becomes a stable reference for the next. Don't delete them; they form the brownfield documentation trail for the QoL pack.
- After Sprint 5, run `/bmad-retrospective` to formally close the Issue #104 epic before merging `gh-104-prd` to `main`.

## Open questions / future variants

- **4-sprint compressed variant** (S4 + S5 folded into a single 18-story "Delivery" sprint) is feasible on 1M context but produces a brutal end-of-sprint diff. Only use if willing to accept ship-and-iterate-on-bug-reports rather than catching things in review.
- **Per-sprint ultrareview** (`/ultrareview` after each sprint's commits land) is recommended for Sprints 3 and 4 specifically — those carry the highest risk grade per `epics.md` (HIGH and HIGH respectively).
