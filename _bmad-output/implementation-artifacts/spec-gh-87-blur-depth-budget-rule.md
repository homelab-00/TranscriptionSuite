---
title: 'UI-contract blur-depth budget rule (Issue #87)'
type: 'feature'
created: '2026-04-21'
status: 'done'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md'
  - '{project-root}/dashboard/ui-contract/design-language.md'
baseline_commit: '66473b4'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `dashboard/ui-contract/design-language.md:61` documents "Blur stacking: excessive `backdrop-blur` on nested layers" as an anti-pattern, but the project ships **17 source files using 49 total `backdrop-blur` references** (notably `App.tsx:8`, `AudioNoteModal.tsx:5`, `SessionView/ServerView/NotebookView/BugReportModal.tsx:4` each) with no machine-enforced ceiling. Issue #87's brainstorm root-caused the Mac visible-CPU/GPU symptom partly to this stacked-blur compositor pressure (Cluster A/2). Today, a contributor can keep adding `backdrop-blur-xl` divs forever and only a code reviewer catches it; CI does not.

**Approach:** Extend the existing UI-contract closed-set system with a per-file **occurrence budget** for `backdrop-blur` references. The contract YAML gains a `blur_depth_budgets` block: a `default_max` (proposed: 3) plus `per_file_overrides` map that grandfathers every existing file at its current count with a brief rationale field. The fact extractor counts regex occurrences of `/backdrop-blur(?:-[a-z0-9-]+)?/` per source file. The validator emits a new issue code `blur_budget_exceeded` whenever an extracted count exceeds the file's allowed budget. New files get the default. Adding a blur to a file at its budget fails CI; the contributor must either remove a blur OR explicitly raise that file's override (with justification) — turning the design-language warning into a forcing function.

## Boundaries & Constraints

**Always:**
- Ship green: pre-existing per-file counts are grandfathered into `per_file_overrides` so `npm run ui:contract:check` passes immediately on this commit with no source-file edits.
- The new check is **opt-in by detection**: it only fires on files where extracted count > budget. Files at-or-below budget are silent.
- The default budget applies to any file not listed in `per_file_overrides`.
- All changes are local to `dashboard/ui-contract/*` and `dashboard/scripts/ui-contract/*`. No edits to component source files (`dashboard/components/**`, `dashboard/App.tsx`, etc.).
- The new contract section must be schema-validated (extend `transcription-suite-ui.contract.schema.json`).
- Add at least one new test in `test-contract.mjs` that proves a budget-exceeding fact triggers the new issue code.
- Bump `meta.spec_version` (1.0.20 → 1.0.21) and refresh the baseline.
- Update `design-language.md:61` to reference the now-enforced rule and the YAML key contributors should edit when they need to raise a budget.

**Ask First:**
- Changing the proposed `default_max` from 3 to a different number — first sprint sets the ceiling; if 3 turns out to be wrong, the user picks the new value.
- Counting `filter: blur-*` (non-backdrop blur) — out of scope unless explicitly asked. Brainstorm targets backdrop-blur only.
- Failing on a file's existing count via a tightened budget — never lower a grandfathered override in this story; that is a separate cleanup sprint.

