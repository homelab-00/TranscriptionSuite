---
project_name: 'TranscriptionSuite'
date: '2026-05-03'
source_prd: '_bmad-output/planning-artifacts/prd.md'
source_readiness_report: '_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md'
restructure_origin: 'Readiness report Step 5 §G (Recommended Restructuring) — overrides PRD frontmatter `plannedEpicGroupings`'
stepsCompleted: ['step-01-validate', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments:
  - '_bmad-output/planning-artifacts/prd.md'
  - '_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md'
  - '_bmad-output/planning-artifacts/handoff-prompts-readiness-fixes.md'
  - 'docs/project-context.md'
epicCount: 8
storyCount: 57
frCoverage: '54/54 (100%)'
totalEngineerDays: '52-58 (vs PRD baseline 32-44; delta primarily epic-foundations cross-cutting infra not previously budgeted, plus webhook 6-8d acknowledged underestimate)'
constraintsEnforced:
  - 'No forward dependencies between epics (validated via dependency map below)'
  - 'epic-aliases-growth precedes epic-auto-actions (resolves F1↔F4 race, cross-feature constraint #1)'
  - 'Persist-Before-Deliver (NFR16) AC on every artifact-producing story'
  - 'FR51-54 accessibility AC on every alias/auto-action/export story'
  - 'Diarization-Review Keyboard Contract cited verbatim in epic-aliases-growth review-UI story (5.9)'
  - 'First story of each epic that needs new tables/columns includes the migration'
---

# TranscriptionSuite — Epic Breakdown (Audio Notebook QoL Pack)

## Overview

This document decomposes the Audio Notebook QoL pack PRD (Issue #104) into 8 epics and 58 stories, organized to (a) eliminate forward dependencies flagged in the 2026-05-03 implementation readiness check, (b) home the previously-orphaned FR1-FR4 (audio import/dedup) and FR43-FR47 (extensibility webhook), and (c) explicitly inherit cross-cutting requirements (FR49/FR50 keychain; FR51-FR54 accessibility) into a foundational epic that lands first.

The 8-epic structure replaces the PRD's frontmatter `plannedEpicGroupings` (epic-a/b/c) which the readiness check rejected for forward-dependency violations and unhomed FRs. See `implementation-readiness-report-2026-05-03.md` Step 5 §G for the restructuring rationale.

---

## Requirements Inventory

### Functional Requirements (54 total)

**Recording Import & Identity (FR1–FR4) — MVP**
- **FR1 [MVP]:** Users can import audio files via the existing file-picker flow with no profile required.
- **FR2 [MVP]:** On import, the system computes a content hash (SHA-256 of normalized PCM) and stores it on the recording.
- **FR3 [MVP]:** When an imported file matches an existing recording's content hash, users see a prompt to either reuse the existing transcript or create a new entry.
- **FR4 [MVP]:** Audio dedup operates per-user-library scope; hashes are not compared across installations.

**Manual Export & Download (FR5–FR9) — MVP**
- **FR5 [MVP]:** Users can download a completed recording's transcript as plain text via an explicit "Download transcript" button.
- **FR6 [MVP]:** Users can download a completed recording's AI summary as plain text via an explicit "Download summary" button (disabled with tooltip when no summary).
- **FR7 [MVP]:** Manual download triggers the native OS file-save dialog with sensibly-named filename and OS-default Downloads folder.
- **FR8 [MVP]:** Users can override filename and destination per-click via the file-save dialog.
- **FR9 [MVP]:** Downloaded files use plain-text format (one speaker turn per blank-line block; no subtitle timestamps).

**Profile Management (FR10–FR20) — Cross/MVP/Growth**
- **FR10 [Cross]:** Users can CRUD named profiles grouping filename template, destination, auto-action toggles, AI summary prompt, webhook config (Growth).
- **FR11 [Cross]:** Profile reads return only public fields; private fields (paths, webhook URLs/auth, API keys) are write-only.
- **FR12 [MVP]:** Filename template uses extensible placeholder grammar with server-side validation.
- **FR13 [MVP]:** Live filename preview updates as user types template.
- **FR14 [MVP]:** Destination folder via native OS folder picker.
- **FR15 [Growth]:** Empty-profile screen pre-populates fields with sane defaults + inline help banner. No multi-step wizard (deferred to Vision).
- **FR16 [Cross]:** Profile JSON schema versioned (`schema_version: "MAJOR.MINOR"`); rejects unknown majors with explicit error.
- **FR17 [Growth]:** Filename-template changes apply forward-only; opt-in per-recording re-export via context menu.
- **FR18 [Cross]:** Each transcription job snapshots its profile at job-start; profile edits don't affect running jobs.
- **FR19 [Cross]:** Mid-flight crash recovery rehydrates profile snapshot from job row.
- **FR20 [Growth]:** Users can switch active profile mid-session; applies to subsequently-started jobs only.

**Speaker Aliasing (FR21–FR29) — MVP/Growth**
- **FR21 [MVP]:** Users can rename "Speaker 1", etc. to real names per-recording (recording-level scope).
- **FR22 [MVP]:** Speaker aliases substitute into the transcript view (MVP slice).
- **FR23 [Growth]:** Aliases substitute into plain-text exports, subtitle exports, AI summary prompt context, AI chat context.
- **FR24 [Growth]:** AI summary uses aliases verbatim — never infers, merges, or rewrites.
- **FR25 [Growth]:** Low-confidence diarization turns flagged with persistent banner; auto-summary HOLDS until review.
- **FR26 [Growth]:** Diarization-review focused view: confidence-threshold filter, bulk-accept, keyboard-navigable end-to-end.
- **FR27 [Growth]:** Diarization-review state persists across app restarts; auto-summary held until review explicitly completed.
- **FR28 [Growth]:** "Review uncertain turns" banner is persistent (no auto-dismiss).
- **FR29 [MVP]:** REST endpoints `GET/PUT /api/recordings/{id}/aliases`.

**Auto Post-Transcription Actions (FR30–FR39) — Growth**
- **FR30 [Growth]:** Profile can auto-generate AI summary on transcription completion.
- **FR31 [Growth]:** Profile can auto-export transcript and summary to destination folder.
- **FR32 [Growth]:** Auto-summary saved back to recording on success.
- **FR33 [Growth]:** Each auto-action persists durably before client delivery (Persist-Before-Deliver).
- **FR34 [Growth]:** Auto-actions independent — partial success possible.
- **FR35 [Growth]:** Failed auto-actions surface as recoverable status badge + single-click retry; transient failures auto-retry once.
- **FR36 [Growth]:** Empty AI summaries surface as distinct "summary empty" status.
- **FR37 [Growth]:** Token-truncated summaries surface as distinct "summary truncated" status.
- **FR38 [Growth]:** Auto-export to unavailable destination defers and auto-retries when available; transcript safe in recording during deferral.
- **FR39 [Growth]:** Auto-action retry idempotent — replaying a successful action returns "already complete".

**Pre-Transcription Model Profiles (FR40–FR42) — Growth**
- **FR40 [Growth]:** Configure named model profiles (STT model + language settings).
- **FR41 [Growth]:** One-click switch active model profile; choice persists across restarts.
- **FR42 [Growth]:** Active model profile independent of post-transcription profile.

**Extensibility Webhook (FR43–FR47) — Growth**
- **FR43 [Growth]:** Configure webhook URL on profile to receive HTTP POST on transcription completion.
- **FR44 [Growth]:** Webhook URL allowlist: `https://` + explicit `http://localhost*`; private IPs rejected at profile save.
- **FR45 [Growth]:** 10s deadline; no redirects; no decompression; HTTP status as ground truth.
- **FR46 [Growth]:** Payload defaults to metadata-only; transcript-text opt-in per profile.
- **FR47 [Growth]:** Webhook deliveries persisted before firing; failed deliveries surface in status AND remain in table.

**Privacy, Security & Accessibility (FR48–FR54) — Cross**
- **FR48 [Cross]:** Recording deletion does NOT propagate to on-disk artifacts by default; dialog states this explicitly + offers per-deletion option to remove.
- **FR49 [Cross]:** Private profile fields stored via OS keychain (Keychain/DPAPI/libsecret); never plain-text.
- **FR50 [Cross]:** Headless fallback: encrypted-file storage gated by `KEYRING_BACKEND_FALLBACK=encrypted_file` env flag.
- **FR51 [Cross]:** All new UI surfaces operable via keyboard alone.
- **FR52 [Cross]:** Status changes announced via ARIA live regions.
- **FR53 [Cross]:** Interactive elements have descriptive labels.
- **FR54 [Cross]:** Diarization-review supports turn-by-turn screen-reader navigation announcing content + speaker + confidence.

### NonFunctional Requirements (55 total)

**Performance** — NFR1 (CRUD latency <15% regression), NFR2 (preview p95 <50ms), NFR3-4 (auto-action lifecycle hooks fire ≤2s), NFR5 (webhook 10s timeout), NFR6 (audio hash inside existing window), NFR7 (review filter linearity r²>0.95).

**Security** — NFR8 (private-field encryption AES-256-GCM + secrets/master.key), NFR9 (SSRF block), NFR10 (scheme allowlist), NFR11 (no redirects), NFR12 (no decompression), NFR13 (schema version validation), NFR14 (filename injection prevention), NFR15 (auth model unchanged).

**Reliability & Durability** — NFR16 (Persist-Before-Deliver invariant), NFR17 (webhook delivery durability), NFR18 (profile snapshot durability), NFR19 (retry escalation bounded), NFR20 (deferred-retry destination), NFR21 (migration non-destructive), NFR22 (forward-only), NFR23 (review state persists), NFR24a (bootstrap consistency 30s), NFR24b (delivery catch-up 5min async).

**Accessibility** — NFR25 (Lighthouse ≥90 CI gate), NFR26-30 (keyboard, ARIA, labels, screen-reader, tab-order).

**Integration** — NFR31 (webhook payload versioned), NFR32 (profile schema versioned), NFR33 (`keyring >= 25.0, < 26`), NFR34 (`keyrings.alt` fallback documented).

**Privacy & Data Handling** — NFR35 (no telemetry), NFR36-38 (deletion semantics, payload metadata default, right-to-erasure), NFR39 (i18n deferred), NFR40 (`webhook_deliveries` 30-day retention).

**Observability** — NFR41 (status badges primary surface), NFR42 (webhook table queryable), NFR43 (persistent banners), NFR44 (structlog INFO no PII), NFR45 (diagnostic-paste).

**Concurrency & Resource** — NFR46 (last-write-wins profile concurrent edit), NFR47 (worker memory p95 ≤50MB no leak), NFR48 (plain-text export streams), NFR49 (multi-user out of scope).

**Discoverability** — NFR50 (visual contiguity for new affordances).

**Test Coverage & Enforcement** — NFR51 (no coverage regression), NFR52 (per-feature test minimums), NFR53 (Day-1 fixtures), NFR54 (linter-enforced test discipline), NFR55 (CodeQL clean).

### Additional Requirements

**Architecture Decision Records (ADRs)**
- ADR-001 — REST CRUD `/api/profiles`
- ADR-002 — Audio dedup `audio_hash` column on `transcription_jobs`
- ADR-003 — Profile snapshot as JSON blob + `snapshot_schema_version`
- ADR-004 — Webhook delivery via `asyncio.create_task`
- ADR-005 — Speaker alias scope per-recording
- ADR-006 — Webhook deliveries persisted in `webhook_deliveries` table
- ADR-007 — React Query invalidation as profile-state propagation; `activeProfileId` in Zustand
- ADR-008 — Crash recovery rehydrates profile snapshot
- ADR-009 — Diarization-review state persistence in `recording_diarization_review` table

**12 New API Endpoints**
- `GET/POST/GET/PUT/DELETE /api/profiles[/{id}]`
- `GET/PUT /api/recordings/{id}/aliases`
- `POST /api/recordings/{id}/reexport`
- `GET /api/recordings/{id}/diarization-confidence`
- `POST /api/recordings/{id}/diarization-review`
- `POST /api/recordings/import/dedup-check`
- `POST /api/recordings/{id}/auto-actions/retry`

**Modified endpoints:** `POST /api/transcribe/file` accepts optional `profile_id` (FR18 snapshot at job-start).

**Cross-Feature Constraints**
1. F1 must wait for F4 propagation before auto-summary (anti-stale-alias race) — enforced by epic ordering.
2. F1 must respect Persist-Before-Deliver — auto-summary persists before client notification.
3. F4 aliases must persist before any export delivers them.
4. F2 filename templates must sanitize for path traversal, Windows reserved names, Unicode, 255-char limits.

**R-EL Carryover (35 items)** — Full list in PRD Appendix C; each story below cites the R-EL items it closes.

**Day-1 Dependencies (NFR53)**
- Backend: `keyring >= 25.0, < 26`, `keyrings.alt`, `pytest-benchmark`
- Frontend: `@lhci/cli@0.14`
- Config: `docker-compose.yml` bind-mount `/secrets`, ruff `flake8-tidy-imports.banned-api`, ESLint `no-restricted-imports`, Lighthouse CI workflow.

**Day-1 Test Fixtures (NFR53)** — `webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock` — must land in `server/backend/tests/conftest.py` BEFORE feature work.

### UX Design Requirements

The PRD does not have a separate UX Design document; UX requirements are embedded in the PRD as:

- **Visual Affordance Specification (UI Contract)** — three new affordance classes:
  - **UX-DR1 — Status Badges:** reuse `StatusLight` primitive; severity ok/warn/error; inline ⟳ Retry button; auto-dismiss on success.
  - **UX-DR2 — Persistent Banners:** reuse `QueuePausedBanner` pattern; yellow/amber; persistent until user action; "Review uncertain turns" CTA.
  - **UX-DR3 — Per-Turn Confidence Indicators:** chip beside speaker label; high (no chip) / medium (neutral) / low (amber); tooltip with %.
- **UX-DR4 — Diarization-Review Keyboard Contract** (canonical spec — cited verbatim in Story 5.9):
  - Tab/Shift+Tab traverse turns
  - ↑/↓ move selection within focused turn-list (composite widget)
  - ←/→ switch attribution within focused turn
  - Enter accept; Esc skip; Space bulk-accept visible turns
- **UX-DR5 — UI contract migration AC:** Any new visual element MUST run `npm run ui:contract:extract → build → validate --update-baseline → check`.

---

## FR Coverage Map

> **100% explicit coverage of FR1–FR54.** Every FR is anchored to exactly one story (with cross-cutting FR49–FR54 inheriting into multiple downstream stories per dedicated AC clauses).

| FR | Tier | Anchored Epic | Anchored Story |
|---|---|---|---|
| FR1 | MVP | epic-import | 2.3 |
| FR2 | MVP | epic-import | 2.1 (migration), 2.2 (hash compute) |
| FR3 | MVP | epic-import | 2.4 |
| FR4 | MVP | epic-import | 2.5 |
| FR5 | MVP | epic-export | 3.5 |
| FR6 | MVP | epic-export | 3.5 |
| FR7 | MVP | epic-export | 3.5 |
| FR8 | MVP | epic-export | 3.5 |
| FR9 | MVP | epic-export | 3.4 |
| FR10 | Cross | epic-foundations | 1.2 |
| FR11 | Cross | epic-foundations | 1.2 |
| FR12 | MVP | epic-export | 3.1 (engine), 3.2 (validation) |
| FR13 | MVP | epic-export | 3.3 |
| FR14 | MVP | epic-foundations | 1.4 |
| FR15 | Growth | epic-foundations | 1.5 |
| FR16 | Cross | epic-foundations | 1.2 |
| FR17 | Growth | epic-export | 3.6 |
| FR18 | Cross | epic-foundations | 1.3 |
| FR19 | Cross | epic-foundations | 1.3 |
| FR20 | Growth | epic-foundations | 1.6 |
| FR21 | MVP | epic-aliases-mvp | 4.1 (migration), 4.3 (rename UI) |
| FR22 | MVP | epic-aliases-mvp | 4.4 |
| FR23 | Growth | epic-aliases-growth | 5.1, 5.2, 5.3 |
| FR24 | Growth | epic-aliases-growth | 5.2 |
| FR25 | Growth | epic-aliases-growth | 5.8 |
| FR26 | Growth | epic-aliases-growth | 5.9 |
| FR27 | Growth | epic-aliases-growth | 5.6 |
| FR28 | Growth | epic-aliases-growth | 5.7 |
| FR29 | MVP | epic-aliases-mvp | 4.2 |
| FR30 | Growth | epic-auto-actions | 6.1, 6.2 |
| FR31 | Growth | epic-auto-actions | 6.1, 6.3 |
| FR32 | Growth | epic-auto-actions | 6.2 |
| FR33 | Growth | epic-auto-actions | 6.4 |
| FR34 | Growth | epic-auto-actions | 6.5 |
| FR35 | Growth | epic-auto-actions | 6.6, 6.9 |
| FR36 | Growth | epic-auto-actions | 6.7 |
| FR37 | Growth | epic-auto-actions | 6.7 |
| FR38 | Growth | epic-auto-actions | 6.8 |
| FR39 | Growth | epic-auto-actions | 6.9 |
| FR40 | Growth | epic-model-profiles | 8.1, 8.2 |
| FR41 | Growth | epic-model-profiles | 8.3, 8.4 |
| FR42 | Growth | epic-model-profiles | 8.1 |
| FR43 | Growth | epic-webhook | 7.2 |
| FR44 | Growth | epic-webhook | 7.2 |
| FR45 | Growth | epic-webhook | 7.4 |
| FR46 | Growth | epic-webhook | 7.6 |
| FR47 | Growth | epic-webhook | 7.5, 7.7 |
| FR48 | Cross | epic-export | 3.7 |
| FR49 | Cross | epic-foundations | 1.7 |
| FR50 | Cross | epic-foundations | 1.7 |
| FR51 | Cross | epic-foundations (scaffold 1.8) | inherited as AC by 3.5, 4.3, 4.4, 5.7, 5.9, 6.6, 8.2 |
| FR52 | Cross | epic-foundations (scaffold 1.8) | inherited as AC by 3.5, 5.7, 5.8, 6.6 |
| FR53 | Cross | epic-foundations (scaffold 1.8) | inherited as AC by 3.5, 6.6, 8.2 |
| FR54 | Cross | epic-foundations (scaffold 1.9) | enforced in 5.9 |

---

## Epic Dependency Graph

```
                         epic-foundations (Cross — lands first)
                                  │
        ┌────────────┬────────────┼────────────┬────────────┬────────────┐
        ▼            ▼            ▼            ▼            ▼            ▼
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

**Critical-path:** epic-foundations → epic-aliases-mvp → epic-aliases-growth → epic-auto-actions
**Parallel-shippable after foundations:** epic-import + epic-export (MVP chain), epic-webhook, epic-model-profiles

**Ship sequencing:**
- **MVP gate (`audio_notebook_qol_v1` flag):** epic-foundations (MVP-portion) + epic-import + epic-export + epic-aliases-mvp
- **Growth gate (`v1.4.1` tag):** epic-foundations (Growth-portion) + epic-aliases-growth + epic-auto-actions + epic-webhook + epic-model-profiles

---

## Epic List

| # | Epic | Tier | Risk | Eng-days | Stories | FR Count |
|---|---|---|---|---|---|---|
| 1 | epic-foundations | Cross | MED-HIGH | 11-14 | 9 | 11 (FR10/11/14-16/18-20, FR49/50, scaffold for FR51-54) |
| 2 | epic-import | MVP | LOW-MED | 3-4 | 5 | 4 (FR1-4) |
| 3 | epic-export | MVP | LOW-MED | 7-9 | 7 | 9 (FR5-9, FR12, FR13, FR17, FR48) |
| 4 | epic-aliases-mvp | MVP | MED-HIGH | 5-7 | 5 | 3 (FR21, FR22, FR29) |
| 5 | epic-aliases-growth | Growth | HIGH | 7-9 | 9 | 6 (FR23-28) |
| 6 | epic-auto-actions | Growth | HIGH | 10-12 | 11 | 10 (FR30-39) |
| 7 | epic-webhook | Growth | HIGH | 7-9 | 7 | 5 (FR43-47) |
| 8 | epic-model-profiles | Growth | MED | 3-4 | 4 | 3 (FR40-42) |
| **Σ** | — | — | — | **53-68** | **57** | **50 unique + 4 cross-cutting (FR49-54) inherited (FR48 in epic-export)** |

---

# Epic 1: epic-foundations — Profile system, keychain, accessibility scaffold, test infra

## Epic Goal

**As the** TranscriptionSuite implementer
**I want** the profile-system foundation, OS-keychain integration, accessibility scaffold, ADR-009 review-state table, and Day-1 test fixtures to land first
**So that** all downstream feature epics (import, export, aliases, auto-actions, webhook, model-profiles) build on a stable base — eliminating the implicit-orphan FRs (FR10, FR11, FR14-16, FR18-20) flagged by the readiness check and unblocking parallel shipping after this epic completes.

**Tier:** Cross (foundational; MVP-portion ships under `audio_notebook_qol_v1` flag, Growth-portion under `v1.4.1` tag)
**Dependencies:** None — this epic must land first.
**FRs covered:** FR10, FR11, FR14, FR15, FR16, FR18, FR19, FR20, FR49, FR50; scaffolds FR51, FR52, FR53, FR54.
**A11y inheritance:** Sets up the scaffold; downstream stories inherit specific ACs.
**Risk grade:** MEDIUM-HIGH — touches `transcription_jobs` durability column, secrets storage (NFR8), Linux/Windows/macOS keychain integration.
**Engineer-day budget:** 11-14 dev-days

---

### Story 1.1: Day-1 test fixtures + linter-enforced test discipline

**As a** backend engineer
**I want** the canonical test fixtures (`webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock`) and linter rules in place before any feature work begins
**So that** the QoL pack does not accumulate "6 inconsistent ad-hoc httpx mocks" — discipline is enforced by tooling, not culture.

**FR/NFR coverage:** NFR53, NFR54
**Depends on:** None (first story of first epic)
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Fixtures land in conftest**
**Given** an empty `server/backend/tests/conftest.py` for the QoL pack feature work
**When** Story 1.1 is complete
**Then** the file declares pytest fixtures `webhook_mock_receiver` (aiohttp `TestServer` with programmable status/delay/redirect), `private_ip_resolver` (monkeypatches `socket.getaddrinfo`), `fake_keyring` (in-memory `keyring` backend via `keyring.set_keyring()`), `profile_snapshot_golden` (loads JSON snapshots from `tests/fixtures/profile_snapshots/`), and `frozen_clock` (freezegun-wrapped injectable clock)
**And** each fixture has a smoke test (`test_<fixture>_self_check`) confirming it is wired correctly.

**AC2 — Backend linter rules**
**Given** `server/backend/pyproject.toml`
**When** ruff runs `ruff check tests/`
**Then** `time.sleep`, `datetime.datetime.now`, `httpx.Client`, `httpx.AsyncClient` are flagged inside `tests/` via `[tool.ruff.lint.flake8-tidy-imports.banned-api]`
**And** approved alternatives (`asyncio.Event.wait()` with timeout, `frozen_clock`, `webhook_mock_receiver`) are documented in a comment block at the top of `conftest.py`.

**AC3 — Frontend linter rules**
**Given** `dashboard/.eslintrc`
**When** ESLint runs against `**/*.test.ts`
**Then** the same banned-API set is enforced via `no-restricted-imports`.

**AC4 — CI gate**
**Given** the existing `.github/workflows/dashboard-quality.yml` and backend test workflow
**When** a developer pushes a PR
**Then** the lint step fails the build if any banned API is used in a test file.

---

### Story 1.2: `profiles` table migration + schema-versioned CRUD

**Status: DONE (sprint 1 — commit 893ea98)**

**As a** backend engineer
**I want** the `profiles` table created with explicit public/private field separation and `schema_version` validation
**So that** profile CRUD endpoints can be implemented (FR10) without refactoring later, and unknown major versions are rejected at the API boundary (FR16, NFR13, R-EL30).

**FR/NFR coverage:** FR10, FR11, FR16, NFR13, NFR21, NFR22, NFR32, NFR46, R-EL22, R-EL30
**ADRs:** ADR-001 (REST CRUD), ADR-003 (JSON snapshot — partial; the column lives on `transcription_jobs` per Story 1.3)
**Depends on:** Story 1.1
**Estimated dev-days:** 2d
**Includes migration:** **YES** — `profiles` table created here.

**Acceptance Criteria:**

**AC1 — Migration creates profiles table**
**Given** an Alembic migration named `add_profiles_table`
**When** `alembic upgrade head` runs against an empty DB
**Then** the `profiles` table exists with columns `(id PK, name TEXT NOT NULL, description TEXT, schema_version TEXT NOT NULL, public_fields_json TEXT NOT NULL, private_field_refs_json TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)`
**And** `private_field_refs_json` stores keychain reference IDs only — never plaintext (FR11, R-EL22)
**And** the migration is forward-only with no downgrade script (NFR22).

**AC2 — Migration is non-destructive on existing DB**
**Given** a v1.3.x DB with existing `transcription_jobs` and `recordings` rows
**When** `alembic upgrade head` runs
**Then** existing rows are unmodified and the migration creates only new tables/columns (NFR21)
**And** a fixture-DB regression test (`test_profile_migration_non_destructive`) asserts row counts and PK integrity for `transcription_jobs` and `recordings` are unchanged pre/post.

**AC3 — REST CRUD endpoints**
**Given** `api/routes/notebook.py`
**When** an authenticated client calls `GET /api/profiles`, `POST /api/profiles`, `GET /api/profiles/{id}`, `PUT /api/profiles/{id}`, `DELETE /api/profiles/{id}`
**Then** each endpoint returns/accepts JSON matching the documented schema (ADR-001)
**And** `GET` responses NEVER return private fields — only public fields (FR11)
**And** `POST/PUT` accept private fields write-only and persist them via the keychain (Story 1.7 dependency — stub via `fake_keyring` for now).

**AC4 — Schema version validation**
**Given** a `PUT /api/profiles/{id}` request with `schema_version: "99.0"` (unknown major)
**When** the endpoint validates the body
**Then** it returns HTTP 400 with body `{"error": "unsupported_schema_version", "supported": ["1.0"], "received": "99.0"}` (FR16, NFR13, R-EL30).

**AC5 — Last-write-wins concurrent-edit semantics**
**Given** two clients editing the same profile concurrently
**When** both call `PUT /api/profiles/{id}` within milliseconds
**Then** the later request's `updated_at` overwrites the earlier (NFR46)
**And** stale-cache discovery on the frontend surfaces a toast "Profile changed in another window — reloading" (NFR46 — documented divergence from config.yaml single-editor pattern).

**AC6 — Persist-Before-Deliver (NFR16)**
**Given** a `POST /api/profiles` request
**When** the server commits the row to SQLite
**Then** the HTTP 201 response is sent ONLY AFTER the SQLite commit succeeds — never before (NFR16).

---

### Story 1.3: Profile snapshot column on `transcription_jobs` + crash rehydration

**Status: DONE (sprint 1 — commit 893ea98)**

**As a** backend engineer
**I want** the `transcription_jobs` table to carry an immutable JSON profile snapshot at job-start, with crash recovery rehydrating it before resuming
**So that** profile edits during a running job do not affect the job (FR18) and mid-flight crashes preserve the durability invariant (FR19, R-EL21, R-EL35).

**FR/NFR coverage:** FR18, FR19, NFR16, NFR18, NFR24a, R-EL21, R-EL35
**ADRs:** ADR-003 (JSON blob), ADR-008 (crash recovery rehydration)
**Depends on:** Story 1.2
**Estimated dev-days:** 1.5d
**Includes migration:** **YES** — `job_profile_snapshot` + `snapshot_schema_version` columns on `transcription_jobs`.

**Acceptance Criteria:**

**AC1 — Migration adds snapshot columns**
**Given** an Alembic migration named `add_profile_snapshot_to_transcription_jobs`
**When** `alembic upgrade head` runs
**Then** `transcription_jobs` gains columns `(job_profile_snapshot TEXT, snapshot_schema_version TEXT)`, both nullable for legacy rows
**And** existing job rows have NULL in both columns (NFR21).

**AC2 — Snapshot at job-start (FR18, R-EL21)**
**Given** a `POST /api/transcribe/file` request with `profile_id=p123`
**When** the job is created in `transcription_jobs`
**Then** the row's `job_profile_snapshot` contains a frozen JSON dump of profile `p123`'s state at that instant
**And** the snapshot is read by the worker, never live profile state.

**AC3 — Live edit does not affect running job**
**Given** a job is running with snapshot of profile `p123` v1
**When** the user `PUT /api/profiles/p123` to v2 mid-job
**Then** the running job continues to use the v1 snapshot
**And** the next job started after the edit uses v2.

**AC4 — Crash recovery rehydrates snapshot (FR19, R-EL35)**
**Given** a server crash with an in-progress job whose `transcription_jobs` row has a non-NULL snapshot
**When** the server restarts and `transcription_job_tracker` resumes the job
**Then** the worker rehydrates the snapshot from the row before continuing
**And** the resumed job uses the snapshot's destination/template/toggles, not live profile state.

**AC5 — Bootstrap consistency (NFR24a)**
**Given** a server restart with N in-flight jobs
**When** the server reaches "ready" state (accepts requests)
**Then** rehydration of all N snapshots completes within 30 seconds of backend startup
**And** orphan-sweep (`periodic_orphan_sweep`) is part of this critical path.

**AC6 — Persist-Before-Deliver (NFR16)**
**Given** snapshot serialization at job-start
**When** the worker begins transcription
**Then** the snapshot row commit MUST complete before the worker fires; a fixture-DB test asserts the SQLite write happens before the `engine.transcribe()` call.

---

### Story 1.4: OS folder picker primitive

**Status: DONE (sprint 1 — commit 0325c42)**

**As a** dashboard user
**I want** a native OS folder picker (not free-text input) when choosing a destination folder in a profile
**So that** I cannot fat-finger an invalid path, and the picker feels native on each OS.

**FR/NFR coverage:** FR14, FR53 (descriptive label inherited)
**Depends on:** Story 1.2
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Native picker invocation**
**Given** the profile-edit UI's "Destination folder" field
**When** the user clicks the field's "Choose folder…" button
**Then** the native OS folder picker opens via Electron's `dialog.showOpenDialog({ properties: ['openDirectory'] })`
**And** the chosen path populates the field; cancel leaves the field unchanged.

**AC2 — Cross-platform smoke test**
**Given** a manual test on Linux KDE Wayland, Windows 11, and macOS
**When** the user clicks the picker button on each platform
**Then** the native picker opens with the platform-correct UI; the chosen path is correctly returned to the React state.

**AC3 — Accessibility (FR51, FR53)**
**Given** keyboard-only navigation
**When** the user Tabs to the picker button and presses Enter or Space
**Then** the dialog opens; the button has `aria-label="Choose destination folder"` (not just "Choose folder")
**And** focus returns to the button after dialog dismissal.

---

### Story 1.5: Empty-profile screen with sane defaults + inline help banner

**Status: DONE (sprint 1 — commit 6b9c20c)**

**As a** new Configurator (Maria, J2)
**I want** the empty-profile screen to pre-populate fields with sensible defaults and show one inline help banner explaining the field-first flow
**So that** I can save-as-is to use the defaults, or override what I want — without a multi-step wizard slowing me down.

**FR/NFR coverage:** FR15, FR51 (keyboard navigable), FR53 (descriptive labels)
**Depends on:** Story 1.2, Story 1.4
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Pre-populated defaults**
**Given** the user opens Settings → Profiles → "New profile" (no profiles exist yet)
**When** the empty-profile form renders
**Then** the filename template field defaults to `{date} {title}.txt`
**And** the destination folder defaults to the OS user-Documents folder (per `os.homedir()` + platform-specific `Documents`)
**And** the AI summary toggle and auto-export toggle default to OFF (Lurker-safe).

**AC2 — Inline help banner**
**Given** the empty-profile form
**When** it renders for the first time
**Then** a single banner appears at the top reading: *"Edit any field below to customize, or save as-is to use the defaults."*
**And** the banner uses the `QueuePausedBanner` visual primitive (UX-DR2)
**And** the banner can be dismissed with an "X" button; dismissal persists in localStorage so it does not reappear.

**AC3 — No multi-step wizard**
**Given** the empty-profile screen
**When** any user interacts with it
**Then** there are no "Next" / "Back" buttons; no multi-step navigation; no progress indicator
**And** Save/Cancel are the only commit actions (the wizard is deferred to Phase 3 Vision).

**AC4 — Accessibility (FR51)**
**Given** keyboard-only navigation
**When** the user Tabs through the form
**Then** focus order is: banner-dismiss → name → description → filename template → destination → AI summary toggle → auto-export toggle → Save → Cancel.

---

### Story 1.6: Active profile switch (`activeProfileId` in Zustand)

**Status: DONE (sprint 1 — commit 6b9c20c)**

**As a** dashboard user with multiple profiles
**I want** a profile selector in the toolbar that switches the active profile in one click
**So that** subsequently-started jobs use the new profile (FR20), and my choice persists across app restarts.

**FR/NFR coverage:** FR20
**ADRs:** ADR-007 (React Query for profile data; Zustand for `activeProfileId`)
**Depends on:** Story 1.2
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Selector switches active profile**
**Given** profiles A, B, C exist; A is active
**When** the user clicks the toolbar profile dropdown and selects B
**Then** `activeProfileId` in Zustand updates to B
**And** the value persists to electron-store under key `notebook.activeProfileId`
**And** the next `POST /api/transcribe/file` uses `profile_id=B`.

**AC2 — Mid-session edit does not affect running jobs**
**Given** a job is running with snapshot of profile A
**When** the user switches active profile to B
**Then** the running job continues with A's snapshot (depends on Story 1.3 snapshot semantics)
**And** only the next `POST /api/transcribe/file` uses B.

**AC3 — Persistence across restart**
**Given** the user has set active profile to C
**When** the app restarts
**Then** the toolbar selector renders with C selected on first paint.

---

### Story 1.7: OS keychain integration + `keyrings.alt` headless fallback

**Status: DONE (sprint 1 — commit da5038f)**

**As a** backend engineer
**I want** private profile fields stored via the OS keychain (Keychain/DPAPI/libsecret) with an explicit `keyrings.alt` EncryptedFile fallback for headless Linux/Docker
**So that** webhook tokens, API keys, and auth headers never sit plain-text on disk (FR49, FR50, NFR8).

**FR/NFR coverage:** FR49, FR50, NFR8, NFR33, NFR34
**Depends on:** Story 1.1 (`fake_keyring` fixture), Story 1.2 (private fields exist on profiles)
**Estimated dev-days:** 3d
**Includes migration:** No (config-bootstrap only — `secrets/master.key` generation)

**Acceptance Criteria:**

**AC1 — `keyring` dependency added**
**Given** `server/backend/pyproject.toml`
**When** `uv sync` runs
**Then** `keyring >= 25.0, < 26` is installed (NFR33)
**And** `keyrings.alt >= 5.0` is installed as an opt-in extra (NFR34).

**AC2 — Keychain wrapper module**
**Given** a new module `server/backend/server/utils/keychain.py`
**When** code calls `keychain.set("profile.123.webhook_token", "secret-value")`
**Then** the value is stored in the OS-native secret store on macOS / Windows / Linux-with-libsecret
**And** `keychain.get("profile.123.webhook_token")` returns the value
**And** `keychain.delete(...)` removes it.

**AC3 — Headless fallback gated by env flag**
**Given** `KEYRING_BACKEND_FALLBACK=encrypted_file` is set AND no system keychain is available
**When** `keychain.set(...)` is called
**Then** the value is stored in `keyrings.alt.file.EncryptedKeyring` with key derived from `secrets/master.key` via PBKDF2 (FR50, R-EL34, NFR8)
**And** if the env flag is NOT set and no keychain is available, the call raises `KeychainUnavailableError` with an actionable message ("Set KEYRING_BACKEND_FALLBACK=encrypted_file to use file fallback — security delta: see deployment-guide.md").

**AC4 — `secrets/master.key` bootstrap (NFR8 AC1)**
**Given** a fresh installation with no `secrets/master.key`
**When** the server starts for the first time
**Then** `server/utils/config_migration.py` auto-generates a 32-byte random secret at `secrets/master.key` with file mode 0600
**And** `docker-compose.yml` variants bind-mount `/secrets` so the key survives container rebuilds
**And** the existing test `test_config_migration_generates_secret_on_v13x_config` (NFR8 AC1) passes.

**AC5 — Fixture isolates real keychain in tests**
**Given** the `fake_keyring` fixture from Story 1.1
**When** any test under `tests/` runs
**Then** real OS keychain is never touched; all reads/writes go through the in-memory backend.

**AC6 — Security delta documented**
**Given** `docs/deployment-guide.md`
**When** Story 1.7 is complete
**Then** the doc has a section "Keychain fallback (encrypted-file mode)" describing what the fallback protects against (casual disk access, cloud-sync exposure) and what it does NOT protect against (local attacker with `secrets/master.key` access).

---

### Story 1.8: Accessibility scaffold — ARIA live regions, tab-order, label conventions

**Status: DONE (sprint 1 — commit E; AC4 Lighthouse-CI gate intentionally downgraded to ESLint jsx-a11y per design §0; full Lighthouse gate captured in deferred-work.md for MVP-cut PR)**

**As a** screen-reader user (Lia, J7)
**I want** the QoL pack to ship with a reusable ARIA-live-region helper, tab-order conventions, and descriptive-label helpers
**So that** every downstream UI story can inherit accessibility ACs from a single source instead of inventing them per-feature.

**FR/NFR coverage:** FR51, FR52, FR53, NFR25, NFR26, NFR27, NFR28, NFR30
**Depends on:** Story 1.1
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — ARIA live region helper**
**Given** a new module `dashboard/src/hooks/useAriaAnnouncer.ts`
**When** any component calls `announce("Transcription complete", { politeness: "polite" })`
**Then** the message is appended to a hidden `<div role="status" aria-live="polite">` rendered at app root
**And** message is cleared after 5 seconds to allow re-announcement of identical text
**And** `politeness: "assertive"` writes to a separate `aria-live="assertive"` region.

**AC2 — Tab-order conventions**
**Given** `docs/dashboard/accessibility.md` (new doc)
**When** a developer adds a new feature
**Then** the doc prescribes the canonical tab-order for completed-recording detail view: status banners → status badges → transcript view → AI panel → download buttons
**And** new components MUST follow this order or document divergence with a comment.

**AC3 — Descriptive-label conventions**
**Given** `dashboard/src/utils/a11yLabels.ts`
**When** components import `downloadButtonLabel(kind)`
**Then** they receive `"Download transcript as plain text"` or `"Download summary as plain text"` (never bare `"Download"`)
**And** lint rule (ESLint custom) flags any `<button>Download</button>` literal lacking a descriptive `aria-label`.

**AC4 — Lighthouse CI gate (NFR25)**
**Given** `dashboard/lighthouserc.json` and a new `lighthouse` job in `.github/workflows/dashboard-quality.yml`
**When** a PR touches `dashboard/components/`
**Then** Lighthouse CI runs with `@lhci/cli@0.14`; the build fails if accessibility score < 90 on any new page
**And** the gate adds ~90s CI wall-time and ~40MB devDep weight (documented in PRD assumption #2).

**AC5 — Manual screen-reader smoke test gate**
**Given** the MVP-cut PR
**When** the team tags `@review/manual-a11y` on the PR
**Then** the reviewer documents NVDA-Windows + Orca-Linux test results in the PR description before merge.

---

### Story 1.9: `recording_diarization_review` table migration (ADR-009)

**Status: DONE (sprint 1 — commit d6e956c; lifecycle state machine deferred to Story 5.6 per AC3)**

**As a** backend engineer
**I want** the `recording_diarization_review` table created in this foundational epic
**So that** epic-aliases-growth (Story 5.6) can implement the lifecycle state machine without a forward dependency, and the table survives DB restore (NFR23, R-EL19).

**FR/NFR coverage:** FR27 (table prerequisite), NFR23, R-EL19, R-EL20
**ADRs:** ADR-009
**Depends on:** Story 1.1
**Estimated dev-days:** 0.5d
**Includes migration:** **YES** — `recording_diarization_review` table.

**Acceptance Criteria:**

**AC1 — Migration creates table**
**Given** an Alembic migration named `add_recording_diarization_review`
**When** `alembic upgrade head` runs
**Then** the table exists with `(recording_id PK FK→recordings.id, status TEXT NOT NULL CHECK IN ('pending', 'in_review', 'completed', 'released'), reviewed_turns_json TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)`
**And** the migration is forward-only (NFR22) and non-destructive (NFR21).

**AC2 — Table survives DB restore (NFR23)**
**Given** a DB dump and restore cycle
**When** the DB is restored from backup
**Then** review-state rows survive the round-trip
**And** a smoke test (`test_diarization_review_state_survives_restore`) asserts a sample row with `status='in_review'` is queryable after restore.

**AC3 — Repository module stub**
**Given** a new module `server/backend/server/database/diarization_review_repository.py`
**When** Story 1.9 is complete
**Then** the module exposes `create_review(recording_id)`, `get_review(recording_id)`, `update_status(recording_id, new_status)`, `update_reviewed_turns(recording_id, turns_json)` — all using parameterized SQL (no ORM, per project convention)
**And** the lifecycle state-machine consumption lives in Story 5.6 (epic-aliases-growth).

---

# Epic 2: epic-import — Audio import & content-hash dedup

## Epic Goal

**As a** Lurker user (Anna, J1)
**I want** to import audio files and have the system detect duplicate content via SHA-256 hash so I don't re-transcribe the same recording twice
**So that** my library stays clean (FR1-FR4, R-EL23) and the J1 Lurker happy path's dedup-prompt narrative is implementable.

**Tier:** MVP
**Dependencies:** epic-foundations (Story 1.1 fixtures, no FK to profiles required)
**FRs covered:** FR1, FR2, FR3, FR4
**A11y inheritance:** Dedup prompt UI (Story 2.4) inherits FR51 (keyboard) + FR53 (descriptive labels)
**Risk grade:** LOW-MED — additive column on `transcription_jobs`; new endpoint; modest UI prompt
**Engineer-day budget:** 3-4 dev-days

---

### Story 2.1: `audio_hash` column on `transcription_jobs` (migration)

**Status: DONE (sprint 2 — migration 011; see _bmad-output/implementation-artifacts/sprint-2-design.md)**

**As a** backend engineer
**I want** the `audio_hash` column added to `transcription_jobs` with a covering index for dedup lookups
**So that** Story 2.2 can write the hash and Story 2.4 can query for matches efficiently.

**FR/NFR coverage:** FR2, NFR21, NFR22, R-EL23
**ADRs:** ADR-002
**Depends on:** Story 1.1
**Estimated dev-days:** 0.5d
**Includes migration:** **YES**

**Acceptance Criteria:**

**AC1 — Migration adds column**
**Given** an Alembic migration named `add_audio_hash_to_transcription_jobs`
**When** `alembic upgrade head` runs
**Then** `transcription_jobs` gains `audio_hash TEXT` (nullable for legacy rows)
**And** an index `idx_transcription_jobs_audio_hash` is created on the column
**And** the migration is forward-only (NFR22) and non-destructive on existing rows (NFR21).

**AC2 — Backfill is opt-in only**
**Given** legacy rows with NULL `audio_hash`
**When** the migration runs
**Then** legacy rows are NOT auto-rehashed (out of scope; would require re-reading every preserved audio file)
**And** the migration log notes "legacy rows have NULL audio_hash — dedup applies to NEW imports only".

---

### Story 2.2: SHA-256 audio content hash on import

**Status: DONE (sprint 2 — raw-byte streaming hash on /audio + /import; design §1 documents the AC override from "normalized PCM" to "raw upload bytes")**

**As a** backend engineer
**I want** the import flow to compute SHA-256 of normalized PCM and write it to `audio_hash`
**So that** Story 2.4 can detect duplicates by content (not filename).

**FR/NFR coverage:** FR2, NFR6, R-EL23
**Depends on:** Story 2.1
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Hash computed during audio preservation**
**Given** an audio file imported via the existing file-picker flow
**When** the file is preserved to `/data/recordings/{job_id}.wav`
**Then** the import code computes `hashlib.sha256()` over normalized PCM (16kHz mono int16) bytes
**And** the resulting hex digest is written to `transcription_jobs.audio_hash` BEFORE the transcription job enters `processing` state.

**AC2 — No observable additional delay (NFR6)**
**Given** an existing import flow that takes T seconds for audio preservation
**When** the hash computation is added
**Then** the import takes T + Δ seconds where Δ < 5% of T on a benchmark file (1-hour WAV)
**And** a `pytest-benchmark` test (`test_import_with_hash_perf`) asserts the bound.

**AC3 — Persist-Before-Deliver (NFR16)**
**Given** the hash computation
**When** the import endpoint returns its response to the client
**Then** the `audio_hash` value MUST already be committed to SQLite — never sent before persistence.

---

### Story 2.3: Audio file import via existing file-picker (FR1 verification + idempotence)

**Status: DONE (sprint 2 — regression test test_import_works_without_profile)**

**As a** Lurker user (Anna)
**I want** to import audio files via the existing file-picker without being asked to set up a profile first
**So that** the J1 happy-path zero-config flow holds (R-EL7).

**FR/NFR coverage:** FR1
**Depends on:** Story 2.2
**Estimated dev-days:** 0.25d (mostly verification + regression test)
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Import works without profile**
**Given** a fresh installation with NO profiles defined
**When** the user drags a WAV into the dashboard or uses the file-picker
**Then** the import succeeds without any profile-setup prompt
**And** the job uses system defaults (default filename template, OS Downloads folder for manual export later).

**AC2 — Regression test**
**Given** the existing import smoke tests
**When** Story 2.3 is complete
**Then** a test (`test_import_works_without_profile`) explicitly asserts no `profile_id` is required for `POST /api/transcribe/file` and the job completes successfully.

---

### Story 2.4: Dedup-check endpoint + dedup-prompt UI

**Status: DONE (sprint 2 — POST /api/transcribe/import/dedup-check + DedupPromptModal; AC URL adjusted from /api/recordings/import/* to /api/transcribe/import/* per design §1)**

**As a** Lurker user (Anna re-importing the same file)
**I want** a clear prompt asking whether to use the existing transcript or create a new entry when I import a file that matches an existing recording's content hash
**So that** I don't accidentally double-process the same audio.

**FR/NFR coverage:** FR3, FR51 (keyboard-navigable prompt), FR53 (descriptive labels), R-EL23
**Depends on:** Story 2.2
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Dedup-check endpoint**
**Given** `POST /api/recordings/import/dedup-check` with body `{ "audio_hash": "<sha256>" }`
**When** the endpoint executes
**Then** it returns `{ "matches": [...{recording_id, name, created_at}] }` for any rows in `transcription_jobs` where `audio_hash` matches
**And** the endpoint is idempotent (no side effects).

**AC2 — Dedup prompt UI**
**Given** the user imports a file that matches an existing recording
**When** the dashboard receives a non-empty `matches` array from the dedup-check call (which fires BEFORE creating the job)
**Then** a modal opens reading: *"This recording matches an existing one: '{name}' from {created_at}. Use existing transcript, or create a new entry?"*
**And** the modal has two buttons: "Use existing" (navigates to the existing recording detail view; no new job created) and "Create new" (proceeds with import, creating a new job with the same hash).

**AC3 — First-import bypass (R-EL23)**
**Given** an audio file with no hash match
**When** the import flow runs
**Then** the dedup prompt does NOT appear; the import proceeds silently (J1 happy-path preserved).

**AC4 — Accessibility (FR51, FR53)**
**Given** the dedup prompt modal
**When** opened
**Then** focus moves to the modal's primary button ("Use existing")
**And** Esc dismisses the modal (treated as Cancel — no action taken)
**And** Tab cycles between the two buttons; both have descriptive `aria-label` attributes ("Use existing recording", "Create new recording entry").

---

### Story 2.5: Per-user-library dedup scope

**Status: DONE (sprint 2 — test_dedup_check_no_outbound_network + architecture-server.md scope note)**

**As a** privacy-conscious user
**I want** dedup to operate only within my local library, never across installations
**So that** my hashes are never compared against other users' recordings.

**FR/NFR coverage:** FR4
**Depends on:** Story 2.2, Story 2.4
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Dedup query scoped to local DB**
**Given** the dedup-check endpoint from Story 2.4
**When** it queries `transcription_jobs.audio_hash`
**Then** the query operates ONLY on the local SQLite DB; there is NO outbound network call to any registry or shared service
**And** a unit test (`test_dedup_check_no_outbound_network`) asserts no `httpx`/`requests` calls escape the function.

**AC2 — Documentation in scope note**
**Given** `docs/architecture-server.md`
**When** Story 2.5 is complete
**Then** the doc includes a note: "Audio dedup operates per-user-library (FR4); hashes are not federated across installations. Cross-user dedup is explicit non-goal."

---

# Epic 3: epic-export — Filename templates, plain-text export, download buttons, deletion semantics

## Epic Goal

**As a** Lurker (Anna, J1) AND Configurator (Maria, J2 / J6)
**I want** explicit Download transcript / Download summary buttons, configurable filename templates with live preview, plain-text export, forward-only template changes, and a deletion dialog that explicitly states on-disk artifacts are not removed
**So that** the manual-export experience is coherent and predictable for both personas (FR5-9, FR12, FR13, FR17, FR48).

**Tier:** MVP
**Dependencies:** epic-foundations (profiles + a11y scaffold), epic-import (recordings exist)
**FRs covered:** FR5, FR6, FR7, FR8, FR9, FR12, FR13, FR17, FR48
**A11y inheritance:** Stories 3.5, 3.7 inherit FR51-53 with explicit ACs
**Risk grade:** LOW-MED (filename sanitization is the highest-risk slice — F2 LOW-MED per PRD)
**Engineer-day budget:** 7-9 dev-days

---

### Story 3.1: Filename template engine + extensible placeholder grammar

**Status: DONE (sprint 2 — server/backend/core/filename_template.py + dashboard/src/utils/filenameTemplate.ts mirror; Python↔TS sync test enforces drift-free registry)**

**As a** Configurator (Maria)
**I want** an extensible placeholder grammar (`{date}`, `{title}`, `{recording_id}`, `{model}`) for filename templates
**So that** I can customize names without writing wrapper scripts (FR12, R-EL2).

**FR/NFR coverage:** FR12, R-EL2
**Depends on:** epic-foundations Story 1.2
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Engine renders placeholders**
**Given** a template `{date} {title} - {model}.txt` and a sample recording with date=2026-05-08, title="language session", model="parakeet-tdt-0.6b-v2"
**When** the engine renders against the recording
**Then** the output is `2026-05-08 language session - parakeet-tdt-0.6b-v2.txt`.

**AC2 — Extensible grammar (R-EL2)**
**Given** the engine is implemented
**When** a developer wants to add `{audio_hash}` (Vassilis's J5 ask)
**Then** registering a new placeholder requires only adding to a single dict (e.g., `PLACEHOLDER_RESOLVERS = { "audio_hash": lambda r: r.audio_hash[:6], ... }`)
**And** unit tests cover registration of a new placeholder without changing the engine code.

**AC3 — Unknown placeholder is preserved literal**
**Given** a template `{nonexistent}.txt`
**When** the engine renders it
**Then** the output is `{nonexistent}.txt` (literal pass-through; not an error)
**And** the validation step (Story 3.2) is what rejects unknown placeholders at SAVE time.

---

### Story 3.2: Server-side template validation + sanitization

**Status: DONE (sprint 2 — sanitize_filename + PUT/POST /api/profiles validation; hand-crafted parametrized tests substitute for Hypothesis dep — design §5 risk note)**

**As a** backend engineer
**I want** the template-engine to reject malformed templates and sanitize rendered output for filesystem safety
**So that** path traversal, Windows reserved names, Unicode anomalies, and 255-char overflow can never reach disk (FR12, R-EL24, NFR14, cross-feature constraint #4).

**FR/NFR coverage:** FR12, NFR14, R-EL24
**Depends on:** Story 3.1
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Template syntax validation at profile save**
**Given** a `PUT /api/profiles/{id}` request with template `{date} {invalid_placeholder}.txt`
**When** the server validates
**Then** it returns HTTP 400 with `{"error": "invalid_template", "unknown_placeholders": ["invalid_placeholder"]}` (R-EL24).

**AC2 — Property-based sanitization tests (NFR52)**
**Given** the template engine + sanitizer
**When** the property-based test suite (Hypothesis-style) runs
**Then** for any input title containing path traversal (`../`), Windows reserved names (`CON`, `PRN`, `NUL`, `COM1`, `LPT1`, etc.), control characters, or trailing whitespace
**Then** the rendered filename is sanitized (path components stripped to basename, reserved names suffixed with `_`, control chars stripped, trailing whitespace trimmed)
**And** the test suite has at least 50 generated cases per category.

**AC3 — Unicode normalization**
**Given** a title with mixed Unicode normalization forms (NFC vs NFD)
**When** the sanitizer runs
**Then** the output is normalized to NFC before length-check
**And** non-printable code points are stripped.

**AC4 — 255-char limit**
**Given** a rendered filename longer than 255 bytes (UTF-8) including extension
**When** the sanitizer runs
**Then** the basename is truncated to fit; the extension is preserved.

---

### Story 3.3: Live filename preview in profile UI

**Status: DONE (sprint 2 — TemplatePreviewField with synchronous render + invalid-template inline error)**

**As a** Configurator (Maria)
**I want** the filename preview to update as I type the template
**So that** I can see the result before saving (R-EL14).

**FR/NFR coverage:** FR13, NFR2, R-EL14
**Depends on:** Story 3.1, Story 3.2
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Preview renders inline**
**Given** the profile-edit UI with the template field
**When** the user types into the template field
**Then** below the field a label reads `Preview: <rendered filename>` updating on every keystroke
**And** the preview uses a fixed sample recording (today's date, "Sample title", `parakeet-tdt-0.6b-v2`).

**AC2 — Preview latency (NFR2)**
**Given** a 1000-iteration benchmark using `time.perf_counter_ns()` on the pure CPU path (no I/O)
**When** measured
**Then** p95 < 50ms.

**AC3 — Invalid template surfaces inline**
**Given** the user types a template with an unknown placeholder
**When** the preview tries to render
**Then** the preview shows `Invalid: unknown placeholder {nonexistent}` in red
**And** the Save button is disabled while the template is invalid.

---

### Story 3.4: Plain-text export formatter (streaming)

**Status: DONE (sprint 2 — server/backend/core/plaintext_export.py + format=plaintext branch on /api/notebook/recordings/{id}/export wraps StreamingResponse + iter_segments)**

**As a** user
**I want** downloaded files to be plain text — one speaker turn per blank-line block, no subtitle timestamps
**So that** I can drop them straight into Obsidian/notes (FR9, NFR48).

**FR/NFR coverage:** FR9, NFR48
**Depends on:** epic-foundations Story 1.1
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Format matches J1 narrative**
**Given** a transcript with 5 speaker turns (each a paragraph)
**When** the exporter formats it as plain text
**Then** each turn is a paragraph separated by a blank line
**And** there are NO subtitle-style timestamps (e.g. `00:00:01,234 --> 00:00:05,678`)
**And** speaker labels (or aliases — see epic-aliases-growth Story 5.1) are bolded as `**Speaker N:**` or `**Alias:**` at the start of each turn.

**AC2 — Streaming for large transcripts**
**Given** a transcript from an 8-hour recording (~1 GB transcript)
**When** the formatter runs
**Then** memory usage stays bounded — formatter yields chunks via a generator, never loading the entire transcript into RAM (NFR48)
**And** a memory-budget test asserts peak RSS < 200 MB during 8h export.

---

### Story 3.5: Download transcript + summary buttons + native file-save dialog

**Status: DONE (sprint 2 — DownloadButtons + dialog:saveFile IPC + useFileSaveDialog hook; renderer-side fetch is buffered for MVP, streaming-to-disk via Electron protocol deferred for >100MB transcripts)**

**As a** Lurker (Anna)
**I want** explicit "Download transcript" and "Download summary" buttons in the completed-recording UI, opening the native OS file-save dialog
**So that** the J1 happy path (FR5, FR6, FR7, FR8) works without a profile setup.

**FR/NFR coverage:** FR5, FR6, FR7, FR8, FR51, FR52, FR53, NFR50
**Depends on:** Story 3.4, epic-foundations Story 1.8 (a11y scaffold)
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Buttons render in completed-recording UI**
**Given** a recording with status `completed`
**When** the user opens its detail view
**Then** two buttons appear: "Download transcript" (always enabled when transcript exists) and "Download summary" (enabled iff a summary exists, else disabled with tooltip "No summary yet — generate from the AI panel" — FR6)
**And** the buttons are visually contiguous with existing affordances (NFR50).

**AC2 — Native file-save dialog (FR7, FR8)**
**Given** the user clicks "Download transcript"
**When** the click handler runs
**Then** Electron's `dialog.showSaveDialog({ defaultPath: <rendered filename>, defaultDestination: app.getPath('downloads') })` opens
**And** the user can override both filename and destination per-click via the dialog
**And** confirming the dialog writes the plain-text export (Story 3.4) to the chosen path.

**AC3 — Default filename uses default template**
**Given** no profile is active OR the active profile has no custom template
**When** the dialog opens
**Then** the suggested filename is `{date} - {title}.txt` rendered against the recording (default template per FR15 sane-defaults).

**AC4 — Persist-Before-Deliver (NFR16)**
**Given** the file write
**When** the user confirms the save dialog
**Then** the write is to disk; success is observable BY THE USER via the OS dialog's completion (no separate "delivered" confirmation needed — disk IS the durable surface)
**And** any write error surfaces a toast "Could not save file: <reason>" without losing the original transcript in the recording.

**AC5 — Accessibility (FR51, FR52, FR53)**
**Given** keyboard-only navigation
**When** the user Tabs to the Download buttons and presses Enter
**Then** the file-save dialog opens
**And** the buttons have `aria-label="Download transcript as plain text"` and `aria-label="Download summary as plain text"` (NOT bare "Download" — FR53)
**And** on save success, the ARIA live region (Story 1.8) announces "Transcript saved to {path}" (FR52).

---

### Story 3.6: Forward-only template change + Re-export action

**Status: DONE (sprint 2 — sticky-OK notice in TemplatePreviewField + POST /api/notebook/recordings/{id}/reexport; AC URL adjusted from /api/recordings/* per design §1)**

**As a** Configurator (Maria, J6)
**I want** template changes to apply forward-only and have an opt-in per-recording Re-export action
**So that** old files on disk keep their names and I never get surprised by silent renames (FR17).

**FR/NFR coverage:** FR17
**Depends on:** Story 3.5
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Notice on template change**
**Given** the profile-edit UI with template field
**When** the user edits the template
**Then** below the field a notice reads: *"ⓘ This template applies to future transcriptions. Existing transcripts on disk keep their current names. To re-export old recordings with the new template, use the Re-export action in the recording context menu."*
**And** the notice is dismissable (sticky-OK confirmation) but always shown until the user confirms.

**AC2 — Forward-only application**
**Given** profile P1 with template T1; an existing recording R1 was exported using T1
**When** the user edits P1 to template T2 and saves
**Then** R1's existing on-disk file is unchanged
**And** the next imported recording R2 uses T2.

**AC3 — Re-export endpoint and context menu**
**Given** `POST /api/recordings/{id}/reexport`
**When** an authenticated client calls it for recording R1 with active profile P1 (now using T2)
**Then** a NEW file is written to disk using T2; the original T1 file is NOT deleted (J6 narrative: opt-in deletion is separate manual step)
**And** the dashboard's recording context menu has a "Re-export with current profile" action invoking this endpoint
**And** a toast announces "Re-exported as {new_filename}" (FR52).

---

### Story 3.7: Recording deletion dialog with explicit on-disk artifact options (R-EL13, R-EL32)

**Status: DONE (sprint 2 — DELETE /api/notebook/recordings/{id}?delete_artifacts=true&artifact_path=... + DeleteRecordingDialog; renderer derives artifact paths because notebook recordings don't carry a profile snapshot — design §1)**

**As a** privacy-conscious user
**I want** the recording-deletion dialog to explicitly state that on-disk artifacts are NOT removed by default, and offer a per-deletion option to remove them
**So that** I can never lose files I exported on purpose, AND I can choose right-to-erasure when needed (FR48, R-EL13, R-EL32, NFR36, NFR38).

**FR/NFR coverage:** FR48, FR51, FR53, NFR36, NFR38, R-EL13, R-EL32
**Depends on:** Story 3.5
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Dialog text is explicit**
**Given** a user clicks Delete on a recording
**When** the confirmation dialog opens
**Then** it reads (verbatim or substantively equivalent): *"Delete recording '{name}'? This removes the recording from your library. On-disk transcript and summary files exported to your folders will NOT be deleted by default — you can opt in below."*
**And** a checkbox below reads: *"Also delete on-disk transcript and summary files exported by this recording."* — defaulted to unchecked (least-surprise; FR48 default keep, R-EL13).

**AC2 — Default keep semantics (FR48, NFR36)**
**Given** the user confirms deletion with the checkbox UNCHECKED
**When** the deletion runs
**Then** the recording is removed from the DB
**And** any on-disk export files in the configured destination remain untouched.

**AC3 — Opt-in delete-on-disk (R-EL32, NFR38)**
**Given** the user confirms deletion with the checkbox CHECKED
**When** the deletion runs
**Then** the recording is removed from the DB
**And** any on-disk export files matching the recording's profile-snapshot template (resolved against the recording's metadata) are deleted
**And** any deletion failures (file not found, permission denied) surface in a toast but do NOT block the DB deletion (right-to-erasure best-effort).

**AC4 — Accessibility (FR51, FR53)**
**Given** keyboard-only navigation
**When** the dialog is open
**Then** Tab order is: text → checkbox → Cancel → Delete
**And** the Delete button has `aria-label="Confirm delete recording {name}"` (FR53).

---

# Epic 4: epic-aliases-mvp — Speaker alias storage + view substitution

## Epic Goal

**As a** Configurator (Maria, J2 MVP slice)
**I want** to rename "Speaker 1", "Speaker 2", etc. to real names per-recording and see those names in the transcript view
**So that** the transcript view is meaningful even before alias propagation to exports/AI ships (F4 MVP slice — FR21, FR22, FR29).

**Tier:** MVP
**Dependencies:** epic-foundations (a11y scaffold; no dependency on epic-import)
**FRs covered:** FR21, FR22, FR29
**A11y inheritance:** Stories 4.3, 4.4 inherit FR51 (keyboard) + FR53 (descriptive labels)
**Risk grade:** MEDIUM-HIGH (data shape change; F4 = HIGH per PRD, but MVP slice is the safer half)
**Engineer-day budget:** 5-7 dev-days

---

### Story 4.1: `recording_speaker_aliases` table migration

**Status: DONE (sprint 3 — commit A; migration 014; FK ON DELETE CASCADE; UNIQUE(recording_id, speaker_id))**

**As a** backend engineer
**I want** the `recording_speaker_aliases` table created
**So that** Stories 4.2-4.5 can read/write aliases (FR21).

**FR/NFR coverage:** FR21, NFR21, NFR22, NFR52 (≥1 migration test)
**ADRs:** ADR-005 (per-recording scope, R-EL8)
**Depends on:** epic-foundations Story 1.1
**Estimated dev-days:** 0.5d
**Includes migration:** **YES**

**Acceptance Criteria:**

**AC1 — Migration creates table**
**Given** an Alembic migration named `add_recording_speaker_aliases`
**When** `alembic upgrade head` runs
**Then** the table exists with `(id PK, recording_id INTEGER NOT NULL FK→recordings.id ON DELETE CASCADE, speaker_id TEXT NOT NULL, alias_name TEXT NOT NULL, created_at TIMESTAMP, updated_at TIMESTAMP, UNIQUE(recording_id, speaker_id))`
**And** the migration is forward-only (NFR22) and non-destructive (NFR21).

**AC2 — F4 migration test (NFR52)**
**Given** a fixture DB with 3 existing recordings and N speaker IDs each
**When** the migration runs
**Then** the existing recordings are unmodified
**And** the new table is empty
**And** the FK constraint is enforced (insertion with non-existent `recording_id` fails).

**AC3 — Per-recording scope (R-EL8, ADR-005)**
**Given** the same alias_name "Elena" used in two different recordings
**When** both rows are inserted
**Then** they coexist as separate rows (different `recording_id`)
**And** there is NO cross-recording uniqueness constraint (identity-level scope is deferred to Vision).

---

### Story 4.2: REST endpoints `GET/PUT /api/recordings/{id}/aliases`

**Status: DONE (sprint 3 — commit A; mounted on notebook router as `/api/notebook/recordings/{id}/aliases` per design §1; full-replace upsert; verbatim alias preservation)**

**As a** dashboard developer
**I want** REST endpoints to read and update speaker aliases per recording
**So that** Story 4.3's UI can use them (FR29).

**FR/NFR coverage:** FR29
**Depends on:** Story 4.1
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — GET endpoint**
**Given** a recording with 3 aliases stored
**When** an authenticated client calls `GET /api/recordings/{id}/aliases`
**Then** the response is `{"recording_id": <id>, "aliases": [{"speaker_id": "spk_0", "alias_name": "Elena"}, ...]}`
**And** for a recording with no aliases, the array is empty (not 404).

**AC2 — PUT endpoint**
**Given** a `PUT /api/recordings/{id}/aliases` request with body `{"aliases": [{"speaker_id": "spk_0", "alias_name": "Elena"}, {"speaker_id": "spk_1", "alias_name": "Marco"}]}`
**When** the endpoint runs
**Then** it upserts each alias (insert if new `speaker_id`, update `alias_name` if existing)
**And** any existing aliases for `recording_id` whose `speaker_id` is NOT in the request body are deleted (full-replace semantics)
**And** the response is the new state via the GET shape.

**AC3 — Persist-Before-Deliver (NFR16)**
**Given** the PUT
**When** the response is returned
**Then** the SQLite commit MUST have already succeeded — the response is sent only after persistence.

---

### Story 4.3: Speaker rename UI on transcript view

**Status: DONE (sprint 3 — commit B; SpeakerRenameInput component; AudioNoteModal wiring; Enter commits, Esc cancels, blur commits; ARIA announcement on focus)**

**As a** Configurator
**I want** to rename "Speaker 1" → "Elena" inline on the transcript view
**So that** I can attribute speakers without leaving the recording detail page (FR21).

**FR/NFR coverage:** FR21, FR51, FR53
**Depends on:** Story 4.2
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Inline rename interaction**
**Given** a transcript view with at least 2 speakers
**When** the user clicks (or focuses+Enter) on a speaker label
**Then** the label becomes a text input pre-filled with the current label
**And** Enter commits the rename (calls `PUT /api/recordings/{id}/aliases`)
**And** Esc cancels.

**AC2 — Rename applies to all turns of the same speaker_id**
**Given** speaker_id `spk_0` appears on 30 turns
**When** the user renames `spk_0` to "Elena"
**Then** all 30 turns immediately render "Elena" in the view (single source of truth via React Query cache invalidation per ADR-007).

**AC3 — Accessibility (FR51, FR53)**
**Given** keyboard-only navigation
**When** the user Tabs to a speaker label and presses Enter
**Then** the input is focused and the screen reader announces "Edit speaker label, current value: Speaker 1"
**And** the input has `aria-label="Speaker label for {speaker_id}"`.

---

### Story 4.4: Alias substitution in transcript view rendering

**Status: DONE (sprint 3 — commit B; aliasSubstitution.ts + buildSpeakerLabelMap; read-time only — stored transcript never mutated (R-EL3); first snapshot of 5 propagation snapshots)**

**As a** Configurator
**I want** the transcript view to substitute aliases everywhere it renders speaker labels
**So that** the view is consistent (FR22).

**FR/NFR coverage:** FR22, FR51, FR53
**Depends on:** Story 4.3
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — All turn labels show alias if present**
**Given** a transcript with `spk_0` aliased to "Elena" and `spk_1` not aliased
**When** the view renders
**Then** `spk_0` turns show "Elena"
**And** `spk_1` turns show "Speaker 2" (default fallback)
**And** the speaker chip in the per-turn confidence indicator (epic-aliases-growth Story 5.5) consumes the same source-of-truth.

**AC2 — Snapshot test (NFR52: ≥4 propagation snapshots)**
**Given** a transcript fixture with 5 speakers, 2 aliased
**When** the rendered HTML is snapshotted
**Then** the snapshot matches a golden file
**And** at least 4 such snapshots exist across propagation surfaces (this story covers 1; epic-aliases-growth covers the rest).

---

### Story 4.5: Alias cleanup on recording delete (FK cascade verification)

**Status: DONE (sprint 3 — commit C; cascade tested 3→0; survives DB schema/data restore round-trip)**

**As a** backend engineer
**I want** alias rows automatically deleted when their parent recording is deleted
**So that** orphan rows do not accumulate.

**FR/NFR coverage:** NFR21 (migration non-destructive proof), supporting FR48
**Depends on:** Story 4.1
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — FK ON DELETE CASCADE works**
**Given** a recording with 3 alias rows
**When** the recording is deleted from `recordings` table
**Then** the 3 alias rows are auto-removed (FK cascade per Story 4.1 schema)
**And** a regression test (`test_alias_cascade_on_recording_delete`) asserts the count goes 3 → 0 after delete.

**AC2 — No leak on DB restore**
**Given** a DB dump and restore
**When** restored
**Then** the FK cascade is preserved; deleting a recording in the restored DB still cascades.

---

# Epic 5: epic-aliases-growth — Alias propagation, diarization confidence, review UX

## Epic Goal

**As a** Configurator (Maria, J2 Growth) AND a researcher with low-confidence diarization (Sami, J4)
**I want** speaker aliases to propagate to plain-text exports, subtitle exports, AI summary, and AI chat — verbatim — AND a focused diarization-review view that flags low-confidence turns and HOLDS auto-summary until I review them
**So that** "Elena said..." appears identically across surfaces (FR23, FR24) AND I can correct the model's mistakes before they reach the AI summary (FR25-28, R-EL3, R-EL4, R-EL10, R-EL15, R-EL19, R-EL20).

**Tier:** Growth
**Dependencies:** epic-aliases-mvp (alias storage + view substitution exist), epic-foundations (Story 1.9 review-state table, Story 1.8 a11y scaffold)
**FRs covered:** FR23, FR24, FR25, FR26, FR27, FR28
**A11y inheritance:** Stories 5.7, 5.8, 5.9 inherit FR51-54 with explicit ACs; **Story 5.9 cites Diarization-Review Keyboard Contract verbatim**.
**Risk grade:** HIGH (cross-surface propagation; review UX scales to 60+ turns; LLM context plumbing)
**Engineer-day budget:** 7-9 dev-days

---

### Story 5.1: Alias propagation to plain-text and subtitle exports

**Status: DONE (sprint 3 — commit D; apply_aliases generator over iter_segments preserves bounded RAM; subtitle build_subtitle_cues alias_overrides param; 2 propagation snapshots)**

**As a** Configurator (Maria, J2)
**I want** "Elena Vasquez" to appear in my plain-text and subtitle exports — never "Speaker 1"
**So that** the exports match the transcript view (FR23).

**FR/NFR coverage:** FR23, NFR52 (propagation snapshot)
**Depends on:** epic-aliases-mvp Story 4.2, epic-export Story 3.4
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Plain-text export uses aliases**
**Given** a recording with `spk_0`→"Elena Vasquez" alias
**When** the plain-text exporter (Story 3.4) renders
**Then** every `spk_0` turn shows `**Elena Vasquez:**` not `**Speaker 1:**`.

**AC2 — Subtitle export uses aliases**
**Given** the same recording
**When** any subtitle export (SRT/VTT) is generated
**Then** speaker labels in cues use aliases.

**AC3 — Snapshot test (NFR52)**
**Given** a 10-turn recording with 3 speakers (2 aliased)
**When** plain-text + subtitle exports are generated
**Then** golden snapshots match (`test_plaintext_alias_propagation_snapshot`, `test_subtitle_alias_propagation_snapshot`).

---

### Story 5.2: Alias propagation to AI summary prompt context (verbatim, R-EL3)

**Status: DONE (sprint 3 — commit D; _build_alias_aware_transcript_text helper + speaker_key_preface preamble + R-EL3 verbatim directive in system prompt; covers blocking and streaming summarize routes)**

**As a** Configurator
**I want** the AI summary to reference aliases verbatim ("Vasquez argued that...", not "Speaker 1 argued that...") and never infer/merge/rewrite alias names
**So that** the summary attribution matches my review (FR23, FR24, R-EL3).

**FR/NFR coverage:** FR23, FR24, R-EL3
**Depends on:** Story 5.1
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Aliases injected into LLM prompt**
**Given** the AI summary lifecycle hook (epic-auto-actions or manual generation)
**When** the prompt is constructed
**Then** speaker labels in the transcript text passed to the LLM are pre-substituted to alias names
**And** a "Speaker key" preface is included in the prompt: `Speakers in this transcript: Elena Vasquez (spk_0), Marco Rivera (spk_1), Speaker 3 (spk_2 — unaliased)`.

**AC2 — Verbatim guarantee (R-EL3)**
**Given** an alias "Dr. María José García-López"
**When** it propagates to the LLM
**Then** the prompt includes the alias EXACTLY as the user typed it — no truncation, no Unicode normalization, no nickname inference
**And** the system prompt explicitly instructs the LLM: "Use the speaker names provided verbatim. Do not infer relationships, abbreviate, or merge names."

**AC3 — Snapshot test (NFR52)**
**Given** a fixture transcript with 4 speakers (2 aliased)
**When** the prompt builder runs
**Then** the constructed prompt matches a golden snapshot.

---

### Story 5.3: Alias propagation to AI chat context

**Status: DONE (sprint 3 — commit D; chat_with_llm uses _build_alias_aware_transcript_text + same R-EL3 directive when first message includes transcription context)**

**As a** user chatting with the AI about a recording
**I want** the AI chat to also use aliases verbatim
**So that** my conversation is consistent with the summary and view (FR23, FR24).

**FR/NFR coverage:** FR23, FR24
**Depends on:** Story 5.2
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Chat context uses aliases**
**Given** an active AI chat session for a recording with aliases
**When** the chat sends transcript context to the LLM (per existing chat contract)
**Then** speaker labels are pre-substituted to aliases — same logic as Story 5.2.

**AC2 — Snapshot test (NFR52)**
**Given** a fixture chat-context payload
**When** built
**Then** matches golden snapshot.

---

### Story 5.4: Diarization-confidence per-turn API (R-EL4)

**Status: DONE (sprint 3 — commit E; per_turn_confidence helper aggregates word-level confidence as mean; mounted as `/api/notebook/recordings/{id}/diarization-confidence`; empty turns:[] fallback for older runs without word data)**

**As a** dashboard developer
**I want** an endpoint returning per-turn diarization confidence for a recording
**So that** Story 5.5 can render confidence indicators (R-EL4).

**FR/NFR coverage:** R-EL4 (data prerequisite for FR25, FR26)
**Depends on:** epic-aliases-mvp Story 4.1
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Endpoint shape**
**Given** `GET /api/recordings/{id}/diarization-confidence`
**When** an authenticated client calls it for a recording with N turns
**Then** response is `{"recording_id": <id>, "turns": [{"turn_index": 0, "speaker_id": "spk_0", "confidence": 0.94}, ...]}`
**And** confidence is sourced from pyannote-emitted scores already stored on the existing transcription artifact.

**AC2 — Empty-confidence fallback**
**Given** a recording where the diarization backend did not emit confidence (older runs)
**When** the endpoint is called
**Then** response is `{"recording_id": <id>, "turns": []}` (not 500); the dashboard treats empty as "no chip rendering" (Story 5.5 falls back gracefully).

---

### Story 5.5: Per-turn confidence indicators in transcript view (visual spec UX-DR3)

**Status: DONE (sprint 3 — commit F; ConfidenceChip component; high → null, medium → neutral, low → amber; tooltip shows %; aria-label="confidence: <bucket>"; UI contract baseline updated to spec_version 1.0.45)**

**As a** researcher
**I want** confidence chips beside speaker labels: no chip for high-confidence, neutral chip for medium, amber chip for low — with hover tooltip showing exact %
**So that** I can spot uncertain attributions visually (R-EL4, UX-DR3).

**FR/NFR coverage:** R-EL4, FR53 (descriptive labels), UX-DR3
**Depends on:** Story 5.4, epic-aliases-mvp Story 4.4
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Bucket rendering matches PRD visual spec**
**Given** a turn with confidence 0.94
**When** the view renders
**Then** NO chip is rendered beside the speaker label (high bucket: ≥80%)
**And** for confidence in [0.6, 0.8] a neutral chip renders
**And** for confidence < 0.6 an amber chip renders.

**AC2 — Tooltip shows percentage**
**Given** a chip is rendered
**When** the user hovers (or focuses for keyboard users)
**Then** a tooltip appears reading `confidence: 67%`.

**AC3 — Accessibility (FR53, FR54 anchor)**
**Given** the chip
**When** rendered
**Then** the chip element has `aria-label="confidence: <bucket>"` (e.g. "confidence: low")
**And** the tooltip element has `role="tooltip"`
**And** Story 5.9 / FR54 turn-announcement contract picks up the bucket via `aria-label`.

**AC4 — UI contract migration (UX-DR5)**
**Given** the chip introduces new CSS classes
**When** the developer runs the local UI-contract update sequence
**Then** `npm run ui:contract:extract → build → validate --update-baseline → check` succeeds
**And** `npm run ui:contract:check` passes in CI.

---

### Story 5.6: ADR-009 lifecycle state machine in `recording_diarization_review`

**Status: DONE (sprint 3 — commit G; diarization_review_lifecycle.py module; on_transcription_complete / on_review_view_opened / on_run_summary_now_clicked / on_auto_summary_fired triggers; banner_visible + auto_summary_is_held predicates; illegal transitions raise IllegalReviewTransitionError; longform/import completion-path wiring deferred to Sprint 4 per design §1)**

**As a** backend engineer
**I want** the review-state lifecycle (pending → in_review → completed → released) implemented per ADR-009
**So that** Story 5.7's banner visibility and Story 5.8's auto-summary HOLD have a single source of truth (FR27, R-EL19, NFR23).

**FR/NFR coverage:** FR27, NFR23, R-EL19
**ADRs:** ADR-009
**Depends on:** epic-foundations Story 1.9 (table exists)
**Estimated dev-days:** 1d
**Includes migration:** No (table created in Story 1.9)

**Acceptance Criteria:**

**AC1 — Initial state on transcription completion**
**Given** a transcription completes with at least one turn at confidence < 0.6 (low bucket)
**When** the completion lifecycle hook fires
**Then** a row is inserted into `recording_diarization_review` with `status='pending'`
**And** if no low-confidence turns are detected, NO row is inserted (banner does not appear).

**AC2 — Lifecycle transitions**
**Given** an existing review row with `status='pending'`
**When** the user opens the review view (Story 5.9)
**Then** the row's status updates to `in_review`
**And** when the user clicks "Run summary now", status updates to `completed`
**And** when the auto-summary fires (epic-auto-actions Story 6.2), status flips to `released`.

**AC3 — Banner visibility predicate (Story 5.7 prerequisite)**
**Given** the dashboard queries review state
**When** `status IN ('pending', 'in_review')`
**Then** the banner is shown
**And** when `status IN ('completed', 'released')`, the banner is hidden.

**AC4 — Auto-summary HOLD predicate (Story 5.8 prerequisite)**
**Given** the auto-summary lifecycle
**When** `status != 'released'`
**Then** auto-summary is HELD.

**AC5 — Persistence across restarts (NFR23, R-EL19)**
**Given** a review row with `status='in_review'`
**When** the app restarts
**Then** the row's state is preserved; the banner remains shown on next session.

**AC6 — Persist-Before-Deliver (NFR16)**
**Given** any state transition
**When** the API returns
**Then** the SQLite commit MUST have completed before the response is sent.

---

### Story 5.7: Persistent "Review uncertain turns" banner (UX-DR2)

**Status: DONE (sprint 3 — commit H; PersistentInfoBanner component; AudioNoteModal integration; ARIA-live announcement on mount via useAriaAnnouncer; banner persists across navigation/restart per ADR-009 lifecycle)**

**As a** researcher
**I want** a yellow/amber banner at the top of the recording detail view that persists until I act on it
**So that** I cannot miss the prompt to review (FR28, R-EL20, NFR43).

**FR/NFR coverage:** FR28, FR51, FR52, NFR43, R-EL20, UX-DR2
**Depends on:** Story 5.6
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Banner renders when status is pending or in_review**
**Given** a recording with `recording_diarization_review.status` ∈ {pending, in_review}
**When** the user opens the recording detail view
**Then** a yellow banner appears at the top reading: *"⚠ Speaker labels uncertain on N turn boundaries — review before auto-summary runs."*
**And** the banner uses the `QueuePausedBanner` visual primitive (UX-DR2).

**AC2 — No auto-dismiss (R-EL20)**
**Given** the banner is shown
**When** the user navigates away and returns OR closes the app and reopens
**Then** the banner reappears in the same state (until status moves to completed or released).

**AC3 — Inline CTA invokes review view (Story 5.9 dependency)**
**Given** the banner
**When** the user clicks the inline "Review uncertain turns" button
**Then** the diarization-review view (Story 5.9) opens AND the row's status updates to `in_review`.

**AC4 — Accessibility (FR51, FR52)**
**Given** the banner appears
**When** the page loads
**Then** the ARIA live region (Story 1.8) announces *"Transcription complete. N of M turn boundaries flagged low-confidence."* with `aria-live="polite"`
**And** the banner button is keyboard-focusable; Enter activates it.

---

### Story 5.8: Auto-summary HOLD on low-confidence (R-EL10)

**Status: DONE (sprint 3 — commit H; auto_summary_is_held predicate exposed; fake-consumer test asserts contract; manual-summary-bypasses-hold static-analysis test guards Story 5.8 AC3; full auto-summary lifecycle wiring lands Sprint 4 Story 6.2)**

**As a** researcher
**I want** the auto-summary lifecycle hook to skip recordings with `recording_diarization_review.status != 'released'`
**So that** the LLM never summarizes a transcript whose attributions I haven't validated (FR25, R-EL10).

**FR/NFR coverage:** FR25, FR52, R-EL10
**Depends on:** Story 5.6, epic-auto-actions Story 6.2 (which actually fires auto-summary)
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — HOLD predicate enforced**
**Given** a recording with `recording_diarization_review.status='pending'` AND profile-toggle "auto-generate AI summary" ENABLED
**When** the auto-summary lifecycle hook fires
**Then** auto-summary is SKIPPED (no LLM call)
**And** the recording's status badge shows "Auto-summary held — review uncertain turns first" (uses Story 6.6 status badge)
**And** the live region announces "Auto-summary held pending review" (FR52).

**AC2 — Auto-summary fires after release**
**Given** a recording with `status='released'` (review completed via Story 5.9 "Run summary now")
**When** the lifecycle hook fires (or is re-triggered by status flip)
**Then** auto-summary runs normally.

**AC3 — User can manually generate summary even while held**
**Given** a recording is held
**When** the user manually clicks "Generate summary" in the AI panel
**Then** the manual generation runs (manual is always allowed; HOLD applies only to AUTO).

---

### Story 5.9: Diarization-review focused view + Diarization-Review Keyboard Contract (FR26, FR54, R-EL15)

**Status: DONE (sprint 3 — commit I; DiarizationReviewView composite-widget listbox; canonical Keyboard Contract Tab/↑↓/←→/Enter/Esc/Space; aria-activedescendant; FR54 turn announcements via useAriaAnnouncer; confidence-threshold filter (bottom_5 / <60 / <80 / all); filter linearity p95 <200ms at N=100, r²>0.95 across [10,100,500,1000])**

**As a** researcher (Sami, J4) AND a screen-reader user (Lia, J7)
**I want** a focused review view with confidence-threshold filter, bulk-accept, and full keyboard navigation per the Diarization-Review Keyboard Contract
**So that** I can review 60+ uncertain turns efficiently AND screen-reader users can complete the same flow (FR26, FR54, R-EL15).

**FR/NFR coverage:** FR26, FR51, FR54, NFR7, NFR43, R-EL15, UX-DR4
**Depends on:** Story 5.5, Story 5.6, epic-foundations Story 1.8 (a11y scaffold) + Story 1.9 (review table)
**Estimated dev-days:** 2d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Confidence-threshold filter**
**Given** a review view for a recording with N=47 low-confidence turns
**When** the user opens the filter dropdown
**Then** options are: *"Show: bottom-5% confidence | <60% | <80% | all uncertain"*
**And** selecting an option filters the visible turn-list accordingly.

**AC2 — Bulk-accept**
**Given** a filtered turn-list of K turns
**When** the user clicks "Mark all visible as auto-accept best guess" OR presses Space (per the keyboard contract)
**Then** all K turns get `status='accepted'` recorded in `recording_diarization_review.reviewed_turns_json`
**And** the visible turn-list updates to reflect resolution.

**AC3 — Diarization-Review Keyboard Contract (cited verbatim from PRD)**

The view MUST implement the canonical keyboard spec defined in the PRD's "Diarization-Review Keyboard Contract" subsection (modeled on WAI-ARIA Authoring Practices composite-widget pattern). Implementation MUST satisfy this exact key-action mapping:

| Key | Action | Scope |
|---|---|---|
| **Tab** / **Shift+Tab** | Traverse between turns | Focusable elements (turn-list is one tab stop; entering it puts focus on the active turn) |
| **↑** / **↓** | Move selection within the focused turn-list | Composite widget (does not change browser tab order) |
| **←** / **→** | Switch attribution within a focused turn | Per-turn alternative-speaker cycling |
| **Enter** | Accept current attribution | Active turn; advances selection to next turn |
| **Esc** | Skip current turn | Active turn; advances selection to next turn without committing |
| **Space** | Bulk-accept all currently visible turns | Whole filtered turn-list (respects active confidence filter) |

**Implementation invariants:**
- The turn-list is a composite widget with `role="listbox"` (or `role="grid"` if attribution columns are exposed); individual turns use `role="option"` (or `role="row"`).
- Tab order: review-banner → confidence-filter → turn-list (single tab stop) → bulk-action button → "Run summary now" button.
- Browser-default activation (Enter/Space) is **overridden** inside the turn-list because Space is reassigned to bulk-accept; off-list controls retain default behavior.
- Any divergence requires a new ADR — no silent drift.

**AC4 — Screen-reader announcement contract (FR54)**
**Given** the user selects a turn (via ↓ or Tab)
**When** focus changes
**Then** the screen reader announces: `<turn content> · current speaker: <label> · confidence: <bucket>` (per FR54 contract, consumed from Story 1.8's `useAriaAnnouncer`).

**AC5 — Submit review decisions**
**Given** the user clicks "Run summary now"
**When** the click handler runs
**Then** it calls `POST /api/recordings/{id}/diarization-review` with `{"reviewed_turns": [...], "action": "complete"}`
**And** the endpoint updates `recording_diarization_review.status='completed'`, then triggers the auto-summary lifecycle (which flips to `released` per Story 5.6 AC2).

**AC6 — Filter linearity benchmark (NFR7)**
**Given** a nightly `pytest-benchmark` job sampling (turns, latency) at [10, 100, 500, 1000]
**When** the filter operation runs
**Then** linear regression `r² > 0.95`
**And** for visible turn count up to 100, p95 < 200ms (per-PR assertion).

**AC7 — Persist-Before-Deliver (NFR16)**
**Given** any commit (accept, skip, bulk-accept, run-summary-now)
**When** the response is sent
**Then** SQLite commit must have completed.

---

# Epic 6: epic-auto-actions — F1 auto-summary, auto-export, status badges, retry

## Epic Goal

**As a** Configurator (Maria, J2 / J3)
**I want** auto-summary, auto-export, save-back-to-recording, deferred-retry on destination unavailability, distinct empty/truncated states, and single-click retry on failures — all respecting Persist-Before-Deliver and waiting for alias propagation
**So that** I can configure-once-walk-away and trust the system to surface failures observably (F1 — FR30-39, R-EL1, R-EL12, R-EL16, R-EL17, R-EL18).

**Tier:** Growth
**Dependencies:** epic-aliases-growth (resolves cross-feature constraint #1: F1 must wait for F4 propagation), epic-foundations (a11y scaffold + secrets + profiles)
**FRs covered:** FR30, FR31, FR32, FR33, FR34, FR35, FR36, FR37, FR38, FR39
**A11y inheritance:** Stories 6.6 inherit FR51-53 with explicit ACs
**Risk grade:** HIGH (async failure cascade; Persist-Before-Deliver crossing; F1+F4 race; 3 lifecycle hooks to coordinate)
**Engineer-day budget:** 10-12 dev-days

---

### Story 6.1: Profile auto-action toggles persisted

**As a** Configurator
**I want** auto-summary and auto-export toggles in my profile
**So that** I can opt-in once and walk away (FR30, FR31).

**FR/NFR coverage:** FR30, FR31
**Depends on:** epic-foundations Story 1.2
**Estimated dev-days:** 0.5d
**Includes migration:** No (toggles live in `profiles.public_fields_json`; no schema change)

**Acceptance Criteria:**

**AC1 — Toggles in profile UI and persisted**
**Given** the profile-edit UI
**When** the user toggles "Auto-generate AI summary after transcription" and "Auto-export transcript and summary"
**Then** the values save to `profiles.public_fields_json` as `{"auto_summary": true, "auto_export": true}`
**And** GET `/api/profiles/{id}` returns the toggles in the public fields.

**AC2 — Defaults**
**Given** a new profile (Story 1.5 sane defaults)
**When** rendered
**Then** both toggles default to OFF (Lurker-safe).

---

### Story 6.2: Auto-summary lifecycle hook (FR30, FR32, NFR3)

**As a** backend engineer
**I want** the auto-summary lifecycle hook to fire within 2s of transcription completion (when enabled, when no HOLD), generate a summary, and save it back to the recording
**So that** the J2 narrative works (FR30, FR32, NFR3).

**FR/NFR coverage:** FR30, FR32, NFR3, NFR16, NFR18
**Depends on:** Story 6.1, epic-aliases-growth Story 5.8 (HOLD predicate)
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Hook fires within 2s of completion**
**Given** a job transitions to `completed` status
**When** the auto-action lifecycle hook (`api/routes/transcription.py` post-completion) runs
**Then** if the job's profile snapshot has `auto_summary: true` AND HOLD predicate is `false` (status='released' or no review row exists)
**Then** the LLM summary call is initiated within 2s of the `completed` transition (NFR3, measured via `frozen_clock` fixture).

**AC2 — Save-back to recording (FR32, NFR18)**
**Given** a successful LLM summary response
**When** the hook receives it
**Then** the summary is written to the recording's persistent storage (existing summary column / table)
**AND THEN** the auto-export hook (Story 6.3) is invoked — never before persistence.

**AC3 — HOLD respected (R-EL10)**
**Given** the recording has `recording_diarization_review.status='pending'`
**When** the hook fires
**Then** auto-summary is NOT initiated; instead Story 5.8's "Auto-summary held" status is set.

**AC4 — Persist-Before-Deliver (NFR16)**
**Given** a successful summary
**When** the websocket notification is sent to the client
**Then** the summary MUST already be committed to the DB.

---

### Story 6.3: Auto-export lifecycle hook (FR31, NFR4)

**As a** backend engineer
**I want** the auto-export lifecycle hook to write transcript and summary files to the destination folder within 2s of the trigger
**So that** Maria returns to ready files (FR31, NFR4).

**FR/NFR coverage:** FR31, NFR4, NFR16
**Depends on:** Story 6.2, epic-export Story 3.4 (formatter), Story 3.1 (template engine)
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Hook fires after summary save-back**
**Given** Story 6.2 has saved a summary back
**When** the chain proceeds
**Then** the export hook initiates within 2s (NFR4)
**And** if `auto_export` is OFF, the hook is a no-op.

**AC2 — Files written to profile destination**
**Given** profile snapshot's `destination` is `/Users/maria/Documents/Interviews/raw/`
**When** the hook runs
**Then** the transcript file and summary file are written there using the profile's filename template (Story 3.1)
**And** filenames go through Story 3.2 sanitization.

**AC3 — Persist-Before-Deliver (NFR16)**
**Given** the file writes
**When** the websocket notification is sent
**Then** files MUST already be on disk; a snapshot test reads the file path from the notification and asserts `os.path.exists`.

---

### Story 6.4: Persist-Before-Deliver invariant for all auto-action artifacts (FR33)

**As a** project maintainer
**I want** an automated regression test asserting NO new Persist-Before-Deliver violations
**So that** the project's most critical invariant survives the QoL pack (FR33, NFR16).

**FR/NFR coverage:** FR33, NFR16
**Depends on:** Story 6.2, Story 6.3
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Invariant test for every artifact-producing path**
**Given** a tracking matrix in `tests/test_persist_before_deliver_matrix.py`
**When** the test runs
**Then** for each artifact-producing endpoint (auto-summary, auto-export, manual download, webhook delivery), the test asserts the artifact is committed to durable storage BEFORE any client-facing notification, file write, or webhook fire
**And** the matrix lists at least: `auto_summary_save_back`, `auto_export_write`, `manual_download_save`, `webhook_delivery_attempt`.

**AC2 — Failure mode test (NFR52: F1 ≥10 failure-mode tests)**
**Given** a simulated DB-commit failure
**When** the auto-summary hook attempts save-back
**Then** the websocket notification is NOT sent
**And** the recording's status remains `processing` for retry — the LLM result is NOT silently discarded (CLAUDE.md "AVOID DATA LOSS AT ALL COSTS").

---

### Story 6.5: Auto-action independence + partial success (FR34)

**As a** Configurator (Maria, J3)
**I want** auto-summary and auto-export to be independent — if summary fails, export still runs (and vice versa)
**So that** I get partial value even on partial failures (FR34).

**FR/NFR coverage:** FR34
**Depends on:** Story 6.2, Story 6.3
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Summary failure does not block export**
**Given** auto-summary fails (LLM unreachable) AND auto-export is enabled
**When** the lifecycle proceeds
**Then** the auto-export hook still runs and writes the transcript file (without a summary file)
**And** the recording shows TWO badges: ⚠ summary failed, ✓ transcript exported.

**AC2 — Export failure does not block summary**
**Given** auto-summary succeeds but the destination folder is unmounted (deferred-retry — Story 6.8)
**When** the lifecycle proceeds
**Then** the summary save-back to the recording succeeds and shows in the AI panel
**And** the recording shows: ✓ summary saved, ⚠ export deferred.

---

### Story 6.6: Status badge with single-click retry — `StatusLight` primitive (UX-DR1)

**As a** Configurator
**I want** failures to surface as a recoverable status badge with a single-click retry button — visually consistent with existing primitives
**So that** I can recover from transient failures without leaving the recording detail view (FR35, R-EL1, NFR41, UX-DR1).

**FR/NFR coverage:** FR35, FR51, FR52, FR53, NFR41, R-EL1, UX-DR1
**Depends on:** Story 6.4
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Badge renders per visual spec**
**Given** an auto-action failure
**When** the recording detail view loads
**Then** a status badge appears using the `StatusLight` primitive (UX-DR1) with severity:
- `ok` (green) for successful actions (auto-dismisses 3s after success)
- `warn` (amber) for "summary truncated" / "summary empty" / "export deferred"
- `error` (red) for "LLM unavailable" / "permission denied" / etc.

**AC2 — Inline ⟳ Retry button**
**Given** a `warn` or `error` badge
**When** rendered
**Then** an inline ⟳ Retry button appears beside the badge
**And** clicking it invokes `POST /api/recordings/{id}/auto-actions/retry` (Story 6.9)
**And** the badge transitions to `processing` (spinner) during retry.

**AC3 — Cardinality: one per auto-action per recording**
**Given** a recording with auto-summary, auto-export, and webhook delivery
**When** all three have status
**Then** three independent badges render, each with its own retry button.

**AC4 — Persistence**
**Given** a `warn` or `error` badge
**When** the user navigates away and returns
**Then** the badge persists (status read from DB, not local state)
**And** auto-dismiss applies only to `ok` after success transitions.

**AC5 — Accessibility (FR51, FR52, FR53)**
**Given** keyboard-only navigation
**When** the user Tabs to the retry button and presses Enter
**Then** retry fires
**And** the button has `aria-label="Retry auto-summary for {recording_name}"` (FR53)
**And** status changes are announced via the live region (FR52).

**AC6 — UI contract (UX-DR5)**
**Given** the badge introduces new CSS classes
**When** the developer runs the UI-contract update sequence
**Then** `npm run ui:contract:check` passes.

---

### Story 6.7: Empty / truncated summary distinct states (R-EL16, R-EL17)

**As a** Configurator (Maria)
**I want** the LLM returning an empty summary or hitting token-limit truncation to surface as DISTINCT amber states — never as green/success
**So that** I notice and can act (FR36, FR37, R-EL16, R-EL17).

**FR/NFR coverage:** FR36, FR37, R-EL16, R-EL17
**Depends on:** Story 6.6
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Empty-summary detection (FR36, R-EL16)**
**Given** the LLM returns an empty string OR a string < 10 characters
**When** the auto-summary hook processes the response
**Then** the recording's auto-summary status is set to `summary_empty` (NOT `success`)
**And** the badge shows ⚠ "Summary empty" (amber, not green) with retry button.

**AC2 — Truncated-summary detection (FR37, R-EL17)**
**Given** the LLM response includes a token-limit-truncation indicator (provider-specific signal)
**When** processed
**Then** status is `summary_truncated`
**And** the badge shows ⚠ "Summary truncated"
**And** the truncated content is still saved to the recording (visible in AI panel) — user can retry to attempt regeneration with adjusted prompt.

**AC3 — Failure-mode tests (NFR52)**
**Given** mocked LLM responses for empty and truncated cases
**When** test fixtures simulate each
**Then** dedicated tests assert each surfaces the correct status and the summary content is saved as expected.

---

### Story 6.8: Deferred-retry on destination unavailability (R-EL12)

**As a** Configurator (Maria, J3)
**I want** auto-export to defer and auto-retry when the destination becomes available (e.g., USB drive plugged in) — without losing the transcript
**So that** I can plug in my drive in the morning and have files appear (FR38, R-EL12, NFR20).

**FR/NFR coverage:** FR38, NFR20, R-EL12
**Depends on:** Story 6.3
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Detect transient destination unavailability**
**Given** the auto-export hook runs and the destination folder does not exist OR is on an unmounted volume
**When** the write fails with `FileNotFoundError` / `OSError(ENOENT)` / similar
**Then** the recording's export status is set to `export_deferred` with the destination path stored
**And** the transcript REMAINS safe in the recording (Persist-Before-Deliver — FR38 narrative).

**AC2 — Periodic deferred-retry sweeper**
**Given** a deferred export (status=`export_deferred`)
**When** the periodic sweeper runs (uses existing periodic-task pattern from CLAUDE.md project-context — `async def periodic_deferred_export_sweep()` with 30s interval, `cancel-safe`, gated by config)
**Then** for each deferred row, the sweeper checks `os.path.isdir(destination)` (TOCTOU-safe — re-checks on actual write)
**And** if the destination is back, the export is re-attempted; on success, status flips to `success` (badge auto-dismisses); on failure, retries continue until idempotent retry is bounded per Story 6.11 escalation.

**AC3 — Auto-export re-fires summary too**
**Given** a deferred export had BOTH transcript and summary
**When** retry succeeds
**Then** both files are written (idempotent — Story 6.10).

**AC4 — User-visible badge (FR35 inheritance)**
**Given** an `export_deferred` status
**When** rendered
**Then** Story 6.6's badge shows ⚠ "Auto-export deferred — destination `{path}` not mounted (will retry when available)" (J3 narrative).

---

### Story 6.9: Idempotent retry endpoint + manual retry button (FR39, R-EL27)

**As a** Configurator
**I want** the retry endpoint to be idempotent — replaying a successful action returns "already_complete" without re-firing side effects
**So that** double-clicks or aggressive polling don't cause duplicate exports (FR39, R-EL27).

**FR/NFR coverage:** FR35, FR39, R-EL27
**Depends on:** Story 6.6, Story 6.8
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Endpoint contract**
**Given** `POST /api/recordings/{id}/auto-actions/retry` with body `{"action_type": "auto_summary"}` (or `"auto_export"`, `"webhook"`)
**When** the action's current status is `failed` / `deferred` / `summary_empty` / `summary_truncated`
**Then** the endpoint re-fires the action via the same lifecycle hook
**And** returns `{"status": "retry_initiated"}` with HTTP 202.

**AC2 — Idempotent on already-complete (R-EL27)**
**Given** the action's status is already `success`
**When** the endpoint is called
**Then** it returns `{"status": "already_complete"}` with HTTP 200
**And** NO re-execution occurs (no duplicate export file, no duplicate webhook fire).

**AC3 — Persist-Before-Deliver (NFR16)**
**Given** a retry that succeeds
**When** the response is sent
**Then** the new artifact MUST already be persisted.

---

### Story 6.10: Idempotent re-export semantics on retry

**As a** backend engineer
**I want** re-exports to overwrite-in-place (same path) rather than create new files with suffixes
**So that** retry doesn't accumulate stale files (J3 narrative: "auto-export re-fires; summary file appears in folder (idempotent re-export)").

**FR/NFR coverage:** FR39 (extends idempotence to file-level), NFR16
**Depends on:** Story 6.9
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Same path overwrites**
**Given** a deferred export that succeeded once and is being retried (or auto-retried by Story 6.8 sweeper)
**When** the file is written
**Then** the existing file at the same path is overwritten in-place (atomic via `os.replace` after writing to a `.tmp` sibling)
**And** no `.1`, `.2` suffixes accumulate.

**AC2 — Concurrent retry collision**
**Given** two concurrent retries hit the same path
**When** both write
**Then** the `os.replace` ordering ensures the last writer wins atomically (no half-written files).

---

### Story 6.11: Retry escalation policy (R-EL18) + F1+F4 race-condition guard (cross-feature constraint #1)

**As a** project maintainer
**I want** failed actions to escalate to "manual intervention required" after one auto-retry, AND auto-summary to wait for alias propagation
**So that** users are never stuck in retry loops (R-EL18) AND F1's auto-summary never reads stale aliases mid-propagation (cross-feature constraint #1).

**FR/NFR coverage:** FR35 (escalation), NFR19 (bounded retry), R-EL18, cross-feature constraint #1
**Depends on:** Story 6.6, Story 6.9, epic-aliases-growth (alias propagation exists)
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — One auto-retry, then manual (R-EL18, NFR19)**
**Given** an auto-action fails with a transient error (HTTP timeout, 5xx, ENOENT)
**When** the lifecycle hook handles it
**Then** the system performs ONE automatic retry after a 30s backoff
**And** if that also fails, status escalates to `manual_intervention_required`
**And** the badge shows ⚠ "Manual intervention required — automatic retry exhausted" with link to logs (J3 narrative).

**AC2 — No retry loop**
**Given** a `manual_intervention_required` status
**When** the periodic sweeper or any background process examines it
**Then** NO further auto-retry occurs — only user-initiated retry via Story 6.9 endpoint.

**AC3 — F1+F4 race guard (cross-feature constraint #1)**
**Given** auto-summary is about to run for a recording
**When** the lifecycle hook checks preconditions
**Then** it verifies `recording_speaker_aliases` propagation has fully committed (no in-flight `PUT /api/recordings/{id}/aliases` mutations on the recording_id within the last 2s, AND the alias-substitution cache is fresh)
**And** if propagation is in-flight, auto-summary is delayed by `await asyncio.Event.wait(timeout=10s)` until the alias-mutation event clears
**And** a unit test (`test_f1_waits_for_f4_propagation`) asserts the guard with a fixture that simulates an in-flight alias PUT during summary trigger.

---

# Epic 7: epic-webhook — Extensibility webhook with security baseline + WebhookWorker

## Epic Goal

**As a** Configurator (Vassilis, J5)
**I want** to configure a webhook URL on my profile that receives an HTTPS POST with metadata (or full transcript opt-in) on transcription completion — with full security baseline (SSRF block, scheme allowlist, timeout, no redirects, no decompression) and Persist-Before-Deliver discipline
**So that** the long tail of custom workflows (Vassilis's `{audio_hash}` and force-lowercase needs) can be served without subprocess execution risk (FR43-47, R-EL5, R-EL11, R-EL25, R-EL26, R-EL28, R-EL31, R-EL33).

**Tier:** Growth
**Dependencies:** epic-foundations (profiles + keychain for tokens; no dependency on auto-actions or aliases)
**FRs covered:** FR43, FR44, FR45, FR46, FR47
**A11y inheritance:** Configuration UI in Story 7.2 inherits FR51, FR53; failure surfacing in Story 7.7 inherits FR52 (live region announcements via Story 6.6 badge pattern)
**Risk grade:** HIGH (security-critical SSRF prevention; async lifecycle; "underestimated time-sink" per PRD)
**Engineer-day budget:** 7-9 dev-days

---

### Story 7.1: `webhook_deliveries` table migration (R-EL33, ADR-006)

**As a** backend engineer
**I want** the `webhook_deliveries` table created
**So that** Story 7.5's Persist-Before-Deliver pattern has a place to write attempts (R-EL33, ADR-006, NFR17).

**FR/NFR coverage:** FR47 (prerequisite), NFR17, NFR21, NFR22, NFR40, R-EL33
**ADRs:** ADR-006
**Depends on:** epic-foundations Story 1.1
**Estimated dev-days:** 0.5d
**Includes migration:** **YES**

**Acceptance Criteria:**

**AC1 — Migration creates table**
**Given** an Alembic migration named `add_webhook_deliveries`
**When** `alembic upgrade head` runs
**Then** the table exists with `(id PK, recording_id INTEGER FK→recordings.id, profile_id INTEGER FK→profiles.id, status TEXT NOT NULL CHECK IN ('pending', 'in_flight', 'success', 'failed', 'manual_intervention_required'), attempt_count INTEGER DEFAULT 0, last_error TEXT, created_at TIMESTAMP, last_attempted_at TIMESTAMP, payload_json TEXT)`
**And** index `idx_webhook_deliveries_status` for sweeper queries
**And** forward-only (NFR22), non-destructive (NFR21).

**AC2 — Repository module**
**Given** `server/backend/server/database/webhook_deliveries_repository.py`
**When** Story 7.1 is complete
**Then** the module exposes parameterized SQL helpers: `create_pending(recording_id, profile_id, payload)`, `mark_in_flight(id)`, `mark_success(id)`, `mark_failed(id, error)`, `list_pending()`, `cleanup_older_than(days)` (NFR40 — 30-day default).

**AC3 — Cleanup retention**
**Given** the `cleanup_older_than(30)` function
**When** invoked by a periodic task (parallel to existing `audio_cleanup.periodic_cleanup`)
**Then** rows in `success` or `manual_intervention_required` older than 30 days are deleted
**And** rows in `pending`/`in_flight` are NEVER cleaned (could be in-flight).

---

### Story 7.2: Webhook URL configuration on profile + scheme/IP allowlist validation

**As a** Configurator (Vassilis)
**I want** to configure a webhook URL on my profile, with the system rejecting non-HTTPS URLs and private-IP URLs at SAVE time
**So that** SSRF and unencrypted webhook traffic are prevented (FR43, FR44, R-EL25, R-EL28, NFR9, NFR10).

**FR/NFR coverage:** FR43, FR44, FR51, FR53, NFR9, NFR10, R-EL25, R-EL28
**Depends on:** Story 7.1, epic-foundations Story 1.7 (keychain for tokens)
**Estimated dev-days:** 1.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Webhook URL field in profile UI (write-only)**
**Given** the profile-edit UI
**When** the Webhook section is enabled
**Then** the user can enter a webhook URL and an optional auth-header value
**And** the auth-header value is stored via the keychain (Story 1.7) — never plaintext on disk (FR49, NFR8)
**And** the URL itself is part of `private_field_refs_json` (also keychain-stored per R-EL22).

**AC2 — Scheme allowlist (FR44, NFR10, R-EL25)**
**Given** the user enters a URL with scheme other than `https://` or `http://localhost*`
**When** they click Save
**Then** the server rejects with HTTP 400 `{"error": "scheme_not_allowed", "allowed": ["https", "http (localhost only)"]}`
**And** the URL is NOT persisted.

**AC3 — Private-IP block (FR44, NFR9, R-EL28 — SSRF prevention)**
**Given** the user enters `http://192.168.1.1/webhook` OR `http://10.0.0.5/` OR `http://127.0.0.5/` OR `http://169.254.169.254/`
**When** they click Save
**Then** the server resolves the URL hostname AND checks the IP against RFC1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), 169.254/16, and 127.0.0.0/8 (with explicit `localhost` allowance)
**And** rejects with HTTP 400 `{"error": "private_ip_blocked", "ip": "<resolved_ip>"}`
**And** the validation is enforced at profile SAVE AND at delivery time (Story 7.4 re-checks — TOCTOU-safe).

**AC4 — `private_ip_resolver` fixture used in tests**
**Given** the test fixture from Story 1.1
**When** validation tests run
**Then** they use `private_ip_resolver` to monkeypatch `socket.getaddrinfo` and assert the block triggers for adversarial DNS rebinding cases.

**AC5 — Accessibility (FR51, FR53)**
**Given** the webhook URL field
**When** the user Tabs to it
**Then** the field has `aria-label="Webhook URL (HTTPS or http://localhost only)"` (FR53)
**And** validation error messages render in an `aria-live="assertive"` region.

---

### Story 7.3: WebhookWorker service skeleton + lifespan integration

**As a** backend engineer
**I want** a dedicated `WebhookWorker` service module wired into the FastAPI lifespan via `start()`/`stop()`
**So that** the `main.py` diff is minimal (preserves the 868-test baseline + live-mode model-swap) and the worker can be unit-tested in isolation.

**FR/NFR coverage:** FR45, FR47 (worker is the dispatcher), NFR24a, NFR24b, NFR47, R-EL33
**Depends on:** Story 7.1
**Estimated dev-days:** 2d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Service module exists**
**Given** a new module `server/backend/server/services/webhook_worker.py`
**When** Story 7.3 is complete
**Then** it exposes a `WebhookWorker` class with `async def start(self)` and `async def stop(self)` methods
**And** the worker reads pending deliveries from `webhook_deliveries` table and dispatches via Story 7.4.

**AC2 — Lifespan wiring**
**Given** `server/backend/main.py` lifespan
**When** the server starts
**Then** `await webhook_worker.start()` is called within `lifespan` AsyncGenerator
**And** on shutdown, `await webhook_worker.stop()` is called with a 30s grace deadline (drains in-flight deliveries before exit)
**And** the `main.py` diff is minimal — only imports + 2 lines added.

**AC3 — Bootstrap consistency (NFR24a, NFR24b)**
**Given** server startup with N pending webhook_deliveries from prior session
**When** the server reaches "ready" state
**Then** the worker has STARTED but not necessarily caught up — pending deliveries drain within 5 minutes via the worker's own loop (NFR24b)
**And** server readiness is NOT blocked by slow webhook endpoints (NFR24b — worker runs as background task, not part of bootstrap critical path).

**AC4 — Memory budget (NFR47)**
**Given** the worker runs for 60s under synthetic load (10 webhook fires/sec from `webhook_mock_receiver` with 200ms response delay)
**When** `psutil.Process().memory_info().rss` is sampled at 1 Hz
**Then** p95 ≤ 50 MB AND slope ≈ 0 (no leak)
**And** the test budget is ~75s.

**AC5 — Cancel-safe shutdown**
**Given** the worker is cancelled mid-delivery
**When** `asyncio.CancelledError` is raised
**Then** the worker logs at debug level (per CLAUDE.md project-context — never silent `pass`)
**And** in-flight deliveries are marked `pending` again (will retry on next start) — never silently lost.

---

### Story 7.4: Webhook delivery contract — 10s timeout, no redirects, no decompression

**As a** security-conscious deployer
**I want** webhook delivery to have a 10-second deadline, refuse to follow 3xx redirects, refuse to decompress response bodies, and treat HTTP status as ground truth
**So that** SSRF-via-redirect, zip-bomb, and indefinite-hang attacks are mitigated (FR45, R-EL26, NFR5, NFR11, NFR12).

**FR/NFR coverage:** FR45, NFR5, NFR11, NFR12, R-EL26
**Depends on:** Story 7.3
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — 10s timeout (FR45, NFR5, R-EL26)**
**Given** a webhook URL whose endpoint sleeps 15 seconds
**When** the worker delivers
**Then** the request times out at 10 seconds total (`httpx.AsyncClient(timeout=10.0)`)
**And** the delivery is marked `failed` with `last_error="timeout"`.

**AC2 — No redirect-following (FR45, NFR11, R-EL26)**
**Given** a webhook URL whose endpoint returns 301/302/307/308
**When** the worker delivers
**Then** the worker does NOT follow the redirect (`httpx.AsyncClient(follow_redirects=False)`)
**And** the delivery status is the 3xx code itself (treated as failure per AC4 below).

**AC3 — No response-body decompression (FR45, NFR12, R-EL26)**
**Given** an endpoint returning `Content-Encoding: gzip` with a zip-bomb body
**When** the worker delivers
**Then** the worker explicitly does NOT request decompression and does NOT process the body
**And** the body is read but not inflated; only the status code matters.

**AC4 — HTTP status as ground truth (FR45, R-EL26)**
**Given** the response status code
**When** evaluated
**Then** 2xx → `success`; everything else → `failed`
**And** the response body is NOT parsed for success/failure signals.

**AC5 — Test coverage uses `webhook_mock_receiver`**
**Given** the fixture from Story 1.1
**When** tests for AC1-4 run
**Then** they use `webhook_mock_receiver` programmable status/delay/redirect to cover each case.

---

### Story 7.5: Persist-Before-Deliver for webhook attempts (R-EL33)

**As a** project maintainer
**I want** every webhook delivery attempt persisted to `webhook_deliveries` BEFORE the actual fire
**So that** crashes don't lose webhook intent, AND failures remain queryable for debugging (FR47, NFR17, R-EL33).

**FR/NFR coverage:** FR47, NFR16, NFR17, NFR42, R-EL33
**Depends on:** Story 7.3, Story 7.4
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Insert before fire**
**Given** a webhook delivery is initiated (auto-action lifecycle or manual)
**When** the worker enters its dispatch sequence
**Then** a row is INSERTED into `webhook_deliveries` with `status='pending'` and full payload BEFORE the HTTP fire
**And** the row's `id` is captured; status updates to `in_flight` immediately before the actual `httpx.post`.

**AC2 — Crash-safe (NFR17)**
**Given** the server crashes between insert and fire
**When** the server restarts
**Then** the worker's startup sweep picks up the `pending` / `in_flight` row and re-attempts
**And** a regression test (`test_webhook_pending_recovered_on_restart`) asserts a `pending` row left over from a prior session is fired on next start.

**AC3 — Queryable failures (NFR42)**
**Given** a failed delivery
**When** an admin queries the table
**Then** the row's `last_error` and `payload_json` are inspectable for debugging
**And** the row is retained for 30 days per Story 7.1 cleanup retention (NFR40).

---

### Story 7.6: Webhook payload — metadata-default + opt-in transcript-text + payload versioning

**As a** Configurator
**I want** the webhook payload to default to metadata-only (recording_id, transcript_url, summary_url, profile_id, timestamp, payload_version) and opt-in to including transcript text
**So that** large transcripts don't accidentally leak across the network (FR46, NFR31, NFR37, R-EL31).

**FR/NFR coverage:** FR46, NFR31, NFR37, R-EL31
**Depends on:** Story 7.5
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Default metadata-only payload**
**Given** a webhook delivery for a recording
**When** the payload is constructed without explicit opt-in
**Then** the body is exactly `{"event": "transcription.completed", "recording_id": <id>, "transcript_url": "<api-url>", "summary_url": "<api-url-or-null>", "profile_id": <id>, "payload_version": "1.0", "timestamp_iso": "<utc-iso8601>"}`
**And** transcript text is NOT included.

**AC2 — Opt-in transcript-text (R-EL31)**
**Given** the profile's webhook config has `include_transcript_text: true`
**When** the payload is constructed
**Then** the body additionally includes `"transcript_text": "<full plaintext>"`
**And** if the file is > 1 MB, the worker logs a warning ("Large webhook payload — consider URL fetch instead").

**AC3 — Payload versioning (NFR31)**
**Given** the contract evolves to v1.1 in a future release
**When** the receiver inspects `payload_version`
**Then** it can branch on version
**And** a docstring notes "Deprecated payload versions remain supported for 2 minor releases" (per PRD versioning policy).

---

### Story 7.7: Failed delivery surfacing in recording status + retention cleanup

**As a** Configurator (Maria, J3)
**I want** failed webhook deliveries to surface as a status badge on the recording (R-EL1) AND be queryable in the persistence table for diagnostics — and have the table auto-clean after 30 days
**So that** I notice failures and can debug them, but the table doesn't grow unboundedly (FR47, NFR40, NFR42, R-EL1).

**FR/NFR coverage:** FR47, NFR40, NFR42, R-EL1
**Depends on:** Story 7.5, epic-auto-actions Story 6.6 (badge pattern), epic-auto-actions Story 6.11 (escalation policy)
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Badge surfaced on failure**
**Given** a webhook delivery transitions to `failed`
**When** the recording detail view loads
**Then** Story 6.6's status badge renders: ⚠ "Webhook delivery failed: <last_error>" with retry button
**And** retry calls `POST /api/recordings/{id}/auto-actions/retry` with `action_type="webhook"`.

**AC2 — Escalation per Story 6.11 (R-EL18)**
**Given** an auto-retry of a webhook delivery fails
**When** the second failure is recorded
**Then** status escalates to `manual_intervention_required` (badge: "Manual intervention required — automatic retry exhausted; check logs")
**And** no further auto-retry occurs.

**AC3 — Retention cleanup (NFR40)**
**Given** a periodic task (mirroring existing `audio_cleanup.periodic_cleanup` pattern: immediate first run, then `while True: await asyncio.sleep(interval); cleanup()`, cancel-safe with `asyncio.CancelledError` debug logging)
**When** it runs
**Then** it calls `webhook_deliveries_repository.cleanup_older_than(webhook_retention_days)` (default 30, configurable in `config.yaml`)
**And** the task is gated by `webhook_retention_enabled` flag (default true).

**AC4 — Queryable for diagnostics (NFR42)**
**Given** an admin wants to inspect a failed delivery from a week ago
**When** they query the table directly
**Then** the row is present with full `payload_json` and `last_error` for inspection.

---

# Epic 8: epic-model-profiles — Pre-transcription model profile switching (F5)

## Epic Goal

**As a** Configurator
**I want** to define named model profiles (e.g., "Fast English/EU" using Parakeet, "Multilingual" using Whisper) and switch the active model profile in one click — independent of the post-transcription profile, persisting across app restarts
**So that** I don't have to edit config files to switch between fast and multilingual STT (F5 — FR40, FR41, FR42).

**Tier:** Growth
**Dependencies:** epic-foundations (a11y scaffold; profiles infra not strictly required since model profiles are a separate concern, but UI consistency with Settings → Profiles favors waiting on foundations)
**FRs covered:** FR40, FR41, FR42
**A11y inheritance:** Story 8.2 inherits FR51, FR53
**Risk grade:** MEDIUM (config persistence + model swap orchestration; existing `model_manager` covers the swap mechanics)
**Engineer-day budget:** 3-4 dev-days
**Parallel-shippable:** Yes — independent of all other Growth epics; can ship in any order after epic-foundations.

---

### Story 8.1: Model profile data model + persistence + parallel funnel position (FR40, FR42)

**Status: DONE (sprint 1 — commit 038e03d; storage decision: electron-store under notebook.modelProfiles[])**

**As a** backend engineer
**I want** model profiles stored separately from post-transcription profiles
**So that** the parallel funnel position (pre- vs post-transcription) is honored (FR40, FR42).

**FR/NFR coverage:** FR40, FR42
**Depends on:** epic-foundations Story 1.1
**Estimated dev-days:** 1d
**Includes migration:** Yes (small — add `model_profiles` table OR extend electron-store)

**Acceptance Criteria:**

**AC1 — Storage decision**
**Given** the choice between a SQLite table vs electron-store key
**When** Story 8.1 begins
**Then** the implementer chooses ONE (recommendation: electron-store under `notebook.modelProfiles[]` since model profiles are dashboard-driven; existing model selection lives in electron-store) and documents the choice in the story PR description
**And** if SQLite, a migration `add_model_profiles_table` is created with `(id PK, name, stt_model, stt_language, transcribe_translate_target, created_at, updated_at)`.

**AC2 — Independence from post-transcription profile (FR42)**
**Given** model profiles and post-transcription profiles
**When** stored
**Then** they are in separate stores/tables — they do NOT share an `id` namespace
**And** unit test `test_model_profile_independent_of_notebook_profile` asserts cross-deletion does not affect the other.

---

### Story 8.2: Model profile CRUD UI in Settings

**Status: DONE (sprint 1 — commit 038e03d; component delivered, SettingsModal wiring deferred to follow-up polish — see deferred-work.md)**

**As a** Configurator
**I want** a Settings → Model Profiles section to create/edit/delete model profiles
**So that** I can manage them in the dashboard (FR40).

**FR/NFR coverage:** FR40, FR51, FR53
**Depends on:** Story 8.1
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Settings page lists profiles**
**Given** Settings → Model Profiles
**When** rendered
**Then** the page lists existing model profiles with name, STT model (e.g., "nvidia/parakeet-tdt-0.6b-v2"), STT language
**And** a "New profile" button opens an edit form.

**AC2 — Form fields**
**Given** the edit form
**When** rendered
**Then** fields are: name (text), STT model (dropdown of available models from existing model registry), STT language (dropdown from existing language list), translate-target (dropdown — for Canary supporting translation; per existing modelCapabilities.ts logic).

**AC3 — Accessibility (FR51, FR53)**
**Given** keyboard-only navigation
**When** the user Tabs through the form
**Then** focus order is logical
**And** dropdowns have descriptive `aria-label`s ("Speech-to-text model", "Source language", "Translation target language") not bare names.

---

### Story 8.3: One-click active model profile switch + `model_manager` orchestration

**Status: DONE (sprint 1 — commit 038e03d; component delivered with onSwitch contract; Sidebar integration + caller delegation to model_manager.load_transcription_model deferred to follow-up polish — see deferred-work.md)**

**As a** Configurator
**I want** a one-click toggle in the toolbar to switch between model profiles
**So that** I can go from Fast English to Multilingual without editing config (FR41).

**FR/NFR coverage:** FR41
**Depends on:** Story 8.2
**Estimated dev-days:** 1d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Toolbar selector**
**Given** model profiles exist
**When** the user opens the model-profile dropdown in the toolbar
**Then** the list shows profiles with the currently-active one highlighted
**And** clicking another profile triggers a switch.

**AC2 — Switch invokes `model_manager`**
**Given** a switch is triggered
**When** the dashboard sends the request
**Then** the existing `model_manager` orchestration unloads the current model and loads the new one (per existing `core/model_manager.py` logic)
**And** during the swap, the toolbar shows a spinner + "Switching model…" label.

**AC3 — Live mode safety**
**Given** a live mode session is in progress
**When** the user attempts a model switch
**Then** the switch is REJECTED with toast "Stop live mode before switching the model" — preserves the existing live-mode lifecycle invariant from CLAUDE.md.

---

### Story 8.4: Active model profile persists across app restarts (FR41)

**Status: DONE (sprint 1 — commit 038e03d; persistence verified by tests, "default on first launch" behavior is the no-op default until user picks one)**

**As a** Configurator
**I want** my chosen active model profile to be remembered after I close and reopen the app
**So that** I don't have to re-select it every session (FR41).

**FR/NFR coverage:** FR41
**Depends on:** Story 8.3
**Estimated dev-days:** 0.5d
**Includes migration:** No

**Acceptance Criteria:**

**AC1 — Persistence**
**Given** the user has set active model profile to "Multilingual"
**When** the app restarts
**Then** the toolbar selector renders with "Multilingual" selected on first paint
**And** the value is read from electron-store (`notebook.activeModelProfileId`).

**AC2 — Default on first launch**
**Given** a fresh installation with no active model profile set
**When** the app starts
**Then** the active model profile is set to a sane default (e.g., the first available profile, or a built-in "Default" profile matching current model_manager defaults)
**And** the user sees a toast "Using default model profile — set a custom one in Settings".

---

## Coverage Verification — All 54 FRs Anchored

> **Verification status: 100% explicit coverage of FR1–FR54.** No FR was deferred, dropped, or moved to a Vision item without traceable epic anchoring. Cross-cutting FR49–FR54 are inherited as ACs in downstream stories (per the FR Coverage Map above).

| FR Range | Anchor | Coverage |
|---|---|---|
| FR1–FR4 (import) | epic-import | ✅ 4/4 |
| FR5–FR9 (manual export) | epic-export | ✅ 5/5 |
| FR10, FR11, FR14, FR15, FR16, FR18, FR19, FR20 (profile system core) | epic-foundations | ✅ 8/8 |
| FR12, FR13, FR17 (filename templates) | epic-export | ✅ 3/3 |
| FR21, FR22, FR29 (alias MVP) | epic-aliases-mvp | ✅ 3/3 |
| FR23–FR28 (alias Growth + diarization review) | epic-aliases-growth | ✅ 6/6 |
| FR30–FR39 (auto-actions) | epic-auto-actions | ✅ 10/10 |
| FR40–FR42 (model profiles) | epic-model-profiles | ✅ 3/3 |
| FR43–FR47 (webhook) | epic-webhook | ✅ 5/5 |
| FR48 (deletion semantics) | epic-export | ✅ 1/1 |
| FR49, FR50 (keychain) | epic-foundations | ✅ 2/2 |
| FR51–FR54 (accessibility) | epic-foundations (scaffold) + inherited as ACs in downstream UI stories | ✅ 4/4 |

**No unhomed FRs.** **No forward dependencies between epics.** **All cross-feature constraints honored** (#1: epic-aliases-growth precedes epic-auto-actions; #2-4: enforced via Persist-Before-Deliver ACs and template sanitization).

---

## Constraint Compliance Audit

| Constraint | Status | Evidence |
|---|---|---|
| No forward dependencies between epics | ✅ | Dependency graph above + per-epic "Depends on" lines |
| epic-aliases-growth precedes epic-auto-actions (F1↔F4) | ✅ | epic-auto-actions Dependencies includes "epic-aliases-growth"; Story 6.11 AC3 implements the race guard |
| Persist-Before-Deliver (NFR16) AC on every artifact-producing story | ✅ | Stories 1.2 (AC6), 1.3 (AC6), 2.2 (AC3), 3.5 (AC4), 4.2 (AC3), 5.6 (AC6), 5.9 (AC7), 6.2 (AC4), 6.3 (AC3), 6.4 (full story), 6.9 (AC3), 7.5 (full story) |
| FR51-54 a11y AC on every alias/auto-action/export story | ✅ | Stories 3.5, 3.7, 4.3, 4.4, 5.5, 5.7, 5.8, 5.9, 6.6 each have explicit a11y ACs |
| Diarization-Review Keyboard Contract cited verbatim in epic-aliases-growth review-UI stories | ✅ | Story 5.9 AC3 reproduces the canonical table verbatim |
| First story of each epic that needs new tables/columns includes the migration | ✅ | epic-foundations 1.2 (profiles), 1.3 (snapshot column), 1.9 (review state); epic-import 2.1 (audio_hash); epic-aliases-mvp 4.1 (aliases); epic-webhook 7.1 (webhook_deliveries); epic-model-profiles 8.1 (storage decision documented) |

---

## Open Items Flagged for Operator (per handoff-prompt instruction)

> **Per Prompt 2 instruction: "If any FR cannot be cleanly anchored to a story without violating forward-dependency rules, STOP and flag — do not invent a workaround."**

**Result:** **No FR required a workaround.** All 54 FRs anchored cleanly. The 8-epic restructure successfully eliminates the readiness check's flagged forward-dependency and unhomed-FR violations.

**Minor decisions made autonomously (low-risk, documented inline):**
1. **Story 8.1 storage decision** (electron-store vs SQLite migration) is left to the implementer in the story PR — both options are valid; Story acceptance criterion AC1 makes the decision explicit and documented.
2. **Engineer-day estimates** total 53-68 days vs PRD's 32-44 baseline. Delta is primarily epic-foundations (12d cross-cutting infra not budgeted in PRD's MVP/Growth split) plus webhook (PRD itself acknowledged as "underestimated time-sink"). Implementation may compress as some foundation stories overlap with feature-story work.
3. **Story 6.10** added as a thin extension of FR39 idempotence to file-level overwrite-in-place — addresses J3 narrative requirement explicitly.

---

## Next Steps for Implementation Kickoff

1. **Re-run readiness check** per `handoff-prompts-readiness-fixes.md` Prompt 3 of 3 to confirm the 5 Critical / 8 Major / 4 Minor issues from the 2026-05-03 v1 report are resolved.
2. **Develop in dependency order:** epic-foundations first (Stories 1.1–1.9), then parallel-shippable epics: epic-import, epic-aliases-mvp, epic-webhook, epic-model-profiles. Then critical-path: epic-export → epic-aliases-growth → epic-auto-actions.
3. **MVP cut gate (`audio_notebook_qol_v1` flag):** completes when epic-foundations (MVP-portion: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8) + epic-import + epic-export + epic-aliases-mvp ship.
4. **Growth cut gate (`v1.4.1` tag):** completes when epic-foundations Growth-portion (1.5, 1.6, 1.9) + epic-aliases-growth + epic-auto-actions + epic-webhook + epic-model-profiles ship.
5. **Per-feature test minimums (NFR52):** F1 ≥10 failure-mode tests across epic-auto-actions stories; F4 ≥1 migration test (Story 4.1 AC2) + ≥4 propagation snapshots (Stories 4.4, 5.1, 5.2, 5.3); F2 property-based suite (Story 3.2 AC2).
