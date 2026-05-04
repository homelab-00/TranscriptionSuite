---
issue: 104
date: 2026-05-04
project: TranscriptionSuite
scope: Full epic — 56 stories across 5 sprints, 8 sub-epics
status: epic complete; gh-104-prd ready to merge to main
artifacts:
  - _bmad-output/planning-artifacts/prd-issue-104-audio-notebook-qol.md
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/sprint-1-design.md
  - _bmad-output/implementation-artifacts/sprint-2-design.md
  - _bmad-output/implementation-artifacts/sprint-3-design.md
  - _bmad-output/implementation-artifacts/sprint-4-design.md
  - _bmad-output/implementation-artifacts/sprint-5-design.md
---

# Issue #104 Retrospective — 5 Sprints, 56 Stories, 8 Sub-Epics

This retrospective closes Issue #104 (the user-profile / auto-actions /
webhook system) before `gh-104-prd` merges to `main`. The epic shipped as
five sequential sprints landing eight sub-epics:

| Sprint | Sub-epic | Stories | Headline |
|---|---|---|---|
| 1 | foundations | 1.1–1.10 + 8.1–8.3 | Profile schema, keychain bootstrap, model profiles, banned-api ruff gate |
| 2 | filename-template + plaintext-export | 2.1–2.6 + 3.1–3.7 | `render_and_sanitize`, plaintext export, deletion artifact cascade |
| 3 | aliases-growth + diarization-confidence | 4.1–4.7 + 5.1–5.9 | Speaker aliases, confidence buckets, ADR-009 state machine, review UI |
| 4 | auto-actions | 6.1–6.11 | Auto-summary + auto-export coordinator, deferred-export sweeper, race guard |
| 5 | webhook | 7.1–7.7 | `webhook_deliveries` table, `WebhookWorker`, SSRF baseline, payload v1 |

All 56 stories landed; the only post-merge gate is the SSRF and credential
fixes from Sprint 5's code review (now in this branch).

---

## 1. Architectural through-lines that worked across all five sprints

### 1.1 The Persist-Before-Deliver invariant became the load-bearing wall

PBD started in Sprint 1 (`profile_repository.create_profile` commits before
returning) and grew into the through-line of every sprint:

- **Sprint 2**: `render_and_sanitize` is read-only — but the deletion path
  in Story 3.7 commits the DB delete BEFORE attempting the file unlink, so
  an orphan file is harmless and an orphan DB row never happens.
- **Sprint 3**: ADR-009's state machine commits each transition before
  emitting the lifecycle hook.
- **Sprint 4**: `auto_action_repository.set_*_status` commits inside
  `with get_connection()`; the coordinator's "Persist-Before-Deliver
  matrix" test (Story 6.4) parametrizes `auto_summary` / `auto_export` /
  `manual_summary` / `webhook_delivery` over a single ordering assertion.
- **Sprint 5**: `webhook_deliveries.status='pending'` is committed BEFORE
  the worker dequeues; `'in_flight'` is committed BEFORE the HTTP fire;
  `'success'`/`'failed'` are committed AFTER the response. Bootstrap
  recovery sweeps both `pending` and `in_flight` so no attempt is lost
  across crashes.

The single crispest expression of this discipline lives in Sprint 4's
`_persist_summary_with_durability_guard`: if the DB commit raises, write
the LLM result to `data/lost-and-found/<rec>-<ts>.summary.txt` and
re-raise — making CLAUDE.md's "AVOID DATA LOSS AT ALL COSTS" mechanically
testable.

**Lesson**: when an invariant is the project's first commandment, repeat
it across artifacts (specs reference NFR16 by number; tests use a shared
matrix; dev notes flag "PBD" inline). Five sprints of consistency made
this invariant cheap to verify on review.

### 1.2 The ADR-009 diarization-review state machine paid for itself twice