**Never:**
- Do not edit any component source file to bring counts under budget. Grandfather everything as-is.
- Do not introduce a runtime check (this is a build-time / CI gate only).
- Do not add a new dependency.
- Do not silently fall back to default when an override is malformed — schema must reject malformed overrides.
- Do not count occurrences inside JS/TS comments or string literals that are not className contexts (use the same content-scanning approach the existing extractor uses).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Existing repo state | All 17 current files at their grandfathered counts | `npm run ui:contract:check` passes; no `blur_budget_exceeded` issues | N/A |
| Contributor adds a blur to file at budget | e.g., add a `backdrop-blur-md` div to `Sidebar.tsx` (currently 1, override 1) | Validator emits `blur_budget_exceeded` issue with file path + actual vs allowed | Exits non-zero; pre-commit hook fails |
| Contributor adds new file with 4 backdrop-blur references | New `components/Foo.tsx`, count=4, no override → default=3 | `blur_budget_exceeded` for `components/Foo.tsx`: actual=4 vs allowed=3 | Exits non-zero |
| Contributor adds new file with 2 backdrop-blur references | New `components/Bar.tsx`, count=2 ≤ default=3 | Pass; no issue | N/A |
| Contributor removes a blur from file at override | `Sidebar.tsx` count drops from 1 to 0 | Pass; no issue. Override stays at 1 (intentional — overrides are ceilings, not equalities) | N/A |
| Contributor raises an override to add a blur | `Sidebar.tsx`: bump override 1 → 2, then add the blur | Validator passes; baseline regen + spec_version bump required (existing flow) | N/A |
| Contributor adds malformed override | `per_file_overrides: { "x.tsx": "not-a-number" }` | Schema validation fails with `schema_validation_failed` | Exits non-zero |
| Contributor introduces `backdrop-blur-[8px]` arbitrary value | Any file | Counted by the regex; subject to budget | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/ui-contract/transcription-suite-ui.contract.yaml` -- WRITE. Add new `blur_depth_budgets` section under `tokens` (or top-level next to existing budgets). Bump `spec_version` 1.0.20 → 1.0.21.
- `dashboard/ui-contract/transcription-suite-ui.contract.schema.json` -- WRITE. Add a JSON-schema definition for `blur_depth_budgets`: `{ default_max: integer, per_file_overrides: { [file]: { max: integer, reason: string } } }`.
- `dashboard/ui-contract/contract-baseline.json` -- WRITE. Refresh after `--update-baseline`.
- `dashboard/scripts/ui-contract/shared.mjs` -- WRITE. In `extractFacts()`, after the existing per-token loop, walk `fileContentMap` again and produce `tokens.blur_levels.per_file_counts: { [file]: number }` using a regex over each file's raw content.
- `dashboard/scripts/ui-contract/validate-contract.mjs` -- WRITE. (a) Add the new section to `normalizeContractForComparison` and `normalizeFactsForComparison`. (b) Add a new check function `checkBlurBudgets(contract, facts)` that emits `{ code: 'blur_budget_exceeded', severity: 'error', path: '<file>', message: 'Backdrop-blur references in <file> exceed budget (actual=<n> allowed=<m>).', details: { file, actual, allowed } }` for each violation. (c) Push results into `report.issues` from `createValidationReport`.
- `dashboard/scripts/ui-contract/test-contract.mjs` -- WRITE. Add two new test cases: (1) `Drift fail for blur budget exceeded on existing file` — clone facts, bump one file's count to override+1, expect `blur_budget_exceeded`; (2) `Pass case for new file under default budget` — clone facts, add a new file at default-1 count, expect no new issue.
- `dashboard/ui-contract/design-language.md` -- WRITE. Edit the bullet at line 61 to reference the enforced rule and the YAML key contributors edit when raising a budget.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/scripts/ui-contract/shared.mjs` -- Added `extractBackdropBlurCountsPerFile` + tightened regex `BACKDROP_BLUR_OCCURRENCE_RE = /(?<![A-Za-z0-9_-])backdrop-blur(?:-[a-z0-9-]+)?(?:\b|\[)/g` (negative lookbehind blocks `--backdrop-blur-*` CSS-variable declarations and `data-backdrop-blur-*` attribute-style false positives). Added SEPARATE `blurScanFiles(root)` walker that unions `sourceFiles(root)` with `src/**/*.tsx` — used ONLY by `extractBackdropBlurCountsForBlurScan(root)` so the wider set does not leak into component_coverage. `extractFacts()` returns `tokens.blur_levels.per_file_counts`.
- [x] `dashboard/scripts/ui-contract/build-contract.mjs` -- Read the prior YAML's `meta.spec_version` and `blur_depth_budgets` and pass both through unchanged when regenerating. Without this, `extract → build` would wipe human-curated sections and reset the version.
- [x] `dashboard/ui-contract/transcription-suite-ui.contract.schema.json` -- Added `blur_depth_budgets` with required `default_max` (≥1 integer) and required `per_file_overrides` whose values require `max` integer + non-empty `reason`. Included in top-level `required`.
- [x] `dashboard/ui-contract/transcription-suite-ui.contract.yaml` -- Added `blur_depth_budgets:` block. `default_max: 3` plus 6 grandfathered overrides for files >3: App.tsx=8, AudioNoteModal=5, BugReport/Notebook/Server/Session=4. After iter-2 scope expansion, `useConfirm.tsx` is now scanned at count=2 — under default, no override needed.
- [x] `dashboard/scripts/ui-contract/validate-contract.mjs` -- Added `checkBlurBudgets(contract, facts)` emitting `blur_budget_exceeded`. Wired into `createValidationReport`.
- [x] `dashboard/scripts/ui-contract/test-contract.mjs` -- Added three test cases (renumbered to avoid collision with the existing non-style/versioning cases): override-violation (App.tsx 8→9), pass when new file ≤ default_max, fail when new file > default_max. Test count 13 → 16.
- [x] `dashboard/ui-contract/design-language.md` -- Line 61 now references `blur_depth_budgets:` and the recovery recipe.
- [x] `dashboard/.claude/skills/ui-contract/SKILL.md` (or repo-root `CLAUDE.md` if the skill file does not exist) -- Added a one-line bullet pointing at the new `blur_budget_exceeded` failure code and the override-bump recipe.
- [x] Bumped `meta.spec_version` 1.0.20 → 1.0.21; refreshed baseline.
- [x] `npm run typecheck` and `npm run ui:contract:check` both pass (16/16).

