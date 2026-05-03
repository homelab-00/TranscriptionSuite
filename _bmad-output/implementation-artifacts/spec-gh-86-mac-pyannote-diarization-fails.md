---
title: 'Gate Pyannote diarization on Apple Silicon Metal — auto-migrate to Sortformer (Issue #86 #2)'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: '20fc3c7e'
context:
  - '{project-root}/docs/project-context.md'
  - '{project-root}/dashboard/components/views/ServerView.tsx'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On Mac M4Pro Metal mode, selecting `pyannote/speaker-diarization-community-1` for diarization silently produces no speaker output (Issue #86 #2 — Sortformer works, Pyannote does not, HF token + gated-repo access correctly granted). Root cause is upstream: `pyannote.audio 4.0.4` does not support MPS — three issues in `pyannote/pyannote-audio` are closed wontfix (#1886 M4 kernel crash, #1337 wrong M1 timestamps, #1091 silent CPU fallback). Locally `_resolve_device()` in `diarization_engine.py:47-66` correctly falls back to MPS when CUDA is absent; pyannote then breaks; `parallel_diarize.py` swallows the failure as `(result, None)` and the route handler degrades to zero speakers with no error surface. The dashboard exposes Pyannote freely on every runtime profile today (`ServerView.tsx:2269-2289`), so Mac users have no signal.

**Approach:** Gate the Pyannote dropdown option in `ServerView.tsx`'s diarization picker when `runtimeProfile === 'metal'` (filter `DIARIZATION_DEFAULT_MODEL` out of the options array on Metal). Auto-migrate any persisted Pyannote selection to Sortformer via a single post-hydration `useEffect` that handles both initial mount AND mid-session profile toggles. Render an inline reason below the dropdown citing upstream issue #1886. Show an inline warning beside the Custom HF-repo input when its value matches `^pyannote\//i` on Metal — warn but don't block (future non-pyannote custom diarizers must remain possible). No server-side change.

## Boundaries & Constraints

**Always:**
- Use `runtimeProfile === 'metal'` (already in scope as `isMetal` at `ServerView.tsx:278`) as the only gate predicate.
- One post-hydration migration effect depending on `[isMetal, diarizationHydrated, diarizationModelSelection]`. Do NOT extend the `Promise.all` hydration block at lines 370-378 — `runtimeProfile` is loaded by a separate effect (lines 322-328); a single effect subsumes mount + mid-session migrations.
- Detect pyannote-flavored custom HF repos via case-insensitive `^pyannote\//i`, mirroring the regex-constant shape in `dashboard/src/services/modelCapabilities.ts`.
- Cite upstream wontfix issue #1886 in the inline reason for audit trail.
- Preserve existing behaviour on non-Metal profiles — no filtering, no warnings, no migration.

**Ask First:**
- Final wording for the inline reason (default: `"Pyannote diarization is not supported on Apple Silicon (pyannote.audio MPS path is broken upstream — see pyannote/pyannote-audio#1886). Sortformer (Metal) is the recommended diarizer on Mac."`) and the custom-input warning (default: `"Custom pyannote repos are not supported on Apple Silicon — switch to Sortformer."`).

**Never:**
- Do NOT remove or version-pin `pyannote.audio` in `pyproject.toml` — required dep for Linux/Windows NeMo paths.
- Do NOT modify `_resolve_device()` in `diarization_engine.py` — its MPS→CPU fallback is correct.
- Do NOT change `parallel_diarize.py`'s silent-degrade behaviour — separate UX bug; file as a follow-up if user agrees post-implementation.
- Do NOT touch the MLX log pipeline (`gh-86 #3` in `deferred-work.md`).
- Do NOT add a `runtimeProfile`-aware helper to `modelCapabilities.ts` — that file is pure model-name regex; platform-aware logic belongs in `ServerView.tsx` next to the existing `DIARIZATION_*` constants.
- Do NOT block the Custom field on Metal — only warn when the entered value matches the pyannote pattern.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|----------|--------------|---------------------------|
| Mac Metal, persisted Pyannote (or no choice) | `isMetal === true`, persisted value === `DIARIZATION_DEFAULT_MODEL` (or absent) | Dropdown options = `[Sortformer, Custom]`; selected value coerced to Sortformer; `api.config.set('server.diarizationModelSelection', Sortformer)` called once after hydration; inline reason rendered below dropdown. |
| Mac Metal, persisted Custom = `pyannote/<repo>` | `isMetal === true`, selection === Custom, custom value matches `^pyannote\//i` | Custom option remains selectable and editable; inline amber warning beside the custom input. Server start NOT blocked. |
| Mac Metal, persisted Custom = non-pyannote | `isMetal === true`, selection === Custom, custom value does not match `^pyannote\//i` | No warning beside custom input. |
| Linux/Windows, any persisted choice | `isMetal === false` | All three options available; no warnings; no migration — existing behaviour unchanged. |
| Profile toggled `cpu → metal` mid-session, current selection is Pyannote | `isMetal` transitions `false → true`, `diarizationModelSelection === DIARIZATION_DEFAULT_MODEL` | Same coercion fires (Pyannote → Sortformer + persist); dropdown re-filters; inline reason appears. |
| Profile toggled `metal → cpu` mid-session | `isMetal` transitions `true → false` | Dropdown re-includes Pyannote; inline reason hidden; selected value preserved (no auto-revert). |

</frozen-after-approval>

## Code Map

- `dashboard/components/views/ServerView.tsx` — primary surface. Five additive changes: (1) `PYANNOTE_REPO_PATTERN` constant near `DIARIZATION_*` constants at lines 84-86; (2) `diarizationOptions` derived value (memoized on `[isMetal]`) consumed by `CustomSelect` at lines 2269-2279; (3) post-hydration migration `useEffect([isMetal, diarizationHydrated, diarizationModelSelection])` near the existing MLX-related effect around line 862; (4) inline reason `<p>` below the dropdown when `isMetal`; (5) inline `AlertTriangle`-styled amber warning beside the custom HF-repo input when `isMetal && PYANNOTE_REPO_PATTERN.test(diarizationCustomModel)`.
- `dashboard/components/__tests__/ServerView.test.tsx` — extend with `describe('Pyannote diarization gate on Mac Metal', ...)`. Mock `api.config.get('server.runtimeProfile')` and `api.config.get('server.diarizationModelSelection')` per case; assert dropdown DOM, persisted-value side-effect via `vi.mocked(api.config.set)`, and inline-text presence/absence.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/ServerView.tsx` — implement all five changes per Code Map. The migration effect calls `setDiarizationModelSelection(DIARIZATION_SORTFORMER_OPTION)` and `api.config.set('server.diarizationModelSelection', DIARIZATION_SORTFORMER_OPTION)` when `isMetal && diarizationHydrated && diarizationModelSelection === DIARIZATION_DEFAULT_MODEL`.
- [x] `dashboard/components/__tests__/ServerView.test.tsx` — one test per I/O matrix row. Mid-session toggle covered by the same `useEffect` dependency on `isMetal` (mount-time `runtimeProfile === 'metal'` exercises the same false→true transition path; documented in test-block comment). Headlessui mock upgraded to invoke render-prop children so dropdown option text is queryable.
- [x] After UI edits, run UI-contract pipeline: `npm run ui:contract:extract` → `npm run ui:contract:build` → `node scripts/ui-contract/validate-contract.mjs --update-baseline` → `npm run ui:contract:check`. Bumped `meta.spec_version` 1.0.24 → 1.0.25.

**Acceptance Criteria:**
- Given `isMetal === true` and persisted choice is Pyannote, when hydration completes, then selected value becomes Sortformer AND `api.config.set('server.diarizationModelSelection', Sortformer)` is called exactly once.
- Given `isMetal === true`, when rendered, then dropdown contains exactly `[Sortformer, Custom]` (no Pyannote option in the DOM) and the inline reason text is visible.
- Given `isMetal === false` and persisted choice is Pyannote, when mounted, then all three options present and selected value remains Pyannote — no migration.
- Given `isMetal === true` and Custom value matches `^pyannote\//i`, when rendered, then inline amber warning is visible next to the custom input.
- Given `isMetal === true` and Custom value is `nvidia/sortformer-fork`, when rendered, then no warning beside custom input.
- Given user toggles `runtimeProfile` from `cpu` to `metal` while `diarizationModelSelection === DIARIZATION_DEFAULT_MODEL`, when the toggle takes effect, then selection migrates to Sortformer and is persisted.
- `npm run typecheck` passes from `dashboard/`. `npx vitest run components/__tests__/ServerView.test.tsx` passes. `npm run ui:contract:check` passes from `dashboard/`.

## Spec Change Log

### 2026-04-26 — adversarial review patches (Step 4, iteration 1)

Two `patch`-class findings from the parallel reviewer cycle (blind hunter / edge-case hunter / acceptance auditor) were applied directly to the implementation; the frozen spec body was not amended (root causes were code-level, not intent-level).

1. **Removed redundant explicit `api.config.set` from the migration `useEffect`** (edge-case hunter #6). An existing auto-persist effect at `ServerView.tsx:1019-1024` already writes `server.diarizationModelSelection` whenever the state changes — the explicit `set` in the migration effect produced two writes per migration, contradicting the spec's "exactly once" acceptance criterion. The migration now only calls `setDiarizationModelSelection(SORTFORMER)` and lets the auto-persist effect handle the IPC write. **Avoided known-bad state:** redundant IPC traffic + spec/test mismatch on the "exactly once" assertion. **KEEP:** the migration effect's three-condition guard (`isMetal && diarizationHydrated && diarizationModelSelection === DIARIZATION_DEFAULT_MODEL`) — necessary to prevent infinite loop and to scope to the Pyannote-specific case.

2. **Added `.trim()` to the custom-input pyannote-pattern check** (edge-case hunter #2). The custom warning gate `PYANNOTE_REPO_PATTERN.test(diarizationCustomModel)` was bypassed by leading/trailing whitespace, while `activeDiarizationModel` at `ServerView.tsx:815-819` already trims before sending to the server — so a value like `"  pyannote/community  "` would skip the warning and still reach the broken backend. The check now trims first. New Vitest case `'on Mac Metal with Custom + whitespace-prefixed pyannote value, still shows the warning'` locks the behavior. **Avoided known-bad state:** silent-bypass of the gate via copy-paste artifacts. **KEEP:** the warning-but-don't-block design (per spec Never) — the trim fix only widens the warn surface, it does not introduce a hard block.

Migration test was also tightened from `toHaveBeenCalledWith(...)` to `setSpy.mock.calls.filter(...).length === 1` to actually enforce the "exactly once" AC.

Other reviewer findings classified: 1 deferred to `deferred-work.md` (test-isolation `electronAPI` not restored across describes — pre-existing pattern, no current symptom); remainder rejected as spec-design choices (e.g. custom field warns-but-doesn't-block per Never), false alarms (PYANNOTE_REPO_PATTERN constant grouping is already correct), or out-of-scope nitpicks.

## Design Notes

**Why one migration effect, not extend the hydration `Promise.all`.** `runtimeProfile` is hydrated by a separate effect (line 322-328). Loading both keys in one `Promise.all` would race against the existing profile loader. A single `useEffect([isMetal, diarizationHydrated, diarizationModelSelection])` cleanly subsumes mount-time AND mid-session profile-toggle migrations from one place.

**Why warn but don't block the Custom field.** Future MLX-native pyannote forks or non-pyannote diarizers (e.g. NeMo Sortformer ports) could appear. Blocking would be a regression; warning preserves user agency.

## Verification

**Commands** (from `dashboard/`):
- `npm run typecheck` — expected: 0 errors.
- `npx vitest run components/__tests__/ServerView.test.tsx` — expected: all tests pass including new gate block.
- `npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` — expected: contract check passes.

Bill has no Apple Silicon to validate the Mac path manually; Vitest assertions are the primary verification surface. Issue #86 reporter (or any user reproducing the gate) confirms visually after release. Track upstream pyannote MPS support via `gh issue list --repo pyannote/pyannote-audio --search MPS` for any future un-wontfixing.

## Suggested Review Order

**Gate predicate**

- Pyannote regex constant grouped with existing `DIARIZATION_*` constants; comment cites upstream wontfix issues.
  [`ServerView.tsx:89`](../../dashboard/components/views/ServerView.tsx#L89)

- `useMemo` filter that omits `DIARIZATION_DEFAULT_MODEL` from dropdown options on Metal — single-line feature truth.
  [`ServerView.tsx:297`](../../dashboard/components/views/ServerView.tsx#L297)

**Migration**

- Single post-hydration `useEffect` auto-migrates persisted Pyannote → Sortformer; persistence flows through the existing auto-persist effect at line 1019 (Step 4 patch removed the redundant explicit `set`).
  [`ServerView.tsx:962`](../../dashboard/components/views/ServerView.tsx#L962)

**UX surfaces**

- Inline informational `<p>` below the dropdown citing pyannote-audio#1886 — always visible on Metal regardless of selection.
  [`ServerView.tsx:2304`](../../dashboard/components/views/ServerView.tsx#L2304)

- `AlertTriangle`-styled amber warning beside the custom HF-repo input; trims input before pattern test (Step 4 patch closes whitespace-bypass).
  [`ServerView.tsx:2325`](../../dashboard/components/views/ServerView.tsx#L2325)

**Tests**

- Headlessui mock upgraded to invoke render-prop children so dropdown option text is queryable in jsdom.
  [`ServerView.test.tsx:148`](../../dashboard/components/__tests__/ServerView.test.tsx#L148)

- Six tests covering each I/O matrix row, the "exactly once" persistence assertion, and the whitespace-bypass case.
  [`ServerView.test.tsx:283`](../../dashboard/components/__tests__/ServerView.test.tsx#L283)