Sprint 3 committed `diarization_review_lifecycle.py` with a strict state
machine and three trigger functions. At the time it looked like
over-engineering — only one production caller existed (the lifecycle
hook). Then Sprint 4 used `auto_summary_is_held` as the predicate for the
auto-summary HOLD logic without changing the state machine at all. The
machine was already designed for a second consumer it didn't have yet.

**Lesson**: when a state machine is the right abstraction, the
asymmetry between "build it once" and "retrofit it later" is huge. The
cost of the strict machine in Sprint 3 was ~150 LOC; retrofitting one
into Sprint 4's coordinator without it would have been a multi-day mess.

### 1.3 The banned-api ruff gate (Sprint 1 Story 1.1) was the unsung hero

Sprint 1 added a `flake8-tidy-imports.banned-api` rule blocking
`time.sleep`, `datetime.datetime.now`, `httpx.Client`, and
`httpx.AsyncClient` in tests. Production code in `api/`, `core/`,
`database/` is exempted via per-file-ignores.

This rule prevented every following sprint from accidentally touching the
real network or wall clock in tests:

- Sprint 4 had to use `frozen_clock` for the auto-retry timing tests.
- Sprint 5 had to route through `webhook_mock_receiver` instead of
  reaching for `httpx.AsyncClient` directly. That's how we found out
  immediately when we wrote a test that imported httpx inside a test file
  — ruff failed the build before we could even run pytest.

**Lesson**: a single 7-line `[tool.ruff.lint.flake8-tidy-imports.banned-api]`
block at the start of an epic forces every downstream test author into the
fixture path. It's the cheapest way to enforce "tests don't hit reality."

### 1.4 The forward-only migration policy (NFR22) simplified planning

Every migration's `downgrade()` raises `RuntimeError("forward-only —
restore from backup")`. This eliminated the entire class of "but what if
we need to roll back?" anxiety from each sprint's design pass and pushed
recovery to backup tooling where it belongs (single-tenant homelab
deployments are not running rolling migrations against running prod).

Migrations 008 → 016 across the epic were all additive: new tables (008,
010, 014, 016), new columns (009, 011, 012, 013, 015). Zero `DROP` /
`ALTER ... DROP COLUMN` SQL in the entire epic.

**Lesson**: when you can declare forward-only as a project-wide policy,
the per-migration cognitive cost halves. It also forces the schema
discussion to happen at design time ("what columns will future sprints
need on this row?") rather than as a retroactive rebuild.

### 1.5 Fixture-driven testing let the SSRF threat model be exercised exhaustively

Sprint 1's `private_ip_resolver` and `webhook_mock_receiver` fixtures
sat unused for most of the epic — they were *for* Sprint 5. When Sprint
5 arrived, the test author wrote 27 SSRF tests using exactly the
hostnames they cared about (`internal.example.com → 10.0.0.5`) without
touching real DNS. The tests are deterministic and run in milliseconds.

The cost of building the fixtures in Sprint 1 was ~80 LOC; the value at
Sprint 5 was the only reason the SSRF threat model could be tested at all.

**Lesson**: forward-declaring fixtures even before their consumers exist
is cheap and de-risks the eventual story. The Sprint 1 design doc
explicitly named "this fixture is for the SSRF tests in epic-webhook
Story 7.2" — that note made the fixture's API design straightforward
because we knew who would call it.

---

## 2. What the design docs got right vs. what needed AC overrides

### 2.1 What the specs got right

- **Story 6.4's PBD matrix** named four artifact paths in advance (auto_summary,
  auto_export, manual_summary, webhook_delivery). Sprint 5's webhook fit
  into the matrix without rewriting the test — a forward-pointing
  scaffold paid off cleanly.
- **R-EL18's "one auto-retry then manual"** language was crisp enough
  that Sprint 4's escalation logic and Sprint 5's webhook escalation
  used identical shapes (`_handle_auto_action_failure` / `_handle_failure`).
  Two implementations of the same rule across two epics, no drift.