**Acceptance Criteria:**
- Given the repo at this commit, when a contributor runs `npm run ui:contract:check`, then it passes (16/16 tests).
- Given a contributor adds a `<div className="backdrop-blur-md" />` to `dashboard/components/Sidebar.tsx`, when they run `npm run ui:contract:check`, then it emits `[blur_budget_exceeded] dashboard/components/Sidebar.tsx: Backdrop-blur references exceed budget (actual=2 allowed=1)` and exits non-zero.
- Given a contributor creates a new `dashboard/components/foo.tsx` with two `backdrop-blur-xl` references, when they run the check, then it passes (2 ≤ default 3).
- Given a contributor creates a new file with four `backdrop-blur-xl` references, when they run the check, then it emits `blur_budget_exceeded` for that file (4 > default 3).
- Given the schema, when a YAML override entry is missing `reason`, then `schema_validation_failed` fires before any semantic check runs.

## Spec Change Log

### Iteration 2 — bad_spec loopback (2026-04-21)

**Triggering findings:**
- Edge Hunter EH-1 (HIGH) — `dashboard/src/hooks/useConfirm.tsx` carries 2 `backdrop-blur` references TODAY but is silently outside the scanned file set, because `sourceFiles()` only walks `components/**/*.tsx` and does not walk `src/**/*.tsx`. The rule has a coverage hole on existing code; brand-new hooks/services that render blurred chrome would also evade enforcement.
- Edge Hunter EH-2 (HIGH) — The regex `/backdrop-blur(?:-[a-z0-9-]+)?(?:\b|\[)/g` falsely counts `--backdrop-blur-xs:` in `src/index.css` (the Tailwind theme variable declaration). Currently inflates that file's count by 1. Future theme variable additions could push files over budget without any actual class usage, and would also catch HTML-attribute-style strings like `data-backdrop-blur-*`.
- Acceptance Auditor AA-2 (MED) — Contributor workflow for raising a budget is not documented anywhere a contributor would naturally find it after a CI failure (CLAUDE.md, the ui-contract skill, etc.).
- Acceptance Auditor AA-3 / AA-4 (LOW) — Spec AC line said "15/15 tests" but actual is 16; test-comment headers collide between blur cases (9a-c) and non-style/versioning cases.
- Iter-2 self-discovered — `build-contract.mjs` hardcodes `spec_version: '1.0.19'` and does not write a `blur_depth_budgets` block. Following the documented skill workflow ("raise budget → run extract+build+update-baseline+check") would WIPE the entire `blur_depth_budgets` section AND reset the version, then fail schema validation. Round-trip preservation of human-curated sections is essential.

