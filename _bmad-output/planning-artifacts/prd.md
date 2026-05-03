---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
status: 'complete'
completionDate: '2026-05-03'
totalLines: 1317
newDependencies:
  backend:
    - 'keyring >= 25.0, < 26 (OS keychain wrapper for FR49)'
    - 'keyrings.alt (opt-in headless fallback for FR50)'
    - 'pytest-benchmark (performance regression gate for NFR1)'
  frontend:
    - '@lhci/cli@0.14 devDep (Lighthouse CI accessibility gate for NFR25)'
  configChanges:
    - 'docker-compose.yml variants: bind-mount /secrets volume for master.key'
    - 'server/backend/pyproject.toml: ruff flake8-tidy-imports.banned-api rules for tests/ (NFR54)'
    - 'dashboard/.eslintrc: no-restricted-imports in **/*.test.ts (NFR54)'
    - 'dashboard/.github/workflows/dashboard-quality.yml: extend with lighthouse job (NFR25)'
releaseMode: 'phased'
implementationBudget:
  mvpEngineerDays: '18-24 (F2 dedup 2d / F3 profile CRUD 6-8d / F4 review MVP 6-8d / F6 cancel-replay 4d)'
  growthEngineerDays: '14-20 (Webhook worker 6-8d underestimated / keychain 3-4d / F4 Growth UI + a11y J7 4-6d)'
  totalCalendarWindow: '8-11 weeks at 4 dev-days/week solo cadence'
  shipStrategy: 'MVP first behind audio_notebook_qol_v1 flag; Growth behind v1.4.1 tag'
day1Dependencies:
  - 'keyring >= 25.0, < 26 (server/backend/pyproject.toml) — wraps macOS Keychain / Windows DPAPI / Linux libsecret'
  - 'keyrings.alt >= 5.0 (opt-in for headless Docker/WSL2; gated by KEYRING_BACKEND_FALLBACK=encrypted_file env)'
day1TestFixtures:
  - 'webhook_mock_receiver (aiohttp.test_utils.TestServer wrapper, programmable status/delay/redirect) — 40+ test reuse'
  - 'private_ip_resolver (monkeypatches socket.getaddrinfo for adversarial URLs)'
  - 'fake_keyring (in-memory keyring backend via keyring.set_keyring())'
  - 'profile_snapshot_golden (JSON snapshots in tests/fixtures/profile_snapshots/)'
  - 'frozen_clock (freezegun-wrapped injectable clock; mandatory for time-of-day tests)'
innovationStepSkipped: 'No genuine innovation signals; PRD framing is "paving the cow path" (Executive Summary). One mild UX novelty (surfaced diarization confidence before AI summary) already captured in differentiator section + R-EL10/R-EL15/R-EL19/R-EL20.'
domainStepSkipped: 'low-complexity domain (general productivity); domain-class concerns captured in elicitationCarryover (R-EL13 deletion semantics, R-EL22 profile schema privacy, J7 accessibility cross-cutting AC)'
elicitationCarryover:
  - id: 'R-EL1'
    requirement: 'Auto-actions surface recoverable error states with single-click retry'
    source: 'Pre-mortem + Sally'
  - id: 'R-EL2'
    requirement: 'Filename templates support extensible placeholder grammar (not fixed list)'
    source: 'Pre-mortem'
  - id: 'R-EL3'
    requirement: 'AI summary uses aliases verbatim — no AI co-reference inference'
    source: 'Red Team + Dr. Quinn'
  - id: 'R-EL4'
    requirement: 'Diarization confidence per turn must be surfaceable BEFORE AI summary consumes labels'
    source: 'Dr. Quinn TRIZ #2'
  - id: 'R-EL5'
    requirement: 'Post-transcription extensibility hook (webhook or script trigger)'
    source: 'Pre-mortem + Dr. Quinn'
  - id: 'R-EL6'
    requirement: 'Convention defaults shipped as swappable profiles, not hardcoded paths'
    source: 'Dr. Quinn TRIZ #3'
  - id: 'R-EL7'
    requirement: 'Vision must hold for "the Lurker" (zero-config user) — defaults match today flow'
    source: 'Mary'
  - id: 'R-EL8'
    requirement: 'Speaker alias scope is recording-level; flag identity-level (cross-recording) as future scope decision'
    source: 'Pre-mortem'
  - id: 'R-EL9'
    requirement: 'Profiles allow per-recording override'
    source: 'Feynman G1'
  - id: 'R-EL10'
    requirement: 'Auto-summary waits for user confirmation when low-confidence diarization turns exist'
    source: 'Feynman G2'
  - id: 'R-EL11'
    requirement: 'Extensibility hook ships as webhook-to-URL by default; subprocess execution deferred or strictly scoped'
    source: 'Feynman G3'
  - id: 'R-EL12'
    requirement: 'Deferred-retry on transient destination unavailability (network drive, USB drive, missing folder); transcript stays safe in recording per Persist-Before-Deliver'
    source: 'Customer Support Theater Ticket #1'
  - id: 'R-EL13'
    requirement: 'Recording deletion does NOT propagate to auto-exported on-disk artifacts; deletion confirmation dialog says so explicitly'
    source: 'Customer Support Theater Ticket #3'
  - id: 'R-EL14'
    requirement: 'Live filename preview in profile setup UI updates as the user types the template'
    source: 'Focus Group / Maria'
  - id: 'R-EL15'
    requirement: 'Diarization-confidence review supports bulk-accept, confidence-threshold filter, keyboard navigation; scales to 60+ uncertain turns without becoming a chore'
    source: 'Focus Group / Sami'
  - id: 'R-EL16'
    requirement: 'F1 "succeeded with empty result" is a distinct surfaced state from "failed" (user sees empty summary indicator, not green)'
    source: 'Failure Mode Analysis'
  - id: 'R-EL17'
    requirement: 'F1 surfaces "summary truncated" status when LLM output hits token limit'
    source: 'Failure Mode Analysis'
  - id: 'R-EL18'
    requirement: 'Retry escalation policy: 1 auto-retry on transient errors; 2nd failure surfaces "manual intervention required" with link to logs (no infinite retry loop)'
    source: 'Failure Mode Analysis'
  - id: 'R-EL19'
    requirement: 'Diarization review state persists across app restarts; auto-summary remains held until review is explicitly completed'
    source: 'Failure Mode Analysis'
  - id: 'R-EL20'
    requirement: '"Review uncertain turns" banner is persistent (does not auto-dismiss until acted on)'
    source: 'Failure Mode Analysis'
  - id: 'R-EL21'
    requirement: 'Transcription jobs snapshot their profile at job-start; profile edits during job execution do not affect the running job'
    source: 'Murat (Party Mode 4) — F1 ship-broken without it'
  - id: 'R-EL22'
    requirement: 'Profile schema separates public-shareable from private-machine-local fields; private (destination paths, webhook URLs/auth, API keys) never serialized to user-readable formats; export-to-JSON (Vision) reads only public fields'
    source: 'Carson + Murat (Party Mode 4) — privacy landmine + schema-decision-now-or-refactor-later'
  - id: 'R-EL23'
    requirement: 'On import, audio content hashed (SHA-256 of normalized PCM); duplicates of existing recordings prompt user to use existing or create new; per-user-library scope, not global'
    source: 'Carson (Party Mode 4) — billing/UX dedup'
  - id: 'R-EL24'
    requirement: 'Filename-template syntax validated server-side; malformed templates rejected with parse error at profile save'
    source: 'FMA (Step 7 elicitation)'
  - id: 'R-EL25'
    requirement: 'Webhook URL scheme allowlist: https:// + explicit http://localhost* only; other schemes rejected at profile save'
    source: 'FMA (Step 7 elicitation)'
  - id: 'R-EL26'
    requirement: 'Webhook delivery: 10-second timeout, no redirect-following, no response-body decompression, HTTP status code is ground truth for success/failure'
    source: 'Expert Panel + FMA (Step 7 elicitation)'
  - id: 'R-EL27'
    requirement: 'Retry endpoint idempotent — returns {status: already_complete} when target action already succeeded'
    source: 'FMA (Step 7 elicitation)'
  - id: 'R-EL28'
    requirement: 'Webhook URL validation rejects RFC1918, 169.254/16, 127.0.0.0/8 ranges for http:// scheme; explicit http://localhost is the only loopback allowance'
    source: 'Security Audit (Step 7 elicitation)'
  - id: 'R-EL29'
    requirement: 'Private profile fields (webhook tokens, API keys) stored via OS keychain when available (macOS Keychain / Windows DPAPI / Linux libsecret); never plain-text on disk'
    source: 'Security Audit (Step 7 elicitation)'
  - id: 'R-EL30'
    requirement: 'Profile schema major-version validation — server rejects unknown major versions on PUT/POST with explicit error'
    source: 'Security Audit (Step 7 elicitation)'
  - id: 'R-EL31'
    requirement: 'Webhook payload defaults to metadata-only; transcript text in payload is opt-in per profile setting'
    source: 'Security Audit (Step 7 elicitation)'
  - id: 'R-EL32'
    requirement: 'Recording deletion dialog offers per-deletion option to also delete auto-exported on-disk artifacts (right-to-erasure honoring)'
    source: 'Security Audit (Step 7 elicitation)'
  - id: 'R-EL33'
    requirement: 'Webhook deliveries persisted to webhook_deliveries table (status, attempt_count, last_error, payload_json); same persist-before-deliver discipline as transcriptions'
    source: 'Winston (Party Mode 5) — durability'
  - id: 'R-EL34'
    requirement: 'Keychain fallback to keyrings.alt EncryptedFile backend gated by KEYRING_BACKEND_FALLBACK=encrypted_file env flag; key derived from config.yaml server-side secret via PBKDF2; security delta documented in deployment-guide.md'
    source: 'Winston + Amelia (Party Mode 5) — headless Linux/Docker realism'
  - id: 'R-EL35'
    requirement: 'Mid-flight transcription crash recovery rehydrates profile snapshot from job row before resuming'
    source: 'Winston (Party Mode 5) — Persist-Before-Deliver under restart'
inputDocuments:
  - 'docs/project-context.md'
  - 'docs/index.md'
  - 'docs/README_DEV.md'
  - 'docs/architecture-server.md'
  - 'docs/architecture-dashboard.md'
  - 'docs/integration-architecture.md'
  - 'docs/api-contracts-server.md'
  - 'docs/data-models-server.md'
  - 'GitHub Issue #104 (Small quality-of-life features for file transcription workflows)'
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 0
  projectDocs: 8
  externalIssues: 1
workflowType: 'prd'
projectType: 'brownfield'
sourceFeatureRequest: 'GH #104'
classification:
  projectType: 'desktop_app + api_backend'
  domain: 'general — Audio Notebook post-transcription workflow / personal knowledge work'
  complexity: 'medium'
  projectContext: 'brownfield'
plannedEpicGroupings:
  - id: 'epic-a'
    title: 'Post-transcription workflow'
    features: ['F1', 'F2', 'F3', 'F6']
    rationale: 'Single user story — complete the scene from import to handoff'
  - id: 'epic-b'
    title: 'Speaker aliasing (cross-cutting)'
    features: ['F4']
    rationale: 'Data-shape change touching DB, view, exports, LLM context — deserves its own rigor'
  - id: 'epic-c'
    title: 'Pre-transcription model profiles'
    features: ['F5']
    rationale: 'Different funnel position (pre- vs post-transcription) but same PRD for narrative coherence'