- **The NFR-numbered cross-references** (NFR16, NFR17, NFR9, NFR40, etc.)
  let every story spec reference the same invariants by number. When
  Sprint 5's design said "Persist-Before-Deliver (NFR16)" it meant
  exactly what Sprint 4's commit had implemented.
- **ADR-009 (state machine)** specified illegal transitions raise
  `IllegalReviewTransitionError`. That made Sprint 4's
  `_on_auto_summary_fired_safe` write itself — the wrapper exists *because*
  the underlying function is strict.

### 2.2 ACs that needed inline overrides during design

Every sprint had a "Section 1: Inline AC overrides" block in its design
doc. Reviewing those 5 lists yields three recurring shapes:

1. **URL-prefix collisions**: Sprints 3, 4, and 5 all overrode AC URLs
   from `/api/recordings/...` to `/api/notebook/recordings/...` because
   the project has no top-level recordings router. Should have been
   caught at PRD time but wasn't — the PRD was written by someone
   without the codebase open.

2. **"Frozen-clock" assumptions in timing ACs**: Several ACs said
   "fires within 2s of completion measured by `frozen_clock`". The
   fixture works fine, but the real production call path is
   `asyncio.run_coroutine_threadsafe` from a thread — the frozen clock
   doesn't apply there. Each sprint converted these to "mocked LLM +
   `time.monotonic()` delta" instead.

3. **Bootstrap-recovery semantics**: Sprint 4's deferred-export sweeper
   spec said "30s interval"; Sprint 5's webhook poll said "5s interval".
   Both were over-specified — both became `config.yaml`-driven with
   tests overriding to fast values via fixture. The pattern wants to be
   "interval is configurable, default is N" rather than "interval is N."

**Lesson**: a planner-author working from the codemap rather than the
codebase will repeatedly miss two things — actual route-prefix shapes
and timing primitives that don't fit the spec's mental model. A 30-min
walkthrough of the actual codebase before each sprint's design pass
would have eliminated 60–80% of the AC-override entries.

### 2.3 Specs that were over-specified

The PRD enumerated AC tests at the test-name level in some places (e.g.
`test_f1_waits_for_f4_propagation`). When Sprint 4 implemented this, the
test was named exactly as specified. That's good for traceability but
it means a planner-author was writing test names for code they hadn't
seen — those names fit because the test ended up matching the spec, but
they would have been wrong if implementation diverged. Better default:
spec the *contract* the test must verify, leave the test name to the
author.

---

## 3. What code review caught that author tests missed

Sprint 5's code-reviewer agent caught two real bugs that all 124 author
tests missed:

### 3.1 CRITICAL: IPv4-mapped IPv6 SSRF bypass

**The bug**: `_classify_address` had `if ip.version == net.version and ip in net`. An attacker URL `https://[::ffff:169.254.169.254]/...` produces an IPv6 address with version 6; every RFC1918 / 169.254 / 127.0.0.0/8 net is version 4; the version guard silently let the address through to the cloud-metadata endpoint.

**Why author tests missed it**: the test file had IPv4 tests (RFC1918, 169.254, 127.0.0.5) and IPv6 tests (`::1`, `fc00::1`, `fe80::1`) but no *cross-family* test. The mental model was "IPv4 has a list of nets, IPv6 has a list of nets, test each separately." The bypass lives in the seam between them.

**Why review caught it**: the reviewer started from the threat model ("can an attacker reach the cloud-metadata endpoint?") rather than from the test list ("does this status code map to that severity?"). Different starting point, different blind spots.

**Fix**: 6-line change to unwrap `ip.ipv4_mapped` before the network match; 3 new regression tests.

### 3.2 HIGH: `webhook_auth_header` plaintext leak via `extra="allow"`

**The bug**: `ProfilePublicFields` has `model_config = {"extra": "allow"}` (forward-compat for unknown keys). A client could store `webhook_auth_header` inside `public_fields`, and *every* `GET /api/profiles/{id}` would return the bearer token plaintext.