**Root causes:** Spec implicitly inherited the existing `sourceFiles()` walk scope without questioning whether it actually covered every `.tsx` that can carry styling. Spec specified the regex without anchoring its left boundary against CSS-variable identifier characters.

**What was amended:**
- Code Map / Tasks: added an explicit task to extend `sourceFiles()` to walk `dashboard/src/**/*.tsx` so hooks/services that render JSX (e.g., `useConfirm.tsx`) are subject to the rule.
- Code Map / Tasks: tighten the regex to `(?<![A-Za-z0-9_-])backdrop-blur(?:-[a-z0-9-]+)?(?:\b|\[)/g` — the negative lookbehind rejects any leading identifier-character (`-`, alpha, digit, `_`), eliminating CSS-variable false positives (`--backdrop-blur-xs`) and HTML-attribute false positives (`data-backdrop-blur-*`).
- Tasks: after the scope+regex fix, re-extract facts and update the YAML to add an override for any newly-discovered file whose count > default_max (today: `src/hooks/useConfirm.tsx` at count 2, ≤ default_max=3 — no override needed).
- Tasks: add a one-line entry to `dashboard/.claude/skills/ui-contract/SKILL.md` (or fall back to `CLAUDE.md` Quick Reference if the skill file is not present) describing the new failure mode and recovery recipe (edit YAML override → bump spec_version → refresh baseline).
- Tasks: fix spec AC count "15/15" → "16/16"; renumber post-blur test comments in `test-contract.mjs` to avoid collision.

**Known-bad state avoided:** A contributor adds 5 backdrop-blur divs to `src/hooks/useConfirm.tsx` (or any future `src/**/*.tsx`) and the budget check sees nothing; OR Tailwind theme grows new `--backdrop-blur-*` variables and falsely fails the CI gate.

**KEEP instructions (must survive re-derivation):**
- Architecture: facts contain `tokens.blur_levels.per_file_counts`; validator's `checkBlurBudgets` emits `blur_budget_exceeded`; YAML's `blur_depth_budgets:` block has `default_max` + `per_file_overrides` map. Preserve verbatim.
- All six grandfathered overrides (App.tsx=8, AudioNoteModal=5, BugReport/Notebook/Server/Session=4) — preserve, do not rebuild from scratch.
- `default_max: 3`.
- The `reason:` requirement on each override (schema + test).
- The three test cases (9a/9b/9c) and what they assert. Renumber comments only.
- The design-language.md:61 update text.
- Schema shape and top-level placement (sibling of `inline_style_allowlist`).

## Design Notes

**Why per-file occurrence count rather than DOM-nesting depth:** Static analysis cannot reconstruct DOM nesting reliably (conditional renders, portals, runtime state). Per-file `backdrop-blur` occurrence count is a deterministic, easily-auditable proxy. The metric correlates well with compositor cost: each `backdrop-blur-*` className typically maps to one promoted layer that samples its background each frame; bounding the per-file count bounds the worst-case stacking when all conditional branches mount at once (e.g., overlapping modals).

**Why grandfather aggressively rather than enforce a uniform ceiling:** This sprint is about *stopping the bleeding* — preventing new stacking — not about a cleanup pass. Existing high-blur files (App.tsx with 8, AudioNoteModal with 5) are mutually-exclusive code paths the design intentionally accepts today; rewriting them is a separate brownfield story. Each grandfathered override carries a `reason:` string so future readers see why the budget is what it is, and a follow-up cleanup sprint can systematically lower budgets one file at a time.

**Why a new top-level YAML section vs. extending the closed-set machinery:** The existing `setDiff`-based comparisons answer "is the set of X equal between contract and facts?". This rule is a different shape: "is the count of X per file ≤ a per-file ceiling?". Reusing `setDiff` would require encoding `(file, count)` tuples as strings — fragile and noisy in error output. A dedicated `checkBlurBudgets` function with its own issue code keeps error messages clear and lets future budget rules (e.g., per-component shadow count) follow the same shape without further generalization.