crossFeatureConstraints:
  - 'F1 must wait for F4 propagation before auto-generating summary (prevents stale-alias race)'
  - 'F1 must respect Persist-Before-Deliver — auto-summary persists to recording before client notification'
  - 'F4 aliases must persist before any export delivers them (durability invariant)'
  - 'F2 filename templates must sanitize for path traversal, Windows reserved names, Unicode, 255-char limits'
---

# Product Requirements Document - TranscriptionSuite

**Author:** Bill
**Date:** 2026-05-02
**Source:** GitHub Issue #104 — "Small quality-of-life features for file transcription workflows"
**Project type:** Brownfield (existing app — Audio Notebook QoL pack)
**Classification:** desktop_app + api_backend · general (post-transcription workflow) · medium complexity · brownfield

---

> **TL;DR** — Audio Notebook stops at "transcript done" but users need to walk
> across to their notes app. This PRD adds six surgical features so that walk
> takes one drag-drop instead of seven manual chores.

## Executive Summary

Today, completing a transcription in Audio Notebook means renaming files,
copying transcripts, prompting an AI for a summary, relabeling speakers, and
switching model configs by hand. The transcription itself works — the
artifacts produced still require manual translation before they're useful in
the user's downstream tool.

Each of those manual steps is **workflow leakage**: a cost users either pay
(slow workflow), externalize (wrapper scripts), or absorb (less use of the
product). Issue #104's author externalized — the wrapper script is evidence
of demand, written in code instead of words. This PRD folds that script back
into the product.

Two complementary personas anchor the work. **The Configurator** —
journalists, researchers, lawyers with established downstream-tool habits —
sets up a profile once and walks away. **The Lurker** opens the app, records,
and expects sane defaults that match today's flow without configuration. The
vision must hold for both: opt-in at configuration time, zero-touch at runtime.

The user's destination is their notes app, research vault, or interview
archive — never us. This is a positioning defense as much as a feature pack:
the moment a user replaces Audio Notebook with a 50-line shell script, the
app's claim to be a knowledge-work tool collapses into "transcription engine
plus manual ferrying."

> **Reader note:** Throughout this PRD, the six Issue #104 features are
> referenced as **F1–F6**. See **Appendix A** for canonical definitions.
> R-EL items (elicitation carryover) are defined in **Appendix C**.

---

## What Makes This Special

> Audio Notebook does not own the user's workflow — Obsidian, Logseq, Notion,
> or a plain Markdown folder does. The differentiation is delivering
> transcription artifacts that match the user's downstream conventions by
> default, with **swappable convention profiles** rather than hardcoded paths.

Five concrete differentiators:

1. **Configure-once, run-zero-touch automation**
   Auto-summary, auto-export, and auto-naming flow through the existing
   Persist-Before-Deliver discipline. User opts in at profile setup; system
   runs without intervention per session.

2. **Observable failure recovery**
   Every auto-action that fails surfaces a recoverable status artifact with
   single-click retry. No silent failures, no log-only errors.

3. **Identity-stable speaker aliases with surfaced diarization confidence**
   User-defined real names propagate verbatim to view, exports, and AI
   summary/chat context. Low-confidence turn boundaries are flagged before AI
   consumes them, preventing "verbatim alias on the wrong attribution."

4. **Extensibility hook as the product boundary**
   Post-transcription webhook or script trigger means edge-case workflows do
   not require rewriting the wrapper. Sane defaults plus a hook is what makes
   the product durable against the next custom workflow.

5. **One-click pre-transcription model profile**
   Fast English/EU vs multilingual fallback as a single toggle — a separate
   toggle, not bundled into the post-transcription profile.

The core insight is that we are **paving the cow path** — formalizing the
route users already walk. Issue #104 is N=1 evidence with high signal density:
the author hand-built the bridge as a wrapper script. Stronger than a survey
response, weaker than a cohort. The honest framing of "Why now" is
**opportunistic, low-cost, high-leverage** — not a burning platform.
Infrastructure already exists (LLM service, durability layer, recordings
table, export pipeline); cost of building is contained; cost of *not*
building is users continuing to write external scripts that bypass the app's
affordances and accumulate as drift.

> **Effort is concentrated in two of the six features — speaker aliasing
> (F4) and auto post-transcription actions (F1).** Both cross the durability
> boundary and have cross-cutting blast radius (DB, view, exports, LLM
> context, async failure modes). The remaining four are surgical and additive.

---

## Project Classification

