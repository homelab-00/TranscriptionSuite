---
date: 2026-05-03
project: TranscriptionSuite
prd_under_review: _bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md
stepsCompleted: ['step-01-document-discovery', 'step-02-prd-analysis', 'step-03-epic-coverage-validation', 'step-04-ux-alignment', 'step-05-epic-quality-review', 'step-06-final-assessment']
filesIncluded:
  prd: _bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md
  architecture: 'embedded-in-prd (ADRs 001-008 + API Design Convention + Implementation Considerations)'
  epics: 'declared-in-prd-frontmatter-only (epic-a/b/c groupings — no separate epics-and-stories file)'
  ux: 'embedded-in-prd (7 user journeys + cross-cutting accessibility AC)'
status: complete
verdict: NOT_READY
issuesFound: 17
criticalIssues: 5
majorIssues: 8
minorIssues: 4
---

# Implementation Readiness Assessment Report

**Date:** 2026-05-03
**Project:** TranscriptionSuite
**PRD Under Review:** `_bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md` — *Audio Notebook QoL pack* (Issue #104)

---

## Step 1 — Document Discovery

### Search Scope
`{planning_artifacts}` resolves to `/home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/_bmad-output/planning-artifacts/`.

### Files Found in `planning_artifacts/`

**PRD Documents:**
- `prd-issue-104-audio-notebook-qol.md` (90,995 bytes, modified 2026-05-03) — Audio Notebook QoL pack PRD (single whole document)

**Architecture Documents:**
- *(none found at the planning-artifacts root)*

**Epics & Stories Documents:**
- *(none found at the planning-artifacts root as stand-alone files)*

**UX Design Documents:**
- *(none found at the planning-artifacts root)*

**Other Planning Files (not in scope for this check):**
- `tech-spec-per-conversation-model-switching.md` — unrelated tech spec for a previously delivered feature

### Document Inventory

| Type | Whole | Sharded | Decision |
|---|---|---|---|
| PRD | ✅ `prd-issue-104-audio-notebook-qol.md` | ❌ | Use whole `prd-issue-104-audio-notebook-qol.md` |
| Architecture | ❌ | ❌ | **Missing — must verify whether embedded in PRD** |
| Epics | ❌ stand-alone | ❌ | **Missing — must verify whether embedded in PRD** |
| UX | ❌ | ❌ | **Missing — must verify whether embedded in PRD** |

### Duplicates
None detected. No `*prd*` folder or `*prd-*.md` siblings exist alongside `prd-issue-104-audio-notebook-qol.md`.

### Critical Issues / Warnings
- ⚠️ **No stand-alone Architecture, Epics, or UX documents found.** Many BMad PRDs embed an Epic Breakdown, UX/UI considerations, and a Solution Architecture / Technical Design section inline. The PRD will be inspected in Step 2 to determine whether those sections exist inside `prd-issue-104-audio-notebook-qol.md` itself, or whether the planning artifacts are genuinely incomplete.
- ⚠️ Implementation specs in `_bmad-output/implementation-artifacts/` are **out of scope** for this readiness check (they are post-planning artifacts). They will not be used as substitutes for missing planning docs.

### Resolution Plan
Proceed to Step 2 — PRD Analysis. During Step 2 we will inspect `prd-issue-104-audio-notebook-qol.md` for embedded epics / UX / architecture and reclassify the inventory above accordingly before judging epic coverage in Step 3.


---

## Step 2 — PRD Analysis

### Document Structure Found Inside `prd-issue-104-audio-notebook-qol.md`

The "missing" Architecture, UX, and Epics docs from Step 1 are partially **embedded inline** in the PRD:

| Inline Section | Substitutes For | Completeness |
|---|---|---|
| `## Project-Type Specific Requirements` (ADRs 001-008, API Design Convention, Endpoint deltas, Implementation Considerations) | Architecture document | Partial — design-level, not solution-design level |
| `## User Journeys` (J1–J7) + Journey Requirements Summary table | UX design document | Strong — 7 journeys covering Lurker / Configurator / Failure / Diarization edge / Originating user / Migration / Accessibility |
| `## Project Scoping & Phased Development` + frontmatter `plannedEpicGroupings` (epic-a/b/c) | Epics-and-stories document | **Weak** — only epic *groupings* declared; no actual epic specs, no user stories with acceptance criteria |
| `## Functional Requirements` (FR1–FR54) | FR catalog | Complete |
| `## Non-Functional Requirements` (NFR1–NFR55) | NFR catalog | Complete |
| `## Appendix C — R-EL Glossary` (R-EL1–R-EL35) | Elicitation carryover index | Complete |
| `## Appendix A — Feature Definitions` (F1–F6) | Feature anchor index | Complete |

### Functional Requirements Extracted (FR1–FR54)

#### Recording Import & Identity (FR1–FR4) — MVP
- **FR1 [MVP]:** Users can import audio files via the existing file-picker flow with no profile required.
- **FR2 [MVP]:** On import, the system computes a content hash (SHA-256 of normalized PCM) and stores it on the recording.
- **FR3 [MVP]:** When an imported file matches an existing recording's content hash, users see a prompt to either reuse the existing transcript or create a new entry.
- **FR4 [MVP]:** Audio dedup operates per-user-library scope; hashes are not compared across installations.

#### Manual Export & Download (FR5–FR9) — MVP
- **FR5 [MVP]:** Users can download a completed recording's transcript as plain text via an explicit "Download transcript" button.
- **FR6 [MVP]:** Users can download a completed recording's AI summary as plain text via an explicit "Download summary" button (disabled with tooltip when no summary exists).
- **FR7 [MVP]:** Manual download triggers the native OS file-save dialog with sensibly-named filename (default template) and OS user-Downloads default destination.
- **FR8 [MVP]:** Users can override filename and destination per-click via the file-save dialog.
- **FR9 [MVP]:** Downloaded files use plain-text format (one speaker turn per blank-line block; no subtitle timestamps).

#### Profile Management (FR10–FR20) — Cross/MVP/Growth
- **FR10 [Cross]:** Users can CRUD named profiles grouping filename template, destination folder, auto-action toggles, AI summary prompt, and (Growth) webhook config. *MVP slice = filename + destination + basic CRUD; Growth slice adds auto-actions + webhook.*
- **FR11 [Cross]:** Profile reads return only public fields; private fields (destination paths, webhook URLs/auth, API keys) are write-only.
- **FR12 [MVP]:** Filename template uses extensible placeholder grammar (`{date}`, `{title}`, `{recording_id}`, `{model}` minimum) with server-side validation rejecting malformed templates.
- **FR13 [MVP]:** Live filename preview updates as user types template, computed against sample recording.
- **FR14 [MVP]:** Destination folder selected via native OS folder picker (not free-text input).
- **FR15 [Growth]:** Empty-profile screen offers opt-in 30-second setup wizard or direct field editing (hybrid field-first).
- **FR16 [Cross]:** Profile JSON schema is versioned (`schema_version: "MAJOR.MINOR"`); unknown majors rejected on save.
- **FR17 [Growth]:** Filename-template changes apply forward-only; existing files keep names; per-recording opt-in re-export via context menu.
- **FR18 [Cross]:** Each transcription job snapshots its profile state at job-start; profile edits during job don't affect running job.
- **FR19 [Cross]:** Mid-flight transcription crash recovery rehydrates profile snapshot from job row before resuming.
- **FR20 [Growth]:** Users can switch active profile mid-session; change applies to subsequently-started jobs only.

#### Speaker Aliasing (FR21–FR29) — MVP/Growth
- **FR21 [MVP]:** Users can rename "Speaker 1/2/..." to real names per-recording; recording-level scope (not cross-recording identity).
- **FR22 [MVP]:** Aliases substitute into the transcript view (MVP slice).
- **FR23 [Growth]:** Aliases substitute into plain-text exports, subtitle exports, AI summary prompt context, AI chat context.
- **FR24 [Growth]:** AI summary uses aliases verbatim — no inference, merging, or rewriting.
- **FR25 [Growth]:** Low-confidence diarization completion flags persistent banner and HOLDS auto-summary until review.
- **FR26 [Growth]:** Review view filters by confidence threshold, supports bulk-accept, keyboard-navigable end-to-end.
- **FR27 [Growth]:** Diarization-review state persists across app restarts; auto-summary held until review explicitly completed.
- **FR28 [Growth]:** "Review uncertain turns" banner is persistent — does not auto-dismiss until acted on.
- **FR29 [MVP]:** Read/update aliases via REST endpoints (`GET/PUT /api/recordings/{id}/aliases`).

#### Auto Post-Transcription Actions (FR30–FR39) — Growth
- **FR30 [Growth]:** Profile can auto-generate AI summary on completion.
- **FR31 [Growth]:** Profile can auto-export transcript and summary to destination folder on completion.
- **FR32 [Growth]:** Auto-summary auto-saved back to recording on success.
- **FR33 [Growth]:** Each auto-action persists durably before client delivery (Persist-Before-Deliver invariant).
- **FR34 [Growth]:** Auto-actions are independent; partial success allowed (transcript ok, summary fails).
- **FR35 [Growth]:** Failed auto-actions surface as recoverable status badge with single-click retry; transient failures auto-retry once before manual.
- **FR36 [Growth]:** Empty AI summaries surface as distinct "summary empty" status (not green/success).
- **FR37 [Growth]:** Token-limit-truncated summaries surface as distinct "summary truncated" status with truncated content available.
- **FR38 [Growth]:** Auto-export to unavailable destination defers and auto-retries when destination becomes available; transcript stays safe in recording during deferral.
- **FR39 [Growth]:** Auto-action retry is idempotent — replay returns "already complete" without re-firing side effects.

#### Pre-Transcription Model Profiles (FR40–FR42) — Growth
- **FR40 [Growth]:** Configure named model profiles selecting STT model + language settings (e.g., Fast English/EU = Parakeet/Canary; Multilingual = Whisper).
- **FR41 [Growth]:** Switch active model profile in one click; choice persists across restarts.
- **FR42 [Growth]:** Active model profile is independent of post-transcription profile (parallel funnel position).

#### Extensibility Webhook (FR43–FR47) — Growth
- **FR43 [Growth]:** Configure webhook URL on profile to receive HTTP POST on completion.
- **FR44 [Growth]:** Webhook URL allowlist: `https://` only + explicit `http://localhost*`; private IP ranges (RFC1918, 169.254/16, 127.0.0.0/8 except `localhost`) rejected at profile save.
- **FR45 [Growth]:** Webhook delivery: 10s deadline, no redirect-following, no response-body decompression, HTTP status as ground truth (2xx success, all else failure).
- **FR46 [Growth]:** Webhook payload defaults to metadata-only; transcript text in payload is opt-in per profile.
- **FR47 [Growth]:** Webhook deliveries persisted (status, attempt_count, last_error, payload) before firing; failures surface in recording status AND remain in persistence table.

#### Privacy, Security & Accessibility (FR48–FR54) — Cross
- **FR48 [Cross]:** Recording deletion does NOT propagate to auto-exported on-disk artifacts by default; deletion confirmation dialog states this AND offers per-deletion option to also remove on-disk artifacts.
- **FR49 [Cross]:** Private profile fields stored via OS-native secret store (macOS Keychain, Windows DPAPI, Linux libsecret); never plain-text on disk.
- **FR50 [Cross]:** OS keychain unavailable → encrypted-file fallback gated by `KEYRING_BACKEND_FALLBACK=encrypted_file` env flag; security delta documented in deployment guides.
- **FR51 [Cross]:** All UI surfaces in QoL pack are keyboard-only operable (tab, enter, arrows).
- **FR52 [Cross]:** Status changes announced via ARIA live regions with appropriate politeness levels.
- **FR53 [Cross]:** Interactive elements have descriptive labels (not generic "Download"/"Click here") accessible to screen readers.
- **FR54 [Cross]:** Diarization-review view supports turn-by-turn screen-reader navigation announcing content + speaker label + confidence level per turn.

**Total Functional Requirements: 54** (FR1–FR54)
- MVP-tagged: 17 (FR1–FR9, FR12–FR14, FR21, FR22, FR29, plus partial-Cross items)
- Growth-tagged: 24
- Cross-tagged: 13 (foundational/cross-cutting; mostly Profile/Privacy/Security/A11y)

### Non-Functional Requirements Extracted (NFR1–NFR55)

#### Performance (NFR1–NFR7)
- **NFR1:** `pytest-benchmark` regression gate — CI fails if median latency degrades >15% vs v1.3.x baseline.
- **NFR2:** Live filename preview p95 < 50ms (1000 iterations, perf_counter_ns, stubbed I/O).
- **NFR3:** Auto-summary lifecycle hook fires within 2s of job → `completed`.
- **NFR4:** Auto-export lifecycle hook same 2s deadline as NFR3 (independent).
- **NFR5:** Webhook delivery 10s timeout (R-EL26).
- **NFR6:** Audio dedup hash within existing audio-preservation window (no observable additional delay).
- **NFR7:** Diarization-review filter linearity benchmark r²>0.95 at [10,100,500,1000] turns; per-PR ≤200ms up to 100 turns.

#### Security (NFR8–NFR15)
- **NFR8:** Private-field-at-rest encryption — OS keychain primary; AES-256-GCM + PBKDF2 fallback; `secrets/master.key` (mode 0600) auto-generated first-launch; AC test `test_config_migration_generates_secret_on_v13x_config`; security-delta documented.
- **NFR9:** SSRF prevention — webhook URL validation blocks RFC1918/169.254/127 (except `localhost`) at profile save AND delivery.
- **NFR10:** Webhook scheme allowlist `https://` + `http://localhost*`.
- **NFR11:** Server does not follow 3xx redirects.
- **NFR12:** No response-body decompression (zip-bomb prevention).
- **NFR13:** Profile schema major-version validation rejects unknown majors with explicit 400.
- **NFR14:** Filename template injection prevention — sanitized for path traversal, Windows reserved names, Unicode normalization, 255-char limits.
- **NFR15:** Existing token-based auth model unchanged.

#### Reliability & Durability (NFR16–NFR24b)
- **NFR16:** Persist-Before-Deliver invariant preserved (no new violations).
- **NFR17:** Webhook delivery durability — persisted to `webhook_deliveries` BEFORE firing.
- **NFR18:** Profile snapshot durability — persisted at job-start; rehydrated on crash recovery.
- **NFR19:** Retry escalation bounded — 1 auto-retry, then manual.
- **NFR20:** Deferred-retry on transient destination unavailability.
- **NFR21:** F4 migration non-destructive (creates new tables/columns without modifying existing data).
- **NFR22:** Migrations forward-only (no downgrade scripts).
- **NFR23:** Diarization-review state persists across restarts.
- **NFR24a:** Bootstrap consistency — coherent DB state and accepting requests within 30s of backend startup; profile-snapshot rehydration + orphan-sweep on critical path.
- **NFR24b:** Delivery catch-up — webhook backlog drained within 5 min of bootstrap; runs as async background, NOT critical path.

#### Accessibility (NFR25–NFR30)
- **NFR25:** Lighthouse CI accessibility score ≥90 on all new pages, gate enforced in `dashboard-quality.yml`. New devDep `@lhci/cli@0.14`, `dashboard/lighthouserc.json`, +90s CI wall-time.
- **NFR26:** Keyboard-only operability (re FR51).
- **NFR27:** ARIA live regions for async status (re FR52).
- **NFR28:** Descriptive interactive labels (re FR53).
- **NFR29:** Diarization-review screen-reader navigation (re FR54).
- **NFR30:** Logical tab-order across new components.

#### Integration (NFR31–NFR34)
- **NFR31:** Webhook contract versioned (`payload_version`); deprecated versions supported 2 minor releases.
- **NFR32:** Profile schema versioned (`schema_version`); forward-compatible.
- **NFR33:** Single `keyring >= 25.0, < 26` dependency wraps macOS Keychain / Windows DPAPI / Linux libsecret.
- **NFR34:** Headless-Linux fallback documented — `keyrings.alt` EncryptedFile via env flag.

#### Privacy & Data Handling (NFR35–NFR40)
- **NFR35:** No outbound telemetry by design (telemetry = data leaving host's trust boundary; local logs/metrics/diagnostics not telemetry).
- **NFR36:** Recording deletion does not propagate to disk (re R-EL13/R-EL32).
- **NFR37:** Webhook payload metadata-default; transcript-text inclusion opt-in per profile.
- **NFR38:** Right-to-erasure surface in deletion dialog.
- **NFR39:** i18n explicit deferral — UI strings English-only; Unicode in user content preserved end-to-end. Multi-language UI Vision-deferred.
- **NFR40:** `webhook_deliveries` retention — 30-day default (`webhook_retention_days`); periodic cleanup follows existing `audio_cleanup` pattern.

#### Observability (NFR41–NFR45)
- **NFR41:** Status badges as primary user observability surface.
- **NFR42:** Webhook delivery inspection table queryable for debugging.
- **NFR43:** Persistent banners for action-required states.
- **NFR44:** Structured logging for security-sensitive ops via structlog INFO with structured context (operation, recording_id/profile_id, timestamp); no PII in logs.
- **NFR45:** User log-export via existing diagnostic-paste mechanism (depends on `tech-spec-gpu-error-surfacing-diag-paste-fix`).

#### Concurrency & Resource (NFR46–NFR49)
- **NFR46:** Profile concurrent-edit semantics — last-write-wins with `updated_at` timestamp; concurrent edits surface as toast on stale-cache discovery. Documented as deliberate divergence from existing config-edit patterns; ETag/optimistic locking deferred to Vision.
- **NFR47:** Webhook worker memory budget — psutil 1Hz sampling under synthetic load; assertion p95≤50MB AND slope≈0 (no leak); ~75s test budget.
- **NFR48:** Plain-text export streams content (no buffering); supports up to 8 hours / ~1 GB transcripts without exhausting RAM.
- **NFR49:** Multi-user/team scaling out of scope (Vision item).

#### Discoverability (NFR50)
- **NFR50:** Visual contiguity for new affordances — Download buttons, status badges, banners contiguous with existing affordances; no hidden settings required for MVP-tier features (Lurker workflow holds without configuration).

#### Test Coverage & Enforcement (NFR51–NFR55)
- **NFR51:** Coverage no regression vs v1.3.x baseline (~80% backend).
- **NFR52:** Per-feature test minimums by risk grade — F1 ≥10 failure-mode tests; F4 ≥1 migration test + ≥4 propagation snapshots; F2 property-based suite for sanitization.
- **NFR53:** Day-1 test fixtures land BEFORE feature implementation — `webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock` in `server/backend/tests/conftest.py`.
- **NFR54:** Test-time discipline ENFORCED via linters — backend ruff `flake8-tidy-imports.banned-api` bans `time.sleep`/`datetime.datetime.now`/`httpx.Client`/`httpx.AsyncClient` inside `tests/`; frontend ESLint `no-restricted-imports` scoped to `**/*.test.ts`; CI gate via `dashboard-quality.yml`. Approved alternatives: `asyncio.Event.wait()`, `frozen_clock`, `webhook_mock_receiver`.
- **NFR55:** CodeQL + dashboard-quality CI gates pass without new findings.

**Total Non-Functional Requirements: 55** (NFR1–NFR55) across 9 categories.

### Additional Requirements / Constraints

#### Architecture Decision Records (ADRs 1–8)
- **ADR-001:** REST CRUD `/api/profiles` (consistency with `/api/recordings/*`).
- **ADR-002:** Audio dedup via `audio_hash` column on existing `transcription_jobs` table (no separate table for v1.4).
- **ADR-003:** Profile snapshot as JSON blob in `job_profile_snapshot` column with `snapshot_schema_version`.
- **ADR-004:** Webhook delivery via `asyncio.create_task` (not full queue table); failed surface via R-EL1.
- **ADR-005:** Per-recording alias scope for v1.4; identity-level deferred to Vision.
- **ADR-006:** Webhook deliveries persisted in `webhook_deliveries` table (Persist-Before-Deliver discipline).
- **ADR-007:** Profile state in React Query (server cache); `activeProfileId` in Zustand (client ephemeral); edits trigger `queryClient.invalidateQueries(['profiles', id])`.
- **ADR-008:** Crash recovery rehydrates profile snapshot in `transcription_job_tracker`.

#### API Endpoints (12 new + 1 modified + lifecycle hooks)
12 new endpoints in `api/routes/notebook.py` (profiles CRUD, aliases R/U, reexport, diarization-confidence/review, dedup-check, auto-actions/retry); `POST /api/transcribe/file` modified to accept optional `profile_id`; job-completion lifecycle fires auto-actions after persistent state written.

#### Cross-feature Constraints (frontmatter)
- F1 must wait for F4 propagation before auto-summary (prevents stale-alias race).
- F1 must respect Persist-Before-Deliver — auto-summary persists to recording before client notification.
- F4 aliases must persist before any export delivers them (durability invariant).
- F2 filename templates sanitize for path traversal, Windows reserved names, Unicode, 255-char limits.

#### R-EL Carryover Items (R-EL1–R-EL35)
35 elicitation carryover requirements harvested across pre-mortem, red team, expert panel, customer support theater, focus group, FMA, security audit, party-mode, and TRIZ phases. All listed in PRD Appendix C with source attribution. Cross-referenced into FRs/NFRs/ADRs.

#### Day-1 Dependencies & Test Fixtures
- Backend deps: `keyring >= 25.0, < 26`, `keyrings.alt` (opt-in headless), `pytest-benchmark`.
- Frontend deps: `@lhci/cli@0.14` devDep.
- Config changes: docker-compose bind-mount `/secrets`, ruff banned-api, ESLint `no-restricted-imports`, dashboard-quality.yml lighthouse job.
- Day-1 fixtures: `webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock`.

#### Phased Tier Architecture
- **MVP** (`audio_notebook_qol_v1` flag): F2 + F3 + F4 MVP slice + F6 — 18-24 dev-days
- **Growth** (`v1.4.1` tag, on top of MVP): F4 Growth slice + F1 + F5 + webhooks — 14-20 dev-days
- **Vision** (deferred; each requires its own PRD): identity-level aliases, subprocess hook, built-in presets, multi-target export, profile sharing, auth-gated reveal endpoint
- **Total v1.4.x window:** 8-11 calendar weeks at 4 dev-days/week solo cadence

### PRD Completeness Assessment

#### Strengths
1. **Exhaustive requirement extraction.** 54 FRs + 55 NFRs + 35 R-ELs + 8 ADRs is unusually thorough for a 6-feature QoL pack. Every elicitation pass (pre-mortem, red team, FMA, security audit, party-mode) is traceable to specific R-EL items with source attribution.
2. **Strong cross-referencing.** Appendix B provides a topic-to-section index. Appendix A consolidates feature anchors (tier, persona, journeys, FRs, R-ELs, risk grade, budget). Appendix C glosses every R-EL.
3. **Risk grading per feature.** F1 and F4 explicitly marked HIGH risk with mitigation strategies (split into MVP/Growth slices, persist-before-deliver, race-condition guards).
4. **Tier discipline.** Every FR carries an explicit `[MVP]` / `[Growth]` / `[Cross]` tag. Phased ship strategy is concrete (flags, tags, calendar windows, decision points, decision-maker named).
5. **Day-1 test infrastructure committed.** NFR53 + NFR54 + NFR47 demonstrate awareness that test discipline is enforced before features land.
6. **Acceptance criteria embedded in Success Criteria.** User Success / Business Success / Technical Success all have verification steps (manual acceptance test, integration test, snapshot test, etc.).
7. **Project-rule alignment.** Persist-Before-Deliver invariant explicitly preserved (NFR16/NFR17/NFR18); existing `audio_cleanup` pattern referenced for `webhook_deliveries` retention; existing diagnostic-paste mechanism referenced (NFR45); existing token auth model preserved (NFR15); existing Lifespan + periodic-task pattern preserved (NFR24a/b).
8. **Honest dissent documented.** "Alternative Paths Considered (and Not Taken)" captures Path A (Ship-and-Validate) and Path B (Blue Ocean reframe) with reasons rejected — important guardrails against future second-guessing.

#### Concerns / Gaps to Verify Downstream
1. **No actual epics-and-stories file.** Frontmatter declares `plannedEpicGroupings: epic-a/b/c` but there is no `epics.md` or `epic-a.md` with story-level acceptance criteria. The PRD ends at "feature definition" granularity, not "ready-to-implement story" granularity. Step 3 will assess whether this is fatal.
2. **No solution-design document for the WebhookWorker or `webhook_deliveries` schema.** ADR-006 commits to a persisted deliveries table but no schema (column types, indexes, constraints) or worker state machine is specified beyond "extracted module at `server/backend/server/services/webhook_worker.py`."
3. **F5 has thin journey coverage.** PRD acknowledges this explicitly ("only J2-implicit reference") — accepted as low-narrative-density, but Step 3 may want a stronger story-level definition since user value is asserted, not journey-demonstrated.
4. **NFR45 has a transitive dependency** on `tech-spec-gpu-error-surfacing-diag-paste-fix` — if that mechanism changes during v1.4, NFR45 must be re-validated. The PRD flags this but does not version-pin the dependency.
5. **Profile UI Wizard (FR15) is Growth-tagged but the wizard's content/structure is not specified.** Only "30-second setup wizard" is described. No wizard-step breakdown.
6. **R-EL15 keyboard-navigation contract is asserted but not specified at the keystroke level.** J4 narrative shows ↑/↓/←/→/Enter/Esc/Space; J7 shows Tab/Shift+Tab/arrows/Enter/Esc/Space. Some overlap but no canonical spec.
7. **No state machine for diarization review.** R-EL19 (state persists), R-EL20 (banner persists), FR25 (HOLD auto-summary), FR27 (state persists), FR28 (banner persists) all reference review state lifecycle, but no explicit state diagram (pending → in-review → completed → released).
8. **No data model spec for `recording_speaker_aliases` table.** F4 MVP slice creates the table but no column list, indexes, or relation to existing `transcription_jobs` is documented.
9. **No explicit migration plan ordering** for the three new tables (`profiles`, `webhook_deliveries`, `recording_speaker_aliases`) and the two new columns (`audio_hash`, `job_profile_snapshot`). Alembic ordering matters for FK constraints.
10. **The CRUD diarization-review API surface is incomplete** — `POST /api/recordings/{id}/diarization-review` accepts review decisions, but no GET to fetch current review state for the persistent banner (FR27/FR28).


---

## Step 3 — Epic Coverage Validation

### Source-of-Truth Caveat

**No stand-alone epics-and-stories document exists.** Coverage in this section is derived from two PRD-internal sources:

1. **`plannedEpicGroupings` in PRD frontmatter** — declares 3 epics (epic-a, epic-b, epic-c) and which features (F1–F6) belong to each.
2. **Appendix A — Feature Definitions** — maps each feature (F1–F6) to its FR range.

This is a **proxy coverage analysis**, not a true epic-coverage analysis. A real epics-and-stories document would have stories, story-level acceptance criteria, and explicit per-story FR traceability. Section 5 (Coverage Statistics) reports proxy coverage; the absence of story-level coverage is itself flagged as a critical gap.

### Planned Epic Groupings (from PRD frontmatter)

| Epic ID | Title | Features Covered | Rationale |
|---|---|---|---|
| **epic-a** | Post-transcription workflow | F1, F2, F3, F6 | Single user story — complete the scene from import to handoff |
| **epic-b** | Speaker aliasing (cross-cutting) | F4 | Data-shape change touching DB, view, exports, LLM context — deserves its own rigor |
| **epic-c** | Pre-transcription model profiles | F5 | Different funnel position (pre- vs post-transcription) but same PRD for narrative coherence |

### Feature-to-FR Map (from Appendix A)

| Feature | Tier | FRs |
|---|---|---|
| **F1** Auto Post-Transcription Actions | Growth | FR30–FR39 |
| **F2** User-Defined Filename Templates | MVP | FR12, FR13, FR17 |
| **F3** Plain-Text Export | MVP | FR9, FR48 (deletion) |
| **F4** Speaker Aliasing (MVP+Growth slices) | MVP slice: FR21, FR22, FR29 / Growth slice: FR23–FR28 |
| **F5** Pre-Transcription Model Profiles | Growth | FR40, FR41, FR42 |
| **F6** Explicit Download Buttons | MVP | FR5, FR6, FR7, FR8 |

### FR-to-Epic Coverage Matrix

| FR | Tier | Section | Belongs to Feature | Covered by Epic | Status |
|---|---|---|---|---|---|
| FR1 | MVP | Recording Import | (no feature anchor — base capability "import audio") | **Not in any epic** | ⚠️ Missing |
| FR2 | MVP | Recording Import | (audio dedup; mapped to R-EL23, ADR-002) | **Not in any epic** | ⚠️ Missing |
| FR3 | MVP | Recording Import | (audio dedup) | **Not in any epic** | ⚠️ Missing |
| FR4 | MVP | Recording Import | (audio dedup scope) | **Not in any epic** | ⚠️ Missing |
| FR5 | MVP | Manual Export | F6 | epic-a | ✅ Covered |
| FR6 | MVP | Manual Export | F6 | epic-a | ✅ Covered |
| FR7 | MVP | Manual Export | F6 | epic-a | ✅ Covered |
| FR8 | MVP | Manual Export | F6 | epic-a | ✅ Covered |
| FR9 | MVP | Manual Export | F3 | epic-a | ✅ Covered |
| FR10 | Cross | Profile Mgmt | (Profile system; foundational across F1/F2/F5) | **Implied epic-a** but not anchored to feature | ⚠️ Implicit |
| FR11 | Cross | Profile Mgmt | (private fields) | **Implied epic-a** | ⚠️ Implicit |
| FR12 | MVP | Profile Mgmt | F2 | epic-a | ✅ Covered |
| FR13 | MVP | Profile Mgmt | F2 | epic-a | ✅ Covered |
| FR14 | MVP | Profile Mgmt | (folder picker, foundational) | **Implied epic-a** | ⚠️ Implicit |
| FR15 | Growth | Profile Mgmt | (wizard, foundational) | **Implied epic-a** | ⚠️ Implicit |
| FR16 | Cross | Profile Mgmt | (schema versioning) | **Implied epic-a** | ⚠️ Implicit |
| FR17 | Growth | Profile Mgmt | F2 | epic-a | ✅ Covered |
| FR18 | Cross | Profile Mgmt | (snapshot at job-start, R-EL21) | **Implied epic-a** | ⚠️ Implicit |
| FR19 | Cross | Profile Mgmt | (crash recovery rehydration, R-EL35) | **Implied epic-a** | ⚠️ Implicit |
| FR20 | Growth | Profile Mgmt | (active profile switch) | **Implied epic-a** | ⚠️ Implicit |
| FR21 | MVP | Speaker Aliasing | F4 MVP slice | epic-b | ✅ Covered |
| FR22 | MVP | Speaker Aliasing | F4 MVP slice | epic-b | ✅ Covered |
| FR23 | Growth | Speaker Aliasing | F4 Growth slice | epic-b | ✅ Covered |
| FR24 | Growth | Speaker Aliasing | F4 Growth slice | epic-b | ✅ Covered |
| FR25 | Growth | Speaker Aliasing | F4 Growth slice | epic-b | ✅ Covered |
| FR26 | Growth | Speaker Aliasing | F4 Growth slice | epic-b | ✅ Covered |
| FR27 | Growth | Speaker Aliasing | F4 Growth slice | epic-b | ✅ Covered |
| FR28 | Growth | Speaker Aliasing | F4 Growth slice | epic-b | ✅ Covered |
| FR29 | MVP | Speaker Aliasing | F4 MVP slice | epic-b | ✅ Covered |
| FR30 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR31 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR32 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR33 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR34 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR35 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR36 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR37 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR38 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR39 | Growth | Auto Actions | F1 | epic-a | ✅ Covered |
| FR40 | Growth | Pre-Tx Models | F5 | epic-c | ✅ Covered |
| FR41 | Growth | Pre-Tx Models | F5 | epic-c | ✅ Covered |
| FR42 | Growth | Pre-Tx Models | F5 | epic-c | ✅ Covered |
| FR43 | Growth | Webhook | (R-EL5 + R-EL11; **no feature-letter anchor**) | **Implied epic-a** but not in any F1–F6 | ⚠️ Orphan |
| FR44 | Growth | Webhook | (security baseline) | **Implied epic-a** but no feature anchor | ⚠️ Orphan |
| FR45 | Growth | Webhook | (delivery contract) | **Implied epic-a** but no feature anchor | ⚠️ Orphan |
| FR46 | Growth | Webhook | (payload contract) | **Implied epic-a** but no feature anchor | ⚠️ Orphan |
| FR47 | Growth | Webhook | (deliveries persistence) | **Implied epic-a** but no feature anchor | ⚠️ Orphan |
| FR48 | Cross | Privacy | F3 (deletion semantics, R-EL13) | epic-a | ✅ Covered |
| FR49 | Cross | Security | (keychain, R-EL29) | **Cross-cutting; no epic anchor** | ⚠️ Cross-cutting |
| FR50 | Cross | Security | (keychain fallback, R-EL34) | **Cross-cutting; no epic anchor** | ⚠️ Cross-cutting |
| FR51 | Cross | Accessibility | (J7 cross-cutting AC for F1/F2/F4/F5/F6) | All three epics inherit | ⚠️ Cross-cutting |
| FR52 | Cross | Accessibility | (J7 cross-cutting AC) | All three epics inherit | ⚠️ Cross-cutting |
| FR53 | Cross | Accessibility | (J7 cross-cutting AC) | All three epics inherit | ⚠️ Cross-cutting |
| FR54 | Cross | Accessibility | (J7 cross-cutting AC) | All three epics inherit | ⚠️ Cross-cutting |

### Coverage Statistics

| Status | Count | % of 54 FRs |
|---|---|---|
| ✅ **Explicitly covered** (mapped via feature-to-epic chain) | 30 | 56% |
| ⚠️ **Implicit** (foundational profile-system FRs, no feature anchor but clearly in epic-a) | 9 | 17% |
| ⚠️ **Orphan** (Webhook FR43–FR47: in PRD scope, in Growth tier, but no F1–F6 anchor) | 5 | 9% |
| ⚠️ **Cross-cutting** (FR49, FR50 security; FR51–FR54 accessibility — must be claimed by every epic) | 6 | 11% |
| ⚠️ **Missing** (FR1–FR4 audio import + dedup: not anchored to any epic or feature) | 4 | 7% |

**Honest coverage: 30/54 = 56% explicit; the remaining 44% require epic restructuring to anchor.**

### Missing / Mis-Anchored FRs (Critical)

#### 🔴 Critical Missing — FR1, FR2, FR3, FR4 (Recording Import & Identity)

**FR1–FR4 do not belong to any of F1–F6** and therefore have no anchor in the planned epic groupings.

- **FR1 [MVP]:** Audio file import via existing file-picker (no profile required). *Foundational; arguably belongs to epic-a as the "entry point" of the post-transcription workflow.*
- **FR2 [MVP]:** SHA-256 audio content hash on import (R-EL23, ADR-002). *Implementation requires `audio_hash` column on `transcription_jobs`; touches the durability layer.*
- **FR3 [MVP]:** Dedup prompt UI on hash match (R-EL23). *Touches import flow + UI; partially demonstrated in J1 narrative.*
- **FR4 [MVP]:** Per-user-library scope for dedup (R-EL23). *Implementation constraint; informs how `audio_hash` index is queried.*

**Impact:** All four are MVP-tagged. They block the J1 Lurker happy path (R-EL23 dedup prompt shown in J1 narrative). Without an epic home, they have no story owner, no per-FR AC, no risk grading.

**Recommendation:** Either (a) add a fourth epic **epic-d "Recording import + dedup"** for FR1–FR4 + R-EL23, or (b) explicitly extend epic-a to include "Import & Dedup" as a subgroup and update the `plannedEpicGroupings.epic-a.features` list to include a new `F0` or `F2.5` anchor.

#### 🟠 Orphan — FR43–FR47 (Extensibility Webhook)

The Extensibility Webhook is one of the PRD's five differentiators and has its own FR section (5 FRs), full security baseline (NFR9–NFR12), persistence story (R-EL33), and an extracted service module (`webhook_worker.py`). But:

- **It has no F1–F6 feature letter** in Appendix A.
- It is **not in `plannedEpicGroupings`** under any of epic-a/b/c.
- F1's risk grade depends on it (auto-actions surface to webhook).
- The 6–8 dev-day estimate flagged "underestimated time-sink" lives here.

**Impact:** This is the largest single Growth-tier work item without an epic home. Stories cannot be written for it.

**Recommendation:** Add a fourth epic **epic-d "Extensibility webhook"** OR redefine F1 to include the webhook (currently F1's Appendix A scope ends at "save-back, observable failure recovery" — webhook is implicit). At minimum, add a **F7 "Extensibility Webhook"** to Appendix A and append F7 to epic-a's feature list.

#### 🟡 Cross-cutting — FR49, FR50 (Security/Keychain) and FR51–FR54 (Accessibility)

- **FR49–FR50 (keychain):** Foundational security; required by the Webhook (FR47 stores tokens) and by Profiles (FR11 private-field separation). Without an epic anchor, they risk being orphaned in implementation.
- **FR51–FR54 (accessibility):** PRD asserts these as "cross-cutting AC for F1, F2, F4, F5, F6." Each of those features should explicitly inherit the AC; without per-epic enumeration, accessibility risks falling between cracks.

**Recommendation:** Either (a) treat as a fifth epic **epic-foundations** that lands first and unblocks the others, or (b) explicitly call out per-epic that FR49–FR54 are inherited acceptance criteria for every story under that epic.

#### 🟡 Implicit — FR10, FR11, FR14–FR16, FR18–FR20 (Profile System core)

The profile system is foundational across F1, F2, F5 (and dependent for the Webhook), but FRs that belong to "the profile system itself" (CRUD, schema, snapshot, public/private separation, wizard, picker, schema versioning, mid-session switch, crash rehydration) do not anchor to a single F. Currently they live "inside" F1 (auto-actions) or F2 (filename templates) implicitly.

**Recommendation:** Promote a sub-epic / story-cluster **"Profile system foundation"** within epic-a covering FR10, FR11, FR14, FR15, FR16, FR18, FR19, FR20.

### Reverse Check — Feature/Capability in PRD but not in any FR?

**No FR-orphaned capabilities found.** Every Appendix A feature anchor and every R-EL is reflected in at least one FR. The PRD is internally consistent in this direction.

### Overall Coverage Verdict

- **Mechanical coverage** (FR is mentioned somewhere in PRD): 100%.
- **Epic coverage** (FR is anchored to a planned epic via a feature letter): **56%** (30/54).
- **Story coverage** (FR has a story with acceptance criteria): **0%** (no stories exist).
- **Critical missing-from-epic-anchor**: 9 FRs (FR1–FR4 import, FR43–FR47 webhook).
- **Cross-cutting at-risk**: 6 FRs (FR49–FR54 security + a11y).


---

## Step 4 — UX Alignment

### UX Document Status

**No stand-alone UX document.** UX content is **embedded inline in `prd-issue-104-audio-notebook-qol.md`** as:
- `## User Journeys` — 7 journeys (J1–J7), 350+ lines, narrative format with persona/opening/rising-action/climax/resolution/reveals
- `## Journey Requirements Summary` — capability-to-journey-to-feature traceability table
- `### Desktop App — Platform & Integration Deltas` — accessibility cross-cutting AC + system integration deltas (file dialogs, folder picker, keychain)
- Cross-cutting AC for J7 (accessibility) explicitly inherited by F1, F2, F4, F5, F6

This is **substantive UX content** for a PRD-only artifact. It is *not* a wireframe or design-system document, but it is enough to pin down user-facing behavior.

### UX ↔ PRD Alignment

| Capability | UX Source (Journey) | FR Anchor | Aligned? |
|---|---|---|---|
| Plain-text export with sensible defaults | J1 | F3 + FR9 + FR12 | ✅ |
| Explicit Download buttons + OS-default destination | J1 | F6 + FR5–FR8 | ✅ |
| Audio dedup on import by content hash | J1 | R-EL23 + FR2–FR4 | ✅ |
| Profile setup (field-first + optional wizard) | J2 | F1 + F2 + FR15 | ✅ |
| Live filename preview | J2, J6 | F2 + R-EL14 + FR13 | ✅ |
| Extensible filename placeholders | J2, J5 | F2 + R-EL2 + FR12 | ✅ |
| Auto-summary, auto-export, save-back | J2, J3, J5 | F1 + FR30–FR33 | ✅ |
| Profile snapshot at job-start | J2, J3 | R-EL21 + FR18 + ADR-003 | ✅ |
| Profile public/private separation | J5 | R-EL22 + FR11 + FR49 | ✅ |
| Speaker alias storage + view substitution | J2 | F4 MVP + FR21–FR22 | ✅ |
| Alias propagation to export + AI context | J2, J4, J5 | F4 Growth + FR23, FR24 | ✅ |
| Diarization confidence per-turn surface | J4 | F4 Growth + R-EL4 + FR25 | ✅ |
| Scalable diarization-review UX | J4, J7 | R-EL15 + FR26 | ✅ |
| Auto-summary HOLD on low-confidence | J4 | R-EL10 + FR25 | ✅ |
| Review state persists across restarts | J4 | R-EL19 + FR27 + NFR23 | ✅ |
| Persistent review banner | J4 | R-EL20 + FR28 | ✅ |
| Status badge + single-click retry | J3 | R-EL1 + FR35 | ✅ |
| Distinct empty-summary / truncated states | J2, J3 | R-EL16 + R-EL17 + FR36 + FR37 | ✅ |
| Retry escalation policy | J3 | R-EL18 + FR35 + NFR19 | ✅ |
| Idempotent re-export on retry | J3 | F1 design constraint + FR39 | ✅ |
| Deferred-retry on destination unavailability | J3 | R-EL12 + FR38 + NFR20 | ✅ |
| Extensibility webhook | J5 | R-EL5 + R-EL11 + FR43–FR47 | ✅ |
| Forward-only template change + opt-in re-export | J6 | (cross-cutting AC) + FR17 | ✅ |
| Recording deletion does not touch on-disk | J1, J2 | R-EL13 + FR48 | ✅ |
| Keyboard-only + screen-reader + ARIA | J7 | (cross-cutting AC) + FR51–FR54 | ✅ |

**Coverage:** All 25 capabilities revealed by the 7 journeys are anchored to FRs and/or R-ELs. **No UX-asserted capability lacks an FR.**

### UX ↔ Architecture (ADRs + Implementation Considerations) Alignment

| UX Need | ADR / Architecture Decision | Aligned? |
|---|---|---|
| Profile setup CRUD (J2, J5, J6) | ADR-001 REST CRUD `/api/profiles` | ✅ |
| Audio dedup prompt at import (J1) | ADR-002 `audio_hash` column on `transcription_jobs` | ✅ |
| Profile-snapshot semantics survive job lifecycle (J2, J3) | ADR-003 JSON blob + `snapshot_schema_version` + ADR-008 crash recovery rehydration | ✅ |
| Webhook delivery on completion (J5) | ADR-004 + ADR-006 (`webhook_deliveries` table) | ✅ |
| Per-recording aliases (J2, J4, J5) | ADR-005 per-recording scope; identity-level deferred | ✅ |
| Profile state propagation in UI (J2, J6) | ADR-007 React Query + Zustand `activeProfileId` + invalidation | ✅ |
| Crash recovery preserves running-job snapshot (J3 implicit) | ADR-008 transcription_job_tracker rehydrates | ✅ |
| OS keychain for private fields (J5 webhook URL) | "Implementation Considerations" + FR49/FR50/NFR8/NFR33/NFR34 | ✅ |
| Native OS file-save dialog (J1, J7) | "Desktop App — Platform & Integration Deltas" → OS file-save dialog | ✅ |
| Native OS folder picker (J2) | "Desktop App — Platform & Integration Deltas" → OS folder picker | ✅ |
| ARIA live regions + WCAG 2.1 AA (J7) | "Accessibility (J7) — cross-cutting" + NFR25 Lighthouse CI gate | ✅ |
| Persistent review banner state across restarts (J4) | NFR23 (state persistence) — but ⚠️ **no ADR for the persistence mechanism** (DB table? localStorage? Zustand persist middleware?) | ⚠️ Partial |

### UX ↔ NFR Alignment

| UX Need | NFR Anchor | Aligned? |
|---|---|---|
| Live filename preview latency (J2 typing experience) | NFR2 (p95 < 50ms) | ✅ |
| Auto-summary fires within 2s of completion (J2) | NFR3 | ✅ |
| Auto-export fires within 2s (J2) | NFR4 | ✅ |
| Webhook 10s timeout (J5) | NFR5 | ✅ |
| Diarization-review filter scales (J4 — 47 turns up to 60+) | NFR7 (linearity benchmark r²>0.95 at 10/100/500/1000) | ✅ |
| Status badges always visible (J3) | NFR41 | ✅ |
| Persistent banners (J4 review banner) | NFR43 | ✅ |
| Plain-text export memory ceiling for long recordings | NFR48 (streams content; supports up to 8h / ~1GB) | ✅ |
| Lurker workflow without configuration (J1) | NFR50 (visual contiguity for new affordances) | ✅ |
| Lighthouse a11y ≥ 90 (J7) | NFR25 | ✅ |

### Alignment Gaps / Warnings

#### ⚠️ 1. Missing ADR for Diarization-Review Persistence Mechanism
**Symptom:** R-EL19, NFR23, FR27 all assert "state persists across restarts" but no ADR (or schema) defines *where* the persistence lives. Three plausible implementations have very different tradeoffs:
- DB table (`recording_diarization_review_state`) — durable, queryable, survives DB-only restore
- Zustand `persist` middleware to localStorage — simpler, but local-only and bypasses server
- Column on `recording_speaker_aliases` table — coupled to alias storage, may complicate F4 MVP slice

**Impact:** Implementation will fork on this decision. Story-level AC will be unanswerable until resolved.

**Recommendation:** Add **ADR-009 — Diarization-review state persistence** with explicit schema + lifecycle (pending → in_review → completed → released).

#### ⚠️ 2. No UX Detail for FR15 Wizard Content
**Symptom:** FR15 introduces a "30-second setup wizard" but the wizard's content is not specified. J2 narrative explicitly says Maria *ignores* the wizard. No journey demonstrates the wizard.

**Impact:** Wizard step-by-step must be invented at implementation time. Without UX content, story acceptance criteria can't be written precisely.

**Recommendation:** Either (a) add a journey J2.5 for a wizard-using persona, or (b) downscope FR15 to "an empty-state CTA that pre-populates form fields with sane defaults" (no multi-step flow), or (c) explicitly defer wizard content to v1.4.1 retrospective.

#### ⚠️ 3. Keyboard Navigation Spec Inconsistency Between J4 and J7
**Symptom:**
- J4 narrative: ↑/↓ to move between turns, ←/→ to switch attribution, Enter to accept, Esc to skip
- J7 narrative: Tab/Shift+Tab to move between turns, arrow keys to switch attribution, Enter to accept, Esc to skip, Space for bulk-accept

The two navigation models conflict (Tab vs ↑/↓ for traversal; arrow keys repurposed). Both journeys assert R-EL15 keyboard nav.

**Impact:** Diarization-review UI will fail one of the two journeys at first launch. R-EL15's "scales to 60+ uncertain turns without becoming a chore" is undermined by either navigation choice without clarity.

**Recommendation:** Pick one navigation contract and document it (best practice: Tab for traversal between focusable elements, arrow keys for in-element selection — matches WAI-ARIA Authoring Practices). Update J4 narrative to match.

#### ⚠️ 4. R-EL15 "Bulk-Accept" UX Not Anchored to Acceptance Criteria
**Symptom:** R-EL15 + FR26 assert bulk-accept; J4 shows "Mark all visible as auto-accept best guess." J7 shows Space for bulk-accept. But:
- Is bulk-accept "all uncertain" or "all visible after filter"?
- Is there an undo for an accidental bulk-accept?
- Does bulk-accept commit to DB immediately or stage for "Run summary now" click?

**Impact:** Without these tied down, implementation may build a non-recoverable bulk-accept (data loss risk for Sami's 60-turn use case).

**Recommendation:** Add explicit AC under FR26: bulk-accept applies to currently-filtered visible turns; commits transactionally; supports per-recording undo until "Run summary now" is clicked.

#### ⚠️ 5. No Visual Spec for Status Badges, Banners, or Per-Turn Confidence Indicators
**Symptom:** PRD asserts status badges (R-EL1, NFR41), persistent banners (R-EL20, NFR43), and per-turn confidence display (R-EL4) but provides no visual spec — color, icon, position, severity hierarchy.

**Impact:** Frontend implementer will invent visual language; risk of inconsistency with existing dashboard `ui-contract` system. Per CLAUDE.md, the project enforces a CSS-class contract — new visual elements require a contract update.

**Recommendation:** Add a small visual-spec table (or wireframe-like ASCII) for the three new UI affordance classes; cross-reference the existing UI primitives in `dashboard/components/ui/` (StatusLight, GlassCard, ActivityNotifications, QueuePausedBanner) to confirm whether any can be reused or extended.

#### ⚠️ 6. F5 Has No Journey Coverage — UX is Asserted, Not Demonstrated
**Symptom:** PRD acknowledges F5 has only "J2 implicit" coverage. No journey shows the user toggling between Fast English/EU vs Multilingual. No UX for where the toggle lives, what it looks like, or how the persistence-across-restart (FR41) is communicated.

**Impact:** F5 risks being implemented as a hidden setting (Lurker-unfriendly, contradicts NFR50 visual contiguity).

**Recommendation:** Add a paragraph or mini-journey describing F5's UX: where the toggle lives in the dashboard chrome, what changes visually when it is switched, and how the user knows their choice persisted.

### UX Alignment Verdict

- **PRD-to-UX coverage:** Strong (25/25 journey capabilities anchored to FRs).
- **Architecture-to-UX coverage:** Mostly aligned (11/12 needs match an ADR or implementation-consideration); 1 gap on diarization-review persistence.
- **NFR-to-UX coverage:** Strong (10/10 UX needs have NFR backing).
- **Critical UX gaps:** 6 specific issues flagged for resolution before implementation (review persistence, wizard content, keyboard contract, bulk-accept AC, visual spec, F5 UX).
- **Overall:** UX content is *substantively present in the PRD* and well-aligned with architecture, but the gaps would block clean story-writing in Step 5.


---

## Step 5 — Epic Quality Review

### Source-of-Truth Caveat (continued from Step 3)

There are **no stories** to review. There are also **no epic specifications** beyond the 3-row `plannedEpicGroupings` declaration in the PRD frontmatter. This step evaluates the planned epic *structure* — the most we can validate without a real epics-and-stories file. Story-level findings are reported as **structural absence** (🔴 Critical) rather than per-story violations.

### A. Epic Structure Validation

#### Epic-A — "Post-transcription workflow" (F1, F2, F3, F6)

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ⚠️ Partial | "Post-transcription workflow" is *workflow*-centric, not *user-outcome*-centric. Better: "Configure-once, walk-away post-transcription pipeline" or "Transcripts ready for Obsidian without manual steps" |
| Epic Goal documented | ❌ Missing | Only one-line `rationale` exists ("complete the scene from import to handoff") — no formal goal statement |
| Value proposition | ✅ Present | The Configurator persona + J2 narrative make value clear |
| Independent of other epics? | ⚠️ **Partially violates** | F1 (auto-summary) requires F4 propagation per cross-feature constraint #1 — i.e., epic-a's F1 work depends on epic-b's F4 Growth-slice completion. **Forward dependency from epic-a → epic-b.** |
| Risk grade | F1=HIGH, F2=LOW-MED, F3=LOW, F6=LOW | Mixed risk profile inside one epic |
| Engineer-day budget | ~8-12d MVP slice + 10-14d Growth slice | Implied from MVP/Growth budgets and feature counts |

**Issues:**
1. 🔴 **Cross-feature constraint #1 ("F1 must wait for F4 propagation") creates an epic-a → epic-b forward dependency.** Epic independence is violated. Epic-a's Growth slice cannot ship without epic-b's Growth slice.
2. 🟠 **Epic-a is heterogeneous** — bundles MVP-tier (F2, F3, F6) and Growth-tier (F1) features into one epic. This makes "ship epic-a" ambiguous; the MVP gate is mid-epic.
3. 🟠 **F1 is HIGH-risk; F2/F3/F6 are LOW.** A single epic mixing these risk grades is hard to schedule, gate, and rollback.
4. 🟡 **Epic-a does not anchor FR1–FR4 (audio import + dedup), FR43–FR47 (webhook), or FR10/FR11/FR14–FR16/FR18–FR20 (profile-system foundation).** Per Step 3, those are orphans.

#### Epic-B — "Speaker aliasing (cross-cutting)" (F4)

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ "Speaker aliasing" is user-recognizable; "(cross-cutting)" notes the technical nature honestly |
| Epic Goal documented | ❌ Missing | One-line rationale only |
| Value proposition | ✅ Present | J2 + J4 + J5 narratives make alias value visible |
| Independent of other epics? | ⚠️ **Forward dependency consumer** | Epic-b *receives* the F1+F4 race-condition guard (cross-feature constraint #1) — i.e., epic-b's Growth slice must ship before epic-a can complete F1 propagation. Epic-b is upstream of epic-a; this is OK but means epic-a is downstream-blocked. |
| Risk grade | F4 = HIGH | Single high-risk feature; entire epic is high-risk |
| Engineer-day budget | MVP slice ~6-8d, Growth slice ~4-6d | Per Appendix A |

**Issues:**
1. 🟠 **Epic-b's MVP slice (FR21, FR22, FR29) is independently shippable; the Growth slice (FR23–FR28) blocks epic-a's F1 Growth slice.** A real epic structure would split this into two epics (epic-b-mvp and epic-b-growth) for clean dependency ordering.
2. 🟠 **Epic-b inherits the diarization-review state-machine ambiguity** (Step 4 gap #1). Stories cannot be written until ADR-009 lands.
3. 🟡 **No story-cluster for the data-model migration** is implied. F4 MVP slice creates `recording_speaker_aliases` table — that should be its own first story per BMad practice (database created when needed, not upfront).

#### Epic-C — "Pre-transcription model profiles" (F5)

| Check | Verdict | Notes |
|---|---|---|
| User-centric title | ✅ "Pre-transcription model profiles" — user-recognizable and outcome-oriented |
| Epic Goal documented | ❌ Missing | One-line rationale only |
| Value proposition | ⚠️ **Asserted, not demonstrated.** PRD acknowledges F5 has thin journey coverage (J2-implicit only). User value is conceptual, not narrative-anchored. |
| Independent of other epics? | ✅ Yes — F5 is genuinely orthogonal to F1–F4, F6 (parallel funnel position per ADR statement) |
| Risk grade | F5 = MEDIUM (config persistence + model swap orchestration; existing model_manager covers swap) |
| Engineer-day budget | "Small (independent of post-transcription work)" — unsized | ⚠️ |

**Issues:**
1. 🟡 **Epic-c is sized only as "small" — no concrete dev-day estimate.** Implementation budget tracking will be opaque.
2. 🟡 **F5 lacks a primary journey** — Step 4 already flagged this. Without UX, story-level AC for FR40/FR41/FR42 will be invented at implementation time.
3. ✅ **Epic-c is the cleanest of the three** — independent, single-feature, MEDIUM risk, no cross-cutting dependencies.

### B. Forward-Dependency Map (Critical)

```
                            +-------------------+
                            | epic-b (F4)       |
                            | MVP slice         |
                            | -- FR21,22,29     |
                            +---------+---------+
                                      |
                                      v (must ship before)
+---------------------------+   +-----+---------+
| epic-a (F1, F2, F3, F6)   |   | epic-b (F4)   |
| MVP slice                 |   | Growth slice  |
| -- F2, F3, F6 + F4 view   |   | -- FR23-28    |
+-------------+-------------+   +-----+---------+
              |                       |
              v                       v
+-----------------------------------------------+
| epic-a (F1) Growth slice -- FR30-39           |
| BLOCKED ON: epic-b Growth slice (alias prop) |
| BLOCKED ON: webhook orphan (FR43-47)          |
| BLOCKED ON: profile-system foundation         |
+-----------------------------------------------+

epic-c (F5) -- INDEPENDENT, parallel-ship
```

**Dependency violations found:**
1. 🔴 **epic-a's Growth slice depends on epic-b's Growth slice** (cross-feature constraint #1: "F1 must wait for F4 propagation"). Per BMad standards, **Epic N cannot require Epic N+1 to work** — but epic-a is alphabetically/numerically *before* epic-b, so the dependency direction is wrong.
2. 🔴 **Webhook orphan (FR43–FR47) is implied to land in epic-a's Growth slice** (since F1 surfaces failures to webhooks per R-EL5/R-EL11) but is not formally part of any epic. It is a 6-8 dev-day work item.
3. 🟠 **Profile-system foundation (FR10–FR20)** is implicit-in-epic-a but its maturity gates F2 (Maria's J2 needs profiles to save), F1 (auto-actions read profile), and the webhook (webhook URL is a profile field). Without explicit foundation epic, three downstream features race to define profile shape.

### C. Story-Level Quality Assessment

**Status:** ❌ **Cannot perform.** No stories exist to review.

What this means concretely:
- No INVEST checks possible.
- No Given/When/Then BDD AC review possible.
- No story-sizing review possible.
- No within-epic story-dependency review possible.
- No "tables created when needed" review possible.
- No starter-template-story review possible (brownfield project — N/A regardless).

The PRD's success criteria do contain *some* AC-like statements (e.g., "configure profile, run 3 sessions without re-opening settings — pass/fail"), and Appendix A defines per-feature one-liners, but these are **acceptance tests for the entire feature, not stories**. They do not decompose the work into independently shippable units.

### D. Database/Migration Story Timing

**Status:** ⚠️ **Cannot enforce "create tables when needed" without stories.** However, the PRD ("Implementation Considerations") commits to:
- `recording_speaker_aliases` (F4 MVP slice) — create the table
- `profiles` (Profile system) — public/private separation
- `webhook_deliveries` (R-EL33) — for webhook persistence
- `audio_hash` column on `transcription_jobs` (R-EL23)
- `job_profile_snapshot` column on `transcription_jobs` (ADR-003)

If stories existed, they should be ordered: profile schema first (foundation), then webhook_deliveries (depends on profile), then aliases (independent), then audio_hash + snapshot columns (additive). The PRD does not order these.

**Issue:** 🟠 **No migration ordering plan.** Alembic creates migrations in chronological order; without explicit story ordering, FK constraints between profiles ↔ webhook_deliveries (if any) may be backwards.

### E. Brownfield Integration Story Check

PRD is correctly classified `brownfield`. Required brownfield stories per BMad practice:
- Integration with existing `transcription_jobs` table (audio_hash, snapshot columns) — ✅ ADR-002, ADR-003 commit to this
- Migration with existing recordings (MVP slice non-destructive) — ✅ NFR21, NFR22 commit
- Compatibility with existing live mode — ✅ "WS /api/live: No changes" explicit
- Compatibility with existing diagnostic-paste — ✅ NFR45 acknowledges + flags risk

**No critical brownfield-integration gaps**, though no explicit "compatibility test story" exists for the live-mode boundary.

### F. Best Practices Compliance Checklist (per planned epic)

| Check | epic-a | epic-b | epic-c |
|---|---|---|---|
| Epic delivers user value | ✅ | ✅ | ⚠️ Asserted, not journey-demonstrated |
| Epic can function independently | ❌ Forward-dep on epic-b | ⚠️ Splits across MVP/Growth slices | ✅ |
| Stories appropriately sized | ❌ No stories | ❌ No stories | ❌ No stories |
| No forward dependencies | ❌ epic-a → epic-b | ⚠️ MVP→Growth split needed | ✅ |
| Database tables created when needed | ⚠️ Unstated | ⚠️ Unstated | N/A |
| Clear acceptance criteria | ⚠️ Feature-level only | ⚠️ Feature-level only | ⚠️ Feature-level only |
| Traceability to FRs maintained | ⚠️ Partial (orphans exist) | ✅ | ✅ |

### G. Severity-Graded Findings

#### 🔴 Critical Violations (5)

1. **No epics-and-stories document exists.** Planning-artifacts has a PRD only. Implementation-ready stories with AC are absent. Story-level INVEST validation is impossible. **All other Critical findings derive from this.**
2. **Forward dependency epic-a → epic-b** (F1 Growth slice waits for F4 Growth slice). Per BMad standard, this requires restructuring (split epic-b's Growth slice out, or merge epic-b Growth into epic-a's Growth, or formally re-order so F4-Growth ships first).
3. **Webhook (FR43–FR47) is unhomed.** A 6-8 dev-day Growth-tier work item with no F-letter, no epic anchor, no story container. Largest single orphan.
4. **FR1–FR4 (audio import + dedup) are unhomed.** MVP-tier; required for J1 Lurker happy path's R-EL23 dedup prompt; no epic anchor.
5. **Cross-cutting FRs (FR49–FR54: keychain + accessibility) have no epic anchor.** They risk being "everyone's problem and no one's owner." NFR25 Lighthouse gate cannot be met without explicit per-epic AC inheritance.

#### 🟠 Major Issues (8)

6. **Epic-a mixes MVP and Growth tiers** — single epic ships in two phases; phase-gate ambiguous.
7. **Epic-a mixes risk grades** (HIGH F1 + LOW F3/F6) — gating + rollback hard.
8. **Profile-system foundation (FR10/FR11/FR14–FR16/FR18–FR20) is implicit-in-epic-a** but should be a sub-epic or first-story-cluster — F2, F1, and webhook all depend on profile shape.
9. **No epic-level Goal statements** — only one-line rationales in frontmatter. Epics need formal goals to anchor stories.
10. **Migration ordering for new tables/columns is unstated** — Alembic ordering matters for FK constraints (profiles ↔ webhook_deliveries, transcription_jobs ↔ recording_speaker_aliases).
11. **Diarization-review persistence ADR is missing** (Step 4 gap #1) — story AC under epic-b Growth blocks on this.
12. **Wizard content (FR15) is undefined** (Step 4 gap #2) — story AC under epic-a profile-system foundation blocks on this.
13. **Keyboard navigation contract conflict between J4 and J7** (Step 4 gap #3) — both R-EL15-asserting journeys; one will fail at first launch.

#### 🟡 Minor Concerns (4)

14. **Bulk-accept UX semantics (R-EL15) under-specified** (Step 4 gap #4) — undo? scope? commit timing? — story AC needs sharpening.
15. **No visual spec for status badges, banners, per-turn confidence indicators** (Step 4 gap #5) — `ui-contract` system requires consistency; risk of drift.
16. **F5 has no journey + unsized budget** (Step 4 gap #6 + Step 5 epic-c issue #1) — under-specified for clean execution.
17. **No explicit live-mode-boundary compatibility test story** for brownfield integration; PRD asserts no changes but no test story confirms it.

### Recommended Restructuring (Concrete)

To fix the critical findings, we recommend the following epic structure for the implementer:

| Epic | Scope | Tier | Depends On |
|---|---|---|---|
| **epic-foundations** | Profile system core (FR10/11/14–16/18–20), keychain (FR49/50), accessibility scaffold (FR51–54), Day-1 test fixtures (NFR53), security ADR-009 | Cross | None — lands first |
| **epic-import** | Audio import + dedup (FR1–4, R-EL23, ADR-002) | MVP | epic-foundations |
| **epic-export** | F2 templates + F3 plain-text + F6 download buttons + R-EL13 deletion (FR5–9, FR12, FR13, FR17, FR48) | MVP | epic-foundations + epic-import |
| **epic-aliases-mvp** | F4 MVP slice (FR21, FR22, FR29) + `recording_speaker_aliases` migration | MVP | epic-foundations |
| **epic-aliases-growth** | F4 Growth slice (FR23–28) + diarization review UX + ADR-009 persistence | Growth | epic-aliases-mvp + epic-foundations |
| **epic-auto-actions** | F1 (FR30–39) + cross-feature-constraint #1 implementation | Growth | epic-aliases-growth + epic-foundations |
| **epic-webhook** | FR43–47 + WebhookWorker + ADR-006 deliveries table | Growth | epic-foundations |
| **epic-model-profiles** | F5 (FR40–42) | Growth | epic-foundations |

This structure: (a) eliminates the epic-a → epic-b forward dependency, (b) homes the orphan FRs, (c) makes MVP/Growth gates clean, (d) puts foundations first, (e) preserves the PRD's intent.

### Epic Quality Verdict

- **Mechanical PRD-to-feature traceability**: Strong.
- **Epic structure quality**: ❌ Fails BMad standard. Forward dependency, mixed-tier epics, unhomed FRs, 0 stories.
- **Story quality**: N/A — no stories to assess.
- **Restructuring is required** before story-writing can begin productively.


---

## Summary and Recommendations

### Overall Readiness Status

> **❌ NOT READY for Phase 4 implementation.**
>
> The PRD is exceptionally rigorous at the requirements layer, but the planning workflow stopped one step short — there is no epics-and-stories document. Coverage is 56% explicit (30/54 FRs anchored to a feature → planned epic chain). 5 Critical issues prevent clean story-writing. The PRD itself is high quality and the gaps are *recoverable in approximately 2-3 days of additional planning work*, not a re-do.

### Severity-Graded Issue Tally

| Severity | Count | Examples |
|---|---|---|
| 🔴 Critical | 5 | No epics-and-stories file; epic-a→epic-b forward dep; webhook orphan; FR1–FR4 unhomed; cross-cutting FRs unanchored |
| 🟠 Major | 8 | Mixed-tier/mixed-risk epics; missing epic Goals; no migration ordering; ADR-009 missing; wizard content undefined; J4↔J7 keyboard contract conflict |
| 🟡 Minor | 4 | Bulk-accept ambiguity; missing visual spec; F5 thin coverage; no live-mode compat test story |
| **Total** | **17** | |

### Critical Issues Requiring Immediate Action

1. **Run `bmad-create-epics-and-stories`** to produce a real `epics.md` (or sharded `epics/` folder) with story-level acceptance criteria. The PRD is ready to feed into this workflow.
2. **Restructure the planned 3 epics into ~8 epics** per the table at the end of Step 5 — eliminates the epic-a → epic-b forward dependency, homes the webhook (currently orphan), homes FR1–FR4 (currently unhomed), and isolates the cross-cutting concerns (FR49–FR54) into a foundations epic that lands first.
3. **Author ADR-009 — Diarization-review state persistence.** Choose the persistence mechanism (DB table vs Zustand persist vs column on aliases). This unblocks story AC for epic-aliases-growth.
4. **Resolve the J4 ↔ J7 keyboard navigation contract conflict.** Pick one model (recommend Tab/Shift+Tab for traversal, arrows for in-element selection — matches WAI-ARIA Authoring Practices) and update J4 narrative.
5. **Specify the FR15 wizard content** OR downscope FR15 to "empty-state CTA with sane defaults pre-populated" (no multi-step flow). Either choice unblocks profile-system stories.

### Recommended Next Steps (Ordered)

1. **Decision: epic restructure approval.** Bill reviews the 8-epic recommendation in Step 5 §G. Approve, modify, or reject. *(~30 min)*
2. **Author ADR-009** for diarization-review persistence; add to PRD's ADR table. *(~1 hour)*
3. **Resolve keyboard nav contract** + update J4 narrative + add to a small UX-spec block. *(~30 min)*
4. **Decide FR15 wizard scope** (full wizard vs empty-state CTA) + update PRD. *(~30 min)*
5. **Add a small visual-spec block** for status badges, banners, and per-turn confidence indicators; cross-reference existing `dashboard/components/ui/` primitives (StatusLight, GlassCard, ActivityNotifications, QueuePausedBanner). *(~1 hour)*
6. **Run `bmad-create-epics-and-stories`** with the restructured epic plan as input. Expect 1-2 days of work to produce a complete `epics.md` with stories and AC. *(~1-2 days)*
7. **Re-run this readiness check** (`bmad-check-implementation-readiness`) against the new epics file before greenlighting Phase 4.

### Recommended Deferrable Items (Won't Block Phase 4 Start)

- 🟡 **Migration ordering** — can be resolved inside the first migration story.
- 🟡 **Bulk-accept undo semantics** — can be handled as a story-level AC during epic-aliases-growth.
- 🟡 **F5 journey** — F5 is small and orthogonal; can ship without a journey if its story AC are tight.
- 🟡 **Live-mode compat test story** — can be added to epic-foundations as a regression-protection story.

### What the PRD Got Right (Worth Preserving)

The PRD is **substantively above average** for a hobbyist project:
- 54 FR + 55 NFR + 35 R-EL + 8 ADR + 7 journeys + 6 feature anchors + cross-reference appendix is rare rigor.
- Risk grading per feature, with mitigation strategies wired into the phased ship plan.
- Persist-Before-Deliver invariant explicitly preserved (NFR16/17/18) — the project's most critical rule per CLAUDE.md.
- Day-1 test infrastructure committed (NFR53/54) — discipline-by-linter, not by culture.
- Honest dissent documented in "Alternative Paths Considered (and Not Taken)."
- Tier discipline (`[MVP]/[Growth]/[Cross]`) on every FR.
- Concrete decision-maker named (Bill, single-decision-maker pattern).
- Clear engineer-day budgets per tier with calendar window estimate (8-11 weeks).

The restructuring described above does **not** require rewriting any of this content — it requires *adding* an epics-and-stories layer on top of it.

### Final Note

This assessment identified **17 issues** across **3 severity tiers** spanning **4 functional areas** (epic structure, requirements coverage, UX detail, architecture decisions). The PRD itself is **high quality and ready to feed into the next workflow step**; the gap is structural — Phase 3 (planning) ended at PRD-completion rather than continuing through `bmad-create-epics-and-stories`. Address the 5 Critical and the highest-impact 4 Major issues (recommended ~2-3 days of work) before Phase 4 (implementation) starts. Re-run this readiness check after restructuring.

---

**Assessment Date:** 2026-05-03
**Assessor:** Implementation Readiness skill (PM agent persona) for Bill
**PRD Reviewed:** `_bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md` (1,320 lines, version dated 2026-05-02)
**Project:** TranscriptionSuite — Audio Notebook QoL pack (Issue #104)