**Counting regex:** `/backdrop-blur(?:-[a-z0-9-]+)?(?:\b|\[)/g` — matches `backdrop-blur`, `backdrop-blur-xl`, `backdrop-blur-3xl`, `backdrop-blur-[8px]`. Applied to raw file content (not just className-string contexts) so that comments mentioning the term pre-emptively also count — defensive: if the source file mentions `backdrop-blur` 8 times in any way, that's still a code-smell signal. False positive cost is negligible vs. accidental drift.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: exits 0.
- `cd dashboard && npm run ui:contract:check` -- expected: 15/15 tests pass; semantic valid; no new issues.
- `cd dashboard && node scripts/ui-contract/validate-contract.mjs --json | jq '.issues[] | select(.code=="blur_budget_exceeded")'` -- expected: empty (no current violations).

**Manual checks (if no CLI):**
- Read `dashboard/ui-contract/transcription-suite-ui.contract.yaml` and confirm `blur_depth_budgets:` block exists with `default_max: 3` and per-file overrides for every file currently above 3 (App.tsx=8, AudioNoteModal.tsx=5, SessionView.tsx=4, ServerView.tsx=4, NotebookView.tsx=4, BugReportModal.tsx=4).
- Read `dashboard/ui-contract/design-language.md` line 61 and confirm it now points readers at `blur_depth_budgets` in the YAML for the enforcement mechanism.

## Suggested Review Order

**The new contract surface**

- Top-level YAML block with default_max + 6 grandfathered per-file overrides (each carries a `reason:`).
  [`transcription-suite-ui.contract.yaml:1144`](../../dashboard/ui-contract/transcription-suite-ui.contract.yaml#L1144)

- JSON-Schema definition for the new block — required `default_max` integer + `per_file_overrides` map of `{ max, reason }`.
  [`transcription-suite-ui.contract.schema.json:366`](../../dashboard/ui-contract/transcription-suite-ui.contract.schema.json#L366)

**The fact extractor (where occurrence counts come from)**

- Tightened regex with negative lookbehind that blocks `--backdrop-blur-*` CSS variables and `data-backdrop-blur-*` attribute false positives.
  [`shared.mjs:660`](../../dashboard/scripts/ui-contract/shared.mjs#L660)

- Separate wider walker `blurScanFiles()` that adds `src/**/*.tsx` for blur-counting only — keeps the closed-set component_coverage check unaffected.
  [`shared.mjs:146`](../../dashboard/scripts/ui-contract/shared.mjs#L146)

- New `per_file_counts` field plumbed into the returned facts.
  [`shared.mjs:851`](../../dashboard/scripts/ui-contract/shared.mjs#L851)

**The validator (where issues are emitted)**

- `checkBlurBudgets(contract, facts)` emits `blur_budget_exceeded` per offending file.
  [`validate-contract.mjs:371`](../../dashboard/scripts/ui-contract/validate-contract.mjs#L371)

- Wired into `createValidationReport` so issues land in the standard report shape.
  [`validate-contract.mjs:599`](../../dashboard/scripts/ui-contract/validate-contract.mjs#L599)

**Round-trip preservation (so `extract → build` doesn't wipe overrides)**

- `build-contract.mjs` now reads the prior YAML's `meta.spec_version` and `blur_depth_budgets` and passes both through.
  [`build-contract.mjs:11`](../../dashboard/scripts/ui-contract/build-contract.mjs#L11)

**Tests + docs**

- Three new test cases (override violation, default-pass, default-fail).
  [`test-contract.mjs:153`](../../dashboard/scripts/ui-contract/test-contract.mjs#L153)

- Design-language anti-pattern bullet now points at the enforcement mechanism.
  [`design-language.md:61`](../../dashboard/ui-contract/design-language.md#L61)

- Skill doc explains the new failure code and the correct edit-then-rebuild order.
  [`SKILL.md:91`](../../.claude/skills/ui-contract/SKILL.md#L91)