| Field | Value |
|---|---|
| **Project Type** | `desktop_app` (Electron dashboard) + `api_backend` (FastAPI server) |
| **Domain** | General — Audio Notebook post-transcription workflow / personal knowledge work |
| **Complexity** | Medium — surgical adds on existing infrastructure, but F4 (speaker aliasing) and F1 (auto post-transcription actions) cross the durability boundary and are architecturally heavier than the rest |
| **Project Context** | Brownfield — TranscriptionSuite is a shipping product (v1.3.x); this PRD covers an additive QoL pack, not a new product |
| **Source** | GitHub Issue #104 — "Small quality-of-life features for file transcription workflows" |
| **Evidence base** | Behavioral (issue author's wrapper script) — N=1 with high signal density. Competitor scan deferred as out-of-scope for an additive QoL pack. |
| **Plausible downstream targets** | Obsidian (referenced in J1, J2), plain Markdown folders (J7); Logseq and Notion are plausible additional targets reachable via the extensibility hook (R-EL5) — no journey-anchored coverage. |

---

## Success Criteria

### User Success

- **The Configurator workflow holds.** A user who sets up a profile once and walks
  away returns to correctly-named, summarized transcripts in their target folder.
  *Verified by manual acceptance test: configure profile, run 3 sessions without
  re-opening settings — pass/fail.*
- **The Lurker workflow degrades gracefully.** A user who never opens settings
  records audio, gets a transcript, and exports it as plain text via an obvious
  button. No setup required. No "must-configure-first" blockers. *Verified by
  manual acceptance test: fresh install → record → export within 30 seconds.*
- **Failure is observable, not silent, and recoverable.** When any auto-action
  fails (LLM unreachable, disk full, alias propagation race), the user sees a
  recoverable error state with a single-click retry. *Verified by integration
  test: induce LLM timeout, disk-full, and transient destination-folder
  unavailability; assert UI artifact appears AND single-click retry succeeds
  on transient cases.*
- **Diarization confidence is visible before AI consumes labels.** Low-confidence
  turn boundaries are visually distinguishable in the speaker-aliasing view.
  *Verified by manual UX test on a recording with known low-confidence turns.*
- **Model profile switching is one-click.** Switching between fast (Parakeet/
  Canary) and multilingual (Whisper) profiles takes ≤1 click in steady-state;
  profile selection persists across app restarts. *Verified by integration test.*

### Business Success

This is a hobbyist / open-source / personal project with no revenue model.
"Business success" reads as **project health** rather than commercial metrics:

- **Issue #104 closes as resolved.** Primary acceptance: issue author confirms
  via comment that the in-app workflow replaces their wrapper script.
  Fallback: 30 days after the QoL pack ships, if the author has not filed
  follow-up concerns, the issue closes by de-facto resolution.
- **No new wrapper-script issues filed within 6 months of v1.4.x.** Treated
  as a *secondary leading indicator* (absence of evidence is not evidence of
  absence; primary signal is Issue #104 author confirmation).
- **GitHub release notes for v1.4.x can name the QoL pack as a flagship
  shipping milestone** — a coherent feature story, not a grab-bag.

### Technical Success

- **No new Persist-Before-Deliver violations introduced by the QoL pack.**
  Every new code path (F1 auto-summary write-back, F4 alias propagation,
  F1 auto-export, F5 profile-switching) preserves the durability invariant.
  *Verified by review checklist + targeted integration tests on each new
  delivery path.*
- **Speaker aliases survive every surface.** "Elena" appears identically in
  the transcript view, plain-text export, AI summary, and AI chat context —
  never a mix of "Elena" and "Speaker 1" for the same recording. *Verified
  by snapshot tests on each surface.*
- **Durability backfill is non-destructive.** Speaker aliasing migration
  (F4) creates new columns/tables without modifying existing transcription
  data. Existing recordings remain valid and unmodified. *Verified by
  migration test against fixture DB.*
- **Auto-action failure modes are exhaustively tested per risk grade:**
  - **F1 (HIGH risk):** ≥10 failure-mode tests covering LLM rate-limit, LLM
    network failure, disk-full on export, transient destination-folder
    unavailability, F1+F4 race condition (auto-summary running during alias
    propagation), and partial-failure recovery.
  - **F4 (HIGH risk):** migration test, alias-propagation test across all
    four surfaces, low-confidence turn-detection test, alias-deletion-on-
    recording-delete test.
  - **F2 (LOW-MED risk):** property-based tests for path traversal, Windows
    reserved names, Unicode, 255-char limits.
  - **F3 / F5 / F6 (LOW risk):** standard unit + integration coverage.
- **Webhook sandboxable.** Default execution model is HTTP POST to a
  user-configured URL — no `subprocess.run` of arbitrary user strings.
  Subprocess execution explicitly deferred to Vision (R-EL11).
- **Coverage stays at or above current baseline (~80% backend, all new
  frontend modules).**
- **CodeQL + dashboard-quality CI gates pass without new findings.**

### Measurable Outcomes

| Metric | Target | Verification |
|---|---|---|
| Issue #104 resolution | Primary: author-confirmed; Fallback: 30-day no-followup | GitHub issue state + comment |
| Wrapper-script regression issues | 0 within 6mo (secondary indicator only) | GitHub label query |
| Backend coverage | ≥ baseline (~80%) | pytest-cov |
| F1 failure-mode tests | ≥10 | pytest collection |
| F4 migration + propagation tests | ≥1 migration test, ≥4 propagation snapshots | pytest collection |
| F2 sanitization tests | property-based suite | pytest collection |
| Persist-Before-Deliver invariant violations | 0 (no new) | Code review + targeted suite |
| New documentation length | sized to fit configuration UX, not arbitrarily capped | manual review |
| CodeQL findings | 0 new | CI |

## Product Scope (Outline)

> **All scope tiers ship within the same v1.4.x release window.** MVP and Growth are *acceptance bundles*, not separate releases — Growth ships on top of MVP if implementation bandwidth allows, otherwise defers to v1.5. Vision items are documented to prevent scope creep, not as v1.5 commitments.

| Tier | Persona | Features | Engineer-days |
|---|---|---|---|
| **MVP** (`audio_notebook_qol_v1` flag) | Lurker | F2 / F3 / F4 MVP slice / F6 | 18-24 |
| **Growth** (`v1.4.1` tag) | Configurator | F4 Growth slice / F1 / F5 / extensibility webhook | 14-20 |
| **Vision** (out-of-scope; each requires its own PRD) | — | Identity-level aliases · Subprocess hook · Built-in presets · Multi-target export · Profile sharing · Auth-gated reveal endpoint | — |

For canonical scope detail (full feature breakdowns, dependencies, calendar schedule, risk mitigation), see **Project Scoping & Phased Development** below.

---

## User Journeys

### Journey 1 — Lurker happy path: "Just record and export"

**Persona:** Anna, language-exchange tutor. Records 60-minute student sessions
on her laptop. Wants a plain-text transcript she can drop into her notes app.
Does not want to configure anything.

**Opening scene.** Anna fires up Audio Notebook for the first time after the
v1.4 update. She doesn't read the changelog. Imports today's session WAV.
Watches the transcription complete.

*Note (R-EL23 dedup):* If Anna re-imports the same recording later
(e.g. dragging from her Downloads folder when the file is also synced to
Dropbox), the import flow detects matching audio content and prompts:
*"This recording matches an existing one. Use existing transcript, or create
a new entry?"* For first-import (J1's happy path), the prompt does not appear.

**Rising action.** The completed-recording UI now has two buttons where there
used to be just a subtitle download: **Download transcript (.txt)** and
**Download summary (.txt)** *(F6)*. Summary is greyed out (*"No summary yet —
generate from the AI panel"*). Transcript is bright. She clicks it.

**Climax.** An OS file-save dialog appears defaulting to `~/Downloads` with
a sensibly-named suggestion `2026-05-08 - language session.txt` *(F2 default
template + OS-default destination + per-click destination override)*. She
accepts the dialog. Plain text. Speaker turns separated by blank lines. No
subtitle timestamps cluttering the prose. *(F3 plain-text export)*.

**Resolution.** She drags the .txt into her Obsidian daily note. Done. Total
clicks since import: four (Download → file-save dialog → Save → Drag).

**Note (R-EL13 deletion semantics):** If Anna later deletes the recording in
the app, the on-disk transcript is **not** removed; the app shows a deletion
confirmation that says so explicitly.

**Reveals:** F2 default template + sanitization, F3 plain-text export, F6
Download buttons, OS-default destination with per-click override, R-EL13
deletion semantics, R-EL23 audio dedup prompt.

---

### Journey 2 — Configurator happy path: "Walk away and come back to ready files"

**Persona:** Maria, journalist. Records 90-minute interviews, three sources
per piece, lives in Obsidian. Has been using Audio Notebook for a month.
Saw the v1.4 release notes and decided to invest 5 minutes in setup.

**Opening scene.** Maria opens Settings → Profiles. The empty-profile screen
shows a small CTA: *"First time? Try the 30-second setup wizard →"* (hybrid
field-first + optional wizard). Maria knows what she wants; she ignores the
wizard and works the fields directly.

**Rising action.** She fills the fields:
- Filename template: `{date} {title} interview.txt` *(F2 placeholders)*
- Below the template, a **live preview** updates as she types:
  *"Preview: `2026-05-03 vasquez-rivera-sharma interview.txt`"* *(R-EL14)*
- Auto-export folder: picks `~/Documents/Interviews/raw/` via folder picker
- Toggles ON: "Auto-generate AI summary after transcription"
- Toggles ON: "Auto-export transcript and summary"

She closes Settings. Imports today's three-source interview file. Walks to
make coffee.

*Note (R-EL21 profile snapshot):* The transcription job snapshots the
profile at the moment Maria hits import. If she later (during the 40-minute
transcription) edits the profile to change the destination folder, the
running job continues using the snapshot — files still land in the original
folder. New jobs use the new profile.

**Climax.** Returns to laptop. The recording shows a green "Complete" status.
Transcript view has aliases — *"Elena Vasquez", "Marco Rivera", "Priya
Sharma"* — because she set them yesterday using F4 *(F4 view substitution +
Growth-slice export propagation)*. Downloads folder has two new files,
named exactly as the live preview promised. Summary opens — says "Vasquez
argued that..." not "Speaker 1 argued that..." *(F4 AI-context propagation)*.

**Resolution.** Drag both files into Obsidian. Manual clicks since import:
zero (config-time investment), one (drag-drop into Obsidian).

*Note (R-EL16 + R-EL17 success-state nuance):* If the LLM had returned an
empty summary or hit token-limit truncation, the recording's status would
**not be green** — it would show ⚠ "Summary empty" or ⚠ "Summary truncated."
Maria would see this immediately and choose to retry, adjust prompt, or accept.

*Note (R-EL13 deletion semantics):* Same explicit notice on recording
deletion as J1.

**Reveals:** F2 extensible placeholder grammar (R-EL2), R-EL14 live preview,
F1 auto-actions, F4 alias propagation, hybrid wizard CTA, R-EL16/R-EL17
distinct success states, R-EL21 profile snapshot at job-start,
Persist-Before-Deliver.

---

### Journey 3 — Failure recovery edge case: "AI is down, retry on click"

**Persona:** Maria again, same setup. Today's recording finishes transcribing
at 2:14 AM (server time) — exactly when her local LLM container is
restarting. Plus tomorrow morning, her external drive isn't connected.

**Opening scene.** Maria opens her recording the next morning. Two unusual
indicators are visible.

**Rising action — first failure (LLM):** Status badge: **⚠ Auto-summary
failed — LLM unavailable (2026-05-03 02:14)**. *(R-EL1)*. Transcript loaded
fine. Auto-export ran *(F1 partial success)*. Folder contains the transcript
file but not the summary file.

**Rising action — second failure (R-EL12 destination unavailable):** Below
the LLM badge: **⚠ Auto-export deferred — destination `~/Volumes/Backup/`
not mounted (will retry when available)**. The transcript is **safe in the
recording** (Persist-Before-Deliver). When the drive comes back online,
deferred-export fires automatically.

**Climax.** Maria connects her drive. Within seconds, the deferred-export
badge turns green and the transcript file appears in `~/Volumes/Backup/`.
She clicks the **⟳ Retry summary** button on the LLM badge. The LLM is now
available. Summary generates in 12 seconds. Badge turns green. Auto-export
re-fires; summary file appears in folder *(idempotent re-export)*.

*Note (R-EL18 retry escalation):* If the retry had also failed, the badge
would show *"Manual intervention required — automatic retry exhausted"*
with a link to LLM logs. The user is never stuck in a retry loop they
can't escape.

**Resolution.** Maria drags both files into Obsidian. She didn't lose the
recording. She didn't lose the transcript. She paid 12 seconds of retry
click + waiting for her drive to come back.

**Reveals:** R-EL1 status badge + retry, R-EL12 deferred-retry on
destination unavailability, R-EL18 retry escalation policy, idempotent
re-export, Persist-Before-Deliver under failure.

---

### Journey 4 — Speaker aliasing edge case: "Diarization is uncertain, AI waits"

**Persona:** Sami, oral-history researcher. Records 4-hour multi-speaker
group interviews with overlapping voices. Diarization confidence is often
mixed — sometimes 18 uncertain turns, sometimes 60.

**Opening scene.** Sami imports today's 4-hour group interview. Auto-summary
is enabled in his profile. He expects to come back to a finished summary.

**Rising action.** Transcription completes after ~40 minutes. Instead of
green "Complete", a yellow banner: **⚠ Speaker labels uncertain on 47 turn
boundaries — review before auto-summary runs.** *(R-EL10)*. The auto-summary
has not run. The banner is **persistent** — it does not auto-dismiss
*(R-EL20)*. Even if Sami closes the app and returns next week, the review
state persists *(R-EL19)*.

**Climax.** Sami clicks "Review uncertain turns." A focused view opens with:
- Filter dropdown: *"Show: bottom-5% confidence | <60% | <80% | all uncertain"*
  *(R-EL15 confidence-filter)*
- Bulk action: **"Mark all visible as auto-accept best guess"** *(R-EL15
  bulk-accept)*
- Keyboard navigation: ↑/↓ to move between turns, ←/→ to switch attribution,
  Enter to accept, Esc to skip *(R-EL15 keyboard)*

He filters to bottom-5% (3 turns), corrects them manually. Bulk-accepts the
remaining 44 as "best guess is fine." Clicks **"Run summary now."**

**Resolution.** AI summary generates with reviewed speaker attribution.
Auto-export re-fires. Folder gets the two named files. Sami knows the
summary's "Dr. Hoffman said..." attributions are accurate because *he saw
the bottom-5% boundaries first*.

**Reveals:** R-EL10 auto-summary HOLD, R-EL15 review UX scales (bulk-accept,
confidence-filter, keyboard nav), R-EL19 review persists across restarts,
R-EL20 banner persistence.

---

### Journey 5 — Issue #104 author closes the loop: "Mostly works, here's what's left"

**Persona:** Vassilis (Issue #104 author). Has a Bash wrapper script he
wrote 3 months ago to bridge the workflow gap. Sees the v1.4.x release
notes mention his issue.

**Opening scene.** Vassilis updates Audio Notebook. Reads changelog: *"GH-104:
Audio Notebook QoL pack..."*

**Rising action.** Opens Settings → Profiles. Recreates his wrapper logic in
the UI: filename template, target folder, auto-summary, auto-export. Saves
profile. Imports a test recording.

**Climax.** Watches it transcribe, summarize, export. Opens target folder:
files named close to his old wrapper's convention — but not identical. His
wrapper did `tr 'A-Z' 'a-z'` for sortability and appended a 6-char audio
hash for dedup. The built-in F2 placeholders don't include `{audio_hash}`,
and force-lowercase isn't a built-in option *(honest portrayal)*.

**Resolution.** Vassilis tests further. The 80% case works. He files a
follow-up GitHub comment on Issue #104:

> *"Working for my main flow. Two gaps from my wrapper: (1) `{audio_hash}`
> placeholder for filename dedup, (2) force-lowercase modifier on
> placeholders. Will use the webhook for both for now. Closing as
> resolved-with-followup."*

He sets up a small webhook server *(R-EL5 extensibility hook)* that handles
his two extras. The webhook URL he configures lives in the **private
fields** of his profile (R-EL22) — it would not be exported if profile
sharing eventually ships. Deletes his wrapper script. Files the
close-with-followup comment. The follow-up gaps go to the v1.5 backlog.

**Reveals:** Profile UI must support common wrapper patterns; F2 placeholders
must cover most cases; **R-EL5 webhook is genuinely needed** for the long
tail; release-notes citation closes the GH issue loop; Step 3's metric
reframing (primary = author confirmation, fallback = 30-day silence) is
correctly calibrated; R-EL22 webhook URL is private-class.

---

### Journey 6 — Configuration migration: "I changed my template, what happens to old files?"

**Persona:** Maria, six weeks after J2. She's settled into her workflow and
realized she wants to add `- transcript` and `- summary` suffixes for
clearer Obsidian sorting. Old recordings are already named the old way.

**Opening scene.** Maria opens Settings → Profiles. Edits the filename
template from `{date} {title} interview.txt` to `{date} {title} interview - transcript.txt`. Notices the live preview update *(R-EL14)*. About to save when she
sees a small notice below the template field:

> *ⓘ This template applies to **future** transcriptions. Existing
> transcripts on disk keep their current names. To re-export old
> recordings with the new template, use the Re-export action in the
> recording context menu.*

**Rising action.** Maria saves the template. Today's interview transcribes
with the new naming. Old files in `~/Documents/Interviews/raw/` keep their
old names — no surprise renames, no missing files.

**Climax.** Maria has 3 old recordings she wants renamed. She right-clicks
each → "Re-export with current profile." Files appear with new names. Old
files coexist (the re-export does not delete originals — that's a separate
manual step she controls).

**Resolution.** Maria's old recordings are now consistent with new ones.
She deletes the old-named files manually. No data loss, no surprises, and
the Re-export action is opt-in per-recording.

**Reveals:** Forward-only template-change semantics, opt-in Re-export action
in recording context menu, no implicit destructive operations on user's
disk.

---

### Journey 7 — Accessibility: "Screen-reader Lia runs the diarization review"

**Persona:** Lia, blind oral-history researcher. Uses NVDA on Windows.
Records 2-hour multi-speaker oral histories. Has been an Audio Notebook
user since v1.2 — has worked around accessibility gaps with patience.

**Opening scene.** Lia imports today's interview via keyboard (Tab to file
picker, Enter, navigate the OS file dialog with screen reader prompts). The
import succeeds. Transcription begins.

**Rising action.** When transcription completes, an **ARIA live region**
announces *"Transcription complete. 2 of 23 turn boundaries flagged
low-confidence."* The yellow review banner is announced as a polite assertion
(`aria-live="polite"` — does not interrupt her current screen-reader stream).
Tab-order is logical: review-banner → review-action button → transcript
navigation → AI panel → download buttons.

**Climax.** Lia presses Enter on the review banner. Focus moves to the
review view. **All review actions are keyboard-accessible** *(R-EL15
keyboard nav)*: Tab/Shift+Tab to move between turns, arrow keys to switch
attribution, Enter to accept, Esc to skip, Space for bulk-accept. Each turn
announces its content + current speaker label + confidence level. She fixes
2 turns, accepts the rest. Auto-summary runs.

**Resolution.** Status announced via live region: *"Auto-summary complete.
Transcript and summary exported to Documents/oral-histories. Press D to
download or Tab to AI panel."* Download buttons are keyboard-activatable
and have descriptive labels (not just "Download" — "Download transcript as
plain text"). Lia uses keyboard navigation in File Explorer to find both
files at the announced path.

**Reveals (cross-cutting AC for F1, F2, F4, F5, F6):**
- All UI surfaces in scope must be keyboard-only operable
- ARIA live regions for transcription completion, auto-action status,
  review state
- Logical tab-order across all new components
- Descriptive labels (not generic "Download" / "Click here")
- Screen-reader-friendly turn-by-turn navigation in the diarization review
- File operations announced via paths (since drag-drop isn't accessible)

This journey does not introduce features — it asserts that every feature
in J1-J6 has an accessible interaction pathway. Acceptance criteria for
F1, F2, F4, F5, F6 each gain a "keyboard-only + screen-reader" sub-AC.

---

## Journey Requirements Summary

Capabilities revealed by these 7 journeys, mapped to features:

| Capability | Journeys | Features / Carryover |
|---|---|---|
| Plain-text export with sensible defaults | 1 | F3 + F2 default template |
| Explicit Download buttons + OS-default destination | 1 | F6 |
| Audio dedup on import by content hash | 1 | R-EL23 |
| Profile setup UI (field-first with optional wizard) | 2 | F1 + F2 + Profile system |
| Live filename preview in profile setup | 2, 6 | R-EL14 |
| Extensible filename placeholders | 2, 5 | F2 + R-EL2 |
| Auto-summary, auto-export, save-back-to-recording | 2, 3, 5 | F1 + Persist-Before-Deliver |
| Profile snapshot at job-start (live edits don't affect running jobs) | 2, 3 | R-EL21 |
| Profile schema: public vs private field separation | 5 | R-EL22 |
| Speaker alias storage + view substitution | 2 | F4 MVP slice |
| Speaker alias propagation to export + AI context | 2, 4, 5 | F4 Growth slice |
| Diarization confidence per-turn surface | 4 | F4 Growth slice + R-EL4 |
| Scalable diarization-review UX | 4, 7 | R-EL15 |
| Auto-summary HOLD on low-confidence | 4 | R-EL10 |
| Review state persists across restarts | 4 | R-EL19 |
| Persistent review banner | 4 | R-EL20 |
| Status badge + single-click retry | 3 | R-EL1 |
| Distinct empty-summary / truncated states | 2, 3 | R-EL16, R-EL17 |
| Retry escalation policy | 3 | R-EL18 |
| Idempotent re-export on retry | 3 | F1 design constraint |
| Deferred-retry on destination unavailability | 3 | R-EL12 |
| Extensibility webhook for non-default workflows | 5 | R-EL5 + R-EL11 |
| Forward-only template change + opt-in Re-export | 6 | (cross-cutting AC) |
| Recording deletion does not touch on-disk artifacts | 1, 2 | R-EL13 |
| Keyboard-only operability + screen-reader + ARIA | 7 | (cross-cutting AC for F1/F2/F4/F5/F6) |

**Coverage analysis:**
- **Lurker happy path** ✅ J1
- **Configurator happy path** ✅ J2
- **Failure recovery** ✅ J3
- **Diarization edge** ✅ J4
- **Originating-user closure** ✅ J5
- **Configuration migration** ✅ J6
- **Accessibility** ✅ J7
- **Admin/Ops user** N/A — single-user desktop app
- **API/Integration consumer** ✅ Implicit in J5's webhook usage
- **Support/Troubleshooting** ✅ Covered by J3's failure-recovery flows

> *From the user-facing perspective above, the technical surface area required to deliver these journeys breaks down as follows.*

---

## Project-Type Specific Requirements

### Project-Type Overview

TranscriptionSuite is a hybrid `desktop_app` (Electron dashboard) +
`api_backend` (FastAPI server) running locally via Docker. The Issue #104
QoL pack adds new behavior to both tiers without changing the platform
support matrix, auth model, or deployment topology. This section covers
the **deltas** the QoL pack introduces.

### Architectural Decisions (ADRs)

| ADR | Decision | Rationale |
|---|---|---|
| **ADR-001 — REST CRUD for profile management** | Use REST CRUD `/api/profiles` over RPC or GraphQL | Consistency with existing `/api/recordings/*` endpoints; simple resource model |
| **ADR-002 — Audio dedup via hash on `transcription_jobs`** | Store `audio_hash` column on existing table; query-level dedup | No separate table needed for v1.4; defer separate `audio_hashes` table to Vision if usage outgrows |
| **ADR-003 — Profile snapshot as JSON blob** | Store snapshot as JSON in `job_profile_snapshot` column with `snapshot_schema_version` | Snapshots are immutable point-in-time records; flexibility outweighs structure |
| **ADR-004 — Webhook delivery via async background task** | `asyncio.create_task` rather than full queue table; failed webhooks surface as recording status (R-EL1) | Lightweight; webhooks are best-effort with R-EL18 escalation |
| **ADR-005 — Speaker alias scope per-recording for v1.4** | Per-recording aliases (R-EL8); identity-level cross-recording deferred to Vision | Cross-recording requires speaker-identity model; out of MVP/Growth scope |
| **ADR-006 — Webhook deliveries persisted in `webhook_deliveries` table** | Persist webhook attempts (status, attempt_count, last_error, payload_json) before firing | Same Persist-Before-Deliver discipline as transcriptions; survives app crashes; future migration to a real queue is just swapping the dispatcher |
| **ADR-007 — React Query invalidation as profile-state propagation** | Profiles are React Query entities; `activeProfileId` is Zustand; edits trigger `queryClient.invalidateQueries(['profiles', id])` | Avoids inventing a pub/sub system; consistent with project-context.md conventions |
| **ADR-008 — Crash recovery rehydrates profile snapshot** | Mid-flight transcription resumed by `transcription_job_tracker` re-loads JSON snapshot blob from job row before continuing | Preserves Persist-Before-Deliver under app restart; profile-snapshot semantics (R-EL21) survive crashes |

### API Design Convention

The endpoint surface uses a **REST+RPC hybrid**:
- Resource-oriented endpoints follow REST conventions (`GET/POST/PUT/DELETE /api/profiles`, `GET/PUT /api/recordings/{id}/aliases`)
- Action-oriented endpoints use RPC-style verbs in the URL (`POST /api/recordings/{id}/auto-actions/retry`, `POST /api/recordings/{id}/reexport`)

This is intentional. RPC-flavored URLs are self-documenting in code review and reduce vocabulary load for contributors.

### Versioning Policy

`schema_version` (profiles) and `payload_version` (webhooks) follow semantic versioning:
- **MAJOR.MINOR** format
- **MAJOR** bump = breaking contract change; **MINOR** bump = additive
- Deprecated versions remain supported for **2 minor releases** before removal
- Server rejects unknown MAJOR versions at validation time (R-EL30)

### Desktop App — Platform & Integration Deltas

**Platform support:** Linux KDE Wayland (primary), Windows 11, macOS — no change. All QoL features must work on all three.

**Auto-update:** Existing electron-builder mechanism. The QoL pack rides v1.4.x through the existing release pipeline. Alembic migrations run on backend startup, transparent to the user.

**System integration — NEW:**
- **OS file-save dialog** (F6, J1): Manual Download buttons trigger native dialog; respects platform conventions
- **OS folder picker** (J2 profile setup): native picker, not text input
- **OS keychain integration (R-EL29):** Private profile fields stored via macOS Keychain / Windows DPAPI / Linux libsecret. **Headless-Linux/Docker fallback (R-EL34):** `keyrings.alt` EncryptedFile backend gated by `KEYRING_BACKEND_FALLBACK=encrypted_file` env flag; key derived from `config.yaml` server-side secret via PBKDF2; security delta documented in `docs/deployment-guide.md`. **Never plain-text on disk.**
- **Accessibility (J7) — cross-cutting:**
  - Keyboard navigation across all new components
  - ARIA live regions for transcription completion, auto-action status, review state
  - Screen-reader-friendly turn-by-turn navigation in diarization review
  - Descriptive button labels (not generic "Download")
  - Logical tab-order on all new screens
  - WCAG 2.1 AA target (manual screen-reader test on Linux + Windows)

**Offline capabilities:**
- Profile CRUD, filename templates, plain-text export, Download buttons: fully offline
- Auto-summary (F1) + AI chat: depend on user's local LLM container; if unavailable, R-EL1 + R-EL18 surface "LLM unavailable" with retry path
- Webhook (R-EL5): user's webhook URL may be unreachable; R-EL12 deferred-retry semantics apply

### API Backend — Endpoint Deltas

**12 new endpoints under `api/routes/notebook.py` and lifecycle hooks in `api/routes/transcription.py`. No new authentication mechanism — existing token-based auth applies to all new endpoints.**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/profiles` | List user's profiles (public fields only) |
| `POST` | `/api/profiles` | Create profile (validates template syntax — R-EL24) |
| `GET` | `/api/profiles/{id}` | Read profile — **public fields only**; private fields are write-only |
| `PUT` | `/api/profiles/{id}` | Update profile (validates schema MAJOR version — R-EL30) |
| `DELETE` | `/api/profiles/{id}` | Delete profile (does not affect in-flight job snapshots) |
| `GET` | `/api/recordings/{id}/aliases` | Read speaker aliases (F4); empty array if none |
| `PUT` | `/api/recordings/{id}/aliases` | Update speaker aliases |
| `POST` | `/api/recordings/{id}/reexport` | Re-export with current profile (J6) |
| `GET` | `/api/recordings/{id}/diarization-confidence` | Per-turn confidence (R-EL4) |
| `POST` | `/api/recordings/{id}/diarization-review` | Submit review decisions (R-EL10) |
| `POST` | `/api/recordings/import/dedup-check` | Hash-based dedup check (R-EL23) |
| `POST` | `/api/recordings/{id}/auto-actions/retry` | Retry failed auto-action; idempotent (R-EL27) |

**Modified endpoints:**

| Endpoint | Change |
|---|---|
| `POST /api/transcribe/file` | Accepts optional `profile_id`; snapshots profile state at job-start (R-EL21) |
| `WS /api/live` | No changes — live mode does not use profiles |
| Job-completion lifecycle | Fires auto-actions (F1) AFTER persistent state is written; webhook fires after auto-actions complete |

**Authentication model:** Unchanged — token-based, first-WS-message auth for live, header-token for HTTP. New endpoints inherit existing auth middleware.

**Private-field handling:** Profile GET endpoints return only public fields. Private fields (destination paths, webhook URLs/auth, API keys) are **write-only** — set via PUT/POST but never returned by GET. Re-editing requires the user to re-enter (no reveal endpoint in v1.4).

**Data formats:**
- **Profile JSON schema** (`schema_version: "1.0"`) with explicit public/private field separation (R-EL22)
- **Speaker alias payload:** `{ recording_id, aliases: [{ speaker_id, alias_name, confidence_threshold? }] }`
- **Auto-action result:** `{ action_type, status: 'success'|'failed'|'empty'|'truncated'|'deferred', error?, retry_url? }`
- **Webhook outbound payload (default — metadata only, R-EL31):** `{ event: 'transcription.completed', recording_id, transcript_url, summary_url?, profile_id, payload_version: '1.0', timestamp_iso }`. Transcript-in-payload is opt-in per profile setting.

**Rate limits:**
- Profile CRUD: standard 100 req/min per token
- Webhook outbound: server enforces ≤1 webhook fire per recording completion
- Auto-action retries: respect R-EL18 (1 auto-retry, then manual)

**Webhook delivery security baseline (R-EL25, R-EL26, R-EL28):**
- **Scheme allowlist:** `https://` + explicit `http://localhost*` only; other schemes rejected at profile save
- **Private IP block:** `http://` URLs to RFC1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), 169.254/16, or 127.0.0.0/8 (other than explicit `localhost`) rejected — SSRF prevention
- **Timeout:** 10-second total deadline per delivery
- **No redirect-following:** server does not follow 3xx responses
- **HTTP status = ground truth:** server treats 2xx as success, 4xx/5xx as failure; body content not parsed
- **No response-body decompression:** prevents zip-bomb attacks

**SDK:** Not required — webhook contract IS the public API for third-party integration.

### Implementation Considerations

- **Database migrations:** F4 adds `recording_speaker_aliases` table (MVP slice = create table without data). Profile system adds `profiles` table with public/private field separation (R-EL22). **`webhook_deliveries` table (R-EL33)** with columns `(id, recording_id, profile_id, status, attempt_count, last_error, created_at, last_attempted_at, payload_json)` — same persist-before-deliver discipline as transcriptions. Audio hash via R-EL23 adds `audio_hash` column on `transcription_jobs`. All migrations forward-only.
- **Webhook delivery worker (extracted module):** `WebhookWorker` lives at `server/backend/server/services/webhook_worker.py`. Wired into `main.py` lifespan via only `start()` / `stop()` — keeps `main.py` diff minimal; protects existing live-mode model-swap and 868-test baseline. Worker reads pending deliveries from `webhook_deliveries` table, fires with scheme allowlist + private-IP block + 10s timeout + no redirects + R-EL18 retry escalation. Failed deliveries surface as recording status (R-EL1) AND remain in the table for inspection.
- **Profile snapshot mechanism:** R-EL21 — at job creation, frozen snapshot of active profile is serialized into the job record (ADR-003). Worker reads snapshot, never live profile state. **R-EL35:** crash recovery in `transcription_job_tracker` rehydrates the snapshot from the job row before resuming.
- **Keychain integration (R-EL29 + R-EL34):** `keyring >= 25.0, < 26` dependency added to `server/backend/pyproject.toml` (battle-tested by pip/twine/poetry; wraps macOS Keychain, Windows DPAPI, Linux SecretService/libsecret). Headless-Linux/Docker fallback uses `keyrings.alt` `EncryptedFile` backend with PBKDF2-derived key.
- **Frontend state model:** Profile state in React Query (server state, cached); `activeProfileId` in Zustand (client ephemeral) — see ADR-007. Edits trigger `queryClient.invalidateQueries(['profiles', id])` for subscribed-component refresh.
- **Telemetry / metrics:** None — TranscriptionSuite does not collect usage telemetry by design.
- **Right-to-erasure (R-EL32):** Recording deletion confirmation dialog offers per-deletion option to also delete auto-exported files on disk; default is keep (least-surprise).

### Day-1 Test Infrastructure Commitments

> See **NFR53** for the canonical Day-1 fixture commitments (`webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock`) and **NFR54** for the linter-enforced test-time discipline (banned `time.sleep` / `datetime.now` / `httpx` in test bodies). Implementation lands in `server/backend/tests/conftest.py` BEFORE any feature work begins.

### Implementation Budget (carried forward to Step 8)

- **MVP (F2 dedup + F3 profiles + F4 review MVP + F6):** 18-24 dev-days
- **Growth (F4 confidence-filter + F1 + F5 + webhooks):** 14-20 dev-days. *Webhook worker (6-8d) is the underestimated time-sink — async lifecycle + crash recovery + test matrix.*
- **Total v1.4.x window:** 8-11 calendar weeks at 4 dev-days/week solo cadence
- **Strategy:** Ship MVP first behind `audio_notebook_qol_v1` flag; Growth gated behind `v1.4.1` tag

---

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Lurker-value-proposition MVP — manual-mode QoL that requires zero configuration. Ships only what gives a brand-new user value on first launch without opening Settings.

**Resource Requirements:** Solo developer (Bill), 4 dev-days/week sustained pace. No additional contributors required for MVP. Backend and frontend can ship in parallel as long as the API contracts are agreed upfront.

### MVP Feature Set (Phase 1 — `audio_notebook_qol_v1` flag)

**Core User Journeys Supported:** J1 (Lurker happy path), J6 (Configuration migration), J7 (Accessibility — cross-cutting AC for all MVP features).

**Must-Have Capabilities:**
- **F2** — Filename templates (extensible placeholder grammar; sanitized for path traversal, Windows reserved names, Unicode, 255-char limits; server-side template syntax validation per R-EL24)
- **F3** — Plain-text export for Notebook recordings
- **F4 MVP slice** — Speaker aliasing storage + view substitution (recording-level alias storage with DB migration + alias CRUD endpoints; view-layer substitution shows aliases not "Speaker 1")
- **F6** — Explicit Download transcript / Download summary buttons in completed-recording UI; OS file-save dialog
- **R-EL13** — Recording deletion does NOT propagate to on-disk artifacts; deletion confirmation dialog says so explicitly
- **R-EL23** — Audio dedup on import via SHA-256 of normalized PCM
- **Day-1 test fixtures** — `webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock` all land in `conftest.py` before feature implementation begins
- **R-EL29 + R-EL34** — OS keychain integration with `keyrings.alt` fallback; `keyring >= 25.0, < 26` dependency added

**Engineer-day budget:** 18-24 dev-days

### Phase 2 (Growth — `v1.4.1` tag, on top of MVP)

**Core User Journeys Supported:** J2 (Configurator happy path), J3 (Failure recovery), J4 (Diarization edge case), J5 (Issue #104 author closes the loop).

**Capabilities:**
- **F4 Growth slice** — alias propagation: plain-text export, subtitle export, AI summary prompt context, AI chat context all use aliases; diarization confidence visible in view
- **F1** — Auto post-transcription actions: auto-summary (with R-EL10 hold for low-confidence), auto-export transcript and summary, save back to recording, F1+F4 race-condition guard, status badges + single-click retry (R-EL1, R-EL18), distinct empty-summary / truncated states (R-EL16, R-EL17)
- **F5** — Pre-transcription model profiles (one-click toggle for fast vs multilingual). *Note: F5 has thin journey coverage (only J2-implicit reference) — accepted as a low-narrative-density feature; user value is well-understood from Issue #104 even without an expanded journey.*
- **Extensibility hook (R-EL5 + R-EL11 + R-EL25/26/28/31)** — webhook-to-URL POST on transcription completion with full security baseline (HTTPS+localhost-only, RFC1918/169.254/127 blocked, 10s timeout, no redirects, no decompression, status-as-truth, payload defaults to metadata-only)
- **R-EL33** — `webhook_deliveries` persistence table; **WebhookWorker** service at `server/backend/server/services/webhook_worker.py`
- **R-EL21 + R-EL35** — Profile snapshot at job-start; crash recovery rehydrates snapshot
- **R-EL12** — Deferred-retry on transient destination unavailability
- **Configurator UI** — profile setup with field-first + optional wizard, live filename preview (R-EL14), folder picker
- **Diarization review UI (Growth slice)** — bulk-accept, confidence-filter, keyboard navigation (R-EL15), persistent banner + cross-restart state (R-EL19, R-EL20)

**Engineer-day budget:** 14-20 dev-days

### Phase 3 (Vision — deferred; not v1.5 commitments)

> Items below are **deferred** — pursuit requires re-prioritization vs. then-current backlog at v1.5 planning. Each will require its own PRD if pursued. Decision-maker for promotion: Bill (project owner) at v1.5 planning.

- **Identity-level speaker aliasing** — cross-recording aliases (R-EL8)
- **Subprocess-execution hook** — local shell-script triggers; deferred until threat model is clearer (R-EL11)
- **Built-in profile presets** for popular downstream tools (Obsidian, Logseq, Notion daily-note formats)
- **Multi-target export** — same recording exports to multiple destinations in one auto-action
- **Profile sharing/import** — JSON export of public fields only (private fields per R-EL22 schema separation are never serialized)
- **Auth-gated reveal endpoint** for re-editing private profile fields without re-entering them

### Calendar Schedule

- **MVP:** 18-24 dev-days × 4 dev-days/week = 4.5–6 calendar weeks
- **Growth:** 14-20 dev-days × 4 dev-days/week = 3.5–5 calendar weeks
- **Total v1.4.x window:** 8-11 calendar weeks
- **Strategy:** MVP ships first behind `audio_notebook_qol_v1` flag (release v1.4.0); Growth ships behind `v1.4.1` tag if implementation bandwidth allows; otherwise Growth defers to v1.5
- **Decision points:** Bill (project owner) decides at the v1.4.0 retrospective whether bandwidth allows Growth before v1.4.1 cuts; decides at v1.5 planning whether any Vision item is promoted into a v1.5 PRD. Single-decision-maker pattern (no committee).

### Risk Mitigation Strategy

**Technical Risks:**

| Risk | Mitigation |
|---|---|
| F4 cross-cutting blast radius (DB → view → export → AI context) | F4 split into MVP slice (storage + view) and Growth slice (export + AI propagation); ship MVP slice first to validate data model |
| F1 async failure cascade (auto-summary fails after job completes) | R-EL1 status badges + R-EL18 retry escalation + Persist-Before-Deliver invariant; F1 in Growth so MVP doesn't depend on it |
| Webhook worker = underestimated time-sink | ADR-006 persistence table; WebhookWorker extracted to dedicated service file; Day-1 webhook_mock_receiver fixture covers 40+ tests upfront |
| Keychain fragility on headless Linux/Docker | R-EL34 `keyrings.alt` fallback gated by env flag; security delta documented |
| Profile snapshot under concurrent edit (race) | R-EL21 snapshot at job-start (immutable); ADR-008 crash recovery rehydration |
| Accessibility regression (J7 cross-cutting) | Manual screen-reader test on Linux + Windows before MVP cut |

**Market Risks:**

| Risk | Mitigation |
|---|---|
| N=1 evidence base (Vassilis only) — what if other users want different things? | Extensibility hook (R-EL5) is the safety valve; explicit Vision items capture next-most-likely asks |
| Issue #104 author doesn't respond to follow-up | 30-day silence = de-facto resolution per Step 3 metric |
| New wrapper-script issues filed within 6 months | Secondary indicator only; primary signal is author confirmation |

**Resource Risks:**

| Risk | Mitigation |
|---|---|
| Solo dev cadence drops below 4 dev-days/week | Growth gates behind v1.4.1 tag — MVP ships independently if Growth slips |
| MVP scope creeps with unscheduled fixes | Day-1 test infrastructure investment prevents "6 inconsistent ad-hoc httpx mocks" failure mode |
| Webhook worker takes 10+ days instead of 6-8 | ADR-006 + extracted service file + Day-1 fixture mitigate; if blowing budget, Growth defers to v1.5 cleanly |

---

## Functional Requirements

> **Tier tags:** `[MVP]` = ships behind `audio_notebook_qol_v1` flag · `[Growth]` = ships behind `v1.4.1` tag · `[Cross]` = applies to both tiers (foundational/cross-cutting).

### Recording Import & Identity

- **FR1 [MVP]:** Users can import audio files via the existing file-picker flow with no profile required.
- **FR2 [MVP]:** On import, the system computes a content hash (SHA-256 of normalized PCM) and stores it on the recording.
- **FR3 [MVP]:** When an imported file matches an existing recording's content hash, users see a prompt to either reuse the existing transcript or create a new entry.
- **FR4 [MVP]:** Audio dedup operates per-user-library scope; hashes are not compared across installations.

### Manual Export & Download

- **FR5 [MVP]:** Users can download a completed recording's transcript as plain text via an explicit "Download transcript" button in the completed-recording UI.
- **FR6 [MVP]:** Users can download a completed recording's AI summary as plain text via an explicit "Download summary" button (disabled with explanatory tooltip when no summary exists).
- **FR7 [MVP]:** Manual download triggers the native OS file-save dialog with a sensibly-named filename (default template) and a default destination of the OS's user-Downloads folder.
- **FR8 [MVP]:** Users can override the filename and destination per-click via the file-save dialog.
- **FR9 [MVP]:** Downloaded files use plain-text format (one speaker turn per blank-line-separated block; no subtitle timestamps).

### Profile Management

- **FR10 [Cross]:** Users can create, read, update, and delete named profiles that group together filename template, destination folder, auto-action toggles, AI summary prompt, and (Growth) webhook configuration. *MVP slice covers filename template + destination + basic CRUD; Growth slice adds auto-action toggles + webhook config.*
- **FR11 [Cross]:** Profile reads return only public fields (filename template, action toggles, prompt, name/description); private fields (destination paths, webhook URLs/auth, API keys) are write-only and never returned by GET endpoints.
- **FR12 [MVP]:** Users can configure a profile's filename template using extensible placeholder grammar (`{date}`, `{title}`, `{recording_id}`, `{model}` minimum) with server-side validation rejecting malformed templates.
- **FR13 [MVP]:** Users see a live filename preview that updates as they type the template, computed against a sample recording.
- **FR14 [MVP]:** Users can choose a destination folder via the native OS folder picker (not a free-text input).
- **FR15 [Growth]:** Users encountering an empty-profile screen can opt into a 30-second setup wizard or work the fields directly (hybrid field-first).
- **FR16 [Cross]:** Profile JSON schema is versioned (`schema_version: "MAJOR.MINOR"`); the system rejects unknown major versions on save with an explicit error.
- **FR17 [Growth]:** Filename-template changes apply forward-only — existing recordings on disk keep their current names; users can opt into per-recording re-export via a recording-context-menu action.
- **FR18 [Cross]:** Each transcription job snapshots its profile state at job-start; profile edits during job execution do not affect the running job.
- **FR19 [Cross]:** Mid-flight transcription crash recovery rehydrates the profile snapshot from the job row before resuming.
- **FR20 [Growth]:** Users can switch the active profile mid-session; the change applies to subsequently-started jobs only.

### Speaker Aliasing

- **FR21 [MVP]:** Users can rename "Speaker 1", "Speaker 2", etc. to real names per-recording; aliases are stored at recording-level scope (not cross-recording identity).
- **FR22 [MVP]:** Speaker aliases substitute into the transcript view (MVP slice).
- **FR23 [Growth]:** Speaker aliases substitute into plain-text exports, subtitle exports, AI summary prompt context, and AI chat context (Growth slice).
- **FR24 [Growth]:** AI summary uses aliases verbatim — the system never infers, merges, or rewrites user-defined alias names.
- **FR25 [Growth]:** When transcription completes with low-confidence diarization turns, the system flags this with a persistent banner and HOLDS auto-summary until the user reviews.
- **FR26 [Growth]:** Users can review uncertain diarization turns via a focused view that filters by confidence threshold, supports bulk-accept, and is keyboard-navigable end-to-end.
- **FR27 [Growth]:** Diarization-review state persists across app restarts; auto-summary remains held until review is explicitly completed.
- **FR28 [Growth]:** The "review uncertain turns" banner is persistent — it does not auto-dismiss until the user acts on it.
- **FR29 [MVP]:** Users can read and update speaker aliases via REST endpoints (`GET/PUT /api/recordings/{id}/aliases`).

### Auto Post-Transcription Actions

- **FR30 [Growth]:** Users can configure a profile to automatically generate an AI summary on transcription completion.
- **FR31 [Growth]:** Users can configure a profile to automatically export transcript and summary to the destination folder on completion.
- **FR32 [Growth]:** Auto-summary is automatically saved back to the recording on success.
- **FR33 [Growth]:** Each auto-action persists durably before delivery to the client (Persist-Before-Deliver invariant).
- **FR34 [Growth]:** Auto-actions are independent — partial success is possible (e.g., transcript exports succeeded, summary failed).
- **FR35 [Growth]:** Failed auto-actions surface as a recoverable status badge with single-click retry; transient failures retry automatically once before requiring manual intervention.
- **FR36 [Growth]:** Empty AI summaries surface as a distinct "summary empty" status (not green / success).
- **FR37 [Growth]:** Token-limit-truncated AI summaries surface as a distinct "summary truncated" status with the truncated content available for review.
- **FR38 [Growth]:** Auto-export to an unavailable destination (network drive unmounted, missing folder) defers and automatically retries when the destination becomes available; the transcript remains safe in the recording during the deferral.
- **FR39 [Growth]:** Auto-action retry is idempotent — replaying a successful action returns "already complete" without re-firing side effects.

### Pre-Transcription Model Profiles

- **FR40 [Growth]:** Users can configure named model profiles that select STT model and language settings (e.g., "Fast English/EU" using Parakeet/Canary; "Multilingual" using Whisper).
- **FR41 [Growth]:** Users can switch the active model profile in one click; the choice persists across app restarts.
- **FR42 [Growth]:** Active model profile is independent of post-transcription profile (parallel funnel position).

### Extensibility Webhook

- **FR43 [Growth]:** Users can configure a webhook URL on a profile to receive an HTTP POST on transcription completion.
- **FR44 [Growth]:** The system enforces a webhook URL allowlist: `https://` only, plus explicit `http://localhost*` for local development; private IP ranges (RFC1918, 169.254/16, 127.0.0.0/8 except `localhost`) are rejected at profile save.
- **FR45 [Growth]:** Webhook delivery enforces a 10-second total deadline, does not follow HTTP redirects, does not decompress response bodies, and treats HTTP status code as ground truth (2xx success, all else failure).
- **FR46 [Growth]:** Webhook payloads default to metadata-only (`recording_id`, transcript URL, summary URL, profile_id, timestamp, payload_version); transcript text in the payload is opt-in per profile setting.
- **FR47 [Growth]:** Webhook deliveries are persisted (status, attempt_count, last_error, payload) before firing; failed deliveries surface in the recording status AND remain in the persistence table for inspection.

### Privacy, Security & Accessibility

- **FR48 [Cross]:** Recording deletion does NOT propagate to auto-exported on-disk artifacts by default; the deletion confirmation dialog explicitly states this AND offers a per-deletion option to also remove on-disk artifacts.
- **FR49 [Cross]:** Private profile fields (webhook tokens, API keys, auth headers) are stored via the OS-native secret store (macOS Keychain, Windows DPAPI, Linux libsecret); never plain-text on disk.
- **FR50 [Cross]:** When the OS keychain is unavailable (headless Linux, Docker), the system falls back to encrypted-file storage gated by an explicit `KEYRING_BACKEND_FALLBACK=encrypted_file` env flag, with the security delta documented in deployment guides.
- **FR51 [Cross]:** All UI surfaces introduced by the QoL pack are operable via keyboard alone (tab navigation, enter to activate, arrow keys for review).
- **FR52 [Cross]:** Status changes (transcription complete, auto-action result, review state) are announced via ARIA live regions with appropriate politeness levels.
- **FR53 [Cross]:** Interactive elements have descriptive labels (not generic "Download" / "Click here") accessible to screen readers.
- **FR54 [Cross]:** The diarization-review view supports turn-by-turn screen-reader navigation with each turn announcing its content + current speaker label + confidence level.

---

## Non-Functional Requirements

### Glossary

- **Telemetry:** Data leaving the trust boundary of the host. Local logs, local metrics, local diagnostics endpoints do NOT count as telemetry. Webhook deliveries cross the trust boundary but are user-configured outbound, not vendor telemetry — different category.

### Performance

- **NFR1 — Profile CRUD latency regression gate:** A `pytest-benchmark` job runs in CI with `server/backend/tests/benchmarks/baseline-v1.3.x.json` committed at v1.3.x tag; CI fails if median latency degrades >15% vs baseline.
- **NFR2 — Live filename preview latency:** Tests stub I/O and measure pure CPU path with `time.perf_counter_ns()` over 1000 iterations; assertion is `p95 < 50ms`.
- **NFR3 — Auto-summary lifecycle hook:** Auto-action lifecycle hook fires within 2 seconds of the transcription job entering `completed` state (separate from the long-running transcription itself).
- **NFR4 — Auto-export lifecycle hook:** Same 2-second deadline as NFR3, independent of auto-summary.
- **NFR5 — Webhook delivery deadline:** Webhook deliveries time out at 10 seconds (R-EL26).
- **NFR6 — Audio dedup hash:** Hash computation completes within the existing audio-preservation window without observable additional delay (no absolute time target — hardware-dependent).
- **NFR7 — Diarization-review filter responsiveness:** Linearity benchmark — `@pytest.mark.benchmark` nightly job samples (turns, latency) at [10, 100, 500, 1000] turn counts; assertion is `r² > 0.95` for linear regression. Per-PR assertion limited to 200 ms for visible turn count up to 100.

### Security

- **NFR8 — Private-field-at-rest encryption:** OS keychain primary (R-EL29); encrypted-file fallback uses AES-256-GCM with PBKDF2-derived key. **Implementation contract:** First-launch auto-generates a 32-byte random secret stored at `secrets/master.key` (file mode 0600), separate from `config.yaml`. Migration via `server/utils/config_migration.py`. AC: `test_config_migration_generates_secret_on_v13x_config` (NFR8-AC1). **Security delta** documented in `docs/deployment-guide.md`: encrypted-file mode protects against casual disk access (cloud-sync exposure, accidental file sharing) but not against a local attacker with `secrets/master.key` access.
- **NFR9 — SSRF prevention:** Webhook URL validation blocks RFC1918, 169.254/16, 127.0.0.0/8 (except explicit `localhost`); enforced at profile save AND at delivery time (R-EL28).
- **NFR10 — Webhook scheme allowlist:** `https://` and `http://localhost*` only (R-EL25).
- **NFR11 — Webhook redirect non-following:** Server does not follow 3xx (R-EL26).
- **NFR12 — Webhook decompression disabled:** Zip-bomb prevention (R-EL26).
- **NFR13 — Profile schema major-version validation:** Server rejects unknown majors with explicit 400 (R-EL30).
- **NFR14 — Filename template injection prevention:** Sanitized for path traversal, Windows reserved names, Unicode normalization, 255-char limits.
- **NFR15 — Existing token-based auth model unchanged.**

### Reliability & Durability

- **NFR16 — Persist-Before-Deliver invariant preserved:** No new violations introduced by the QoL pack.
- **NFR17 — Webhook delivery durability:** Persisted to `webhook_deliveries` table BEFORE firing; survives app crashes and restarts (R-EL33).
- **NFR18 — Profile snapshot durability:** Transcription jobs durably persist their profile snapshot at job-start; crash recovery rehydrates from the job row (R-EL21 + R-EL35).
- **NFR19 — Retry escalation bounded:** 1 auto-retry on transient errors; second failure escalates to manual intervention (R-EL18).
- **NFR20 — Deferred-retry on transient destination unavailability** (R-EL12).
- **NFR21 — Migration non-destructive:** F4 migration creates new tables/columns without modifying existing data.
- **NFR22 — Migration forward-only:** No downgrade scripts.
- **NFR23 — Diarization-review state persistence across restarts** (R-EL19).
- **NFR24a — Bootstrap consistency:** App restart with in-flight transcriptions resumes a coherent DB state and accepts requests within 30 seconds of backend startup. Profile-snapshot rehydration (R-EL35) and orphan-sweep marking are part of this critical path.
- **NFR24b — Delivery catch-up (async background):** Pending webhook deliveries from `webhook_deliveries` table are drained within 5 minutes of bootstrap; catch-up runs as an async background worker, NOT part of the bootstrap critical path. Slow webhook endpoints do not block server readiness.

### Accessibility

- **NFR25 — Lighthouse CI accessibility gate:** Lighthouse CI accessibility score ≥ 90 on all new pages, gate enforced in `dashboard-quality.yml` workflow. **New external dependency:** `@lhci/cli@0.14` devDep, `dashboard/lighthouserc.json`, extended workflow with `lighthouse` job. +90s CI wall-time, ~40MB devDep weight.
- **NFR26 — Keyboard-only operability** (FR51).
- **NFR27 — ARIA live regions for async status changes** (FR52).
- **NFR28 — Descriptive interactive labels** (FR53).
- **NFR29 — Diarization-review screen-reader navigation** (FR54).
- **NFR30 — Logical tab-order across new components.**

### Integration

- **NFR31 — Webhook contract versioned** (`payload_version`); deprecated versions supported 2 minor releases.
- **NFR32 — Profile schema versioned** (`schema_version`); forward-compatible.
- **NFR33 — Single `keyring >= 25.0, < 26` dependency** wraps macOS Keychain / Windows DPAPI / Linux libsecret (FR49).
- **NFR34 — Headless-Linux fallback documented:** `keyrings.alt` EncryptedFile gated by `KEYRING_BACKEND_FALLBACK=encrypted_file` (FR50).

### Privacy & Data Handling

- **NFR35 — No outbound telemetry by design** (per Glossary at top of NFR section: telemetry = data leaving the host's trust boundary). Local diagnostics are not telemetry.
- **NFR36 — Recording deletion does not propagate to disk** (R-EL13 + R-EL32).
- **NFR37 — Webhook payload metadata-default; transcript-text inclusion opt-in per profile** (R-EL31).
- **NFR38 — Right-to-erasure surface in deletion dialog** (R-EL32).
- **NFR39 — i18n explicit deferral:** UI strings English-only; Unicode in user content preserved end-to-end. Multi-language UI is Vision-deferred.
- **NFR40 — `webhook_deliveries` retention:** Persisted rows retained for `webhook_retention_days` (default 30); periodic cleanup follows existing `audio_cleanup.periodic_cleanup()` pattern.

### Observability

- **NFR41 — Status badges as primary user observability surface** (FR35).
- **NFR42 — Webhook delivery inspection table queryable for debugging** (NFR17).
- **NFR43 — Persistent banners for action-required states** (FR28).
- **NFR44 — Structured logging for security-sensitive operations** via structlog at INFO level with structured context (operation, recording_id/profile_id, timestamp); no PII in logs.
- **NFR45 — User log-export via existing diagnostic-paste mechanism** (project's existing diagnostic-paste UX, see `tech-spec-gpu-error-surfacing-diag-paste-fix`); QoL pack additions logged to existing log streams.

### Concurrency & Resource

- **NFR46 — Profile concurrent-edit semantics (NEW pattern divergence):** Last-write-wins with `updated_at` timestamp; concurrent edits surface as toast notification on stale-cache discovery. **Documented as a deliberate divergence** from existing config-edit patterns (config.yaml has single editor; profile API has multiple concurrent web clients). Optimistic-locking with `If-Match: <etag>` deferred to Vision if conflicts become real.
- **NFR47 — Webhook worker memory budget:** Worker run for 60s under synthetic webhook load with `psutil.Process().memory_info().rss` sampled at 1 Hz; assertion is `p95 ≤ 50 MB` AND slope ≈ 0 (no leak). Test budget: ~75s.
- **NFR48 — Plain-text export streams content** rather than buffering entire transcript in memory; supports recordings up to 8 hours / ~1 GB transcript without exhausting RAM.
- **NFR49 — Multi-user / team scaling is out of scope:** Documented as Vision item; current architecture does not support multi-user.

### Discoverability

- **NFR50 — Visual contiguity for new affordances:** Download buttons, status badges, banners are visually contiguous with existing affordances; no hidden settings required for MVP-tier features (Lurker workflow holds without configuration).

### Test Coverage & Enforcement

- **NFR51 — Coverage no regression vs v1.3.x baseline:** Backend coverage measured at v1.3.x tag becomes the floor; QoL pack lands at the same or better coverage ratio.
- **NFR52 — Per-feature test minimums tied to risk grade:** F1 ≥10 failure-mode tests; F4 ≥1 migration test + ≥4 propagation snapshots; F2 property-based suite for sanitization edge cases.
- **NFR53 — Day-1 test fixtures land before feature implementation:** `webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock` in `server/backend/tests/conftest.py`.
- **NFR54 — Test-time discipline ENFORCED via linters (not culture):**
  - **Backend:** ruff `[tool.ruff.lint.flake8-tidy-imports.banned-api]` in `server/backend/pyproject.toml` bans `time.sleep`, `datetime.datetime.now`, `httpx.Client`, `httpx.AsyncClient` inside `tests/`.
  - **Frontend:** ESLint `no-restricted-imports` in `dashboard/.eslintrc` scoped to `**/*.test.ts`.
  - **CI gate:** existing `dashboard-quality.yml` lint step.
  - **Approved alternatives:** `asyncio.Event.wait()` with explicit timeouts, `freezegun`-wrapped `frozen_clock` fixture, `webhook_mock_receiver` fixture's response programming.
- **NFR55 — CodeQL + dashboard-quality CI gates pass without new findings.**

### PRD Assumptions

> Documented dependencies and decisions that downstream implementation work must honor:

1. **`secrets/master.key` location chosen over `config.yaml` embedding** for keychain-fallback secret (NFR8) — cleaner separation, fewer permission-fragility issues across Linux/Windows/macOS Docker bind-mounts. Volume mapping change required in `docker-compose.yml` variants.
2. **Lighthouse CI is a NEW external dependency** for accessibility enforcement (NFR25) — `@lhci/cli@0.14` + `lighthouserc.json` + extended `dashboard-quality.yml`.
3. **`pytest-benchmark` is a NEW dev dependency** for performance regression gate (NFR1) — baseline JSON committed at v1.3.x tag; >15% degradation fails CI.
4. **`flake8-tidy-imports` linter rules** added to `server/backend/pyproject.toml` to enforce NFR54 backend-side; ESLint `no-restricted-imports` for frontend.
5. **NFR45 user log-export depends on existing `diagnostic-paste` mechanism** (pre-existing per `tech-spec-gpu-error-surfacing-diag-paste-fix`). If that mechanism is materially changed during v1.4, this NFR must be re-validated.

### Alternative Paths Considered (and Not Taken)

> Documented as dissent so future-Bill knows these paths were *seen* and *rejected*, not missed.

**Path A — "Ship-and-Validate" (Victor, Step 11 review):** Cut to MVP-only (F1, F4, F6). Ship in 2 weeks. Use the 7 unspent weeks to write one blog post ("Why I built a local-first transcription notebook") and post to Hacker News. Treat HN signal (or absence of it) as the falsification criterion this PRD lacks. If nobody bites, you have answered "did this matter?" with 50 engineer-days unspent.

**Path B — "Blue Ocean reframe" (Victor, Step 11 review):** Stop building bridges to Obsidian/Logseq/Notion and become the destination. Reframe TranscriptionSuite as "the only privacy-first local-sovereign transcription notebook with three SOTA backends." Optimize for being the place users *stay*, not the bridge they *cross*. F1-F6 stay scoped, but the strategic narrative shifts from "QoL bridge polish" to "category-creation."

**Why these were not taken:**

1. **The PRD's premise is "paving the cow path,"** not category creation. Bill explicitly chose this framing in Step 2c with full knowledge of N=1 evidence. Switching to category-creation mid-PRD would invalidate every elicitation pass that built on that framing.
2. **The artifact is the deliverable for this user.** Bill chose `/bmad-create-prd` deliberately over a one-page tech spec. The planning rigor is itself the goal of this exercise — `valid-process` over `minimum-viable-process`. Future PRDs in this codebase inherit the patterns established here.
3. **The success metrics (Step 3) are intentionally weak** because revenue/MAU/adoption metrics don't apply to a hobbyist project. Adding HN-validation as a falsification criterion would commit Bill to *publication*, which is out of scope for this PRD.

**However, the PRD does NOT preclude either path post-ship.** After v1.4.0 ships, Bill can choose to write the blog post (Path A's HN-validation step) or pivot strategy (Path B's reframe). Both remain available; this PRD just doesn't commit to them.

---

## Appendix A — Feature Definitions

> Single source of truth for each Issue #104 feature. Each block consolidates the feature's anchor: tier, persona, journey references, FR range, R-EL anchors, risk grade. For canonical detail follow the cross-references.

### F1 — Auto Post-Transcription Actions

| Field | Value |
|---|---|
| **Tier** | Growth (`v1.4.1` tag) |
| **Persona** | Configurator |
| **Journeys** | J2 (happy path), J3 (failure recovery), J5 (Vassilis's wrapper replacement) |
| **FRs** | FR30–FR39 |
| **R-EL anchors** | R-EL1, R-EL10, R-EL12, R-EL16, R-EL17, R-EL18, R-EL21, R-EL35 |
| **Risk grade** | HIGH (Murat: async failure cascade, Persist-Before-Deliver crossing, F1+F4 race) |
| **Engineer-day budget** | Component of Growth's 14-20 dev-day total |
| **One-line:** | Configure-once, run-zero-touch automation: auto-summary, auto-export, save-back, observable failure recovery. |

### F2 — User-Defined Filename Templates

| Field | Value |
|---|---|
| **Tier** | MVP (`audio_notebook_qol_v1` flag) |
| **Persona** | Lurker (default template) + Configurator (custom template) |
| **Journeys** | J1 (Lurker default), J2 (Configurator custom), J5 (Vassilis re-creates wrapper logic), J6 (template migration) |
| **FRs** | FR12, FR13, FR17 |
| **R-EL anchors** | R-EL2 (extensible grammar), R-EL14 (live preview), R-EL24 (server-side validation) |
| **Risk grade** | LOW-MED (Murat: filename-injection sanitization required) |
| **Engineer-day budget** | ~6-8 dev-days (combined with profile CRUD) |
| **One-line:** | Filenames the user actually wants — placeholder grammar, live preview, sanitized output. |

### F3 — Plain-Text Export

| Field | Value |
|---|---|
| **Tier** | MVP |
| **Persona** | Lurker + Configurator |
| **Journeys** | J1, J2 (auto-export), J5 |
| **FRs** | FR9, FR48 (deletion semantics) |
| **R-EL anchors** | (none specifically — base feature) |
| **Risk grade** | LOW |
| **Engineer-day budget** | Small (component of MVP work) |
| **One-line:** | Clean `.txt` exports — one speaker turn per blank-line block, no subtitle clutter. |

### F4 — Speaker Aliasing (split MVP slice + Growth slice)

| Field | Value |
|---|---|
| **Tier** | **MVP slice:** storage + view substitution. **Growth slice:** export + AI propagation + diarization confidence. |
| **Persona** | Configurator (J2, J5) + Sami the researcher (J4 diarization edge) |
| **Journeys** | J2, J4, J5, J7 (accessibility of review UI) |
| **FRs** | MVP slice: FR21, FR22, FR29. Growth slice: FR23–FR28. |
| **R-EL anchors** | R-EL3 (verbatim alias), R-EL4 (surfaced confidence), R-EL8 (recording-level scope), R-EL10 (auto-summary HOLD), R-EL15 (scalable review UX), R-EL19 (state persistence), R-EL20 (persistent banner) |
| **Risk grade** | HIGH (Murat: data-shape change touches DB → view → export → LLM context; F1+F4 race) |
| **Engineer-day budget** | MVP slice ~6-8d; Growth slice ~4-6d |
| **One-line:** | Real names instead of "Speaker 1" — verbatim across view/export/AI; with diarization-confidence review for low-confidence turns. |

### F5 — Pre-Transcription Model Profiles

| Field | Value |
|---|---|
| **Tier** | Growth |
| **Persona** | Configurator (parallel pre-transcription funnel position) |
| **Journeys** | J2 (implicit; thin coverage acknowledged) |
| **FRs** | FR40, FR41, FR42 |
| **R-EL anchors** | (none specifically — base feature) |
| **Risk grade** | MEDIUM (Murat: config persistence + model swap orchestration; existing model_manager covers swap) |
| **Engineer-day budget** | Small (independent of post-transcription work) |
| **One-line:** | One-click toggle for Fast English/EU vs Multilingual — no config edits. |

### F6 — Explicit Download Buttons

| Field | Value |
|---|---|
| **Tier** | MVP |
| **Persona** | Lurker (primary) |
| **Journeys** | J1, J7 (accessibility) |
| **FRs** | FR5, FR6, FR7, FR8 |
| **R-EL anchors** | (none specifically — base feature) |
| **Risk grade** | LOW |
| **Engineer-day budget** | ~4 dev-days (combined with status badges + retry) |
| **One-line:** | Explicit "Download transcript" / "Download summary" buttons in completed-recording UI. |

---

## Appendix B — Where to Find What (Index / Cross-Reference Table)

> One-page navigability map. Each row points to the canonical sections for a topic.
>
> ⚠ **Maintenance note:** This table must be regenerated when any FR / NFR / R-EL is renumbered, split, or removed. Stale references cascade silently.

| Topic | Executive Summary | Journeys | FR range | NFR range | R-EL range | ADRs |
|---|---|---|---|---|---|---|
| Recording Import & Identity | mentioned | J1 | FR1–FR4 | NFR6 | R-EL23 | ADR-002 |
| Manual Export & Download | mentioned | J1, J7 | FR5–FR9 | NFR48 | — | — |
| Profile Management | mentioned | J2, J5, J6 | FR10–FR20 | NFR1, NFR8, NFR13, NFR14, NFR18, NFR46 | R-EL14, R-EL21, R-EL22, R-EL30, R-EL35 | ADR-001, ADR-003, ADR-007, ADR-008 |
| Speaker Aliasing | differentiator #3 | J2, J4, J5, J7 | FR21–FR29 | NFR21, NFR23 | R-EL3, R-EL4, R-EL8, R-EL10, R-EL15, R-EL19, R-EL20 | ADR-005 |
| Auto Post-Transcription Actions | differentiator #1 | J2, J3, J5 | FR30–FR39 | NFR3, NFR4, NFR16, NFR17, NFR19, NFR20, NFR24a, NFR24b | R-EL1, R-EL12, R-EL16, R-EL17, R-EL18 | ADR-004, ADR-006 |
| Pre-Transcription Model Profiles | differentiator #5 | J2 (implicit) | FR40–FR42 | — | — | — |
| Extensibility Webhook | differentiator #4 | J5 | FR43–FR47 | NFR5, NFR9–NFR12, NFR17, NFR40, NFR42, NFR47 | R-EL5, R-EL11, R-EL25, R-EL26, R-EL28, R-EL31, R-EL33 | ADR-006 |
| Privacy & Right-to-Erasure | mentioned | J1 + J2 notes | FR48 | NFR15, NFR35–NFR38 | R-EL13, R-EL31, R-EL32 | — |
| Security (private fields, encryption) | — | J5 (R-EL22 webhook) | FR49, FR50 | NFR8, NFR33, NFR34, NFR44 | R-EL22, R-EL29, R-EL34 | — |
| Accessibility | — | J7 | FR51–FR54 | NFR25–NFR30 | (J7 cross-cutting) | — |
| Test Coverage | — | — | — | NFR51–NFR55 | — | — |

---

## Appendix C — R-EL Glossary (Carryover Index)

> Elicitation carryover requirements harvested across Steps 2b → 7. Frontmatter has machine-readable form; this appendix has human-readable one-liners.

| ID | Source | Requirement (one-line) |
|---|---|---|
| R-EL1 | Pre-mortem + Sally | Auto-actions surface recoverable error states with single-click retry |
| R-EL2 | Pre-mortem | Filename templates support extensible placeholder grammar |
| R-EL3 | Red Team + Dr. Quinn | AI summary uses aliases verbatim — no AI co-reference inference |
| R-EL4 | Dr. Quinn TRIZ | Diarization confidence per turn must be surfaceable BEFORE AI summary consumes labels |
| R-EL5 | Pre-mortem + Dr. Quinn | Post-transcription extensibility hook (webhook or script trigger) |
| R-EL6 | Dr. Quinn TRIZ | Convention defaults shipped as swappable profiles, not hardcoded paths |
| R-EL7 | Mary | Vision must hold for "the Lurker" (zero-config user) |
| R-EL8 | Pre-mortem | Speaker alias scope is recording-level; cross-recording identity deferred |
| R-EL9 | Feynman G1 | Profiles allow per-recording override |
| R-EL10 | Feynman G2 | Auto-summary waits for user confirmation when low-confidence diarization turns exist |
| R-EL11 | Feynman G3 | Extensibility hook ships as webhook-to-URL by default; subprocess deferred |
| R-EL12 | CST Ticket #1 | Deferred-retry on transient destination unavailability (network drive, USB drive) |
| R-EL13 | CST Ticket #3 | Recording deletion does NOT propagate to auto-exported on-disk artifacts |
| R-EL14 | Focus Group / Maria | Live filename preview in profile setup UI |
| R-EL15 | Focus Group / Sami | Diarization-confidence review supports bulk-accept, confidence-filter, keyboard nav |
| R-EL16 | FMA | F1 "succeeded with empty result" is a distinct surfaced state |
| R-EL17 | FMA | F1 surfaces "summary truncated" status when LLM hits token limit |
| R-EL18 | FMA | Retry escalation: 1 auto-retry; 2nd failure surfaces "manual intervention required" |
| R-EL19 | FMA | Diarization review state persists across app restarts |
| R-EL20 | FMA | "Review uncertain turns" banner is persistent (no auto-dismiss) |
| R-EL21 | Murat (PM4) | Transcription jobs snapshot their profile at job-start |
| R-EL22 | Carson + Murat (PM4) | Profile schema separates public-shareable from private-machine-local fields |
| R-EL23 | Carson (PM4) | On import, audio content hashed for dedup |
| R-EL24 | FMA (Step 7) | Filename-template syntax validated server-side |
| R-EL25 | FMA (Step 7) | Webhook URL scheme allowlist (https + localhost only) |
| R-EL26 | Expert Panel + FMA (Step 7) | Webhook delivery: 10s timeout, no redirects, no decompression, status as truth |
| R-EL27 | FMA (Step 7) | Retry endpoint idempotent — returns `already_complete` |
| R-EL28 | Security (Step 7) | Webhook URL validation rejects RFC1918, 169.254/16, 127.0.0.0/8 except `localhost` |
| R-EL29 | Security (Step 7) | Private profile fields stored via OS keychain (Keychain/DPAPI/libsecret) |
| R-EL30 | Security (Step 7) | Server rejects unknown profile schema major versions on save |
| R-EL31 | Security (Step 7) | Webhook payload metadata-only by default; transcript-text opt-in |
| R-EL32 | Security (Step 7) | Recording deletion offers per-deletion option to also delete on-disk artifacts |
| R-EL33 | Winston (PM5) | Webhook deliveries persisted to `webhook_deliveries` table |
| R-EL34 | Winston + Amelia (PM5) | Keychain fallback to `keyrings.alt` EncryptedFile gated by env flag |
| R-EL35 | Winston (PM5) | Mid-flight crash recovery rehydrates profile snapshot from job row |