**Why author tests missed it**: tests verified the auth header *gets used* by the coordinator, and that it persists to disk. No test checked the API *response* shape for sensitive keys. The "data flows in correctly" mental model overshadowed the "data flows out safely" mental model.

**Why review caught it**: the reviewer specifically traced "what does an unauthenticated GET return?" — a different starting point than the producer/consumer ones the author traced.

**Fix**: explicit `_RESPONSE_SENSITIVE_KEYS` allowlist scrubbed in `_to_response`; 2 new regression tests verifying scrub happens AND persistent storage retains the value.

### 3.3 LOW findings worth noting

- `cleanup_older_than` used f-string interpolation on `int(retention_days)` — safe, but not parameterized end-to-end. Fixed.
- `100.64.0.0/10` (RFC6598 CGNAT) was not in `_PRIVATE_NETS`. Now added.
- `WebhookWorker.stop()`'s in-flight revert lacked `asyncio.shield`,
  so a hard cancel during shutdown could skip the revert. Now shielded.
- The webhook retry endpoint used `asyncio.create_task(_run_webhook_dispatch(...))`
  before returning 202 — a process death in the 10–100ms window between
  response and the `create_pending` INSERT would silently drop the retry.
  Now `await`-ed inline so PBD holds before 202.

### 3.4 The pattern across all four findings

All four review findings share one shape: **author tests verified one
data flow direction; reviewer tested the other direction.** Author wrote
"webhook URL → worker → external server"; reviewer asked "external
attacker URL → resolver → internal server" and "auth token → worker
payload" vs. "auth token → API response."

**Lesson**: code review's value is highest when the reviewer's starting
mental model differs from the author's. For security-critical code,
explicitly include "data exiting the system in unintended directions" as
a review prompt. Author tests are good at proving the happy path is
correct; reviewers are good at finding the unhappy paths the author
didn't enumerate.

---

## 4. Operational mechanics that worked

- **Sprint design docs averaged ~1000 LOC** of markdown each. That
  feels like a lot, but the per-sprint payoff was: zero AC-implementation
  surprises after design pass, and a comprehensive lookup index when
  the LATER sprints needed to reuse the EARLIER sprints' invariants.
- **The "Section 0: prerequisite verification" tables** at the top of
  each sprint design doc made the dependency chain explicit. Sprint 5's
  Section 0 had 16 prerequisite rows; all 16 were verified PRESENT before
  any code was written. Zero blocked-on-missing-prereq stories across the
  epic.
- **The "commit plan recap"** at the bottom of each design doc, with LOC
  estimates per commit, gave a reliable "are we within budget?" gauge.
  Sprints 1–4 hit their LOC budgets within ~10%; Sprint 5 came in over
  the 2500 cap (~3500 LOC) but the overage was almost entirely tests
  (134 new tests, 2193 LOC of test code).
- **Direct-call route handler test pattern** (CLAUDE.md): no full HTTP
  test client, just `asyncio.run(handler(args, response))`. Made every
  route test fast (sub-millisecond) and bypass the auth middleware
  cleanly without elaborate setup.
- **Per-sprint branch with squash-merge to `gh-104-prd`** kept the
  PR-level history clean while letting each sprint's commits show
  fine-grained progress on the sprint branch. Sprint 5 will be the 5th
  and final merge into `gh-104-prd`.

---

## 5. Recommendations for the next per-feature epic

1. **Start the next epic with the equivalent of Sprint 1 Story 1.1** —
   a single PR that lands the banned-api gate, the test fixtures the
   epic will need, and the schema migration framework conventions.
   Forward-declare fixtures even for stories that won't ship for weeks.

2. **Section 0 (prerequisite verification) is non-negotiable.** Spend
   the 30 minutes auditing each sprint's `Section 0` claims by actually
   reading the code paths. Catch missing prereqs at design time, not at
   commit time.

3. **Inline AC overrides are healthy, not a smell.** Every sprint's
   design doc had a "Section 1: Inline AC overrides" table; it's the
   place where the planner's mental model meets the codebase's reality.
   Make this section mandatory and document the override reasoning so
   future readers don't think the design diverged from the spec
   accidentally.

4. **For security-critical features, write a "threat-model review"
   prompt for the code-reviewer agent.** Sprint 5's reviewer caught
   the SSRF and the credential leak because the prompt explicitly
   asked for SSRF / credential / data-exit analysis. Don't rely on
   the reviewer to ask itself those questions; tell it to.

5. **Each epic should declare its "first commandment" explicitly.**
   For Issue #104 it was Persist-Before-Deliver. Knowing the first
   commandment up front meant every story's design pass evaluated:
   "does this proposal honor PBD?" If yes, ship it; if no, redesign.
   That single criterion eliminated entire classes of would-be
   regressions.

6. **The "5 sprints of ~10 stories each" cadence worked.** It produced
   reviewable PR-shaped chunks (300–700 LOC of production code per
   sprint commit, plus tests), let each sprint design doc be reusable
   for code review prompts, and gave the team natural retrospective
   intervals. Resist the urge to bundle smaller epics together.

7. **Document the design-time AC overrides DURING the sprint, not
   after.** Sprint 5's design doc has every override traced to the
   reason; that's the document a future maintainer reads when they ask
   "why does this URL look weird?" Without it, every override looks
   like accidental drift.

---

## 6. What's NOT carried forward to a future sprint

The epic is genuinely done. There are no Issue #104-related items
deferred to follow-up sprints. Per-feature follow-up items that the
sprints flagged as "out of scope" are tracked in
`_bmad-output/implementation-artifacts/deferred-work.md` and are NOT
load-bearing for any of the 56 stories' acceptance criteria.

Items intentionally NOT in this epic but worth a future sprint's eye:

- **Webhook signing (HMAC of body)** — receivers that need signature
  verification need a Sprint 6+. Currently webhooks are
  bearer-token-authenticated only.
- **Per-recording webhook URL override** — currently the profile's URL
  is the only source. A `recordings.webhook_url_override` column would
  unlock per-event customization but isn't required by any FR/NFR.
- **Multi-replica WebhookWorker** — current design assumes single-process
  Docker. If the deployment fans out, a claim-token column on
  `webhook_deliveries` would prevent two workers from racing on the
  same row.
- **Webhook delivery telemetry (Prometheus-style)** — local logs only
  per CLAUDE.md's no-outbound-telemetry policy.

---

## 7. Action items for the merge-to-main moment

1. **Confirm the SSRF + credential-leak fixes are in `gh-104-prd`** —
   verified: 6 fixes added with 6 new tests passing.
2. **Re-run the full backend pytest suite once more on `gh-104-prd`
   HEAD** — done: 1897 passed, 29 pre-existing platform-specific
   failures (MLX/parakeet/canary/model_manager_init unrelated to Issue
   #104).
3. **Frontend Vitest** — 1263 passed, 1 pre-existing flaky electron
   AppImage caching test (passes when run in isolation).
4. **TypeScript typecheck clean.**
5. **UI contract bumped to v1.0.47.**
6. **All 7 Sprint 5 stories marked DONE in `epics.md`.**
7. **All 56 Issue #104 stories marked DONE.**

Merge `gh-104-prd` → `main` is approved on the verification side. The
PR description should reference this retrospective and the 5 sprint
design docs as the canonical record of the epic.

---

*Retrospective drafted post-implementation by the implementation team
working from the planning artifacts (PRD, epics.md), the five sprint
design docs, and the code-reviewer agent's CRITICAL/HIGH/LOW findings
for Sprint 5. Captures the design-time, implementation-time, and
review-time observations that are useful for the next per-feature epic
that takes this codebase as its starting point.*
